"""Benchmark Monte Carlo throughput and the python-vs-numpy corrosion batch.

Run::

    python benchmarks/benchmark_monte_carlo.py
    python benchmarks/benchmark_monte_carlo.py --runs 200 --components 30

Measures:
- Monte Carlo full-simulation runs / sec (perturbed seed + corrosion rate);
- corrosion-batch component updates / sec for the "python" vs "numpy" backends;
- peak memory (tracemalloc).

Use the results to decide whether a compiled backend is warranted. If NumPy
already vectorizes the batch well above your needed throughput, do not add
Rust/C++.
"""

from __future__ import annotations

import argparse
import time
import tracemalloc

from ship_sim.acceleration.backend import ComponentBatch, choose_backend
from ship_sim.config import SimulationConfig
from ship_sim.generation.procedural import (
    ProceduralEnvironmentProvider,
    ProceduralWaveProvider,
    ProceduralWeatherProvider,
)
from ship_sim.models import (
    Material,
    RegionEnvironment,
    Ship,
    ShipComponent,
    Trajectory,
    WaveCondition,
    Waypoint,
    WeatherCondition,
)
from ship_sim.simulation.engine import ShipSimulationEngine


def build_ship(rate_scale: float = 1.0) -> Ship:
    mat = Material(
        name="EH36", density_kg_m3=7850.0, yield_strength_pa=355e6,
        ultimate_strength_pa=490e6, elastic_modulus_pa=210e9,
        base_corrosion_rate_m_per_year=0.00012 * rate_scale,
        galvanic_potential_v=-0.6, coating_breakdown_factor=1.2,
    )
    comps = [
        ShipComponent(name=f"p{i}", material=mat, thickness_m=0.012, area_m2=20.0,
                      exposed_fraction=0.7, original_thickness_m=0.012,
                      corrosion_allowance_m=0.003)
        for i in range(6)
    ]
    return Ship(name="MC", length_m=90.0, beam_m=14.0, draft_m=5.0,
                displacement_mass_kg=4.5e6, center_of_gravity_height_m=5.5,
                metacentric_height_m=0.8, projected_lateral_area_m2=600.0,
                roll_natural_period_s=10.0, components=comps)


def trajectory() -> Trajectory:
    return Trajectory(waypoints=[
        Waypoint(latitude_deg=10.0, longitude_deg=-30.0, time_s=0.0, target_speed_m_s=6.0),
        Waypoint(latitude_deg=40.0, longitude_deg=-10.0, time_s=3600.0 * 24 * 5, target_speed_m_s=6.0),
    ])


def monte_carlo(runs: int, dt_s: float) -> float:
    """Run `runs` full simulations with perturbed seed + corrosion rate."""
    cfg = SimulationConfig.default()
    traj = trajectory()
    rng = __import__("random").Random(0)
    t0 = time.perf_counter()
    for i in range(runs):
        scale = 1.0 + 0.4 * (rng.random() - 0.5)
        ship = build_ship(rate_scale=scale)
        engine = ShipSimulationEngine(
            ship=ship, trajectory=traj,
            environment_provider=ProceduralEnvironmentProvider(i),
            weather_provider=ProceduralWeatherProvider(i),
            wave_provider=ProceduralWaveProvider(i),
            config=cfg, dt_s=dt_s, backend="python",
        )
        engine.run()
    return time.perf_counter() - t0


def batch_throughput(n_components: int, iterations: int):
    """Compare python vs numpy corrosion-batch component-updates/sec."""
    mats = [
        Material(name=f"m{i}", density_kg_m3=7850.0, yield_strength_pa=355e6,
                 ultimate_strength_pa=490e6, elastic_modulus_pa=210e9,
                 base_corrosion_rate_m_per_year=0.0001 * (1 + 0.01 * i),
                 corrosion_resistance_factor=1.0 + 0.1 * (i % 5),
                 galvanic_potential_v=-0.6, coating_breakdown_factor=1.0 + 0.05 * (i % 4))
        for i in range(n_components)
    ]
    comps = [ShipComponent(name=f"c{i}", material=mats[i], thickness_m=0.02,
                           area_m2=10.0, exposed_fraction=0.6, original_thickness_m=0.02)
             for i in range(n_components)]
    batch = ComponentBatch.from_components(comps)
    env = RegionEnvironment(salinity_ppt=36.0, water_temperature_c=24.0, pH=7.8,
                            dissolved_oxygen_mg_l=9.0, pollution_factor_0_1=0.3)
    wx = WeatherCondition(wind_speed_m_s=15.0, wind_direction_deg=80.0,
                          air_temperature_c=20.0, relative_humidity_0_1=0.8,
                          storm_intensity_0_1=0.5)
    wave = WaveCondition(significant_wave_height_m=3.0, peak_period_s=8.0,
                         mean_wave_direction_deg=0.0, current_speed_m_s=0.8)
    cfg = SimulationConfig.default()
    out = {}
    for name in ("python", "numpy"):
        backend = choose_backend(name)
        t0 = time.perf_counter()
        for _ in range(iterations):
            backend.corrosion_rate_batch(batch, env, wx, wave, 6.0, cfg)
        dt = time.perf_counter() - t0
        out[name] = (n_components * iterations) / dt
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Monte Carlo / batch benchmark.")
    parser.add_argument("--runs", type=int, default=120)
    parser.add_argument("--dt-s", type=float, default=3600.0 * 6)
    parser.add_argument("--components", type=int, default=200)
    parser.add_argument("--batch-iters", type=int, default=2000)
    args = parser.parse_args()

    tracemalloc.start()
    elapsed = monte_carlo(args.runs, args.dt_s)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print("=== Monte Carlo benchmark ===")
    print(f"runs                 : {args.runs}")
    print(f"wall time            : {elapsed:.3f} s")
    print(f"MC runs / sec        : {args.runs / elapsed:,.1f}")
    print(f"peak python memory   : {peak / 1e6:.1f} MB")

    print("\n=== corrosion batch throughput (component updates / sec) ===")
    tp = batch_throughput(args.components, args.batch_iters)
    for name, ups in tp.items():
        print(f"{name:7s} : {ups:,.0f} updates/sec")
    if tp.get("python"):
        print(f"numpy speedup        : {tp['numpy'] / tp['python']:.1f}x")


if __name__ == "__main__":
    main()
