"""Runnable demo of the ship_sim corrosion + stability simulation.

Two ways to run:

    # built-in procedural demo scenario
    python -m ship_sim.examples.demo_basic
    python examples/demo_basic.py

    # load a scenario JSON
    python -m ship_sim.examples.demo_basic --scenario examples/scenario_basic.json
    python examples/demo_basic.py --scenario examples/scenario_basic.json

Options:
    --scenario PATH   load inputs from a scenario JSON instead of the built-in demo
    --out PATH        where to write the result JSON (default: examples/result_basic.json)
    --no-timeline     save result summaries only (omit the per-step timeline)
    --dt-hours H      override the timestep (built-in demo only)
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from ship_sim import DISCLAIMER, units
from ship_sim.config import SimulationConfig
from ship_sim.generation.procedural import (
    ProceduralEnvironmentProvider,
    ProceduralWaveProvider,
    ProceduralWeatherProvider,
)
from ship_sim.io import load_scenario, save_result
from ship_sim.models import Material, Ship, ShipComponent, Trajectory, Waypoint
from ship_sim.simulation.engine import ShipSimulationEngine
from ship_sim.simulation.timestep import interpolate_position

SEED = 2026


# ---------------------------------------------------------------------------
# Built-in demo inputs
# ---------------------------------------------------------------------------

def build_demo_ship() -> Ship:
    """A small coastal patrol vessel: steel hull + aluminium superstructure."""
    hull_steel = Material(
        name="EH36 high-strength hull steel", density_kg_m3=7850.0,
        yield_strength_pa=355e6, ultimate_strength_pa=490e6, elastic_modulus_pa=210e9,
        base_corrosion_rate_m_per_year=0.00012, galvanic_potential_v=-0.61,
        coating_breakdown_factor=1.0, fatigue_strength_pa=160e6,
    )
    alloy = Material(
        name="5083 marine aluminium", density_kg_m3=2660.0,
        yield_strength_pa=215e6, ultimate_strength_pa=305e6, elastic_modulus_pa=70e9,
        base_corrosion_rate_m_per_year=0.00002, corrosion_resistance_factor=3.0,
        galvanic_potential_v=-0.94, coating_breakdown_factor=0.8,
    )
    components = [
        ShipComponent(name="bottom_plating", material=hull_steel, thickness_m=0.0140,
                      area_m2=520.0, structural_importance=1.0,
                      location_on_ship="bottom_shell", vertical_position_m=0.2,
                      original_thickness_m=0.0140, corrosion_allowance_m=0.0030,
                      safety_factor_required=1.6),
        ShipComponent(name="side_shell_waterline", material=hull_steel, thickness_m=0.0120,
                      area_m2=380.0, structural_importance=0.9,
                      location_on_ship="side_shell", vertical_position_m=4.5,
                      original_thickness_m=0.0120, corrosion_allowance_m=0.0025),
        ShipComponent(name="main_deck", material=hull_steel, thickness_m=0.0100,
                      area_m2=300.0, exposed_fraction=0.6, structural_importance=0.8,
                      location_on_ship="strength_deck", vertical_position_m=8.5,
                      original_thickness_m=0.0100, corrosion_allowance_m=0.0020),
        ShipComponent(name="superstructure_front", material=alloy, thickness_m=0.0060,
                      area_m2=90.0, exposed_fraction=0.5, structural_importance=0.3,
                      location_on_ship="superstructure", vertical_position_m=12.0,
                      original_thickness_m=0.0060, corrosion_allowance_m=0.0010,
                      safety_factor_required=1.4),
    ]
    return Ship(
        name="PV Sentinel", length_m=72.0, beam_m=12.5, draft_m=4.2,
        displacement_mass_kg=2.4e6, center_of_gravity_height_m=5.1,
        metacentric_height_m=0.85, waterplane_area_m2=620.0,
        projected_lateral_area_m2=540.0, roll_natural_period_s=9.5,
        components=components,
    )


def build_demo_trajectory(days: float = 10.0) -> Trajectory:
    """A multi-day passage from low to high latitude (warm -> cold seas)."""
    cruise = units.knots_to_mps(14.0)
    slow = units.knots_to_mps(9.0)
    h = units.hours_to_seconds
    return Trajectory(
        waypoints=[
            Waypoint(latitude_deg=12.0, longitude_deg=-40.0, time_s=0.0,
                     target_speed_m_s=slow, heading_deg=20.0),
            Waypoint(latitude_deg=28.0, longitude_deg=-30.0, time_s=h(days * 24 * 0.35),
                     target_speed_m_s=cruise, heading_deg=25.0),
            Waypoint(latitude_deg=44.0, longitude_deg=-18.0, time_s=h(days * 24 * 0.75),
                     target_speed_m_s=cruise, heading_deg=35.0),
            Waypoint(latitude_deg=54.0, longitude_deg=-8.0, time_s=h(days * 24),
                     target_speed_m_s=slow, heading_deg=45.0),
        ]
    )


def _built_in_engine(dt_hours: float) -> tuple[ShipSimulationEngine, str, Trajectory]:
    ship = build_demo_ship()
    trajectory = build_demo_trajectory(days=10.0)
    engine = ShipSimulationEngine(
        ship=ship, trajectory=trajectory,
        environment_provider=ProceduralEnvironmentProvider(SEED),
        weather_provider=ProceduralWeatherProvider(SEED),
        wave_provider=ProceduralWaveProvider(SEED),
        config=SimulationConfig.default(),
        dt_s=units.hours_to_seconds(dt_hours), backend="python",
    )
    return engine, "demo_procedural_passage", trajectory


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _bar(value: float, width: int = 20) -> str:
    n = int(round(max(0.0, min(1.0, value)) * width))
    return "#" * n + "-" * (width - n)


def print_summary(name: str, trajectory: Trajectory, result, dt_s: float) -> None:
    print("=" * 74)
    print(f"ship_sim simulation: {name}")
    print("=" * 74)
    print(DISCLAIMER)
    print("-" * 74)
    duration_h = units.seconds_to_hours(trajectory.duration_s)
    print(f"Route: {len(trajectory.waypoints)} waypoints, {duration_h / 24:.1f} days, "
          f"dt = {units.seconds_to_hours(dt_s):.1f} h, {len(result.timeline)} steps")

    print("\nCorrosion (end of voyage):")
    cs = result.final_corrosion_summary
    print(f"  {'component':24s} {'loss %':>7} {'eff. mm':>8} {'rate mm/yr':>11} {'min SF':>7}")
    for cname, c in cs["by_component"].items():
        print(f"  {cname:24s} {c['thickness_loss_fraction']*100:7.2f} "
              f"{c['final_effective_thickness_m']*1e3:8.2f} "
              f"{c['final_corrosion_rate_mm_per_year']:11.3f} "
              f"{c['min_safety_margin']:7.2f}")
    print(f"  most corroded: {cs['most_corroded_component']}")
    dom = ", ".join(f"{d['factor']}={d['mean_value']:.2f}"
                    for d in cs["dominant_environmental_factors"][:4])
    print(f"  dominant corrosion drivers (mean factor): {dom}")

    ss = result.final_stability_summary
    print("\nStability / capsizing:")
    print(f"  max risk score   : {ss['max_risk_score']:.3f}  [{_bar(ss['max_risk_score'])}]")
    if ss["time_of_max_risk_s"] is not None:
        pos = interpolate_position(trajectory, ss["time_of_max_risk_s"])
        print(f"  at               : t={units.seconds_to_hours(ss['time_of_max_risk_s'])/24:.2f} d, "
              f"lat {pos.latitude_deg:.1f}, lon {pos.longitude_deg:.1f}")
    contribs = ss.get("max_risk_dominant_contributions", {}) or {}
    top = sorted(contribs.items(), key=lambda kv: kv[1], reverse=True)[:4]
    print("  dominant risk contributions: " + ", ".join(f"{k}={v:.2f}" for k, v in top))
    print(f"  cumulative capsize probability: {result.cumulative_capsize_probability:.4f}")

    print(f"\nWarning events ({len(result.warnings)}):")
    for w in result.warnings[:8]:
        print(f"  - {w}")
    if len(result.warnings) > 8:
        print(f"  ... and {len(result.warnings) - 8} more")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Run a ship_sim simulation.")
    parser.add_argument("--scenario", type=str, default=None,
                        help="Path to a scenario JSON (else use the built-in demo).")
    parser.add_argument("--out", type=str, default=None,
                        help="Output result JSON path (default: examples/result_basic.json).")
    parser.add_argument("--no-timeline", action="store_true",
                        help="Save result summaries only (omit per-step timeline).")
    parser.add_argument("--dt-hours", type=float, default=6.0,
                        help="Timestep in hours for the built-in demo (default 6).")
    parser.add_argument("--report", action="store_true",
                        help="Also print the full Markdown corrosion/stability/overall reports.")
    args = parser.parse_args(argv)

    if args.scenario:
        loaded = load_scenario(args.scenario)
        engine = loaded.build_engine()
        name, trajectory, dt_s = loaded.name, loaded.trajectory, loaded.dt_s
    else:
        engine, name, trajectory = _built_in_engine(args.dt_hours)
        dt_s = engine.dt_s

    result = engine.run()
    print_summary(name, trajectory, result, dt_s)

    if args.report:
        from ship_sim.reporting.reports import (
            generate_corrosion_report,
            generate_overall_risk_report,
            generate_stability_report,
        )
        print("\n" + "=" * 74 + "\nREPORTS\n" + "=" * 74)
        print("\n" + generate_corrosion_report(result))
        print("\n" + generate_stability_report(result))
        print("\n" + generate_overall_risk_report(result))

    out = Path(args.out) if args.out else Path("examples/result_basic.json")
    save_result(result, out, include_timeline=not args.no_timeline)
    print("-" * 74)
    print(f"Results -> {out}"
          + ("  (summaries only)" if args.no_timeline else "  (with full timeline)"))
    print("(Engineering approximation; see 'assumptions' in the result file.)")


if __name__ == "__main__":
    main()
