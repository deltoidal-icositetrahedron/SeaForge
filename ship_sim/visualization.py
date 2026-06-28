"""Simple matplotlib visualizations of simulation and Monte Carlo results.

Each function builds exactly one Matplotlib figure with unit-labeled axes and
legends where useful, optionally saves it to ``output_path``, and returns the
:class:`matplotlib.figure.Figure` so callers can further customize or display it.

No seaborn is used. Matplotlib is an optional dependency (``pip install
ship_sim[viz]``); importing this module requires it.

For headless use, select a non-interactive backend *before* importing this
module, e.g.::

    import matplotlib; matplotlib.use("Agg")
    from ship_sim import visualization
"""

from __future__ import annotations

from typing import List, Optional

import matplotlib.pyplot as plt

from .models.results import SimulationResult
from .simulation.monte_carlo import MonteCarloResult

_SECONDS_PER_DAY = 86400.0


def _elapsed_days(result: SimulationResult) -> List[float]:
    """Elapsed time (days) from the start of the voyage, per timestep."""
    timeline = result.timeline
    t0 = timeline[0].current_time_s
    return [(s.current_time_s - t0) / _SECONDS_PER_DAY for s in timeline]


def _require_timeline(result: SimulationResult) -> None:
    if not result.timeline:
        raise ValueError(
            "result has no timeline to plot (was it saved with --no-timeline?)."
        )


def _finish(fig, output_path: Optional[str]):
    fig.tight_layout()
    if output_path is not None:
        fig.savefig(output_path, dpi=120, bbox_inches="tight")
    return fig


# ---------------------------------------------------------------------------
# Corrosion
# ---------------------------------------------------------------------------

def plot_corrosion_over_time(
    result: SimulationResult,
    component_name: Optional[str] = None,
    output_path: Optional[str] = None,
):
    """Plot accumulated corrosion (metal loss, mm) over time per component.

    If ``component_name`` is given, only that component is plotted; otherwise all
    components are overlaid.
    """
    _require_timeline(result)
    days = _elapsed_days(result)
    available = sorted(result.timeline[0].accumulated_corrosion_m_by_component)

    if component_name is not None:
        if component_name not in available:
            raise KeyError(
                f"component {component_name!r} not found; available: {available}."
            )
        names = [component_name]
    else:
        names = available

    fig, ax = plt.subplots(figsize=(9, 5))
    for name in names:
        loss_mm = [
            s.accumulated_corrosion_m_by_component.get(name, 0.0) * 1e3
            for s in result.timeline
        ]
        ax.plot(days, loss_mm, label=name)

    ax.set_xlabel("time (days)")
    ax.set_ylabel("accumulated corrosion / metal loss (mm)")
    ax.set_title("Corrosion over time")
    ax.grid(True, alpha=0.3)
    ax.legend(title="component", fontsize=8)
    return _finish(fig, output_path)


def plot_effective_thickness_over_time(
    result: SimulationResult,
    component_name: Optional[str] = None,
    output_path: Optional[str] = None,
):
    """Plot remaining effective thickness (mm) over time per component."""
    _require_timeline(result)
    days = _elapsed_days(result)
    available = sorted(result.timeline[0].effective_thickness_m_by_component)

    if component_name is not None:
        if component_name not in available:
            raise KeyError(
                f"component {component_name!r} not found; available: {available}."
            )
        names = [component_name]
    else:
        names = available

    fig, ax = plt.subplots(figsize=(9, 5))
    for name in names:
        thickness_mm = [
            s.effective_thickness_m_by_component.get(name, 0.0) * 1e3
            for s in result.timeline
        ]
        ax.plot(days, thickness_mm, label=name)

    ax.set_xlabel("time (days)")
    ax.set_ylabel("effective thickness remaining (mm)")
    ax.set_title("Component thickness remaining over time")
    ax.grid(True, alpha=0.3)
    ax.legend(title="component", fontsize=8)
    return _finish(fig, output_path)


# ---------------------------------------------------------------------------
# Stability risk
# ---------------------------------------------------------------------------

def plot_stability_risk_over_time(
    result: SimulationResult, output_path: Optional[str] = None
):
    """Plot the stability-risk score and per-timestep capsize probability."""
    _require_timeline(result)
    days = _elapsed_days(result)
    risk = [s.stability_risk_score_0_1 for s in result.timeline]
    capsize = [s.capsize_probability_timestep for s in result.timeline]

    fig, ax = plt.subplots(figsize=(9, 5))
    (l1,) = ax.plot(days, risk, color="tab:red", label="stability risk score")
    ax.set_xlabel("time (days)")
    ax.set_ylabel("stability risk score (0-1)")
    ax.set_ylim(0.0, 1.0)
    ax.grid(True, alpha=0.3)

    ax2 = ax.twinx()
    (l2,) = ax2.plot(
        days, capsize, color="tab:blue", alpha=0.6,
        label="capsize probability / timestep",
    )
    ax2.set_ylabel("capsize probability per timestep (0-1)")
    ax2.set_ylim(0.0, 1.0)

    ax.set_title("Stability risk over time")
    ax.legend(handles=[l1, l2], loc="upper left", fontsize=8)
    return _finish(fig, output_path)


