"""Human-readable Markdown reports explaining corrosion and stability results.

Three generators turn a :class:`~ship_sim.models.results.SimulationResult` into
readable Markdown:

- :func:`generate_corrosion_report`     -- what corroded, how fast, why.
- :func:`generate_stability_report`     -- when/where capsize risk peaked, why.
- :func:`generate_overall_risk_report`  -- combined summary, top movers,
  warnings, recommendations, and an explicit limitations section.

The reports read directly from the result's summaries and timeline; they add no
new physics, only interpretation. They restate that this is an engineering
approximation, not a certified safety assessment.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..models.results import SimulationResult, SimulationState
from ..units import seconds_to_hours

# Friendly labels for the stability risk-contribution keys.
_RISK_LABELS = {
    "gm": "low metacentric height (GM)",
    "wind": "wind heeling",
    "wave": "wave height / steepness",
    "resonance": "roll resonance",
    "speed": "speed in seaway",
    "structural": "structural weakening",
    "storm": "storm intensity",
    "cg": "high center of gravity",
    "misalignment": "wave/current misalignment",
}

# The explicit limitations mandated for this project (overall report).
MODEL_LIMITATIONS = (
    "Simplified, empirical corrosion model (factor product), not first-principles.",
    "No detailed electrochemical-cell modeling (no anode/cathode kinetics, "
    "polarization curves, or local pitting electrochemistry).",
    "No computational fluid dynamics (CFD) for flow, wind, or green water.",
    "No strip theory or full seakeeping solver (roll response is parameterized).",
    "No finite-element structural model (thickness->strength is a thin-plate proxy).",
    "No classification-society rule compliance (IACS/IMO criteria not evaluated).",
    "No cargo-shift, free-surface, downflooding, or progressive-flooding model.",
    "No guarantee of real-world safety; outputs are comparative/illustrative only.",
)

RECOMMENDED_IMPROVEMENTS = (
    "Integrate time-dependent coating breakdown and galvanic coupling between "
    "dissimilar materials.",
    "Add a proper GZ curve and IMO weather-criterion / area-ratio checks instead "
    "of a small-angle restoring proxy.",
    "Replace the parameterized roll model with linear strip-theory RAOs (and a "
    "JONSWAP/PM spectrum) for encounter response.",
    "Add localized pitting / fatigue-crack growth and load redistribution between "
    "components (toward an FE model).",
    "Calibrate all coefficients against measured corrosion coupons and stability "
    "trials; quantify uncertainty (Monte Carlo).",
)

RECOMMENDED_DATA = (
    "Measured corrosion rates / coupon data for the actual coatings and alloys in "
    "the operating waters.",
    "As-built hydrostatics: real GZ curve, KG, free-surface effects, loading "
    "conditions, and roll-damping/period trials.",
    "Reanalysis or in-situ metocean data (wind, wave spectra, currents, "
    "temperature, salinity, pH, dissolved oxygen) along the route.",
    "Inspection thickness measurements (UT gauging) to anchor effective-thickness "
    "estimates.",
    "Coating age/condition history and cathodic-protection (anode) status.",
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _fmt_time(time_s: Optional[float]) -> str:
    if time_s is None:
        return "n/a"
    h = seconds_to_hours(time_s)
    return f"t = {h:.1f} h ({h / 24:.2f} d)"


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def _dominant_contribution(contribs: Dict[str, float]) -> Optional[Tuple[str, float]]:
    if not contribs:
        return None
    name, value = max(contribs.items(), key=lambda kv: kv[1])
    return name, value


def _max_corrosion_rate(timeline: List[SimulationState]) -> Tuple[Optional[float], Optional[str], float]:
    """Return (time_s, component, rate_mm_per_year) of the peak corrosion rate."""
    best_time: Optional[float] = None
    best_comp: Optional[str] = None
    best_rate = -1.0  # m/year
    for state in timeline:
        for name, rate in state.corrosion_rate_m_per_year_by_component.items():
            if rate > best_rate:
                best_rate = rate
                best_comp = name
                best_time = state.current_time_s
    return best_time, best_comp, max(0.0, best_rate) * 1e3  # -> mm/year


def _stability_contribs(state: SimulationState) -> Dict[str, float]:
    stab = state.intermediate_physics_values.get("stability", {}) or {}
    return stab.get("weighted_contributions", {}) or {}


def _has_timeline(result: SimulationResult) -> bool:
    return bool(result.timeline)


# ---------------------------------------------------------------------------
# Corrosion report
# ---------------------------------------------------------------------------

def generate_corrosion_report(result: SimulationResult) -> str:
    """Markdown report explaining the corrosion outcome and its drivers."""
    cs = result.final_corrosion_summary
    by_component: Dict[str, Any] = cs.get("by_component", {})
    lines: List[str] = ["# Corrosion report", ""]

    if not by_component:
        lines.append("_No corrosion data available._")
        return "\n".join(lines)

    # Rankings.
    by_abs = sorted(
        by_component.items(),
        key=lambda kv: kv[1].get("accumulated_corrosion_m", 0.0),
        reverse=True,
    )
    by_pct = sorted(
        by_component.items(),
        key=lambda kv: kv[1].get("thickness_loss_fraction", 0.0),
        reverse=True,
    )

    lines.append("## Most corroded components (absolute metal loss)")
    lines.append("")
    lines.append("| component | metal loss (mm) | thickness lost | final eff. (mm) | min safety factor |")
    lines.append("|---|---:|---:|---:|---:|")
    for name, c in by_abs:
        lines.append(
            f"| {name} | {c.get('accumulated_corrosion_m', 0.0) * 1e3:.3f} | "
            f"{_fmt_pct(c.get('thickness_loss_fraction', 0.0))} | "
            f"{c.get('final_effective_thickness_m', 0.0) * 1e3:.2f} | "
            f"{c.get('min_safety_margin', float('nan')):.2f} |"
        )
    lines.append("")

    worst_pct_name, worst_pct = by_pct[0]
    lines.append(
        f"**Largest percentage loss:** `{worst_pct_name}` lost "
        f"{_fmt_pct(worst_pct.get('thickness_loss_fraction', 0.0))} of its original "
        f"thickness. **Most metal removed:** `{by_abs[0][0]}`."
    )
    lines.append("")

    # When the corrosion rate peaked.
    if _has_timeline(result):
        t, comp, rate_mmyr = _max_corrosion_rate(result.timeline)
        lines.append("## When corrosion was fastest")
        lines.append(
            f"- Peak instantaneous rate **{rate_mmyr:.3f} mm/year** on `{comp}` at "
            f"{_fmt_time(t)}."
        )
        lines.append("")
    else:
        lines.append("## When corrosion was fastest")
        lines.append("- Timeline not saved; per-step rate history unavailable.")
        lines.append("")

    # Dominant environmental factors.
    lines.append("## Dominant environmental drivers")
    dom = cs.get("dominant_environmental_factors", [])
    if dom:
        lines.append("Mean multiplicative factors over the voyage (1.0 = neutral):")
        lines.append("")
        for d in dom[:6]:
            direction = "accelerated" if d["mean_value"] > 1.0 else "slowed"
            lines.append(
                f"- **{d['factor']}** = {d['mean_value']:.3f} ({direction} corrosion)"
            )
        lines.append("")

    # Corrosion allowance.
    lines.append("## Corrosion allowance")
    allowance_warnings = [w for w in result.warnings if "allowance" in w.lower()]
    if allowance_warnings:
        lines.append("Corrosion allowance was **exceeded** for at least one component:")
        for w in allowance_warnings[:8]:
            lines.append(f"- {w}")
    else:
        lines.append("No component exceeded its design corrosion allowance during the voyage.")
    lines.append("")

    # Assumptions that matter most.
    lines.append("## Assumptions that most affect corrosion")
    relevant = [
        a for a in result.assumptions
        if any(k in a.lower() for k in ("coating", "galvanic", "corro", "step", "independ"))
    ]
    for a in (relevant or result.assumptions):
        lines.append(f"- {a}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Stability report
# ---------------------------------------------------------------------------

def generate_stability_report(result: SimulationResult) -> str:
    """Markdown report explaining the stability/capsize outcome and its drivers."""
    ss = result.final_stability_summary
    lines: List[str] = ["# Stability & capsizing report", ""]

    max_risk = ss.get("max_risk_score", 0.0)
    lines.append("## Peak risk")
    lines.append(f"- Maximum stability-risk score: **{max_risk:.3f}** (0-1 scale).")
    lines.append(f"- Occurred at: **{_fmt_time(ss.get('time_of_max_risk_s'))}**.")
    pos = ss.get("position_of_max_risk")
    if pos:
        lines.append(
            f"- Location: lat {pos.get('latitude_deg'):.2f}, "
            f"lon {pos.get('longitude_deg'):.2f}."
        )
    lines.append(f"- Final risk score at end of voyage: {ss.get('final_risk_score', 0.0):.3f}.")
    lines.append("")

    # What drove the peak risk.
    lines.append("## What drove the peak risk")
    contribs = ss.get("max_risk_dominant_contributions", {}) or {}
    if contribs:
        ranked = sorted(contribs.items(), key=lambda kv: kv[1], reverse=True)
        top = ranked[0]
        lines.append(
            f"The largest contributor at peak risk was **{_RISK_LABELS.get(top[0], top[0])}**."
        )
        lines.append("")
        lines.append("| driver | weighted contribution |")
        lines.append("|---|---:|")
        for name, value in ranked:
            if value <= 0.0:
                continue
            lines.append(f"| {_RISK_LABELS.get(name, name)} | {value:.3f} |")
        lines.append("")
    else:
        lines.append("_No per-driver breakdown available._")
        lines.append("")

    # Warning-level conditions.
    lines.append("## Warning-level conditions")
    if _has_timeline(result):
        flagged = sum(1 for s in result.timeline if s.warnings)
        lines.append(
            f"- {flagged} of {len(result.timeline)} timesteps had one or more warnings."
        )
    stab_warnings = [
        w for w in result.warnings
        if any(k in w.lower() for k in ("capsize", "gm", "resonance", "unstable", "heeling"))
    ]
    if stab_warnings:
        lines.append("- Stability-related warning events:")
        for w in stab_warnings[:8]:
            lines.append(f"  - {w}")
        if len(stab_warnings) > 8:
            lines.append(f"  - ... and {len(stab_warnings) - 8} more")
    else:
        lines.append("- No stability-specific warning events were raised.")
    lines.append("")

    # Cumulative capsize probability.
    lines.append("## Cumulative capsize probability")
    lines.append(
        f"- Voyage-integrated estimate: **{result.cumulative_capsize_probability:.4f}**."
    )
    lines.append(
        "  (Compounded per-timestep hazard; the calibration is intentionally "
        "conservative and tunable via `config.stability`.)"
    )
    lines.append("")

    # Limitations most relevant to stability.
    lines.append("## Strongest limitations of this estimate")
    for item in (
        "Roll response is parameterized (no strip theory / RAOs or model-basin data).",
        "Restoring capacity uses a small-angle GM proxy, not a full GZ curve or "
        "IMO criteria.",
        "Wind heeling and green water are simplified; no CFD.",
        "No cargo shift, free-surface, or flooding effects.",
        "GM is held constant (corrosion-driven weight/KG changes ignored).",
    ):
        lines.append(f"- {item}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Overall report
# ---------------------------------------------------------------------------

def _top_stability_timesteps(
    timeline: List[SimulationState], n: int
) -> List[SimulationState]:
    return sorted(timeline, key=lambda s: s.stability_risk_score_0_1, reverse=True)[:n]


def generate_overall_risk_report(result: SimulationResult) -> str:
    """Combined Markdown report: summary, top movers, warnings, recommendations."""
    cs = result.final_corrosion_summary
    ss = result.final_stability_summary
    lines: List[str] = [
        "# Overall risk report",
        "",
        "> ENGINEERING APPROXIMATION -- NOT a certified naval safety assessment.",
        "",
    ]

    # Final risk summary.
    lines.append("## Final risk summary")
    lines.append(
        f"- Cumulative capsize probability: **{result.cumulative_capsize_probability:.4f}**"
    )
    lines.append(f"- Maximum stability-risk score: **{ss.get('max_risk_score', 0.0):.3f}** "
                 f"at {_fmt_time(ss.get('time_of_max_risk_s'))}")
    lines.append(
        f"- Total metal lost (all components): "
        f"{cs.get('total_accumulated_corrosion_m', 0.0) * 1e3:.2f} mm; "
        f"most corroded: `{cs.get('most_corroded_component')}`"
    )
    lines.append("")

    # Top 5 corrosion-critical components.
    lines.append("## Top 5 corrosion-critical components")
    by_component: Dict[str, Any] = cs.get("by_component", {})
    ranked_components = sorted(
        by_component.items(),
        key=lambda kv: kv[1].get("thickness_loss_fraction", 0.0),
        reverse=True,
    )[:5]
    if ranked_components:
        lines.append("| # | component | thickness lost | min safety factor |")
        lines.append("|---:|---|---:|---:|")
        for i, (name, c) in enumerate(ranked_components, 1):
            lines.append(
                f"| {i} | {name} | {_fmt_pct(c.get('thickness_loss_fraction', 0.0))} | "
                f"{c.get('min_safety_margin', float('nan')):.2f} |"
            )
    else:
        lines.append("_No component data._")
    lines.append("")

    # Top 5 stability-critical timesteps.
    lines.append("## Top 5 stability-critical timesteps")
    if _has_timeline(result):
        lines.append("| # | time | risk | dominant driver |")
        lines.append("|---:|---|---:|---|")
        for i, state in enumerate(_top_stability_timesteps(result.timeline, 5), 1):
            dom = _dominant_contribution(_stability_contribs(state))
            dom_label = _RISK_LABELS.get(dom[0], dom[0]) if dom else "n/a"
            lines.append(
                f"| {i} | {_fmt_time(state.current_time_s)} | "
                f"{state.stability_risk_score_0_1:.3f} | {dom_label} |"
            )
    else:
        lines.append("_Timeline not saved; per-step ranking unavailable._")
    lines.append("")

    # Major warnings.
    lines.append("## Major warnings")
    if result.warnings:
        for w in result.warnings[:12]:
            lines.append(f"- {w}")
        if len(result.warnings) > 12:
            lines.append(f"- ... and {len(result.warnings) - 12} more")
    else:
        lines.append("- None raised.")
    lines.append("")

    # Recommendations.
    lines.append("## Recommended model improvements")
    for item in RECOMMENDED_IMPROVEMENTS:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Recommended real-world data to improve accuracy")
    for item in RECOMMENDED_DATA:
        lines.append(f"- {item}")
    lines.append("")

    # Limitations.
    lines.append("## Limitations")
    for item in MODEL_LIMITATIONS:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Assumptions used in this run")
    for a in result.assumptions:
        lines.append(f"- {a}")
    lines.append("")

    return "\n".join(lines)


__all__ = [
    "generate_corrosion_report",
    "generate_stability_report",
    "generate_overall_risk_report",
    "MODEL_LIMITATIONS",
    "RECOMMENDED_IMPROVEMENTS",
    "RECOMMENDED_DATA",
]
