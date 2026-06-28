"""Tunable coefficients and model settings.

Every empirical constant used by the simulation lives here rather than being
hard-coded inside the physics. This keeps the models auditable and lets a user
calibrate the project against measured data without touching code.

The defaults below are *physically motivated, order-of-magnitude* starting
points drawn from typical marine-corrosion and naval-architecture practice.
They are explicitly **not** certified values -- see the README. Each field
documents its meaning, units, and the role it plays in the (later) physics.

Grouping:

- :class:`CorrosionConfig`   -- environmental drivers of metal loss
- :class:`StabilityConfig`   -- wind/wave heeling and resonance risk
- :class:`StructuralConfig`  -- how thickness loss maps to strength loss
- :class:`MonteCarloConfig`  -- stochastic perturbation defaults
- :class:`BackendConfig`     -- compute backend selection
- :class:`SimulationConfig`  -- top-level container of the above
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _ConfigBase(BaseModel):
    """Base for config models: validate on assignment, forbid typos."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")


# ---------------------------------------------------------------------------
# Corrosion
# ---------------------------------------------------------------------------

class CorrosionConfig(_ConfigBase):
    """Coefficients controlling environmental sensitivity of corrosion rate.

    The intended (Phase 3) form of the corrosion rate is a base rate scaled by
    a product of dimensionless environmental factors, e.g.::

        rate = base_rate * f_salinity * f_temperature * f_pH
                         * f_oxygen * f_pollution * f_zone * f_flow

    Each coefficient below tunes one of those factors. Reference values define
    the operating point at which a factor equals 1.0.
    """

    # -- Salinity --------------------------------------------------------
    salinity_sensitivity: float = Field(
        0.03,
        ge=0.0,
        description=(
            "Fractional change in corrosion rate per ppt of salinity deviation "
            "from the reference. Dimensionless per ppt."
        ),
    )
    reference_salinity_ppt: float = Field(
        35.0, ge=0.0, description="Salinity at which the salinity factor is 1.0 (ppt)."
    )
    salinity_saturation_scale_ppt: float = Field(
        20.0,
        gt=0.0,
        description=(
            "Saturation scale (ppt) for the salinity factor. The factor rises "
            "with salinity but saturates: f = 1 + sensitivity * scale * "
            "tanh((S - S_ref)/scale), so the near-reference slope is "
            "`salinity_sensitivity` and the effect levels off far from S_ref "
            "(higher salinity also lowers O2 solubility, limiting the increase)."
        ),
    )

    # -- Temperature (Arrhenius) ----------------------------------------
    activation_energy_j_per_mol: float = Field(
        40000.0,
        ge=0.0,
        description=(
            "Apparent activation energy for the temperature dependence of "
            "corrosion, used in an Arrhenius factor exp(-Ea/R * (1/T - 1/T_ref)). "
            "Units J/mol; ~30-60 kJ/mol is typical for aqueous corrosion."
        ),
    )
    reference_temperature_c: float = Field(
        15.0,
        description="Water temperature at which the temperature factor is 1.0 (C).",
    )

    # -- pH --------------------------------------------------------------
    ph_sensitivity: float = Field(
        0.10,
        ge=0.0,
        description=(
            "Fractional increase in corrosion rate per unit of pH *below* the "
            "reference (acidity accelerates corrosion). Dimensionless per pH unit."
        ),
    )
    reference_ph: float = Field(
        8.1, description="Seawater pH at which the pH factor is 1.0 (dimensionless)."
    )

    # -- Dissolved oxygen ------------------------------------------------
    oxygen_sensitivity: float = Field(
        0.05,
        ge=0.0,
        description=(
            "Fractional change in corrosion rate per mg/L of dissolved-oxygen "
            "deviation from reference. Oxygen is the dominant cathodic reactant "
            "for steel in seawater. Dimensionless per mg/L."
        ),
    )
    reference_oxygen_mg_l: float = Field(
        8.0, ge=0.0, description="Dissolved O2 at which the oxygen factor is 1.0 (mg/L)."
    )
    oxygen_saturation_scale_mg_l: float = Field(
        6.0,
        gt=0.0,
        description=(
            "Saturation scale (mg/L) for the oxygen factor: f = 1 + sensitivity "
            "* scale * tanh((O2 - O2_ref)/scale). Oxygen feeds the cathodic "
            "reaction so corrosion rises with dissolved O2 but saturates once "
            "oxygen transport is no longer limiting."
        ),
    )

    # -- Pollution / fouling --------------------------------------------
    pollution_multiplier: float = Field(
        0.50,
        ge=0.0,
        description=(
            "Maximum *additional* fractional corrosion rate at pollution_factor "
            "= 1.0 (e.g. 0.5 => up to +50%). Pollutants (sulphides, organics) "
            "can accelerate localized attack. Dimensionless."
        ),
    )

    # -- Splash / wet-dry zone ------------------------------------------
    splash_zone_multiplier: float = Field(
        2.0,
        ge=1.0,
        description=(
            "Maximum multiplier for components experiencing full splash / "
            "wet-dry exposure, which corrode faster than fully submerged steel "
            "due to high oxygen availability and wet-dry cycling. The realized "
            "splash factor scales between 1.0 (calm) and this value with sea "
            "state. Dimensionless (>= 1)."
        ),
    )
    splash_wave_scale_m: float = Field(
        4.0,
        gt=0.0,
        description=(
            "Significant wave height (m) at which wave-driven splash wetting is "
            "considered fully developed (splash factor reaches "
            "splash_zone_multiplier). Used with storm intensity."
        ),
    )

    # -- Flow / erosion-corrosion ---------------------------------------
    speed_erosion_coefficient: float = Field(
        0.02,
        ge=0.0,
        description=(
            "Coefficient in the erosion-corrosion power law "
            "f = 1 + coeff * v_rel**exponent, where v_rel is the relative water "
            "flow speed (m/s). Captures mass-transfer / mechanical enhancement "
            "of corrosion by flow. Units: 1 / (m/s)**exponent."
        ),
    )
    speed_erosion_exponent: float = Field(
        0.8,
        ge=0.0,
        description=(
            "Exponent in the erosion-corrosion power law. ~0.8-1.0 reflects "
            "turbulent mass-transfer control; >2 would reflect mechanical "
            "erosion / cavitation regimes. Dimensionless."
        ),
    )

    # -- Coating ---------------------------------------------------------
    coating_degradation_coefficient: float = Field(
        0.05,
        ge=0.0,
        description=(
            "Baseline fractional coating-integrity loss per year of exposure, "
            "before material- and environment-specific factors. Units 1/year. "
            "(Used by the engine for time-dependent coating breakdown; the "
            "instantaneous corrosion estimate treats the coating as intact.)"
        ),
    )
    intact_coating_factor: float = Field(
        0.15,
        gt=0.0,
        le=1.0,
        description=(
            "Corrosion multiplier of a nominal, fully intact protective coating "
            "(e.g. 0.15 => an intact coating reduces metal loss to ~15% of bare "
            "metal). Scaled by the material's coating_breakdown_factor."
        ),
    )
    min_coating_factor: float = Field(
        0.02,
        gt=0.0,
        le=1.0,
        description=(
            "Lower bound on the coating factor, so even the best coating never "
            "implies exactly zero corrosion. Dimensionless."
        ),
    )


