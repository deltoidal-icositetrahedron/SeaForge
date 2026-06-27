"""Output data models: per-timestep state and the aggregated result.

These are *output* containers. They intentionally use plain dictionaries keyed
by component name for per-component quantities so the (later) simulation engine
can populate them incrementally, and ``intermediate_physics_values`` keeps
traceable physics intermediates (the project values transparency of derived
quantities over opaque scores).

Corrosion rates are reported in mm/year (human-facing) while accumulated and
effective thicknesses are in meters (SI), matching the field names.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .environment import RegionEnvironment
from .waves import WaveCondition
from .weather import WeatherCondition


class _Model(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")


class GeoPosition(_Model):
    """A latitude/longitude position (degrees, WGS84)."""

    latitude_deg: float = Field(..., ge=-90.0, le=90.0)
    longitude_deg: float = Field(..., ge=-180.0, le=180.0)


class SimulationState(_Model):
    """Snapshot of the simulation at a single timestep.

    Per-component dictionaries are keyed by ``ShipComponent.name``.
    """

    current_time_s: float = Field(..., ge=0.0, description="Time from epoch (s).")
    current_position: GeoPosition = Field(..., description="Vessel position.")
    speed_m_s: float = Field(..., ge=0.0, description="Speed over ground (m/s).")
    environment: RegionEnvironment = Field(..., description="Seawater environment.")
    weather: WeatherCondition = Field(..., description="Atmospheric weather.")
    waves: WaveCondition = Field(..., description="Sea state and current.")

    accumulated_corrosion_m_by_component: Dict[str, float] = Field(
        default_factory=dict,
        description="Cumulative metal loss per component (m).",
    )
    effective_thickness_m_by_component: Dict[str, float] = Field(
        default_factory=dict,
        description="Remaining effective thickness per component (m).",
    )
    corrosion_rate_m_per_year_by_component: Dict[str, float] = Field(
        default_factory=dict,
        description="Instantaneous corrosion rate per component (m/year).",
    )

    stability_risk_score_0_1: float = Field(
        0.0, ge=0.0, le=1.0, description="Normalized stability-risk score (0-1)."
    )
    capsize_probability_timestep: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Estimated capsize probability during this timestep.",
    )
    intermediate_physics_values: Dict[str, Any] = Field(
        default_factory=dict,
        description="Traceable derived physics quantities for this timestep.",
    )
    warnings: List[str] = Field(
        default_factory=list, description="Warnings raised at this timestep."
    )


class SimulationResult(_Model):
    """Aggregated result of a full simulation run."""

    timeline: List[SimulationState] = Field(
        default_factory=list, description="Ordered per-timestep states."
    )
    final_corrosion_summary: Dict[str, Any] = Field(
        default_factory=dict,
        description="End-of-voyage corrosion summary per component / overall.",
    )
    final_stability_summary: Dict[str, Any] = Field(
        default_factory=dict,
        description="End-of-voyage stability summary.",
    )
    cumulative_capsize_probability: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Voyage-integrated probability of at least one capsize event.",
    )
    warnings: List[str] = Field(
        default_factory=list, description="Run-level warnings."
    )
    assumptions: List[str] = Field(
        default_factory=list,
        description="Human-readable list of modeling assumptions/simplifications.",
    )


__all__ = ["GeoPosition", "SimulationState", "SimulationResult"]
