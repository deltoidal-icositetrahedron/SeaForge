"""Wave and current condition data model."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")


class WaveCondition(_Model):
    """Sea-state (waves) and current at a point/time on the route.

    Significant wave height and peak period parameterize the sea state; the
    optional spectrum type names the model (e.g. JONSWAP) a seakeeping module
    may later use. Currents affect both encounter kinematics and flow-driven
    (erosion-)corrosion.
    """

    significant_wave_height_m: float = Field(
        ..., ge=0.0, description="Significant wave height, Hs (m)."
    )
    peak_period_s: float = Field(
        ..., gt=0.0, description="Spectral peak period, Tp (s)."
    )
    mean_wave_direction_deg: float = Field(
        ...,
        ge=0.0,
        lt=360.0,
        description="Mean direction waves travel TOWARD (deg from true north).",
    )
    current_speed_m_s: float = Field(
        0.0, ge=0.0, description="Surface current speed (m/s)."
    )
    current_direction_deg: float = Field(
        0.0,
        ge=0.0,
        lt=360.0,
        description="Direction the current flows TOWARD (deg from true north).",
    )
    wave_spectrum_type: Optional[Literal["jonswap", "pierson_moskowitz", "bretschneider"]] = Field(
        None, description="Named wave spectrum model, optional."
    )


__all__ = ["WaveCondition"]
