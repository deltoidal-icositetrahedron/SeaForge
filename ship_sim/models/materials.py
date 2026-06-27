"""Material and ship-component data models.

All quantities are SI (meters, kilograms, seconds, pascals) except where a
field name explicitly states otherwise. Corrosion *inputs* are accepted in the
human-friendly unit of m/year (as named), while the simulation converts to the
internal m/s using :mod:`ship_sim.units` when it runs.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Model(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")


class Material(_Model):
    """Physical and electrochemical properties of a structural material.

    Strengths and moduli are in pascals. ``base_corrosion_rate_m_per_year`` is
    the free-corrosion (bare-metal, reference-environment) rate; environmental
    factors and coatings modify it in the corrosion model.
    """

    name: str = Field(..., min_length=1, description="Human-readable material name.")
    density_kg_m3: float = Field(..., gt=0.0, description="Mass density (kg/m^3).")
    yield_strength_pa: float = Field(..., gt=0.0, description="Yield strength (Pa).")
    ultimate_strength_pa: float = Field(
        ..., gt=0.0, description="Ultimate tensile strength (Pa)."
    )
    elastic_modulus_pa: float = Field(
        ..., gt=0.0, description="Young's modulus (Pa)."
    )
    base_corrosion_rate_m_per_year: float = Field(
        ...,
        ge=0.0,
        description="Free-corrosion rate in the reference environment (m/year).",
    )
    corrosion_resistance_factor: float = Field(
        1.0,
        gt=0.0,
        description=(
            "Dimensionless divisor on corrosion rate (>1 => more resistant, "
            "e.g. stainless/alloyed steels)."
        ),
    )
    galvanic_potential_v: float = Field(
        ...,
        description=(
            "Electrode potential vs a common reference (V). Used for galvanic "
            "coupling comparisons between dissimilar materials."
        ),
    )
    coating_breakdown_factor: float = Field(
        1.0,
        ge=0.0,
        description=(
            "Relative susceptibility of this material's coating system to "
            "breakdown (dimensionless; 1.0 = nominal)."
        ),
    )
    fatigue_strength_pa: Optional[float] = Field(
        None,
        gt=0.0,
        description="Endurance/fatigue strength (Pa), optional.",
    )
    notes: str = Field("", description="Free-form notes / provenance.")

    @model_validator(mode="after")
    def _check_strength_ordering(self) -> "Material":
        if self.ultimate_strength_pa < self.yield_strength_pa:
            raise ValueError(
                "ultimate_strength_pa must be >= yield_strength_pa "
                f"(got {self.ultimate_strength_pa} < {self.yield_strength_pa})."
            )
        return self


class ShipComponent(_Model):
    """A discrete structural element (plate, frame, bulkhead, etc.).

    ``thickness_m`` is the *current* thickness; ``original_thickness_m`` is the
    as-built thickness. Corrosion reduces the former toward the latter minus the
    accumulated loss. ``corrosion_allowance_m`` is the design margin of metal
    intended to be sacrificed to corrosion over the service life.
    """

    name: str = Field(..., min_length=1, description="Component identifier.")
    material: Material = Field(..., description="The component's material.")
    thickness_m: float = Field(..., gt=0.0, description="Current thickness (m).")
    area_m2: float = Field(..., gt=0.0, description="Exposed surface area (m^2).")
    exposed_fraction: float = Field(
        1.0,
        ge=0.0,
        le=1.0,
        description="Fraction of the area in contact with the corrosive medium.",
    )
    structural_importance: float = Field(
        1.0,
        ge=0.0,
        description=(
            "Relative contribution of this component to global strength "
            "(dimensionless weighting; 0 = non-structural)."
        ),
    )
    location_on_ship: str = Field(
        "unspecified",
        description="Descriptive location, e.g. 'bottom_plating', 'deck'.",
    )
    vertical_position_m: float = Field(
        0.0,
        description=(
            "Height of the component above the baseline/keel (m). Negative or "
            "near-zero values indicate submerged regions."
        ),
    )
    original_thickness_m: float = Field(
        ..., gt=0.0, description="As-built thickness (m)."
    )
    corrosion_allowance_m: float = Field(
        0.0, ge=0.0, description="Design corrosion allowance (m)."
    )
    safety_factor_required: float = Field(
        1.5,
        gt=0.0,
        description="Minimum required safety factor for this component.",
    )

    @model_validator(mode="after")
    def _check_thickness(self) -> "ShipComponent":
        if self.thickness_m > self.original_thickness_m + 1e-12:
            raise ValueError(
                "thickness_m cannot exceed original_thickness_m "
                f"({self.thickness_m} > {self.original_thickness_m})."
            )
        if self.corrosion_allowance_m > self.original_thickness_m:
            raise ValueError(
                "corrosion_allowance_m cannot exceed original_thickness_m."
            )
        return self


__all__ = ["Material", "ShipComponent"]
