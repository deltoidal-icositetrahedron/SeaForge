"""Atmospheric weather condition data model."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")


class WeatherCondition(_Model):
    """Above-water atmospheric conditions at a point/time on the route.

    Drives wind heeling (stability) and atmospheric corrosion of exposed
    topside steel via humidity and precipitation.
    """

    wind_speed_m_s: float = Field(
        ..., ge=0.0, description="Mean wind speed (m/s)."
    )
    wind_direction_deg: float = Field(
        ...,
        ge=0.0,
        lt=360.0,
        description="Direction the wind blows FROM (degrees from true north).",
    )
    air_temperature_c: float = Field(
        ..., ge=-60.0, le=60.0, description="Air temperature (C)."
    )
    relative_humidity_0_1: float = Field(
        ..., ge=0.0, le=1.0, description="Relative humidity (fraction 0-1)."
    )
    precipitation_rate_mm_hr: float = Field(
        0.0, ge=0.0, description="Precipitation rate (mm/hr)."
    )
    storm_intensity_0_1: float = Field(
        0.0, ge=0.0, le=1.0, description="Normalized storm intensity (0-1)."
    )
    atmospheric_pressure_pa: Optional[float] = Field(
        None, gt=0.0, description="Atmospheric pressure (Pa), optional."
    )


__all__ = ["WeatherCondition"]
