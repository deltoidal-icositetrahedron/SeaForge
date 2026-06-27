"""Route / trajectory data model.

A trajectory is an ordered list of waypoints with absolute timestamps (seconds
from an arbitrary epoch). Times must be strictly increasing so the simulation
can integrate forward without ambiguity. Speeds are SI (m/s).
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Model(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")


class Waypoint(_Model):
    """A single point on the route with a timestamp and target speed."""

    latitude_deg: float = Field(
        ..., ge=-90.0, le=90.0, description="Latitude (degrees, WGS84)."
    )
    longitude_deg: float = Field(
        ..., ge=-180.0, le=180.0, description="Longitude (degrees, WGS84)."
    )
    time_s: float = Field(
        ..., ge=0.0, description="Absolute time from epoch (s)."
    )
    target_speed_m_s: float = Field(
        ..., ge=0.0, description="Intended speed over ground at this waypoint (m/s)."
    )
    heading_deg: Optional[float] = Field(
        None, ge=0.0, lt=360.0, description="Heading (degrees from true north), optional."
    )


class Trajectory(_Model):
    """An ordered sequence of waypoints defining the voyage."""

    waypoints: List[Waypoint] = Field(
        ..., min_length=2, description="At least two waypoints (start and end)."
    )

    @model_validator(mode="after")
    def _check_times_increasing(self) -> "Trajectory":
        times = [wp.time_s for wp in self.waypoints]
        for earlier, later in zip(times, times[1:]):
            if later <= earlier:
                raise ValueError(
                    "waypoint time_s values must be strictly increasing "
                    f"(found {later} after {earlier})."
                )
        return self

    @property
    def duration_s(self) -> float:
        """Total voyage duration in seconds."""
        return self.waypoints[-1].time_s - self.waypoints[0].time_s


__all__ = ["Waypoint", "Trajectory"]
