"""Tests for scenario loading/assembly and result/config writing."""

from __future__ import annotations

import json

import pytest

from ship_sim.config import SimulationConfig
from ship_sim.generation.procedural import (
    ProceduralWeatherProvider,
    SegmentedWeatherProvider,
)
from ship_sim.io import (
    load_config,
    load_scenario,
    read_scenario,
    read_scenario_dict,
    save_config,
    save_result,
    save_scenario,
)
from ship_sim.models import (
    Material,
    Ship,
    ShipComponent,
    Trajectory,
    Waypoint,
)
from ship_sim.simulation.engine import ShipSimulationEngine


def make_ship() -> Ship:
    steel = Material(
        name="EH36", density_kg_m3=7850.0, yield_strength_pa=355e6,
        ultimate_strength_pa=490e6, elastic_modulus_pa=210e9,
        base_corrosion_rate_m_per_year=0.0001, galvanic_potential_v=-0.6,
    )
    comp = ShipComponent(
        name="bottom_plating", material=steel, thickness_m=0.02, area_m2=100.0,
        original_thickness_m=0.02, corrosion_allowance_m=0.003,
    )
    return Ship(
        name="MV Test", length_m=90.0, beam_m=14.0, draft_m=5.0,
        displacement_mass_kg=4.5e6, center_of_gravity_height_m=5.5,
        metacentric_height_m=0.8, projected_lateral_area_m2=600.0,
        roll_natural_period_s=10.0, components=[comp],
    )


def make_trajectory() -> Trajectory:
    return Trajectory(
        waypoints=[
            Waypoint(latitude_deg=36.0, longitude_deg=-5.0, time_s=0.0, target_speed_m_s=6.0),
            Waypoint(latitude_deg=37.0, longitude_deg=-7.0, time_s=72000.0, target_speed_m_s=6.0),
        ]
    )


def base_scenario_dict(**overrides) -> dict:
    data = {
        "name": "roundtrip",
        "simulation": {"dt_hours": 1.0, "backend": "python"},
        "ship": make_ship().model_dump(mode="json"),
        "trajectory": make_trajectory().model_dump(mode="json"),
        "procedural": {"seed": 5},
    }
    data.update(overrides)
    return data


# --- validation / round-trip ----------------------------------------------

def test_scenario_roundtrip(tmp_path):
    scenario = read_scenario_dict(base_scenario_dict())
    path = tmp_path / "scenario.json"
    save_scenario(scenario, path)
    reloaded = read_scenario(path)
    assert reloaded == scenario


def test_dt_hours_converted_to_si():
    scenario = read_scenario_dict(base_scenario_dict(simulation={"dt_hours": 2.0}))
    assert scenario.simulation.resolved_dt_s == 7200.0


def test_dt_seconds_takes_precedence():
    scenario = read_scenario_dict(
        base_scenario_dict(simulation={"dt_s": 1800.0, "dt_hours": 99.0})
    )
    assert scenario.simulation.resolved_dt_s == 1800.0


def test_missing_dt_raises_clear_error():
    with pytest.raises(ValueError) as exc:
        read_scenario_dict(base_scenario_dict(simulation={"backend": "python"}))
    assert "dt_s" in str(exc.value) or "dt_hours" in str(exc.value)


def test_missing_required_field_message(tmp_path):
    data = base_scenario_dict()
    del data["ship"]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError) as exc:
        read_scenario(path)
    assert "ship" in str(exc.value)


def test_config_overrides_applied_partial():
    data = base_scenario_dict(config={"corrosion": {"splash_zone_multiplier": 3.0}})
    scenario = read_scenario_dict(data)
    assert scenario.config.corrosion.splash_zone_multiplier == 3.0
    # Untouched fields keep their documented defaults.
    assert scenario.config.corrosion.pollution_multiplier == 0.5


# --- assembly into engine objects -----------------------------------------