# ---------------------------------------------------------------------------
# Stability / seakeeping
# ---------------------------------------------------------------------------

class StabilityConfig(_ConfigBase):
    """Coefficients for wind/wave heeling and capsize-risk estimation."""

    wind_heeling_coefficient: float = Field(
        1.0,
        ge=0.0,
        description=(
            "Aerodynamic drag/shape coefficient used in the wind heeling-moment "
            "model M = 0.5 * Cd * rho_air * A * V^2 * lever. Dimensionless; this "
            "is the Cd term. ~1.0-1.3 for typical superstructures."
        ),
    )
    wave_risk_height_coefficient: float = Field(
        0.15,
        ge=0.0,
        description=(
            "Sensitivity of stability-risk score to significant wave height "
            "relative to ship beam/freeboard. Dimensionless per (m/m)."
        ),
    )
    wave_risk_steepness_coefficient: float = Field(
        0.20,
        ge=0.0,
        description=(
            "Sensitivity of stability-risk score to wave steepness (Hs/L). "
            "Steeper waves are more dangerous. Dimensionless."
        ),
    )
    resonance_risk_coefficient: float = Field(
        0.30,
        ge=0.0,
        description=(
            "Peak additional risk when wave encounter period matches the roll "
            "natural period (synchronous rolling). Dimensionless."
        ),
    )
    resonance_bandwidth: float = Field(
        0.25,
        gt=0.0,
        description=(
            "Relative width of the resonance window: the resonance factor is "
            "exp(-((T_encounter/T_roll - 1)/bandwidth)^2). Dimensionless."
        ),
    )

    # -- Wind heeling geometry (all documented approximations) ----------
    air_density_kg_m3: float = Field(
        1.225, gt=0.0, description="Air density used in the wind-force model (kg/m^3)."
    )
    windage_height_fraction_of_beam: float = Field(
        0.6,
        gt=0.0,
        description=(
            "Fallback windage height as a fraction of beam, used to estimate the "
            "projected lateral (windage) area as length * fraction * beam when "
            "ship.projected_lateral_area_m2 is not supplied. Dimensionless."
        ),
    )
    windage_centroid_height_factor: float = Field(
        0.5,
        ge=0.0,
        description=(
            "Height of the windage-area centroid above the waterline as a "
            "fraction of the windage height. Part of the heeling lever arm."
        ),
    )
    lateral_resistance_depth_factor: float = Field(
        0.5,
        ge=0.0,
        description=(
            "Depth of the center of underwater lateral resistance below the "
            "waterline as a fraction of draft. Part of the heeling lever arm."
        ),
    )
    reference_heel_angle_deg: float = Field(
        10.0,
        gt=0.0,
        lt=90.0,
        description=(
            "Heel angle at which the restoring-moment proxy is evaluated using "
            "the small-angle form M_r = Delta * g * GM * sin(phi). "
            "Kept in the near-linear range of the GZ curve."
        ),
    )

    # -- GM risk shaping -------------------------------------------------
    gm_reference_m: float = Field(
        0.3,
        description="GM (m) at the logistic midpoint of the GM risk factor.",
    )
    gm_scale_m: float = Field(
        0.2, gt=0.0, description="Logistic width (m) of the GM risk factor."
    )
    minimum_gm_m: float = Field(
        0.15,
        description="GM (m) below which a low-stability warning is raised.",
    )

    # -- Wave / freeboard risk shaping ----------------------------------
    freeboard_fraction_of_beam: float = Field(
        0.4,
        gt=0.0,
        description="Freeboard proxy as a fraction of beam (used for Hs/freeboard).",
    )
    wave_height_beam_scale: float = Field(
        0.6,
        gt=0.0,
        description="Scale for the saturating Hs/beam term: x/(x+scale).",
    )
    wave_height_freeboard_scale: float = Field(
        1.0,
        gt=0.0,
        description="Scale for the saturating Hs/freeboard term: x/(x+scale).",
    )
    breaking_steepness: float = Field(
        0.142,
        gt=0.0,
        description="Deep-water breaking steepness (~1/7); steepness risk saturates here.",
    )

    # -- Speed / roll ----------------------------------------------------
    froude_danger: float = Field(
        0.35,
        gt=0.0,
        description=(
            "Length Froude number U/sqrt(gL) at which speed-in-seaway risk "
            "saturates (surf-riding/broaching regime in following seas)."
        ),
    )
    roll_period_coefficient: float = Field(
        0.7,
        gt=0.0,
        description=(
            "Coefficient C in the roll-period estimate T_roll = C*B/sqrt(GM) used "
            "only when ship.roll_natural_period_s is not supplied (s per m^0.5)."
        ),
    )

    # -- Wind-vs-restoring shaping --------------------------------------
    wind_ratio_threshold: float = Field(
        1.0,
        gt=0.0,
        description=(
            "Logistic midpoint for the wind-heeling/restoring ratio risk factor. "
            "At ratio=threshold the factor is 0.5."
        ),
    )
    wind_ratio_width: float = Field(
        0.3, gt=0.0, description="Logistic width of the wind/restoring ratio factor."
    )

    # -- Center-of-gravity risk shaping ---------------------------------
    cg_reference_ratio: float = Field(
        0.65,
        gt=0.0,
        description=(
            "Logistic midpoint for KG/(draft+freeboard) (a 'top-heaviness' proxy)."
        ),
    )
    cg_scale_ratio: float = Field(
        0.12, gt=0.0, description="Logistic width for the top-heaviness factor."
    )

    # -- Risk combination weights (noisy contributions; see stability.py)
    risk_weight_gm: float = Field(1.2, ge=0.0, description="Weight of the GM factor.")
    risk_weight_wind: float = Field(
        1.0, ge=0.0, description="Weight of the wind-heeling/restoring factor."
    )
    risk_weight_wave: float = Field(
        0.8, ge=0.0, description="Weight of the wave (height/steepness) factor."
    )
    risk_weight_speed: float = Field(
        0.6, ge=0.0, description="Weight of the speed-in-seaway factor."
    )
    risk_weight_structural: float = Field(
        0.6, ge=0.0, description="Weight of the structural-weakening factor."
    )
    risk_weight_storm: float = Field(
        0.6, ge=0.0, description="Weight of the storm-intensity factor."
    )
    risk_weight_cg: float = Field(
        0.3, ge=0.0, description="Weight of the top-heaviness (CG) factor."
    )
    risk_weight_misalignment: float = Field(
        0.2, ge=0.0, description="Weight of the wave/current misalignment factor."
    )
    risk_warning_threshold: float = Field(
        0.6,
        ge=0.0,
        le=1.0,
        description="Risk score above which a high-capsize-risk warning is raised.",
    )

    # -- Misc empirical shaping constants -------------------------------
    roll_period_gm_floor_m: float = Field(
        0.05,
        gt=0.0,
        description=(
            "GM floor (m) used only when estimating roll period for low/negative "
            "GM, so the T_roll = C*B/sqrt(GM) estimate stays finite."
        ),
    )
    speed_following_seas_weight: float = Field(
        0.6,
        ge=0.0,
        le=1.0,
        description=(
            "Fraction of the speed-in-seaway factor attributed to following/"
            "quartering seas (broaching/surf-riding); the remainder applies in "
            "all headings. Dimensionless 0-1."
        ),
    )
    current_misalignment_scale_m_s: float = Field(
        1.0,
        gt=0.0,
        description=(
            "Saturation scale (m/s) for current speed in the wave/current "
            "misalignment factor: stronger crossing currents -> more confused sea."
        ),
    )

    # -- Capsize probability (per-timestep hazard) ----------------------
    capsize_risk_exponent: float = Field(
        6.0,
        gt=0.0,
        description=(
            "Exponent k mapping the risk score to a per-second capsize hazard "
            "rate ~ risk_score**k, so only high risk yields meaningful probability."
        ),
    )
    capsize_time_at_max_risk_s: float = Field(
        600.0,
        gt=0.0,
        description=(
            "Characteristic mean time-to-capsize (s) at risk_score = 1, setting "
            "the hazard scale. P(capsize over dt) = 1 - exp(-risk**k * dt / tau)."
        ),
    )


