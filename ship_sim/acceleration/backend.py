"""Compute-backend abstraction for batch corrosion / stability updates.

This module provides a small, clean *interface* for accelerating the
embarrassingly-parallel parts of the simulation (batch corrosion-rate updates
over many components, and repeated stability evaluations for Monte Carlo),
without committing to any compiled code. Two backends are implemented today:

- ``"python"`` -- pure-Python reference. Always available. Correct and simple;
  the right choice for small scenarios and as the equivalence baseline.
- ``"numpy"``  -- vectorizes the per-component corrosion arithmetic with NumPy.
  Use when there are many components and/or many Monte Carlo samples, where the
  per-call Python overhead dominates. Numerically identical to ``"python"``.

Planned (NOT implemented -- add only if a benchmark shows a real bottleneck):

- ``"numba"`` -- JIT for hot *scalar* loops (e.g. timestep loops) that don't
  vectorize cleanly in NumPy. Cheapest compiled option (no toolchain), but adds
  a heavy dependency and warm-up cost.
- ``"rust"``  -- PyO3/maturin backend for the tightest loops (batch corrosion
  over components x timesteps, Monte Carlo, wave-encounter, repeated stability).
  Preferred compiled option: safe, clean, fast. Only worth it if profiling shows
  Python/NumPy is the bottleneck for realistic workloads.
- ``"cpp"``   -- pybind11 alternative to Rust if a C++ dependency already exists.

Decision guidance (see ``benchmarks/``): if pure Python/NumPy sustains the
timesteps/sec and Monte-Carlo runs/sec you need, **do not** add compiled code.
The current benchmarks show pure Python is comfortably fast for normal scenarios
(thousands of component-updates/sec, hundreds of timesteps/sec), so no Rust/C++/
Numba backend is shipped. The abstraction below keeps that door open.

The Python implementation must always work without any compiled extension.
"""

from __future__ import annotations

import importlib.util
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Sequence

from ..config import SimulationConfig
from ..models.environment import RegionEnvironment
from ..models.materials import ShipComponent
from ..models.ship import Ship
from ..models.waves import WaveCondition
from ..models.weather import WeatherCondition
from ..simulation.corrosion import (
    oxygen_factor,
    ph_factor,
    pollution_factor,
    salinity_factor,
    speed_erosion_factor,
    splash_factor,
    temperature_factor,
)
from ..simulation.stability import StabilityEstimate, estimate_stability_risk
from ..units import m_per_year_to_m_per_s

_EPS = 1.0e-9

#: Backends that are planned but intentionally not implemented yet.
PLANNED_BACKENDS = ("numba", "rust", "cpp")


def _numpy_available() -> bool:
    return importlib.util.find_spec("numpy") is not None


# ---------------------------------------------------------------------------
# Batch input container
# ---------------------------------------------------------------------------

@dataclass
class ComponentBatch:
    """Per-component material/exposure properties as parallel sequences.

    Holds exactly what the corrosion-rate batch needs, so a backend can operate
    on flat arrays without touching Pydantic models in the hot loop.
    """

    names: List[str]
    base_rate_m_per_year: Sequence[float]
    corrosion_resistance_factor: Sequence[float]
    coating_breakdown_factor: Sequence[float]
    exposed_fraction: Sequence[float]

    @classmethod
    def from_components(cls, components: Sequence[ShipComponent]) -> "ComponentBatch":
        return cls(
            names=[c.name for c in components],
            base_rate_m_per_year=[c.material.base_corrosion_rate_m_per_year for c in components],
            corrosion_resistance_factor=[c.material.corrosion_resistance_factor for c in components],
            coating_breakdown_factor=[c.material.coating_breakdown_factor for c in components],
            exposed_fraction=[c.exposed_fraction for c in components],
        )

    def __len__(self) -> int:
        return len(self.names)


def _shared_environment_multiplier(
    environment: RegionEnvironment,
    weather: WeatherCondition,
    wave: WaveCondition,
    speed_m_s: float,
    config: SimulationConfig,
) -> float:
    """Product of the component-independent environmental corrosion factors.

    These factors are identical for every component at a given timestep, so they
    are computed once (reusing the tested scalar factor functions) and then
    multiplied by the per-component material/exposure terms.
    """
    cfg = config.corrosion
    relative_flow = max(0.0, speed_m_s) + wave.current_speed_m_s
    return (
        salinity_factor(environment.salinity_ppt, cfg)
        * temperature_factor(environment.water_temperature_c, cfg)
        * ph_factor(environment.pH, cfg)
        * oxygen_factor(environment.dissolved_oxygen_mg_l, cfg)
        * pollution_factor(environment.pollution_factor_0_1, cfg)
        * splash_factor(wave.significant_wave_height_m, weather.storm_intensity_0_1, cfg)
        * speed_erosion_factor(relative_flow, cfg)
    )


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------

