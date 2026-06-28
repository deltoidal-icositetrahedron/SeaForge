"""Simplified, physically interpretable stability & capsizing-risk model.

The goal is transparency, not fidelity: every contribution to the capsize-risk
score is a named, bounded factor with a clear physical meaning, so a report can
explain *why* a vessel is at risk. The pieces are:

1. **Structural weakening** (:func:`estimate_structural_weakening`) -- how much
   corrosion-driven thickness loss has reduced effective strength.
2. **Wind heeling moment** (:func:`estimate_wind_heeling_moment`) -- aerodynamic
   heeling from beam-relative wind.
3. **Stability risk** (:func:`estimate_stability_risk`) -- a bounded risk score
   and per-timestep capsize probability combining GM, wind/restoring ratio,
   wave height & steepness, roll resonance, speed-in-seaway, structural
   weakening, storm intensity, top-heaviness, and wave/current misalignment.

Key physical quantities used (all surfaced in the result's ``explanation``):
metacentric height GM, a small-angle restoring-moment proxy
``Delta*g*GM*sin(phi_ref)``, wind heeling moment, wave steepness, Hs relative to
beam and a freeboard proxy, encounter period, roll natural period, a resonance
factor, length Froude number, and a structural weakening factor.

Risk combination
----------------
Each driver is mapped to a factor in ``[0, 1]`` with bounded smooth functions
(logistic or saturating ratios). They are combined as independent hazard
contributions::

    T = sum_i  weight_i * factor_i
    risk_score = 1 - exp(-T)            (always in [0, 1))

so adding any hazard can only increase risk and the score saturates near 1. The
per-timestep capsize probability treats capsizing as a Poisson process whose
hazard rate grows steeply with risk::

    P(capsize over dt) = 1 - exp(-(risk_score**k) * dt / tau)

which is 0 at dt=0 and scales sensibly with dt.

IMPORTANT: This is an engineering approximation. It is NOT a substitute for
intact/damage stability analysis, GZ-curve evaluation against IMO criteria, CFD,
model-basin testing, or classification-society rules.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from .._math import clamp01, logistic, saturating
from ..config import SimulationConfig
from ..models.ship import Ship
from ..models.waves import WaveCondition
from ..models.weather import WeatherCondition
from ..units import GRAVITY
from .seakeeping import estimate_wave_encounter


# ---------------------------------------------------------------------------
# Structural weakening
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StructuralWeakeningEstimate:
    """How far corrosion has reduced effective structural capacity."""

    weakening_factor_0_1: float
    component_margins: Dict[str, float]
    most_critical_components: List[str]
    explanation: str


def estimate_structural_weakening(
    ship: Ship,
    effective_thickness_by_component: Mapping[str, float],
    config: SimulationConfig,
) -> StructuralWeakeningEstimate:
    """Aggregate per-component thickness loss into a 0-1 weakening factor.

    For each component the remaining strength fraction is approximated as
    ``(effective/original) ** section_modulus_exponent`` (section modulus of a
    thin plate scales with thickness; the exponent is tunable). The fractional
    strength *loss* is then weighted by ``structural_importance`` and averaged.

    Components missing from ``effective_thickness_by_component`` are treated as
    intact (full original thickness).

    Returns
    -------
    StructuralWeakeningEstimate
        ``weakening_factor_0_1`` (0 = intact, 1 = fully lost), per-component
        remaining-strength ``component_margins``, the most critical components,
        and a short ``explanation``.
    """
    exponent = config.structural.section_modulus_exponent

    margins: Dict[str, float] = {}
    contributions: Dict[str, float] = {}
    total_weight = 0.0
    weighted_loss = 0.0

    for comp in ship.components:
        original = comp.original_thickness_m
        effective = effective_thickness_by_component.get(comp.name, original)
        effective = max(0.0, min(effective, original))
        remaining_fraction = effective / original if original > 0 else 0.0
        strength_fraction = remaining_fraction ** exponent
        loss = 1.0 - strength_fraction

        weight = comp.structural_importance
        margins[comp.name] = strength_fraction
        contributions[comp.name] = weight * loss
        weighted_loss += weight * loss
        total_weight += weight

    weakening = clamp01(weighted_loss / total_weight) if total_weight > 0 else 0.0

    # Most critical = largest importance-weighted loss contributions.
    ranked = sorted(contributions.items(), key=lambda kv: kv[1], reverse=True)
    most_critical = [name for name, contrib in ranked if contrib > 1e-6][:3]

    if weakening < 1e-6:
        explanation = "All components effectively at full thickness; no weakening."
    else:
        worst = ", ".join(
            f"{name} ({margins[name] * 100:.0f}% strength)" for name in most_critical
        ) or "n/a"
        explanation = (
            f"Importance-weighted effective-strength loss is {weakening * 100:.1f}%. "
            f"Most critical: {worst}."
        )

    return StructuralWeakeningEstimate(
        weakening_factor_0_1=weakening,
        component_margins=margins,
        most_critical_components=most_critical,
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# Wind heeling moment
# ---------------------------------------------------------------------------

def _windage_area_and_height(ship: Ship, config: SimulationConfig) -> tuple[float, float]:
    """Return (projected_lateral_area, effective windage height).

    Uses ``ship.projected_lateral_area_m2`` when available; otherwise falls back
    to ``length * windage_height_fraction_of_beam * beam`` (a documented proxy).
    The windage height is the area divided by length.
    """
    cfg = config.stability
    if ship.projected_lateral_area_m2 is not None:
        area = ship.projected_lateral_area_m2
    else:
        area = ship.length_m * cfg.windage_height_fraction_of_beam * ship.beam_m
    height = area / ship.length_m if ship.length_m > 0 else 0.0
    return area, height


def estimate_wind_heeling_moment(
    ship: Ship,
    weather: WeatherCondition,
    heading_deg: Optional[float],
    config: SimulationConfig,
) -> float:
    """Estimate the wind heeling moment (N*m).

    Aerodynamic force on the windage area::

        F = 0.5 * rho_air * Cd * A * V^2

    applied at a heeling lever arm equal to the windage-centroid height above
    the waterline plus the depth of the center of lateral resistance below it::

        lever = height * windage_centroid_height_factor
              + draft * lateral_resistance_depth_factor

    The heeling component scales with ``|sin(relative wind angle)|`` (max for
    beam wind). If ``heading_deg`` is ``None``, beam wind is assumed (the
    conservative weather-criterion convention), i.e. ``sin = 1``.

    Cd, air density, the windage-area fallback, and the lever-arm fractions are
    all configurable in :class:`~ship_sim.config.StabilityConfig`.
    """
    cfg = config.stability
    area, height = _windage_area_and_height(ship, config)

    force = 0.5 * cfg.air_density_kg_m3 * cfg.wind_heeling_coefficient * area * (
        weather.wind_speed_m_s ** 2
    )
    lever = (
        height * cfg.windage_centroid_height_factor
        + ship.draft_m * cfg.lateral_resistance_depth_factor
    )

    if heading_deg is None:
        sin_factor = 1.0
    else:
        relative = math.radians((weather.wind_direction_deg - heading_deg) % 360.0)
        sin_factor = abs(math.sin(relative))

    return force * lever * sin_factor


# ---------------------------------------------------------------------------
# Stability risk
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StabilityEstimate:
    """Bounded capsize-risk score, per-timestep probability, and its drivers."""

    risk_score_0_1: float
    capsize_probability_timestep: float
    wind_heeling_moment_nm: float
    restoring_moment_proxy_nm: float
    structural_weakening_factor: float
    wave_risk_factor: float
    resonance_risk_factor: float
    speed_in_sea_state_factor: float
    gm_factor: float
    explanation: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


def _roll_natural_period(ship: Ship, gm: float, config: SimulationConfig) -> float:
    """Roll natural period (s): use the ship's value, else C*B/sqrt(GM)."""
    if ship.roll_natural_period_s is not None:
        return ship.roll_natural_period_s
    # Floor GM so T_roll = C*B/sqrt(GM) stays finite for low/negative GM.
    gm_eff = max(gm, config.stability.roll_period_gm_floor_m)
    return config.stability.roll_period_coefficient * ship.beam_m / math.sqrt(gm_eff)