# ---------------------------------------------------------------------------
# Structural
# ---------------------------------------------------------------------------

class StructuralConfig(_ConfigBase):
    """Coefficients mapping corrosion-driven thickness loss to strength loss."""

    section_modulus_exponent: float = Field(
        1.0,
        ge=0.0,
        description=(
            "Exponent relating fractional thickness loss to fractional "
            "section-modulus loss. 1.0 = linear (thin-plate approximation); "
            "higher values penalize loss more steeply. Dimensionless."
        ),
    )
    buckling_sensitivity: float = Field(
        2.0,
        ge=0.0,
        description=(
            "Exponent for plate-buckling capacity vs thickness (Euler/Bryan "
            "plate buckling scales ~ t^2 to t^3). Dimensionless."
        ),
    )
    min_acceptable_thickness_fraction: float = Field(
        0.75,
        gt=0.0,
        le=1.0,
        description=(
            "Fraction of original thickness below which a component is flagged "
            "as structurally compromised (a common renewal criterion). "
            "Dimensionless."
        ),
    )


# ---------------------------------------------------------------------------
# Monte Carlo
# ---------------------------------------------------------------------------

class MonteCarloConfig(_ConfigBase):
    """Defaults for stochastic perturbation of inputs in Monte Carlo runs."""

    n_samples: int = Field(
        1000, ge=1, description="Default number of Monte Carlo samples."
    )
    seed: int | None = Field(
        None, description="RNG seed for reproducibility; None => nondeterministic."
    )
    corrosion_rate_rel_std: float = Field(
        0.20,
        ge=0.0,
        description="Relative standard deviation applied to corrosion rates.",
    )
    wave_height_rel_std: float = Field(
        0.15,
        ge=0.0,
        description="Relative standard deviation applied to significant wave height.",
    )
    wind_speed_rel_std: float = Field(
        0.15, ge=0.0, description="Relative standard deviation applied to wind speed."
    )


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------

