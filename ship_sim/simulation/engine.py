"""Main simulation engine: marches a ship along a trajectory through time.

:class:`ShipSimulationEngine` ties the pieces together. At each timestep it
interpolates the ship's kinematics, queries the environment / weather / wave
providers, advances every component's corrosion, evaluates structural weakening
and capsize risk, and records a :class:`~ship_sim.models.results.SimulationState`.
At the end it aggregates a :class:`~ship_sim.models.results.SimulationResult`
with corrosion, stability, and capsize summaries plus the dominant drivers.

Backends
--------
Only the pure-Python (``"python"``) backend exists today. The per-component
corrosion loop reuses the tested
:func:`~ship_sim.simulation.corrosion.update_component_corrosion`, which is
clean and correct; the environmental factors it recomputes per component are
shared across components, so a future vectorized/NumPy or compiled backend can
compute them once per step. The ``backend`` argument keeps that door open
without committing to it now (the project guidance is not to over-engineer
acceleration before profiling shows a need).

ENGINEERING APPROXIMATION -- not a certified safety tool (see assumptions in the
result and the package docstring).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from ..config import SimulationConfig
from ..models.results import (
    GeoPosition,
    SimulationResult,
    SimulationState,
)
from ..models.ship import Ship
from ..models.trajectory import Trajectory
from ..units import m_per_s_to_m_per_year, seconds_to_hours
from .corrosion import update_component_corrosion
from .stability import estimate_stability_risk, estimate_structural_weakening
from .timestep import (
    get_time_bounds,
    interpolate_heading,
    interpolate_position,
    interpolate_speed,
)

# Corrosion environmental factors tracked for the "dominant factors" summary.
_CORROSION_FACTOR_KEYS = (
    "salinity_factor",
    "temperature_factor",
    "pH_factor",
    "oxygen_factor",
    "pollution_factor",
    "splash_factor",
    "speed_erosion_factor",
    "coating_factor",
)

_SUPPORTED_BACKENDS = ("python",)

# High-level simplifications baked into the engine pipeline (reported to users).
_ENGINE_ASSUMPTIONS = (
    "ENGINEERING APPROXIMATION ONLY -- not a certified intact/damage stability, "
    "structural, or corrosion assessment.",
    "Conditions are sampled once per timestep and held constant over the step "
    "(explicit forward Euler integration of corrosion loss).",
    "Trajectory position uses linear lat/lon interpolation (not great-circle).",
    "Coating is treated as intact; time-dependent coating breakdown is not yet "
    "integrated by the engine.",
    "Components corrode independently; galvanic coupling and load redistribution "
    "between components are not modeled.",
    "GM is treated as constant; corrosion-driven weight/KG changes are ignored.",
)


def _sanitize(obj: Any) -> Any:
    """Recursively replace non-finite floats with None for JSON-safe storage."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


