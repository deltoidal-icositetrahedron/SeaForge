"""GUI-support helpers: scenario assembly, validation, runs, and exports.

This module deliberately contains **no physics and no Streamlit dependency**. It
is the seam between the GUI widgets and the tested simulation core: it turns
plain dicts/tables (as a UI would produce) into validated
:class:`~ship_sim.models.scenario.Scenario` objects, runs the *same* engine /
Monte Carlo / reporting APIs the CLI uses, and serializes results. Keeping it
import-light lets it be unit-tested without launching a GUI.

All validation flows through the existing Pydantic models (via
:func:`ship_sim.io.read_scenario_dict`), so invalid GUI inputs raise the same
field-level errors as a hand-written scenario file.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List, Optional

from ..io import loaded_from_scenario, read_scenario_dict
from ..models.results import SimulationResult
from ..models.scenario import Scenario
from ..reporting.reports import (
    generate_corrosion_report,
    generate_overall_risk_report,
    generate_stability_report,
)
from ..simulation.engine import ShipSimulationEngine
from ..simulation.monte_carlo import MonteCarloResult, run_monte_carlo


# ---------------------------------------------------------------------------
# Backend option lists (kept in sync with the engine / Monte Carlo drivers)
# ---------------------------------------------------------------------------

def engine_backends() -> List[str]:
    """Backends the deterministic engine accepts (currently just 'python')."""
    from ..simulation.engine import _SUPPORTED_BACKENDS

    return list(_SUPPORTED_BACKENDS)


def monte_carlo_backends() -> List[str]:
    """Execution backends the Monte Carlo driver accepts."""
    return ["python", "multiprocessing"]


# ---------------------------------------------------------------------------
# Starting points / round-tripping
# ---------------------------------------------------------------------------

def default_demo_scenario() -> Scenario:
    """A ready-to-edit demo scenario (same vessel/route as the CLI demo)."""
    # Imported lazily to avoid a heavy import chain at module load.
    from ..examples.demo_basic import build_demo_ship, build_demo_trajectory
    from ..models.scenario import ProceduralSettings, SimulationSettings

    return Scenario(
        name="gui_demo_passage",
        description="Editable demo scenario for the dashboard.",
        simulation=SimulationSettings(dt_hours=6.0, backend="python"),
        ship=build_demo_ship(),
        trajectory=build_demo_trajectory(days=10.0),
        procedural=ProceduralSettings(seed=2026),
    )


def scenario_to_editable(scenario: Scenario) -> Dict[str, Any]:
    """Return a plain JSON-able dict the GUI can edit (round-trips via validate)."""
    return scenario.model_dump(mode="json")


def validate_scenario(data: Dict[str, Any]) -> Scenario:
    """Validate an edited scenario dict, raising a readable ``ValueError``."""
    return read_scenario_dict(data)


# ---------------------------------------------------------------------------
# Structural assembly from table-style edits (no physics)
# ---------------------------------------------------------------------------

def inline_components(
    materials: List[Dict[str, Any]], components: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Inline each component's referenced material (by ``material_name``).

    The GUI edits materials and components in separate tables; components refer
    to a material by name. This resolves those references into the nested
    ``material`` object the :class:`Scenario` schema expects.

    Raises ``ValueError`` if a component references an unknown material.
    """
    by_name = {m["name"]: m for m in materials}
    out: List[Dict[str, Any]] = []
    for comp in components:
        comp = dict(comp)
        mat_name = comp.pop("material_name", None)
        if mat_name not in by_name:
            raise ValueError(
                f"component {comp.get('name', '?')!r} references unknown material "
                f"{mat_name!r}; known materials: {sorted(by_name)}."
            )
        comp["material"] = by_name[mat_name]
        out.append(comp)
    return out


def assemble_scenario_dict(
    *,
    name: str,
    description: str = "",
    simulation: Dict[str, Any],
    ship: Dict[str, Any],
    materials: List[Dict[str, Any]],
    components: List[Dict[str, Any]],
    waypoints: List[Dict[str, Any]],
    procedural: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    weather_segments: Optional[List[Dict[str, Any]]] = None,
    wave_segments: Optional[List[Dict[str, Any]]] = None,
    environment_segments: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Assemble a scenario-shaped dict from GUI table edits (not yet validated).

    ``ship`` carries only the hull scalars; ``components`` reference materials by
    ``material_name`` and are inlined here. Pass the result to
    :func:`validate_scenario`.
    """
    ship = dict(ship)
    ship["components"] = inline_components(materials, components)
    data: Dict[str, Any] = {
        "name": name,
        "description": description,
        "simulation": simulation,
        "ship": ship,
        "trajectory": {"waypoints": waypoints},
    }
    if procedural is not None:
        data["procedural"] = procedural
    if config:
        data["config"] = config
    if weather_segments is not None:
        data["weather_segments"] = weather_segments
    if wave_segments is not None:
        data["wave_segments"] = wave_segments
    if environment_segments is not None:
        data["environment_segments"] = environment_segments
    return data


# ---------------------------------------------------------------------------
# Runs (delegate to the same APIs the CLI uses)
# ---------------------------------------------------------------------------

def build_engine(scenario: Scenario) -> ShipSimulationEngine:
    """Build the deterministic engine for an in-memory scenario (CLI path)."""
    return loaded_from_scenario(scenario).build_engine()


def run_deterministic(scenario: Scenario) -> SimulationResult:
    """Run one deterministic simulation and return its result."""
    return build_engine(scenario).run()


def run_monte_carlo_scenario(
    scenario: Scenario,
    n_runs: int,
    random_seed: int,
    backend: str = "python",
) -> MonteCarloResult:
    """Run a Monte Carlo study (delegates to :func:`run_monte_carlo`)."""
    return run_monte_carlo(scenario, n_runs=n_runs, random_seed=random_seed, backend=backend)


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

def export_scenario_json(scenario: Scenario, *, indent: int = 2) -> str:
    """Serialize a scenario to a JSON string (round-trips through the loader)."""
    return scenario.model_dump_json(indent=indent)


def export_result_json(
    result: SimulationResult, *, include_timeline: bool = True, indent: int = 2
) -> str:
    """Serialize a result to JSON; optionally drop the (large) timeline."""
    if not include_timeline:
        result = result.model_copy(update={"timeline": []})
    return result.model_dump_json(indent=indent)


def export_report_markdown(result: SimulationResult) -> str:
    """Combined corrosion + stability + overall Markdown report."""
    return "\n\n".join(
        (
            generate_corrosion_report(result),
            generate_stability_report(result),
            generate_overall_risk_report(result),
        )
    )


def figure_to_png_bytes(fig) -> bytes:
    """Render a Matplotlib figure to PNG bytes (for a GUI download button)."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    return buf.getvalue()


__all__ = [
    "engine_backends",
    "monte_carlo_backends",
    "default_demo_scenario",
    "scenario_to_editable",
    "validate_scenario",
    "inline_components",
    "assemble_scenario_dict",
    "build_engine",
    "run_deterministic",
    "run_monte_carlo_scenario",
    "export_scenario_json",
    "export_result_json",
    "export_report_markdown",
    "figure_to_png_bytes",
]
