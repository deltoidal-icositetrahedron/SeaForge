"""Top-level scenario schema bundling all inputs for a simulation run.

A :class:`Scenario` is the unit of JSON serialization (see :mod:`ship_sim.io`).
It captures everything :class:`~ship_sim.simulation.engine.ShipSimulationEngine`
needs:

- ``simulation``  -- timestep, backend preference, segment-fallback behavior;
- ``ship``        -- geometry/mass/hydrostatics + materials + components;
- ``trajectory``  -- timed waypoints;
- optional ``weather_segments`` / ``wave_segments`` / ``environment_segments``
  -- user-provided conditions (Mode A); each channel that has no segments is
  generated procedurally;
- ``procedural``  -- seed (and optional range overrides) for procedural
  generation (Mode B), used for any channel lacking segments;
- ``config``      -- tunable-coefficient overrides (anything omitted uses the
  documented defaults).

Units: everything is SI internally. A few user-friendly conveniences are
accepted and converted on load (e.g. ``dt_hours`` -> seconds, segment
``*_time_hours`` -> seconds); the SI fields take precedence if both are given.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..config import SimulationConfig
from ..units import hours_to_seconds
from .environment import RegionEnvironment
from .ship import Ship
from .trajectory import Trajectory
from .waves import WaveCondition
from .weather import WeatherCondition


class _Model(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")


class SimulationSettings(_Model):
    """Engine run settings: timestep, backend, and segment fallback."""

    dt_s: Optional[float] = Field(
        None, gt=0.0, description="Timestep in seconds (SI; takes precedence)."
    )
    dt_hours: Optional[float] = Field(
        None, gt=0.0, description="Timestep in hours (converted to seconds on load)."
    )
    backend: str = Field("python", description="Backend preference for the engine.")
    fallback_nearest: bool = Field(
        False,
        description="If a segmented provider finds no match, use the nearest segment.",
    )

    @model_validator(mode="after")
    def _require_dt(self) -> "SimulationSettings":
        if self.dt_s is None and self.dt_hours is None:
            raise ValueError(
                "simulation settings must provide 'dt_s' (seconds) or 'dt_hours'."
            )
        return self

    @property
    def resolved_dt_s(self) -> float:
        """The timestep in seconds (SI), resolving dt_hours if needed."""
        if self.dt_s is not None:
            return self.dt_s
        return hours_to_seconds(self.dt_hours)  # type: ignore[arg-type]


class _SegmentSpec(_Model):
    """Common time/region bounds for a condition segment (Mode A).

    Time bounds may be given in seconds (SI) or hours (converted). A segment
    with no bounds is a catch-all that always matches.
    """

    start_time_s: Optional[float] = Field(None, ge=0.0)
    end_time_s: Optional[float] = Field(None, ge=0.0)
    start_time_hours: Optional[float] = Field(None, ge=0.0)
    end_time_hours: Optional[float] = Field(None, ge=0.0)
    lat_bounds: Optional[Tuple[float, float]] = None
    lon_bounds: Optional[Tuple[float, float]] = None

    @property
    def resolved_start_s(self) -> Optional[float]:
        if self.start_time_s is not None:
            return self.start_time_s
        if self.start_time_hours is not None:
            return hours_to_seconds(self.start_time_hours)
        return None

    @property
    def resolved_end_s(self) -> Optional[float]:
        if self.end_time_s is not None:
            return self.end_time_s
        if self.end_time_hours is not None:
            return hours_to_seconds(self.end_time_hours)
        return None


class WeatherSegment(_SegmentSpec):
    """A weather condition applying over an optional time window / region."""

    condition: WeatherCondition


class WaveSegment(_SegmentSpec):
    """A wave condition applying over an optional time window / region."""

    condition: WaveCondition


class EnvironmentSegment(_SegmentSpec):
    """A seawater-environment condition over an optional time window / region."""

    condition: RegionEnvironment


class ProceduralSettings(_Model):
    """Seed and optional range overrides for procedural generation (Mode B)."""

    seed: int = Field(0, description="RNG seed; same seed => reproducible conditions.")
    ranges: Optional[Dict[str, float]] = Field(
        None,
        description=(
            "Overrides for ProceduralRanges fields (e.g. {'salinity_mean_ppt': 34}). "
            "Unknown keys are rejected at load time."
        ),
    )


class Scenario(_Model):
    """Everything needed to run (or describe) a single simulation."""

    name: str = Field(..., min_length=1, description="Scenario identifier.")
    description: str = Field("", description="Free-form scenario description.")
    schema_version: str = Field(
        "2.0", description="Scenario schema version for forward compatibility."
    )

    simulation: SimulationSettings = Field(..., description="Engine run settings.")
    ship: Ship = Field(..., description="The vessel under study.")
    trajectory: Trajectory = Field(..., description="The voyage route in time.")

    weather_segments: Optional[List[WeatherSegment]] = Field(
        None, description="User-provided weather segments (else procedural)."
    )
    wave_segments: Optional[List[WaveSegment]] = Field(
        None, description="User-provided wave segments (else procedural)."
    )
    environment_segments: Optional[List[EnvironmentSegment]] = Field(
        None, description="User-provided seawater-environment segments (else procedural)."
    )

    procedural: ProceduralSettings = Field(
        default_factory=ProceduralSettings,
        description="Procedural-generation settings for channels without segments.",
    )
    config: SimulationConfig = Field(
        default_factory=SimulationConfig,
        description="Tunable-coefficient overrides (omitted fields use defaults).",
    )


__all__ = [
    "SimulationSettings",
    "WeatherSegment",
    "WaveSegment",
    "EnvironmentSegment",
    "ProceduralSettings",
    "Scenario",
]