# ---------------------------------------------------------------------------
# Seawater environment
# ---------------------------------------------------------------------------

def plot_environment_over_time(
    result: SimulationResult, output_path: Optional[str] = None
):
    """Plot seawater salinity, temperature, pH, and dissolved oxygen over time."""
    _require_timeline(result)
    days = _elapsed_days(result)
    env = [s.environment for s in result.timeline]

    series = [
        ([e.salinity_ppt for e in env], "salinity (ppt)", "tab:purple"),
        ([e.water_temperature_c for e in env], "water temperature (°C)", "tab:red"),
        ([e.pH for e in env], "pH", "tab:green"),
        ([e.dissolved_oxygen_mg_l for e in env], "dissolved O₂ (mg/L)", "tab:blue"),
    ]

    fig, axes = plt.subplots(len(series), 1, sharex=True, figsize=(9, 9))
    for ax, (values, label, color) in zip(axes, series):
        ax.plot(days, values, color=color)
        ax.set_ylabel(label, fontsize=9)
        ax.grid(True, alpha=0.3)
    axes[-1].set_xlabel("time (days)")
    fig.suptitle("Seawater environment over time")
    return _finish(fig, output_path)


# ---------------------------------------------------------------------------
# Waves & weather
# ---------------------------------------------------------------------------

def plot_wave_weather_over_time(
    result: SimulationResult, output_path: Optional[str] = None
):
    """Plot wind speed, storm intensity, significant wave height, and peak period."""
    _require_timeline(result)
    days = _elapsed_days(result)
    weather = [s.weather for s in result.timeline]
    waves = [s.waves for s in result.timeline]

    series = [
        ([w.wind_speed_m_s for w in weather], "wind speed (m/s)", "tab:orange"),
        ([w.storm_intensity_0_1 for w in weather], "storm intensity (0-1)", "tab:red"),
        ([w.significant_wave_height_m for w in waves], "sig. wave height Hs (m)", "tab:blue"),
        ([w.peak_period_s for w in waves], "peak period Tp (s)", "tab:cyan"),
    ]

    fig, axes = plt.subplots(len(series), 1, sharex=True, figsize=(9, 9))
    for ax, (values, label, color) in zip(axes, series):
        ax.plot(days, values, color=color)
        ax.set_ylabel(label, fontsize=9)
        ax.grid(True, alpha=0.3)
    axes[1].set_ylim(0.0, 1.0)  # storm intensity is bounded
    axes[-1].set_xlabel("time (days)")
    fig.suptitle("Waves & weather over time")
    return _finish(fig, output_path)


# ---------------------------------------------------------------------------
# Monte Carlo distributions
# ---------------------------------------------------------------------------

def _hist_with_median(ax, values, xlabel, color):
    lo, hi = min(values), max(values)
    # Treat a (near-)zero spread as degenerate -- a tiny float span (e.g. capsize
    # probability all ~1.0) cannot form 20 finite-width bins.
    if (hi - lo) > 1e-9 * max(1.0, abs(hi)):
        ax.hist(values, bins=20, color=color, alpha=0.75, edgecolor="white")
    else:
        ax.hist(values, bins=1, range=(hi - 0.5, hi + 0.5),
                color=color, alpha=0.75, edgecolor="white")
    med = float(sorted(values)[len(values) // 2]) if values else 0.0
    ax.axvline(med, color="black", linestyle="--", linewidth=1,
               label=f"median {med:.3g}")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("count")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)


def plot_monte_carlo_distributions(
    mc_result: MonteCarloResult, output_path: Optional[str] = None
):
    """Plot histograms of the key Monte Carlo output distributions."""
    if mc_result.n_runs < 1 or not mc_result.samples:
        raise ValueError("mc_result has no samples to plot.")

    samples = mc_result.samples
    # Total metal loss (mm) per run, summed over components.
    n = mc_result.n_runs
    total_corrosion_mm = [
        sum(mc_result.corrosion_by_component[name][i]
            for name in mc_result.corrosion_by_component) * 1e3
        for i in range(n)
    ]

    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    _hist_with_median(axes[0, 0], samples["max_stability_risk"],
                      "max stability risk score (0-1)", "tab:red")
    _hist_with_median(axes[0, 1], samples["cumulative_capsize_probability"],
                      "cumulative capsize probability (0-1)", "tab:blue")
    _hist_with_median(axes[1, 0], samples["n_warnings"],
                      "number of warnings", "tab:orange")
    _hist_with_median(axes[1, 1], total_corrosion_mm,
                      "total metal loss (mm)", "tab:green")

    fig.suptitle(f"Monte Carlo distributions (n = {mc_result.n_runs})")
    return _finish(fig, output_path)


__all__ = [
    "plot_corrosion_over_time",
    "plot_effective_thickness_over_time",
    "plot_stability_risk_over_time",
    "plot_environment_over_time",
    "plot_wave_weather_over_time",
    "plot_monte_carlo_distributions",
]
