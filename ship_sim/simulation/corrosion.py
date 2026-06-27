"""Physically motivated marine-corrosion rate model.

The corrosion rate of a component is built up from a material **base rate**
(free corrosion in a reference seawater environment) multiplied by a product of
**transparent, individually inspectable dimensionless factors**, one per
environmental driver::

    rate = base_rate
         * material_resistance_adjustment      (alloy resistance)
         * salinity_factor                      (conductivity / chloride)
         * temperature_factor                   (Arrhenius)
         * pH_factor                            (acidity)
         * oxygen_factor                        (cathodic reactant supply)
         * pollution_factor                     (aggressive species)
         * splash_factor                        (wet-dry / splash wetting)
         * speed_erosion_factor                 (erosion-corrosion power law)
         * coating_factor                       (barrier protection)
         * exposure_fraction                    (fraction in contact)

Every factor equals ``1.0`` at its reference condition, so deviations from a
nominal environment are easy to read off and explain in a report. None of the
physics is hidden inside a single opaque score.

Modeling choices and simplifications (see also each factor's docstring):

- Steady-state electrochemical corrosion is assumed; transients and passivation
  kinetics are not resolved.
- Temperature uses the seawater temperature (immersed electrochemistry); the
  atmospheric ``WeatherCondition`` currently contributes only through
  storm-driven splash wetting.
- The pH factor is linear and intended for the near-neutral seawater range
  (~6-9.5); strong-acid hydrogen-evolution behavior is not captured.
- Coating is treated as a fresh, nominal coating in the instantaneous estimate.
  Time-dependent coating breakdown (``coating_degradation_coefficient``) is the
  engine's responsibility in a later step.
- Galvanic coupling between dissimilar materials is not yet modeled here.

This module is self-contained: it depends only on the data models, the config,
and the unit helpers, and performs no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..config import CorrosionConfig, SimulationConfig
from ..models.environment import RegionEnvironment
from ..models.materials import Material, ShipComponent
from ..models.waves import WaveCondition
from ..models.weather import WeatherCondition
from ..units import (
    GAS_CONSTANT_R,
    celsius_to_kelvin,
    m_per_s_to_mm_per_year,
    m_per_year_to_m_per_s,
)

# A tiny positive floor used to keep factors strictly positive.
_EPS = 1.0e-9


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CorrosionEstimate:
    """Instantaneous corrosion rate plus every contributing factor.

    All factors are dimensionless and equal 1.0 at their reference condition.
    ``total_multiplier`` is the full multiplier on ``base_rate`` and therefore
    includes the material-resistance adjustment and the exposure fraction (which
    are not separate fields), so that::

        corrosion_rate_m_per_s == base_rate_m_per_s * total_multiplier
    """

    corrosion_rate_m_per_s: float
    corrosion_rate_mm_per_year: float
    salinity_factor: float
    temperature_factor: float
    pH_factor: float
    oxygen_factor: float
    pollution_factor: float
    splash_factor: float
    speed_erosion_factor: float
    coating_factor: float
    total_multiplier: float
    assumptions: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ComponentCorrosionUpdate:
    """Result of advancing one component's corrosion by a single timestep."""

    component_name: str
    thickness_loss_m: float
    accumulated_corrosion_m: float
    effective_thickness_m: float
    remaining_thickness_fraction: float
    corrosion_rate_m_per_s: float
    corrosion_rate_mm_per_year: float
    safety_margin: float
    warnings: List[str] = field(default_factory=list)
    intermediate_factors: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Individual factor models (pure, independently testable)
#
# Each takes the relevant raw quantity and a CorrosionConfig and returns a
# dimensionless factor that is 1.0 at the reference condition.
# ---------------------------------------------------------------------------

def salinity_factor(salinity_ppt: float, cfg: CorrosionConfig) -> float:
    """Saturating increase of corrosion with salinity.

    Higher salinity raises electrolyte conductivity and chloride activity,
    accelerating corrosion, but the effect saturates (and very high salinity
    even lowers oxygen solubility). Modeled as::

        f = 1 + sensitivity * scale * tanh((S - S_ref) / scale)

    so the near-reference slope is ``salinity_sensitivity`` (per ppt) and the
    factor levels off far from the reference. Clamped to stay positive.
    """
    scale = cfg.salinity_saturation_scale_ppt
    f = 1.0 + cfg.salinity_sensitivity * scale * math.tanh(
        (salinity_ppt - cfg.reference_salinity_ppt) / scale
    )
    return max(_EPS, f)


