"""Regional water-column / oceanographic environment data model.

These are the seawater properties that drive electrochemical corrosion. The
user supplies water temperature in Celsius (converted to kelvin internally by
the physics); all other quantities are in their named units.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")


class RegionEnvironment(_Model):
    """Local seawater chemistry and condition at a point/time on the route."""

    salinity_ppt: float = Field(
        ..., ge=0.0, description="Salinity in parts per thousand (ppt)."
    )
    water_temperature_c: float = Field(
        ...,
        ge=-2.0,
        le=40.0,
        description="Seawater temperature (C); seawater freezes near -2 C.",
    )
    pH: float = Field(
        ...,
        ge=6.0,
        le=9.5,
        description="Seawater pH; environmental seawater is ~7.5-8.4.",
    )
    dissolved_oxygen_mg_l: float = Field(
        ..., ge=0.0, description="Dissolved oxygen concentration (mg/L)."
    )
    pollution_factor_0_1: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Normalized pollution load (0 = pristine, 1 = heavily polluted).",
    )
    biofouling_factor_0_1: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Normalized biofouling coverage (0 = clean, 1 = fully fouled).",
    )


__all__ = ["RegionEnvironment"]
