"""Tests for the GUI support helpers (no Streamlit dependency required)."""

from __future__ import annotations

import json

import pytest

from ship_sim.gui import builders
from ship_sim.models.results import SimulationResult
from ship_sim.models.scenario import Scenario


def test_default_demo_scenario_is_valid():
    sc = builders.default_demo_scenario()
    assert isinstance(sc, Scenario)
    assert sc.ship.components


def test_scenario_roundtrips_through_editable():
    sc = builders.default_demo_scenario()
    data = builders.scenario_to_editable(sc)
    rebuilt = builders.validate_scenario(data)
    assert rebuilt == sc


def test_edited_scenario_produces_valid_object():
    sc = builders.default_demo_scenario()
    data = builders.scenario_to_editable(sc)
    # Edit a few fields the way the GUI would.
    data["ship"]["metacentric_height_m"] = 0.55
    data["simulation"] = {"dt_hours": 3.0, "backend": "python"}
    rebuilt = builders.validate_scenario(data)
    assert rebuilt.ship.metacentric_height_m == 0.55
    assert rebuilt.simulation.resolved_dt_s == 10800.0


def test_invalid_edit_fails_validation():
    sc = builders.default_demo_scenario()
    data = builders.scenario_to_editable(sc)
    # thickness greater than original is rejected by the ShipComponent validator.
    data["ship"]["components"][0]["thickness_m"] = 999.0
    with pytest.raises(ValueError):
        builders.validate_scenario(data)


def test_missing_dt_fails_validation():
    sc = builders.default_demo_scenario()
    data = builders.scenario_to_editable(sc)
    data["simulation"] = {"backend": "python"}  # no dt_s / dt_hours
    with pytest.raises(ValueError):
        builders.validate_scenario(data)


def test_inline_components_resolves_material():
    materials = [{"name": "steel", "density_kg_m3": 7850.0, "yield_strength_pa": 355e6,
                  "ultimate_strength_pa": 490e6, "elastic_modulus_pa": 210e9,
                  "base_corrosion_rate_m_per_year": 1e-4, "galvanic_potential_v": -0.6}]
    components = [{"name": "bottom", "material_name": "steel", "thickness_m": 0.014,
                  "area_m2": 100.0, "original_thickness_m": 0.014}]
    inlined = builders.inline_components(materials, components)
    assert inlined[0]["material"]["name"] == "steel"
    assert "material_name" not in inlined[0]


def test_inline_components_unknown_material_raises():
    with pytest.raises(ValueError):
        builders.inline_components([], [{"name": "x", "material_name": "missing"}])


def test_assemble_and_validate_from_tables():
    sc = builders.default_demo_scenario()
    tables_materials = []
    seen = set()
    components = []
    for comp in sc.ship.components:
        if comp.material.name not in seen:
            seen.add(comp.material.name)
            tables_materials.append(comp.material.model_dump(mode="json"))
        row = comp.model_dump(mode="json")
        row.pop("material")
        row["material_name"] = comp.material.name
        components.append(row)
    waypoints = [wp.model_dump(mode="json") for wp in sc.trajectory.waypoints]
    ship_scalars = sc.ship.model_dump(mode="json")
    ship_scalars.pop("components")

    data = builders.assemble_scenario_dict(
        name="from_tables", simulation={"dt_hours": 6.0, "backend": "python"},
        ship=ship_scalars, materials=tables_materials, components=components,
        waypoints=waypoints, procedural={"seed": 1},
    )
    rebuilt = builders.validate_scenario(data)
    assert rebuilt.name == "from_tables"
    assert len(rebuilt.ship.components) == len(sc.ship.components)


# --- runs + exports --------------------------------------------------------

@pytest.fixture(scope="module")
def small_result() -> SimulationResult:
    sc = builders.default_demo_scenario()
    # Shrink the run for speed: bump dt so there are few steps.
    data = builders.scenario_to_editable(sc)
    data["simulation"] = {"dt_hours": 48.0, "backend": "python"}
    sc = builders.validate_scenario(data)
    return builders.run_deterministic(sc)


def test_run_deterministic_via_builders(small_result):
    assert small_result.timeline
    assert 0.0 <= small_result.cumulative_capsize_probability <= 1.0


def test_export_scenario_json_roundtrips():
    sc = builders.default_demo_scenario()
    text = builders.export_scenario_json(sc)
    data = json.loads(text)  # valid JSON
    assert builders.validate_scenario(data) == sc


def test_export_result_json_valid(small_result):
    full = builders.export_result_json(small_result, include_timeline=True)
    reloaded = SimulationResult.model_validate_json(full)
    assert len(reloaded.timeline) == len(small_result.timeline)

    summary = builders.export_result_json(small_result, include_timeline=False)
    reloaded2 = SimulationResult.model_validate_json(summary)
    assert reloaded2.timeline == []
    assert reloaded2.final_corrosion_summary


def test_export_report_markdown(small_result):
    md = builders.export_report_markdown(small_result)
    assert "# Corrosion report" in md
    assert "# Stability & capsizing report" in md
    assert "# Overall risk report" in md


def test_run_monte_carlo_via_builders():
    sc = builders.default_demo_scenario()
    data = builders.scenario_to_editable(sc)
    data["simulation"] = {"dt_hours": 48.0, "backend": "python"}
    sc = builders.validate_scenario(data)
    mc = builders.run_monte_carlo_scenario(sc, n_runs=5, random_seed=1)
    assert mc.n_runs == 5
    for v in mc.samples["cumulative_capsize_probability"]:
        assert 0.0 <= v <= 1.0


def test_backend_lists():
    assert "python" in builders.engine_backends()
    assert "multiprocessing" in builders.monte_carlo_backends()