def temperature_factor(water_temperature_c: float, cfg: CorrosionConfig) -> float:
    """Arrhenius temperature dependence of the corrosion rate.

    ``f = exp(-Ea/R * (1/T - 1/T_ref))`` with temperatures in kelvin. This is
    the physically standard form for a thermally activated process and gives a
    Q10 of roughly 1.5-2 for typical activation energies, rather than an
    arbitrary linear scaling.
    """
    t = celsius_to_kelvin(water_temperature_c)
    t_ref = celsius_to_kelvin(cfg.reference_temperature_c)
    exponent = -(cfg.activation_energy_j_per_mol / GAS_CONSTANT_R) * (
        1.0 / t - 1.0 / t_ref
    )
    return math.exp(exponent)


def ph_factor(ph: float, cfg: CorrosionConfig) -> float:
    """Acidity dependence: lower pH increases corrosion.

    Linear in the deviation below the reference pH, valid for the near-neutral
    seawater range. ``f = 1 + ph_sensitivity * (pH_ref - pH)``, clamped positive.
    """
    return max(_EPS, 1.0 + cfg.ph_sensitivity * (cfg.reference_ph - ph))


def oxygen_factor(dissolved_oxygen_mg_l: float, cfg: CorrosionConfig) -> float:
    """Dissolved-oxygen dependence (cathodic reactant), saturating at high O2.

    Oxygen reduction is the dominant cathodic reaction for steel in aerated
    seawater, so corrosion increases with dissolved oxygen but saturates once
    oxygen is no longer transport-limiting::

        f = 1 + sensitivity * scale * tanh((O2 - O2_ref) / scale)
    """
    scale = cfg.oxygen_saturation_scale_mg_l
    f = 1.0 + cfg.oxygen_sensitivity * scale * math.tanh(
        (dissolved_oxygen_mg_l - cfg.reference_oxygen_mg_l) / scale
    )
    return max(_EPS, f)


def pollution_factor(pollution_0_1: float, cfg: CorrosionConfig) -> float:
    """Pollution dependence: aggressive species accelerate corrosion.

    ``f = 1 + pollution_multiplier * pollution_factor_0_1`` (>= 1).
    """
    return 1.0 + cfg.pollution_multiplier * pollution_0_1


def splash_factor(
    significant_wave_height_m: float, storm_intensity_0_1: float, cfg: CorrosionConfig
) -> float:
    """Wave-driven splash / wet-dry enhancement.

    Splash-zone steel corrodes faster than fully submerged steel because of
    abundant oxygen and wet-dry cycling. Here the enhancement scales with sea
    state (wave height, with a floor from storm intensity) between 1.0 (calm)
    and ``splash_zone_multiplier`` (fully developed splash)::

        wetting = clamp(max(Hs / Hs_scale, storm_intensity), 0, 1)
        f = 1 + (splash_zone_multiplier - 1) * wetting

    Simplification: this uses the ambient sea state rather than each
    component's height relative to the waterline (the engine, which knows the
    draft, can refine this later).
    """
    wetting = max(
        significant_wave_height_m / cfg.splash_wave_scale_m, storm_intensity_0_1
    )
    wetting = min(1.0, max(0.0, wetting))
    return 1.0 + (cfg.splash_zone_multiplier - 1.0) * wetting


def speed_erosion_factor(relative_flow_speed_m_s: float, cfg: CorrosionConfig) -> float:
    """Erosion-corrosion velocity power law.

    Flow thins the diffusion boundary layer and can mechanically remove
    protective films, both of which raise the corrosion rate::

        f = 1 + coeff * v_rel ** exponent  (>= 1)
    """
    v = max(0.0, relative_flow_speed_m_s)
    return 1.0 + cfg.speed_erosion_coefficient * (v ** cfg.speed_erosion_exponent)


def coating_factor(coating_breakdown_factor: float, cfg: CorrosionConfig) -> float:
    """Barrier protection from a fresh, nominal coating.

    A protective coating multiplies the corrosion rate by a small factor. A
    material whose coating system is more susceptible to breakdown
    (``coating_breakdown_factor`` > 1) gets less protection (factor closer to
    1.0); a better coating (< 1) gets more protection::

        f = clamp(intact_coating_factor * coating_breakdown_factor,
                  min_coating_factor, 1.0)

    Time-dependent coating degradation is applied by the engine in a later step.
    """
    f = cfg.intact_coating_factor * coating_breakdown_factor
    return min(1.0, max(cfg.min_coating_factor, f))


