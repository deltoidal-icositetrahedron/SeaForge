"""Ship-level geometry, mass, and hydrostatic data model."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .materials import ShipComponent


class _Model(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")


class Ship(_Model):
    """Principal particulars, mass properties, and structural components.

    Hydrostatic fields use the standard naval-architecture sign conventions:
    heights (``center_of_gravity_height_m``) are measured above the keel/baseline
    (KG), and ``metacentric_height_m`` (GM) is the transverse metacentric height.
    Several fields are optional because they may be derived later or supplied by
    a higher-fidelity hydrostatics module.
    """

    name: str = Field(..., min_length=1, description="Vessel name.")
    length_m: float = Field(..., gt=0.0, description="Length (m), typically LBP/LOA.")
    beam_m: float = Field(..., gt=0.0, description="Moulded beam (m).")
    draft_m: float = Field(..., gt=0.0, description="Mean draft (m).")
    displacement_mass_kg: float = Field(
        ..., gt=0.0, description="Displacement mass (kg)."
    )
    center_of_gravity_height_m: float = Field(
        ..., ge=0.0, description="Vertical center of gravity above keel, KG (m)."
    )
    metacentric_height_m: float = Field(
        ...,
        description=(
            "Transverse metacentric height, GM (m). May be negative for an "
            "initially unstable condition; flagged downstream rather than rejected."
        ),
    )
    waterplane_area_m2: Optional[float] = Field(
        None, gt=0.0, description="Waterplane area (m^2), optional."
    )
    projected_lateral_area_m2: Optional[float] = Field(
        None,
        gt=0.0,
        description="Above-water lateral (windage) area (m^2), optional.",
    )
    roll_natural_period_s: Optional[float] = Field(
        None, gt=0.0, description="Natural roll period, T_roll (s), optional."
    )
    components: List[ShipComponent] = Field(
        default_factory=list, description="Structural components of the vessel."
    )

    @model_validator(mode="after")
    def _check_geometry(self) -> "Ship":
        if self.draft_m > 5.0 * self.beam_m:
            raise ValueError(
                "draft_m is implausibly large relative to beam_m; check inputs."
            )
        names = [c.name for c in self.components]
        if len(names) != len(set(names)):
            raise ValueError("component names must be unique within a ship.")
        return self


__all__ = ["Ship"]
