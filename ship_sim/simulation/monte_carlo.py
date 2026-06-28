"""Monte Carlo uncertainty propagation for ship simulations.

This module is **separate from the deterministic engine**: it only *orchestrates*
repeated :class:`~ship_sim.simulation.engine.ShipSimulationEngine` runs with
perturbed inputs and aggregates the resulting distributions. The engine itself is
untouched and deterministic.

Each run perturbs the uncertain inputs called out in the spec:

- material base corrosion rates and coating breakdown (lognormal multipliers),
- salinity, pH (additive), dissolved oxygen (multiplier),
- significant wave height, peak period, wind speed (multipliers),
- storm intensity (additive),
- ship mass, center-of-gravity height (KG), metacentric height (GM) (multipliers).

Perturbation is **source-agnostic**: condition perturbations are applied by
wrapping whatever providers the scenario uses (procedural *or* user segments),
and procedural providers are additionally re-seeded per run for natural metocean
variability. Reproducibility is guaranteed by deriving an independent
``SeedSequence`` per run from ``random_seed`` (so results are identical whether
runs execute serially or in parallel).

Returned distributions (with p5/p50/p95/mean/std percentiles) cover:

- final corrosion (accumulated metal loss) by component,
- maximum stability-risk score,
- cumulative capsize probability,
- time of maximum risk,
- number of warnings.

A simple Pearson-correlation sensitivity analysis ranks which uncertain inputs
most influence a chosen output (default: max stability risk).

Performance: ``backend="multiprocessing"`` parallelizes runs with the stdlib
(no extra dependency; ``joblib`` would be a drop-in alternative). The inner
numeric kernels are already fast (see ``benchmarks/``), so a Numba/Rust/C++
backend would only be considered if profiling a very large study demanded it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .._math import clamp
from ..config import MonteCarloConfig
from ..generation.procedural import (
    ProceduralEnvironmentProvider,
    ProceduralWaveProvider,
    ProceduralWeatherProvider,
)
from ..models.ship import Ship
from .engine import ShipSimulationEngine


# ---------------------------------------------------------------------------
# Perturbation specification
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PerturbationSpec:
    """Standard deviations for each perturbed input (rel = multiplicative)."""

    corrosion_rate_rel_std: float = 0.20
    coating_breakdown_rel_std: float = 0.20
    salinity_abs_std: float = 1.0          # ppt
    ph_abs_std: float = 0.10
    dissolved_oxygen_rel_std: float = 0.15
    wave_height_rel_std: float = 0.15
    wave_period_rel_std: float = 0.10
    wind_speed_rel_std: float = 0.15
    storm_abs_std: float = 0.10
    mass_rel_std: float = 0.03
    cog_height_rel_std: float = 0.05
    metacentric_height_rel_std: float = 0.15

    @classmethod
    def from_config(cls, mc: MonteCarloConfig) -> "PerturbationSpec":
        """Seed the overlapping std devs from a MonteCarloConfig; keep defaults else."""
        return cls(
            corrosion_rate_rel_std=mc.corrosion_rate_rel_std,
            wave_height_rel_std=mc.wave_height_rel_std,
            wind_speed_rel_std=mc.wind_speed_rel_std,
        )

    def draw(self, rng: np.random.Generator) -> Dict[str, float]:
        """Draw one set of perturbation factors/offsets."""
        def logn(s: float) -> float:
            return float(math.exp(rng.normal(0.0, s))) if s > 0 else 1.0

        def norm(s: float) -> float:
            return float(rng.normal(0.0, s)) if s > 0 else 0.0

        return {
            "corrosion_rate_mult": logn(self.corrosion_rate_rel_std),
            "coating_mult": logn(self.coating_breakdown_rel_std),
            "salinity_off": norm(self.salinity_abs_std),
            "ph_off": norm(self.ph_abs_std),
            "do_mult": logn(self.dissolved_oxygen_rel_std),
            "wave_height_mult": logn(self.wave_height_rel_std),
            "wave_period_mult": logn(self.wave_period_rel_std),
            "wind_mult": logn(self.wind_speed_rel_std),
            "storm_off": norm(self.storm_abs_std),
            "mass_mult": logn(self.mass_rel_std),
            "kg_mult": logn(self.cog_height_rel_std),
            "gm_mult": logn(self.metacentric_height_rel_std),
        }


# ---------------------------------------------------------------------------
# Perturbing provider wrappers (module-level => picklable for multiprocessing)
# ---------------------------------------------------------------------------

class _PerturbedEnvironmentProvider:
    def __init__(self, base, salinity_off, ph_off, do_mult):
        self.base = base
        self.salinity_off = salinity_off
        self.ph_off = ph_off
        self.do_mult = do_mult

    def at(self, position, time_s):
        c = self.base.at(position, time_s)
        return c.model_copy(update={
            "salinity_ppt": max(0.0, c.salinity_ppt + self.salinity_off),
            "pH": clamp(c.pH + self.ph_off, 6.0, 9.5),
            "dissolved_oxygen_mg_l": max(0.0, c.dissolved_oxygen_mg_l * self.do_mult),
        })


class _PerturbedWeatherProvider:
    def __init__(self, base, wind_mult, storm_off):
        self.base = base
        self.wind_mult = wind_mult
        self.storm_off = storm_off

    def at(self, position, time_s):
        c = self.base.at(position, time_s)
        return c.model_copy(update={
            "wind_speed_m_s": max(0.0, c.wind_speed_m_s * self.wind_mult),
            "storm_intensity_0_1": clamp(c.storm_intensity_0_1 + self.storm_off, 0.0, 1.0),
        })


class _PerturbedWaveProvider:
    def __init__(self, base, height_mult, period_mult):
        self.base = base
        self.height_mult = height_mult
        self.period_mult = period_mult

    def at(self, position, time_s, weather):
        c = self.base.at(position, time_s, weather)
        return c.model_copy(update={
            "significant_wave_height_m": max(0.0, c.significant_wave_height_m * self.height_mult),
            "peak_period_s": max(0.1, c.peak_period_s * self.period_mult),
        })


def _maybe_reseed(provider, seed: int):
    """Return a re-seeded copy for procedural providers; pass others through."""
    if isinstance(provider, ProceduralWeatherProvider):
        return ProceduralWeatherProvider(seed, provider.ranges)
    if isinstance(provider, ProceduralWaveProvider):
        return ProceduralWaveProvider(seed, provider.ranges)
    if isinstance(provider, ProceduralEnvironmentProvider):
        return ProceduralEnvironmentProvider(seed, provider.ranges)
    return provider


def _perturb_ship(ship: Ship, draws: Dict[str, float]) -> Ship:
    """Return a deep-copied ship with mass/KG/GM and material properties scaled."""
    sp = ship.model_copy(deep=True)
    sp.displacement_mass_kg = ship.displacement_mass_kg * draws["mass_mult"]
    sp.center_of_gravity_height_m = ship.center_of_gravity_height_m * draws["kg_mult"]
    sp.metacentric_height_m = ship.metacentric_height_m * draws["gm_mult"]
    for comp in sp.components:
        comp.material.base_corrosion_rate_m_per_year = (
            comp.material.base_corrosion_rate_m_per_year * draws["corrosion_rate_mult"]
        )
        comp.material.coating_breakdown_factor = (
            comp.material.coating_breakdown_factor * draws["coating_mult"]
        )
    return sp


# ---------------------------------------------------------------------------
# Single run (top-level for picklability)
# ---------------------------------------------------------------------------

@dataclass
class _RunArgs:
    ship: Ship
    trajectory: Any
    env_provider: Any
    weather_provider: Any
    wave_provider: Any
    config: Any
    dt_s: float
    seedseq: np.random.SeedSequence
    spec: PerturbationSpec


def _single_run(args: _RunArgs) -> Dict[str, Any]:
    rng = np.random.default_rng(args.seedseq)
    draws = args.spec.draw(rng)
    reseed = int(rng.integers(0, 2**31 - 1))

    ship_p = _perturb_ship(args.ship, draws)
    env_p = _PerturbedEnvironmentProvider(
        _maybe_reseed(args.env_provider, reseed + 1),
        draws["salinity_off"], draws["ph_off"], draws["do_mult"],
    )
    weather_p = _PerturbedWeatherProvider(
        _maybe_reseed(args.weather_provider, reseed + 2),
        draws["wind_mult"], draws["storm_off"],
    )
    wave_p = _PerturbedWaveProvider(
        _maybe_reseed(args.wave_provider, reseed + 3),
        draws["wave_height_mult"], draws["wave_period_mult"],
    )

    engine = ShipSimulationEngine(
        ship=ship_p, trajectory=args.trajectory,
        environment_provider=env_p, weather_provider=weather_p, wave_provider=wave_p,
        config=args.config, dt_s=args.dt_s, backend="python",
    )
    result = engine.run()

    ss = result.final_stability_summary
    cs = result.final_corrosion_summary
    return {
        "max_stability_risk": float(ss.get("max_risk_score", 0.0)),
        "cumulative_capsize_probability": float(result.cumulative_capsize_probability),
        "time_of_max_risk_s": float(ss.get("time_of_max_risk_s") or 0.0),
        "n_warnings": float(len(result.warnings)),
        "corrosion_by_component": {
            name: float(c.get("accumulated_corrosion_m", 0.0))
            for name, c in cs.get("by_component", {}).items()
        },
        "inputs": draws,
    }


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class MonteCarloResult:
    """Aggregated Monte Carlo distributions and sensitivity helpers."""

    n_runs: int
    random_seed: int
    samples: Dict[str, List[float]]              # scalar metric -> samples
    corrosion_by_component: Dict[str, List[float]]  # component -> accumulated-loss samples
    input_samples: Dict[str, List[float]]        # perturbation input -> samples

    @staticmethod
    def percentiles(values: List[float]) -> Dict[str, float]:
        """Return p5/p50/p95/mean/std for a sample list (ordered by construction)."""
        arr = np.asarray(values, dtype=float)
        p5, p50, p95 = (float(x) for x in np.percentile(arr, [5, 50, 95]))
        return {
            "p5": p5, "p50": p50, "p95": p95,
            "mean": float(arr.mean()), "std": float(arr.std(ddof=0)),
        }

    def distribution(self, metric: str) -> Dict[str, float]:
        return self.percentiles(self.samples[metric])

    def summary(self) -> Dict[str, Dict[str, float]]:
        """Percentile summary for every metric and per-component corrosion."""
        out: Dict[str, Dict[str, float]] = {
            metric: self.percentiles(values) for metric, values in self.samples.items()
        }
        for name, values in self.corrosion_by_component.items():
            out[f"corrosion[{name}]_m"] = self.percentiles(values)
        return out

    def sensitivity(self, target: str = "max_stability_risk") -> List[Tuple[str, float]]:
        """Pearson correlation of each input with `target`, ranked by |corr|.

        A simple, transparent sensitivity measure: which uncertain inputs most
        move the output. Inputs/targets with zero variance get correlation 0.
        """
        y = np.asarray(self.samples[target], dtype=float)
        ranked: List[Tuple[str, float]] = []
        for name, xs in self.input_samples.items():
            x = np.asarray(xs, dtype=float)
            if x.std() == 0.0 or y.std() == 0.0:
                corr = 0.0
            else:
                corr = float(np.corrcoef(x, y)[0, 1])
                if not math.isfinite(corr):
                    corr = 0.0
            ranked.append((name, corr))
        ranked.sort(key=lambda kv: abs(kv[1]), reverse=True)
        return ranked


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def _as_engine_inputs(base_scenario):
    """Extract (name, ship, trajectory, env, weather, wave, config, dt_s) from a
    LoadedScenario or a Scenario."""
    # Lazy imports to avoid any import cycle at package load.
    from ..io.scenario_loader import LoadedScenario, build_providers
    from ..models.scenario import Scenario

    if isinstance(base_scenario, LoadedScenario):
        ls = base_scenario
        return (ls.ship, ls.trajectory, ls.environment_provider,
                ls.weather_provider, ls.wave_provider, ls.config, ls.dt_s)
    if isinstance(base_scenario, Scenario):
        env_p, weather_p, wave_p = build_providers(base_scenario)
        return (base_scenario.ship, base_scenario.trajectory, env_p, weather_p,
                wave_p, base_scenario.config, base_scenario.simulation.resolved_dt_s)
    raise TypeError(
        "base_scenario must be a Scenario or LoadedScenario; got "
        f"{type(base_scenario).__name__}."
    )


def run_monte_carlo(
    base_scenario,
    n_runs: int,
    random_seed: int,
    backend: str = "python",
    *,
    perturbation: Optional[PerturbationSpec] = None,
    n_jobs: Optional[int] = None,
) -> MonteCarloResult:
    """Run ``n_runs`` perturbed simulations and aggregate the distributions.

    Parameters
    ----------
    base_scenario:
        A :class:`~ship_sim.models.scenario.Scenario` or
        :class:`~ship_sim.io.scenario_loader.LoadedScenario`.
    n_runs:
        Number of Monte Carlo runs (>= 1).
    random_seed:
        Master seed; per-run seeds are spawned from it for reproducibility.
    backend:
        ``"python"`` (serial) or ``"multiprocessing"`` (parallel via stdlib).
    perturbation:
        Optional :class:`PerturbationSpec`; defaults to one derived from
        ``base_scenario``'s ``config.monte_carlo``.
    n_jobs:
        Worker count for multiprocessing (default: all CPUs).
    """
    if n_runs < 1:
        raise ValueError("n_runs must be >= 1.")
    if backend not in ("python", "multiprocessing"):
        raise ValueError(
            f"unknown Monte Carlo backend {backend!r}; use 'python' or 'multiprocessing'."
        )

    ship, trajectory, env_p, weather_p, wave_p, config, dt_s = _as_engine_inputs(base_scenario)
    spec = perturbation or PerturbationSpec.from_config(config.monte_carlo)

    child_seeds = np.random.SeedSequence(random_seed).spawn(n_runs)
    tasks = [
        _RunArgs(ship, trajectory, env_p, weather_p, wave_p, config, dt_s, seedseq, spec)
        for seedseq in child_seeds
    ]

    if backend == "multiprocessing" and n_runs > 1:
        import multiprocessing as mp

        with mp.Pool(processes=n_jobs) as pool:
            run_results = pool.map(_single_run, tasks)
    else:
        run_results = [_single_run(t) for t in tasks]

    return _aggregate(run_results, n_runs, random_seed)


def _aggregate(run_results: List[Dict[str, Any]], n_runs: int, random_seed: int) -> MonteCarloResult:
    scalar_keys = ("max_stability_risk", "cumulative_capsize_probability",
                   "time_of_max_risk_s", "n_warnings")
    samples: Dict[str, List[float]] = {k: [] for k in scalar_keys}
    corrosion: Dict[str, List[float]] = {}
    inputs: Dict[str, List[float]] = {}

    for r in run_results:
        for k in scalar_keys:
            samples[k].append(r[k])
        for name, value in r["corrosion_by_component"].items():
            corrosion.setdefault(name, []).append(value)
        for name, value in r["inputs"].items():
            inputs.setdefault(name, []).append(value)

    return MonteCarloResult(
        n_runs=n_runs,
        random_seed=random_seed,
        samples=samples,
        corrosion_by_component=corrosion,
        input_samples=inputs,
    )


__all__ = [
    "PerturbationSpec",
    "MonteCarloResult",
    "run_monte_carlo",
]