def material_resistance_adjustment(corrosion_resistance_factor: float) -> float:
    """Reduce corrosion for more resistant alloys: ``1 / resistance_factor``."""
    return 1.0 / max(_EPS, corrosion_resistance_factor)


# ---------------------------------------------------------------------------
# Top-level estimate
# ---------------------------------------------------------------------------

def estimate_corrosion_rate(
    material: Material,
    environment: RegionEnvironment,
    weather: WeatherCondition,
    wave: WaveCondition,
    speed_m_s: float,
    exposure_fraction: float,
    config: SimulationConfig,
) -> CorrosionEstimate:
    """Estimate the instantaneous corrosion rate for a material in a condition.

    Parameters
    ----------
    material:
        A :class:`~ship_sim.models.materials.Material`; its
        ``base_corrosion_rate_m_per_year`` and ``corrosion_resistance_factor``
        / ``coating_breakdown_factor`` set the baseline and material factors.
    environment, weather, wave:
        Local seawater, atmospheric, and sea-state conditions.
    speed_m_s:
        Vessel speed over ground (m/s). Combined with the current to form the
        relative flow speed used by the erosion-corrosion factor.
    exposure_fraction:
        Fraction (0-1) of the surface in contact with the corrosive medium. A
        value of 0 yields exactly zero corrosion.
    config:
        Tunable coefficients (uses ``config.corrosion``).

    Returns
    -------
    CorrosionEstimate
        The rate and every contributing dimensionless factor.
    """
    cfg = config.corrosion

    base_rate = m_per_year_to_m_per_s(material.base_corrosion_rate_m_per_year)
    resistance_adj = material_resistance_adjustment(material.corrosion_resistance_factor)

    f_sal = salinity_factor(environment.salinity_ppt, cfg)
    f_temp = temperature_factor(environment.water_temperature_c, cfg)
    f_ph = ph_factor(environment.pH, cfg)
    f_o2 = oxygen_factor(environment.dissolved_oxygen_mg_l, cfg)
    f_poll = pollution_factor(environment.pollution_factor_0_1, cfg)
    f_splash = splash_factor(
        wave.significant_wave_height_m, weather.storm_intensity_0_1, cfg
    )
    relative_flow = max(0.0, speed_m_s) + wave.current_speed_m_s
    f_speed = speed_erosion_factor(relative_flow, cfg)
    f_coat = coating_factor(material.coating_breakdown_factor, cfg)

    exposure = min(1.0, max(0.0, exposure_fraction))

    total_multiplier = (
        resistance_adj
        * f_sal
        * f_temp
        * f_ph
        * f_o2
        * f_poll
        * f_splash
        * f_speed
        * f_coat
        * exposure
    )
    rate_m_s = base_rate * total_multiplier

    assumptions = [
        "Steady-state electrochemical corrosion; transients/passivation not resolved.",
        "Arrhenius temperature dependence using seawater temperature.",
        "pH factor linear, valid for near-neutral seawater (~6-9.5).",
        "Splash from ambient sea state, not component height vs waterline.",
        "Coating treated as fresh/intact (time-dependent breakdown applied by engine).",
        "Galvanic coupling between dissimilar materials not modeled.",
        f"Relative flow speed = speed + current = {relative_flow:.3f} m/s.",
        f"Material resistance adjustment = {resistance_adj:.4f}; "
        f"exposure fraction = {exposure:.3f} (both folded into total_multiplier).",
    ]

    return CorrosionEstimate(
        corrosion_rate_m_per_s=rate_m_s,
        corrosion_rate_mm_per_year=m_per_s_to_mm_per_year(rate_m_s),
        salinity_factor=f_sal,
        temperature_factor=f_temp,
        pH_factor=f_ph,
        oxygen_factor=f_o2,
        pollution_factor=f_poll,
        splash_factor=f_splash,
        speed_erosion_factor=f_speed,
        coating_factor=f_coat,
        total_multiplier=total_multiplier,
        assumptions=assumptions,
    )


# ---------------------------------------------------------------------------
# Per-component, per-timestep update
# ---------------------------------------------------------------------------