def test_load_scenario_builds_procedural_providers(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps(base_scenario_dict()))
    loaded = load_scenario(path)
    assert isinstance(loaded.weather_provider, ProceduralWeatherProvider)
    assert loaded.dt_s == 3600.0
    assert loaded.backend == "python"
    engine = loaded.build_engine()
    assert isinstance(engine, ShipSimulationEngine)
    result = engine.run()
    assert len(result.timeline) == ShipSimulationEngine.n_steps(loaded.trajectory, 3600.0)


def test_load_scenario_uses_segmented_provider_when_segments_present(tmp_path):
    weather = {
        "wind_speed_m_s": 12.0, "wind_direction_deg": 90.0,
        "air_temperature_c": 15.0, "relative_humidity_0_1": 0.7,
        "storm_intensity_0_1": 0.2,
    }
    data = base_scenario_dict(
        weather_segments=[{"condition": weather}]  # catch-all segment
    )
    path = tmp_path / "s.json"
    path.write_text(json.dumps(data))
    loaded = load_scenario(path)
    assert isinstance(loaded.weather_provider, SegmentedWeatherProvider)
    # Procedural still used for the channels without segments.
    assert not isinstance(loaded.environment_provider, SegmentedWeatherProvider)


def test_segment_time_hours_converted(tmp_path):
    weather = {
        "wind_speed_m_s": 12.0, "wind_direction_deg": 90.0,
        "air_temperature_c": 15.0, "relative_humidity_0_1": 0.7,
        "storm_intensity_0_1": 0.2,
    }
    data = base_scenario_dict(
        weather_segments=[
            {"condition": weather, "start_time_hours": 0.0, "end_time_hours": 2.0}
        ]
    )
    scenario = read_scenario_dict(data)
    seg = scenario.weather_segments[0]
    assert seg.resolved_start_s == 0.0
    assert seg.resolved_end_s == 7200.0


def test_unknown_procedural_range_override_rejected(tmp_path):
    data = base_scenario_dict(procedural={"seed": 1, "ranges": {"not_a_field": 1.0}})
    path = tmp_path / "s.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError) as exc:
        load_scenario(path)
    assert "not_a_field" in str(exc.value)


# --- result / config writing ----------------------------------------------

def _run_small_result():
    loaded = load_scenario_dict_to_loaded()
    return loaded.build_engine().run()


def load_scenario_dict_to_loaded():
    # Helper: write a temp-free LoadedScenario via providers from a dict.
    from ship_sim.io.scenario_loader import build_providers

    scenario = read_scenario_dict(base_scenario_dict())
    env_p, wx_p, wave_p = build_providers(scenario)
    from ship_sim.io.scenario_loader import LoadedScenario

    return LoadedScenario(
        name=scenario.name, description="", ship=scenario.ship,
        trajectory=scenario.trajectory, environment_provider=env_p,
        weather_provider=wx_p, wave_provider=wave_p, config=scenario.config,
        dt_s=scenario.simulation.resolved_dt_s, backend=scenario.simulation.backend,
        scenario=scenario,
    )


def test_save_result_with_and_without_timeline(tmp_path):
    from ship_sim.models.results import SimulationResult

    result = _run_small_result()
    assert len(result.timeline) > 0

    full = tmp_path / "full.json"
    save_result(result, full, include_timeline=True)
    reloaded_full = SimulationResult.model_validate_json(full.read_text())
    assert len(reloaded_full.timeline) == len(result.timeline)

    summary = tmp_path / "summary.json"
    save_result(result, summary, include_timeline=False)
    reloaded_summary = SimulationResult.model_validate_json(summary.read_text())
    assert reloaded_summary.timeline == []
    # Summaries survive even without the timeline.
    assert reloaded_summary.final_corrosion_summary
    assert reloaded_summary.final_stability_summary


def test_config_roundtrip(tmp_path):
    cfg = SimulationConfig.default()
    cfg.corrosion.salinity_sensitivity = 0.05
    path = tmp_path / "config.json"
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded == cfg
    assert loaded.corrosion.salinity_sensitivity == 0.05
