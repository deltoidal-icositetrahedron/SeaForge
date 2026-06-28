"""Benchmark the pure-Python engine: timesteps/sec and component-updates/sec.

Run::

    python benchmarks/benchmark_engine.py
    python benchmarks/benchmark_engine.py --components 40 --steps 2000

This measures whether the pure-Python engine is fast enough for normal
scenarios. If it is (it currently is), there is no need for a compiled backend.
"""

from __future__ import annotations

import argparse
import time
import tracemalloc

from ship_sim.config import SimulationConfig
from ship_sim.generation.procedural import (
    ProceduralEnvironmentProvider,
    ProceduralWaveProvider,
    ProceduralWeatherProvider,
)
from ship_sim.models import Material, Ship, ShipComponent, Trajectory, Waypoint
from ship_sim.simulation.engine import ShipSimulationEngine


def build_ship(n_components: int) -> Ship:
    mat = Material(
        name="EH36", density_kg_m3=7850.0, yield_strength_pa=355e6,
        ultimate_strength_pa=490e6, elastic_modulus_pa=210e9,
        base_corrosion_rate_m_per_year=0.00012, galvanic_potential_v=-0.6,
        coating_breakdown_factor=1.2,
    )
    comps = [
        ShipComponent(
            name=f"plate_{i}", material=mat, thickness_m=0.012, area_m2=20.0,
            exposed_fraction=0.5 + 0.5 * (i % 2), structural_importance=1.0,
            vertical_position_m=float(i % 10), original_thickness_m=0.012,
            corrosion_allowance_m=0.003,
        )
        for i in range(n_components)
    ]
    return Ship(
        name="Bench", length_m=120.0, beam_m=18.0, draft_m=6.0,
        displacement_mass_kg=1.2e7, center_of_gravity_height_m=7.0,
        metacentric_height_m=0.9, projected_lateral_area_m2=1000.0,
        roll_natural_period_s=12.0, components=comps,
    )


def build_trajectory(steps: int, dt_s: float) -> Trajectory:
    total = steps * dt_s
    return Trajectory(
        waypoints=[
            Waypoint(latitude_deg=10.0, longitude_deg=-40.0, time_s=0.0, target_speed_m_s=6.0),
            Waypoint(latitude_deg=55.0, longitude_deg=-5.0, time_s=total, target_speed_m_s=6.0),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark the ship_sim engine.")
    parser.add_argument("--components", type=int, default=30)
    parser.add_argument("--steps", type=int, default=1500)
    parser.add_argument("--dt-s", type=float, default=3600.0)
    args = parser.parse_args()

    ship = build_ship(args.components)
    trajectory = build_trajectory(args.steps, args.dt_s)
    engine = ShipSimulationEngine(
        ship=ship, trajectory=trajectory,
        environment_provider=ProceduralEnvironmentProvider(1),
        weather_provider=ProceduralWeatherProvider(1),
        wave_provider=ProceduralWaveProvider(1),
        config=SimulationConfig.default(), dt_s=args.dt_s, backend="python",
    )

    tracemalloc.start()
    t0 = time.perf_counter()
    result = engine.run()
    elapsed = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    n_steps = len(result.timeline)
    n_updates = n_steps * args.components

    print("=== engine benchmark ===")
    print(f"components            : {args.components}")
    print(f"timesteps            : {n_steps}")
    print(f"wall time            : {elapsed:.3f} s")
    print(f"timesteps / sec      : {n_steps / elapsed:,.0f}")
    print(f"component updates/sec : {n_updates / elapsed:,.0f}")
    print(f"peak python memory   : {peak / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