class AccelerationBackend(ABC):
    """Interface for accelerated batch corrosion/stability updates.

    Implementations must be *numerically equivalent* to the pure-Python
    reference (see :class:`PythonBackend`) within floating-point tolerance.
    """

    name: str = "abstract"
    available: bool = False

    @abstractmethod
    def corrosion_rate_batch(
        self,
        batch: ComponentBatch,
        environment: RegionEnvironment,
        weather: WeatherCondition,
        wave: WaveCondition,
        speed_m_s: float,
        config: SimulationConfig,
    ) -> Sequence[float]:
        """Return the corrosion rate (m/s) for every component in ``batch``.

        Equivalent to calling
        :func:`~ship_sim.simulation.corrosion.estimate_corrosion_rate` per
        component, but computed in one shot.
        """

    def stability_risk_batch(
        self,
        ship: Ship,
        effective_thickness_by_component: dict,
        conditions: Sequence[tuple],
        config: SimulationConfig,
    ) -> List[StabilityEstimate]:
        """Evaluate stability risk for many conditions (default: a Python loop).

        ``conditions`` is a sequence of
        ``(weather, wave, speed_m_s, dt_s, heading_degrees)`` tuples. This is a
        shared, non-vectorized implementation (stability is not yet vectorized);
        it is the natural target for a future Numba/Rust backend.
        """
        results: List[StabilityEstimate] = []
        for weather, wave, speed_m_s, dt_s, heading in conditions:
            results.append(
                estimate_stability_risk(
                    ship=ship,
                    effective_thickness_by_component=effective_thickness_by_component,
                    weather=weather,
                    wave=wave,
                    speed_m_s=speed_m_s,
                    dt_s=dt_s,
                    config=config,
                    heading_degrees=heading,
                )
            )
        return results


class PythonBackend(AccelerationBackend):
    """Pure-Python reference backend (always available)."""

    name = "python"
    available = True

    def corrosion_rate_batch(self, batch, environment, weather, wave, speed_m_s, config):
        cfg = config.corrosion
        env_mult = _shared_environment_multiplier(
            environment, weather, wave, speed_m_s, config
        )
        rates: List[float] = []
        for i in range(len(batch)):
            base = m_per_year_to_m_per_s(batch.base_rate_m_per_year[i])
            resistance_adj = 1.0 / max(_EPS, batch.corrosion_resistance_factor[i])
            coat = min(
                1.0,
                max(cfg.min_coating_factor, cfg.intact_coating_factor * batch.coating_breakdown_factor[i]),
            )
            rates.append(base * resistance_adj * coat * env_mult * batch.exposed_fraction[i])
        return rates


class NumpyBackend(AccelerationBackend):
    """Vectorized NumPy backend: same math as PythonBackend, on arrays."""

    name = "numpy"
    available = True

    def __init__(self):
        import numpy as np  # local import so the module loads without numpy

        self._np = np

    def corrosion_rate_batch(self, batch, environment, weather, wave, speed_m_s, config):
        np = self._np
        cfg = config.corrosion
        env_mult = _shared_environment_multiplier(
            environment, weather, wave, speed_m_s, config
        )
        base = m_per_year_to_m_per_s(np.asarray(batch.base_rate_m_per_year, dtype=float))
        resistance_adj = 1.0 / np.maximum(_EPS, np.asarray(batch.corrosion_resistance_factor, dtype=float))
        coat = np.clip(
            cfg.intact_coating_factor * np.asarray(batch.coating_breakdown_factor, dtype=float),
            cfg.min_coating_factor,
            1.0,
        )
        exposed = np.asarray(batch.exposed_fraction, dtype=float)
        return base * resistance_adj * coat * env_mult * exposed


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

_IMPLEMENTED = {"python": PythonBackend, "numpy": NumpyBackend}


def list_available_backends() -> List[str]:
    """Return the names of backends that can be used in this environment."""
    backends = ["python"]
    if _numpy_available():
        backends.append("numpy")
    return backends


def choose_backend(preferred: str = "auto", *, allow_fallback: bool = True) -> AccelerationBackend:
    """Return a backend instance for ``preferred``.

    - ``"auto"`` picks the fastest available (NumPy if present, else Python).
    - ``"python"`` / ``"numpy"`` return that backend (NumPy falls back to Python
      with a warning if NumPy is missing and ``allow_fallback`` is True).
    - ``"numba"`` / ``"rust"`` / ``"cpp"`` raise :class:`NotImplementedError`
      (planned, not shipped).
    - anything else raises :class:`ValueError`.
    """
    available = list_available_backends()

    if preferred == "auto":
        return NumpyBackend() if "numpy" in available else PythonBackend()

    if preferred in PLANNED_BACKENDS:
        raise NotImplementedError(
            f"backend {preferred!r} is planned but not implemented; "
            f"available: {available}. (Add it only if benchmarks justify it.)"
        )

    if preferred not in _IMPLEMENTED:
        raise ValueError(
            f"unknown backend {preferred!r}; available: {available}, "
            f"planned: {list(PLANNED_BACKENDS)}."
        )

    if preferred not in available:  # e.g. numpy requested but not installed
        if allow_fallback:
            warnings.warn(
                f"backend {preferred!r} unavailable; falling back to 'python'.",
                RuntimeWarning,
                stacklevel=2,
            )
            return PythonBackend()
        raise RuntimeError(f"backend {preferred!r} is unavailable and fallback is disabled.")

    return _IMPLEMENTED[preferred]()


__all__ = [
    "AccelerationBackend",
    "PythonBackend",
    "NumpyBackend",
    "ComponentBatch",
    "list_available_backends",
    "choose_backend",
    "PLANNED_BACKENDS",
]