def estimate_stability_risk(
    ship: Ship,
    effective_thickness_by_component: Mapping[str, float],
    weather: WeatherCondition,
    wave: WaveCondition,
    speed_m_s: float,
    dt_s: float,
    config: SimulationConfig,
    heading_degrees: Optional[float] = None,
) -> StabilityEstimate:
    """Estimate capsize risk for one condition and timestep.

    See the module docstring for the combination model. All risk drivers are
    bounded to ``[0, 1]``; ``risk_score`` and ``capsize_probability_timestep``
    are guaranteed to lie in ``[0, 1]``, and the probability scales with
    ``dt_s`` (and is 0 when ``dt_s`` is 0).
    """
    if dt_s < 0.0:
        raise ValueError("dt_s must be non-negative.")

    cfg = config.stability
    gm = ship.metacentric_height_m
    displacement_weight = ship.displacement_mass_kg * GRAVITY

    # --- restoring-moment proxy and wind heeling -----------------------
    phi_ref = math.radians(cfg.reference_heel_angle_deg)
    restoring_proxy = displacement_weight * gm * math.sin(phi_ref)
    wind_moment = estimate_wind_heeling_moment(ship, weather, heading_degrees, config)

    # --- GM factor (low/negative GM -> high risk) ----------------------
    gm_factor = logistic(-(gm - cfg.gm_reference_m) / cfg.gm_scale_m)

    # --- wind heeling vs restoring -------------------------------------
    if restoring_proxy <= 0.0:
        wind_ratio = math.inf
        wind_factor = 1.0  # no positive restoring capacity -> maximal hazard
    else:
        wind_ratio = wind_moment / restoring_proxy
        wind_factor = logistic((wind_ratio - cfg.wind_ratio_threshold) / cfg.wind_ratio_width)

    # --- wave encounter, steepness, resonance --------------------------
    encounter = estimate_wave_encounter(speed_m_s, heading_degrees, wave)
    beam = ship.beam_m
    freeboard_proxy = cfg.freeboard_fraction_of_beam * beam

    height_beam_term = saturating(
        wave.significant_wave_height_m / beam if beam > 0 else 0.0,
        cfg.wave_height_beam_scale,
    )
    height_freeboard_term = saturating(
        wave.significant_wave_height_m / freeboard_proxy if freeboard_proxy > 0 else 0.0,
        cfg.wave_height_freeboard_scale,
    )
    steepness_term = clamp01(encounter.wave_steepness / cfg.breaking_steepness)
    wave_risk_factor = clamp01(
        cfg.wave_risk_height_coefficient * (height_beam_term + height_freeboard_term)
        + cfg.wave_risk_steepness_coefficient * steepness_term
    )

    # Resonance: proximity of encounter period to roll natural period.
    roll_period = _roll_natural_period(ship, gm, config)
    if math.isfinite(encounter.encounter_period_s) and roll_period > 0:
        ratio = encounter.encounter_period_s / roll_period
        resonance_proximity = math.exp(-((ratio - 1.0) / cfg.resonance_bandwidth) ** 2)
    else:
        ratio = math.inf
        resonance_proximity = 0.0
    # Roll is excited most in beam seas: weight by |sin(relative heading)|.
    mu_rad = math.radians(encounter.relative_heading_deg)
    beam_excitation = abs(math.sin(mu_rad))
    resonance_risk_factor = resonance_proximity  # reported as pure timing proximity
    roll_term = resonance_proximity * beam_excitation

    # --- speed in seaway (broaching / surf-riding in following seas) ----
    froude = speed_m_s / math.sqrt(GRAVITY * ship.length_m) if ship.length_m > 0 else 0.0
    speed_term = clamp01(froude / cfg.froude_danger)
    following_weight = clamp01(math.cos(mu_rad))  # 1 following, 0 head
    fw = cfg.speed_following_seas_weight  # share weighted toward following seas
    speed_in_sea_state_factor = clamp01(
        speed_term * height_beam_term * ((1.0 - fw) + fw * following_weight)
    )

    # --- structural weakening ------------------------------------------
    weakening = estimate_structural_weakening(
        ship, effective_thickness_by_component, config
    )
    structural_factor = weakening.weakening_factor_0_1

    # --- storm and top-heaviness (CG) ----------------------------------
    storm_factor = clamp01(weather.storm_intensity_0_1)
    depth_proxy = ship.draft_m + freeboard_proxy
    kg_ratio = ship.center_of_gravity_height_m / depth_proxy if depth_proxy > 0 else 0.0
    cg_factor = logistic((kg_ratio - cfg.cg_reference_ratio) / cfg.cg_scale_ratio)

    # --- wave/current misalignment (confused sea) ----------------------
    misalign_rad = math.radians(
        (wave.mean_wave_direction_deg - wave.current_direction_deg) % 360.0
    )
    current_strength = saturating(wave.current_speed_m_s, cfg.current_misalignment_scale_m_s)
    misalignment_factor = abs(math.sin(misalign_rad)) * current_strength

    # --- combine into a bounded risk score -----------------------------
    contributions = {
        "gm": (cfg.risk_weight_gm, gm_factor),
        "wind": (cfg.risk_weight_wind, wind_factor),
        "wave": (cfg.risk_weight_wave, wave_risk_factor),
        "resonance": (cfg.resonance_risk_coefficient, roll_term),
        "speed": (cfg.risk_weight_speed, speed_in_sea_state_factor),
        "structural": (cfg.risk_weight_structural, structural_factor),
        "storm": (cfg.risk_weight_storm, storm_factor),
        "cg": (cfg.risk_weight_cg, cg_factor),
        "misalignment": (cfg.risk_weight_misalignment, misalignment_factor),
    }
    hazard = sum(w * f for w, f in contributions.values())
    risk_score = clamp01(1.0 - math.exp(-hazard))

    # --- per-timestep capsize probability (Poisson hazard) -------------
    hazard_rate = (risk_score ** cfg.capsize_risk_exponent) / cfg.capsize_time_at_max_risk_s
    capsize_prob = clamp01(1.0 - math.exp(-hazard_rate * dt_s))

    # --- warnings ------------------------------------------------------
    warnings: List[str] = []
    if gm <= 0.0:
        warnings.append(
            f"Negative/zero GM ({gm:.3f} m): vessel is initially unstable."
        )
    elif gm < cfg.minimum_gm_m:
        warnings.append(
            f"Low GM ({gm:.3f} m) below minimum {cfg.minimum_gm_m:.3f} m."
        )
    if restoring_proxy > 0.0 and wind_moment > restoring_proxy:
        warnings.append(
            "Wind heeling moment exceeds the restoring-moment proxy "
            f"(ratio {wind_ratio:.2f})."
        )
    if roll_term > 0.5:
        warnings.append(
            f"Roll-resonance risk: encounter period {encounter.encounter_period_s:.1f} s "
            f"near roll period {roll_period:.1f} s in beam-ish seas."
        )
    if structural_factor > 0.25:
        warnings.append(
            f"Significant structural weakening ({structural_factor * 100:.0f}% "
            "effective-strength loss)."
        )
    if risk_score >= cfg.risk_warning_threshold:
        warnings.append(f"High capsize-risk score ({risk_score:.2f}).")

    explanation: Dict[str, Any] = {
        "GM_m": gm,
        "KG_m": ship.center_of_gravity_height_m,
        "displacement_weight_N": displacement_weight,
        "reference_heel_deg": cfg.reference_heel_angle_deg,
        "restoring_moment_proxy_Nm": restoring_proxy,
        "wind_heeling_moment_Nm": wind_moment,
        "wind_to_restoring_ratio": wind_ratio,
        "relative_heading_deg": encounter.relative_heading_deg,
        "encounter_period_s": encounter.encounter_period_s,
        "roll_natural_period_s": roll_period,
        "encounter_to_roll_ratio": ratio,
        "beam_excitation": beam_excitation,
        "wave_steepness": encounter.wave_steepness,
        "Hs_over_beam": wave.significant_wave_height_m / beam if beam > 0 else 0.0,
        "Hs_over_freeboard_proxy": (
            wave.significant_wave_height_m / freeboard_proxy if freeboard_proxy > 0 else 0.0
        ),
        "froude_number": froude,
        "following_weight": following_weight,
        "kg_ratio": kg_ratio,
        "factors": {
            "gm_factor": gm_factor,
            "wind_factor": wind_factor,
            "wave_risk_factor": wave_risk_factor,
            "resonance_risk_factor": resonance_risk_factor,
            "roll_term(beam-weighted)": roll_term,
            "speed_in_sea_state_factor": speed_in_sea_state_factor,
            "structural_weakening_factor": structural_factor,
            "storm_factor": storm_factor,
            "cg_factor": cg_factor,
            "misalignment_factor": misalignment_factor,
        },
        "weighted_contributions": {
            name: weight * factor for name, (weight, factor) in contributions.items()
        },
        "hazard_sum": hazard,
        "structural_detail": weakening.explanation,
    }

    return StabilityEstimate(
        risk_score_0_1=risk_score,
        capsize_probability_timestep=capsize_prob,
        wind_heeling_moment_nm=wind_moment,
        restoring_moment_proxy_nm=restoring_proxy,
        structural_weakening_factor=structural_factor,
        wave_risk_factor=wave_risk_factor,
        resonance_risk_factor=resonance_risk_factor,
        speed_in_sea_state_factor=speed_in_sea_state_factor,
        gm_factor=gm_factor,
        explanation=explanation,
        warnings=warnings,
    )


__all__ = [
    "StructuralWeakeningEstimate",
    "StabilityEstimate",
    "estimate_structural_weakening",
    "estimate_wind_heeling_moment",
    "estimate_stability_risk",
]