def update_component_corrosion(
    component: ShipComponent,
    accumulated_corrosion_m: float,
    environment: RegionEnvironment,
    weather: WeatherCondition,
    wave: WaveCondition,
    speed_m_s: float,
    dt_s: float,
    config: SimulationConfig,
) -> ComponentCorrosionUpdate:
    """Advance a single component's corrosion by one timestep.

    Computes the instantaneous rate (via :func:`estimate_corrosion_rate`),
    integrates it over ``dt_s`` to get the thickness lost this step, updates the
    accumulated loss and effective thickness, and evaluates safety warnings.

    The ``accumulated_corrosion_m`` passed in is the *total* metal lost so far
    (it should include any pre-existing loss, i.e. ``original - current``
    thickness, when the engine initializes it). Effective thickness is therefore
    ``original_thickness_m - accumulated_corrosion_m``.

    Returns
    -------
    ComponentCorrosionUpdate
        Updated thicknesses, rate, safety margin, warnings, and the full set of
        intermediate factors for reporting.
    """
    if dt_s < 0.0:
        raise ValueError("dt_s must be non-negative.")

    estimate = estimate_corrosion_rate(
        material=component.material,
        environment=environment,
        weather=weather,
        wave=wave,
        speed_m_s=speed_m_s,
        exposure_fraction=component.exposed_fraction,
        config=config,
    )

    thickness_loss = estimate.corrosion_rate_m_per_s * dt_s
    new_accumulated = accumulated_corrosion_m + thickness_loss

    original = component.original_thickness_m
    effective = max(0.0, original - new_accumulated)
    remaining_fraction = effective / original if original > 0.0 else 0.0

    # Safety margin: the design corrosion allowance is sized so that, once it is
    # fully consumed (effective == original - allowance), the available safety
    # factor equals the required one. Above that thickness the margin is larger;
    # below it, smaller. This keeps the allowance, required SF, and thickness
    # mutually consistent in one physically motivated expression.
    allowance = component.corrosion_allowance_m
    design_min_thickness = max(_EPS, original - allowance)
    safety_margin = component.safety_factor_required * effective / design_min_thickness

    warnings: List[str] = []
    if effective < original - allowance:
        warnings.append(
            f"{component.name}: corrosion allowance exceeded "
            f"(effective {effective * 1e3:.2f} mm < design min "
            f"{(original - allowance) * 1e3:.2f} mm)."
        )
    min_fraction = config.structural.min_acceptable_thickness_fraction
    if remaining_fraction < min_fraction:
        warnings.append(
            f"{component.name}: thickness {remaining_fraction * 100:.1f}% of original "
            f"is below the minimum acceptable {min_fraction * 100:.0f}%."
        )
    if safety_margin < component.safety_factor_required:
        warnings.append(
            f"{component.name}: safety margin {safety_margin:.2f} is below the "
            f"required {component.safety_factor_required:.2f}."
        )

    intermediate_factors: Dict[str, Any] = {
        "salinity_factor": estimate.salinity_factor,
        "temperature_factor": estimate.temperature_factor,
        "pH_factor": estimate.pH_factor,
        "oxygen_factor": estimate.oxygen_factor,
        "pollution_factor": estimate.pollution_factor,
        "splash_factor": estimate.splash_factor,
        "speed_erosion_factor": estimate.speed_erosion_factor,
        "coating_factor": estimate.coating_factor,
        "total_multiplier": estimate.total_multiplier,
        "base_rate_mm_per_year": component.material.base_corrosion_rate_m_per_year * 1e3,
        "exposed_fraction": component.exposed_fraction,
    }

    return ComponentCorrosionUpdate(
        component_name=component.name,
        thickness_loss_m=thickness_loss,
        accumulated_corrosion_m=new_accumulated,
        effective_thickness_m=effective,
        remaining_thickness_fraction=remaining_fraction,
        corrosion_rate_m_per_s=estimate.corrosion_rate_m_per_s,
        corrosion_rate_mm_per_year=estimate.corrosion_rate_mm_per_year,
        safety_margin=safety_margin,
        warnings=warnings,
        intermediate_factors=intermediate_factors,
    )


__all__ = [
    "CorrosionEstimate",
    "ComponentCorrosionUpdate",
    "estimate_corrosion_rate",
    "update_component_corrosion",
    "salinity_factor",
    "temperature_factor",
    "ph_factor",
    "oxygen_factor",
    "pollution_factor",
    "splash_factor",
    "speed_erosion_factor",
    "coating_factor",
    "material_resistance_adjustment",
]