class BackendConfig(_ConfigBase):
    """Compute-backend selection.

    Acceleration is intentionally optional (Phase 6). "auto" lets the engine
    pick the fastest available backend; the others force a specific path so
    behavior can be compared and tested.
    """

    backend: Literal["numpy", "numba", "rust", "auto"] = Field(
        "numpy", description="Which compute backend to use for hot loops."
    )
    n_workers: int = Field(
        1,
        ge=1,
        description="Parallel workers for embarrassingly-parallel Monte Carlo.",
    )
    allow_fallback: bool = Field(
        True,
        description="If a requested backend is unavailable, fall back to numpy.",
    )


# ---------------------------------------------------------------------------
# Top-level container
# ---------------------------------------------------------------------------

class SimulationConfig(_ConfigBase):
    """Top-level tunable configuration for the whole simulation."""

    corrosion: CorrosionConfig = Field(default_factory=CorrosionConfig)
    stability: StabilityConfig = Field(default_factory=StabilityConfig)
    structural: StructuralConfig = Field(default_factory=StructuralConfig)
    monte_carlo: MonteCarloConfig = Field(default_factory=MonteCarloConfig)
    backend: BackendConfig = Field(default_factory=BackendConfig)

    @classmethod
    def default(cls) -> "SimulationConfig":
        """Return a configuration populated entirely with documented defaults."""
        return cls()


__all__ = [
    "CorrosionConfig",
    "StabilityConfig",
    "StructuralConfig",
    "MonteCarloConfig",
    "BackendConfig",
    "SimulationConfig",
]