class ShipSimulationEngine:
    """Run a corrosion + stability simulation of a ship over a trajectory."""

    def __init__(
        self,
        ship: Ship,
        trajectory: Trajectory,
        environment_provider: Any,
        weather_provider: Any,
        wave_provider: Any,
        config: SimulationConfig,
        dt_s: float,
        backend: str = "python",
    ) -> None:
        if dt_s <= 0.0:
            raise ValueError("dt_s must be positive.")
        if backend not in _SUPPORTED_BACKENDS:
            raise NotImplementedError(
                f"backend {backend!r} is not supported; available: {_SUPPORTED_BACKENDS}."
            )
        if not ship.components:
            raise ValueError("ship has no components to simulate.")

        self.ship = ship
        self.trajectory = trajectory
        self.environment_provider = environment_provider
        self.weather_provider = weather_provider
        self.wave_provider = wave_provider
        self.config = config
        self.dt_s = dt_s
        self.backend = backend

    # -- timestep schedule ----------------------------------------------

    @staticmethod
    def n_steps(trajectory: Trajectory, dt_s: float) -> int:
        """Number of timesteps the engine will take for this trajectory/dt."""
        start, end = get_time_bounds(trajectory)
        duration = end - start
        return max(1, math.ceil(duration / dt_s - 1e-9))

    def _schedule(self) -> List[Tuple[float, float]]:
        """Return a list of ``(t_start, dt)`` pairs covering the voyage.

        The final step is clamped so the integration ends exactly at the last
        waypoint time.
        """
        start, end = get_time_bounds(self.trajectory)
        n = self.n_steps(self.trajectory, self.dt_s)
        schedule = []
        for i in range(n):
            t = start + i * self.dt_s
            dt = min(self.dt_s, end - t)
            schedule.append((t, dt))
        return schedule

    # -- main loop ------------------------------------------------------

    def run(self) -> SimulationResult:
        """Execute the simulation and return the aggregated result."""
        ship = self.ship
        config = self.config

        # Per-component running state. Accumulated loss starts at any pre-existing
        # loss (original - current thickness) so effective thickness is consistent.
        accumulated: Dict[str, float] = {
            c.name: max(0.0, c.original_thickness_m - c.thickness_m)
            for c in ship.components
        }
        min_safety_margin: Dict[str, float] = {c.name: math.inf for c in ship.components}

        cumulative_no_capsize = 1.0
        timeline: List[SimulationState] = []

        # Dominant-factor accumulation (mean over steps and components).
        factor_sums: Dict[str, float] = {k: 0.0 for k in _CORROSION_FACTOR_KEYS}
        factor_count = 0

        # Max-risk tracking and deduplicated warning events.
        max_risk = -1.0
        max_risk_info: Dict[str, Any] = {}
        seen_warnings: set[str] = set()
        warning_events: List[Tuple[float, str]] = []

        for t, dt in self._schedule():
            position = interpolate_position(self.trajectory, t)
            speed = interpolate_speed(self.trajectory, t)
            heading = interpolate_heading(self.trajectory, t)

            weather = self.weather_provider.at(position, t)
            environment = self.environment_provider.at(position, t)
            wave = self.wave_provider.at(position, t, weather)

            # --- corrosion update for each component ---------------------
            acc_step: Dict[str, float] = {}
            eff_step: Dict[str, float] = {}
            rate_step: Dict[str, float] = {}
            total_mult_step: Dict[str, float] = {}
            step_warnings: List[str] = []

            for comp in ship.components:
                upd = update_component_corrosion(
                    component=comp,
                    accumulated_corrosion_m=accumulated[comp.name],
                    environment=environment,
                    weather=weather,
                    wave=wave,
                    speed_m_s=speed,
                    dt_s=dt,
                    config=config,
                )
                accumulated[comp.name] = upd.accumulated_corrosion_m
                acc_step[comp.name] = upd.accumulated_corrosion_m
                eff_step[comp.name] = upd.effective_thickness_m
                rate_step[comp.name] = m_per_s_to_m_per_year(upd.corrosion_rate_m_per_s)
                total_mult_step[comp.name] = upd.intermediate_factors["total_multiplier"]
                min_safety_margin[comp.name] = min(
                    min_safety_margin[comp.name], upd.safety_margin
                )
                step_warnings.extend(upd.warnings)
                for k in _CORROSION_FACTOR_KEYS:
                    factor_sums[k] += upd.intermediate_factors[k]
                factor_count += 1

            # --- structural weakening & stability -----------------------
            weakening = estimate_structural_weakening(ship, eff_step, config)
            stability = estimate_stability_risk(
                ship=ship,
                effective_thickness_by_component=eff_step,
                weather=weather,
                wave=wave,
                speed_m_s=speed,
                dt_s=dt,
                config=config,
                heading_degrees=heading,
            )
            step_warnings.extend(stability.warnings)

            # --- cumulative capsize probability -------------------------
            cumulative_no_capsize *= 1.0 - stability.capsize_probability_timestep

            # --- record the state ---------------------------------------
            state = SimulationState(
                current_time_s=t,
                current_position=position,
                speed_m_s=speed,
                environment=environment,
                weather=weather,
                waves=wave,
                accumulated_corrosion_m_by_component=dict(acc_step),
                effective_thickness_m_by_component=dict(eff_step),
                corrosion_rate_m_per_year_by_component=dict(rate_step),
                stability_risk_score_0_1=stability.risk_score_0_1,
                capsize_probability_timestep=stability.capsize_probability_timestep,
                intermediate_physics_values=_sanitize(
                    {
                        "heading_deg": heading,
                        "structural_weakening_factor": weakening.weakening_factor_0_1,
                        "corrosion_total_multiplier_by_component": total_mult_step,
                        "stability": stability.explanation,
                    }
                ),
                warnings=list(step_warnings),
            )
            timeline.append(state)

            # --- max risk & warning events ------------------------------
            if stability.risk_score_0_1 > max_risk:
                max_risk = stability.risk_score_0_1
                max_risk_info = {
                    "time_s": t,
                    "position": {
                        "latitude_deg": position.latitude_deg,
                        "longitude_deg": position.longitude_deg,
                    },
                    "weighted_contributions": _sanitize(
                        stability.explanation.get("weighted_contributions", {})
                    ),
                }
            for w in step_warnings:
                if w not in seen_warnings:
                    seen_warnings.add(w)
                    warning_events.append((t, w))

        cumulative_capsize = min(1.0, max(0.0, 1.0 - cumulative_no_capsize))

        return self._build_result(
            timeline=timeline,
            accumulated=accumulated,
            min_safety_margin=min_safety_margin,
            factor_sums=factor_sums,
            factor_count=factor_count,
            max_risk=max_risk,
            max_risk_info=max_risk_info,
            cumulative_capsize=cumulative_capsize,
            warning_events=warning_events,
        )

    # -- result assembly ------------------------------------------------

    def _build_result(
        self,
        timeline: List[SimulationState],
        accumulated: Dict[str, float],
        min_safety_margin: Dict[str, float],
        factor_sums: Dict[str, float],
        factor_count: int,
        max_risk: float,
        max_risk_info: Dict[str, Any],
        cumulative_capsize: float,
        warning_events: List[Tuple[float, str]],
    ) -> SimulationResult:
        ship = self.ship

        by_component: Dict[str, Any] = {}
        most_corroded = None
        worst_loss_fraction = -1.0
        total_loss = 0.0
        final_state = timeline[-1]

        for comp in ship.components:
            original = comp.original_thickness_m
            acc = accumulated[comp.name]
            effective = max(0.0, original - acc)
            loss_fraction = (original - effective) / original if original > 0 else 0.0
            total_loss += acc
            final_rate = final_state.corrosion_rate_m_per_year_by_component[comp.name]
            by_component[comp.name] = {
                "original_thickness_m": original,
                "final_effective_thickness_m": effective,
                "accumulated_corrosion_m": acc,
                "thickness_loss_fraction": loss_fraction,
                "final_corrosion_rate_mm_per_year": final_rate * 1e3,
                "min_safety_margin": min_safety_margin[comp.name],
            }
            if loss_fraction > worst_loss_fraction:
                worst_loss_fraction = loss_fraction
                most_corroded = comp.name

        # Dominant environmental corrosion factors: rank by deviation from 1.0.
        mean_factors = {
            k: (factor_sums[k] / factor_count if factor_count else 1.0)
            for k in _CORROSION_FACTOR_KEYS
        }
        dominant_factors = sorted(
            ({"factor": k, "mean_value": v} for k, v in mean_factors.items()),
            key=lambda d: abs(d["mean_value"] - 1.0),
            reverse=True,
        )

        final_corrosion_summary: Dict[str, Any] = {
            "by_component": by_component,
            "final_effective_thickness_m_by_component": {
                name: by_component[name]["final_effective_thickness_m"]
                for name in by_component
            },
            "min_safety_margin_by_component": dict(min_safety_margin),
            "total_accumulated_corrosion_m": total_loss,
            "most_corroded_component": most_corroded,
            "dominant_environmental_factors": dominant_factors,
        }

        final_stability_summary: Dict[str, Any] = {
            "max_risk_score": max_risk if max_risk >= 0.0 else 0.0,
            "time_of_max_risk_s": max_risk_info.get("time_s"),
            "position_of_max_risk": max_risk_info.get("position"),
            "max_risk_dominant_contributions": max_risk_info.get(
                "weighted_contributions", {}
            ),
            "final_risk_score": final_state.stability_risk_score_0_1,
        }

        warnings = [
            f"[t={seconds_to_hours(t):.2f} h] {msg}"
            for t, msg in sorted(warning_events, key=lambda tw: tw[0])
        ]

        return SimulationResult(
            timeline=timeline,
            final_corrosion_summary=final_corrosion_summary,
            final_stability_summary=final_stability_summary,
            cumulative_capsize_probability=cumulative_capsize,
            warnings=warnings,
            assumptions=list(_ENGINE_ASSUMPTIONS),
        )


__all__ = ["ShipSimulationEngine"]
