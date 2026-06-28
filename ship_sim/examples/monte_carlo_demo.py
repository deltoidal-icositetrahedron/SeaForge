"""Monte Carlo uncertainty demo.

Runs many perturbed simulations of the built-in demo vessel and prints
uncertainty ranges plus a simple sensitivity ranking (which uncertain inputs
most influence the maximum stability risk).

Run::

    python -m ship_sim.examples.monte_carlo_demo
    python examples/monte_carlo_demo.py --runs 100 --backend multiprocessing
"""

from __future__ import annotations

import argparse
import time

from ship_sim import DISCLAIMER
from ship_sim.examples.demo_basic import build_demo_ship, build_demo_trajectory
from ship_sim.models import ProceduralSettings, Scenario, SimulationSettings
from ship_sim.simulation.monte_carlo import run_monte_carlo

# Friendly names for the perturbed inputs (for the sensitivity table).
_INPUT_LABELS = {
    "corrosion_rate_mult": "material corrosion rate",
    "coating_mult": "coating breakdown",
    "salinity_off": "salinity",
    "ph_off": "pH",
    "do_mult": "dissolved oxygen",
    "wave_height_mult": "wave height",
    "wave_period_mult": "wave period",
    "wind_mult": "wind speed",
    "storm_off": "storm intensity",
    "mass_mult": "ship mass",
    "kg_mult": "center of gravity (KG)",
    "gm_mult": "metacentric height (GM)",
}


def build_demo_scenario(dt_hours: float, seed: int) -> Scenario:
    return Scenario(
        name="monte_carlo_demo",
        description="Uncertainty study of the built-in demo passage.",
        simulation=SimulationSettings(dt_hours=dt_hours),
        ship=build_demo_ship(),
        trajectory=build_demo_trajectory(days=10.0),
        procedural=ProceduralSettings(seed=seed),
    )


def _fmt_range(d: dict, scale: float = 1.0, unit: str = "") -> str:
    return (f"p50 {d['p50'] * scale:.3f}  "
            f"[p5 {d['p5'] * scale:.3f} .. p95 {d['p95'] * scale:.3f}]  "
            f"mean {d['mean'] * scale:.3f} +/- {d['std'] * scale:.3f}{unit}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Monte Carlo uncertainty demo.")
    parser.add_argument("--runs", type=int, default=100)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--dt-hours", type=float, default=12.0)
    parser.add_argument("--backend", choices=["python", "multiprocessing"],
                        default="multiprocessing")
    args = parser.parse_args(argv)

    scenario = build_demo_scenario(args.dt_hours, args.seed)

    print("=" * 74)
    print(f"Monte Carlo uncertainty: {scenario.name}  ({args.runs} runs, "
          f"backend={args.backend})")
    print("=" * 74)
    print(DISCLAIMER)
    print("-" * 74)

    t0 = time.perf_counter()
    result = run_monte_carlo(scenario, n_runs=args.runs, random_seed=args.seed,
                             backend=args.backend)
    elapsed = time.perf_counter() - t0
    print(f"Completed {result.n_runs} runs in {elapsed:.2f} s "
          f"({result.n_runs / elapsed:.1f} runs/s)\n")

    print("Uncertainty ranges:")
    print(f"  max stability risk           : "
          f"{_fmt_range(result.distribution('max_stability_risk'))}")
    print(f"  cumulative capsize prob.     : "
          f"{_fmt_range(result.distribution('cumulative_capsize_probability'))}")
    tmax = result.distribution("time_of_max_risk_s")
    print(f"  time of max risk (days)      : "
          f"p50 {tmax['p50']/86400:.2f}  "
          f"[p5 {tmax['p5']/86400:.2f} .. p95 {tmax['p95']/86400:.2f}]")
    print(f"  number of warnings           : "
          f"{_fmt_range(result.distribution('n_warnings'))}")

    print("\n  final corrosion by component (metal loss, mm):")
    for name, values in result.corrosion_by_component.items():
        d = result.percentiles(values)
        print(f"    {name:24s} {_fmt_range(d, scale=1e3, unit=' mm')}")

    print("\nSensitivity (Pearson corr. with max stability risk; |r| ranked):")
    for name, corr in result.sensitivity("max_stability_risk"):
        label = _INPUT_LABELS.get(name, name)
        bar = "#" * int(round(abs(corr) * 30))
        print(f"  {label:24s} r={corr:+.3f}  {bar}")

    print("-" * 74)
    print("(Engineering approximation; correlations are sample-based with "
          f"n={result.n_runs}.)")


if __name__ == "__main__":
    main()
