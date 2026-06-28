"""Tests for the matplotlib visualization helpers (headless / Agg backend)."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # must precede pyplot import in ship_sim.visualization

import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from ship_sim import visualization as viz  # noqa: E402
from ship_sim.config import SimulationConfig  # noqa: E402
from ship_sim.generation.procedural import (  # noqa: E402
    ProceduralEnvironmentProvider,
    ProceduralWaveProvider,
    ProceduralWeatherProvider,
)
from ship_sim.models import (  # noqa: E402
    Material,
    ProceduralSettings,
    Scenario,
    Ship,
    ShipComponent,
    SimulationSettings,
    Trajectory,
    Waypoint,
)
from ship_sim.simulation.engine import ShipSimulationEngine  # noqa: E402
from ship_sim.simulation.monte_carlo import run_monte_carlo  # noqa: E402
from ship_sim.units import hours_to_seconds  # noqa: E402


def make_ship() -> Ship:
    mat = Material(name="EH36", density_kg_m3=7850.0, yield_strength_pa=355e6,
                   ultimate_strength_pa=490e6, elastic_modulus_pa=210e9,
                   base_corrosion_rate_m_per_year=0.0002, galvanic_potential_v=-0.6)
    return Ship(name="Viz", length_m=72.0, beam_m=12.5, draft_m=4.2,
                displacement_mass_kg=2.4e6, center_of_gravity_height_m=5.1,
                metacentric_height_m=0.85, projected_lateral_area_m2=540.0,
                roll_natural_period_s=10.0,
                components=[
                    ShipComponent(name="bottom", material=mat, thickness_m=0.014,
                                  area_m2=500.0, original_thickness_m=0.014),
                    ShipComponent(name="deck", material=mat, thickness_m=0.010,
                                  area_m2=300.0, original_thickness_m=0.010),
                ])


def make_trajectory() -> Trajectory:
    return Trajectory(waypoints=[
        Waypoint(latitude_deg=20.0, longitude_deg=-30.0, time_s=0.0, target_speed_m_s=6.0),
        Waypoint(latitude_deg=30.0, longitude_deg=-35.0, time_s=hours_to_seconds(18.0),
                 target_speed_m_s=6.0),
    ])


@pytest.fixture(scope="module")
def result():
    engine = ShipSimulationEngine(
        make_ship(), make_trajectory(),
        ProceduralEnvironmentProvider(3), ProceduralWeatherProvider(3),
        ProceduralWaveProvider(3), SimulationConfig.default(), dt_s=3600.0,
    )
    return engine.run()


@pytest.fixture(scope="module")
def mc_result():
    sc = Scenario(name="viz_mc", simulation=SimulationSettings(dt_hours=6.0),
                  ship=make_ship(), trajectory=make_trajectory(),
                  procedural=ProceduralSettings(seed=3))
    return run_monte_carlo(sc, n_runs=15, random_seed=1)


def teardown_function(_):
    plt.close("all")


def test_corrosion_plot_returns_figure_and_labels(result):
    fig = viz.plot_corrosion_over_time(result)
    assert isinstance(fig, Figure)
    ax = fig.axes[0]
    assert "mm" in ax.get_ylabel()
    assert "day" in ax.get_xlabel().lower()
    assert ax.get_legend() is not None


def test_corrosion_plot_single_component(result):
    fig = viz.plot_corrosion_over_time(result, component_name="deck")
    ax = fig.axes[0]
    labels = [t.get_text() for t in ax.get_legend().get_texts()]
    assert labels == ["deck"]


def test_corrosion_plot_unknown_component_raises(result):
    with pytest.raises(KeyError):
        viz.plot_corrosion_over_time(result, component_name="nope")


def test_stability_plot(result):
    fig = viz.plot_stability_risk_over_time(result)
    assert isinstance(fig, Figure)
    assert "0-1" in fig.axes[0].get_ylabel()
    # twin axis present
    assert len(fig.axes) >= 2


def test_environment_plot_units(result):
    fig = viz.plot_environment_over_time(result)
    ylabels = " ".join(ax.get_ylabel() for ax in fig.axes)
    assert "ppt" in ylabels and "mg/L" in ylabels and "pH" in ylabels


def test_wave_weather_plot_units(result):
    fig = viz.plot_wave_weather_over_time(result)
    ylabels = " ".join(ax.get_ylabel() for ax in fig.axes)
    assert "m/s" in ylabels and "(m)" in ylabels and "(s)" in ylabels


def test_monte_carlo_plot(mc_result):
    fig = viz.plot_monte_carlo_distributions(mc_result)
    assert isinstance(fig, Figure)
    xlabels = " ".join(ax.get_xlabel() for ax in fig.axes)
    assert "risk" in xlabels and "capsize" in xlabels


def test_saves_to_file(result, tmp_path):
    out = tmp_path / "corrosion.png"
    fig = viz.plot_corrosion_over_time(result, output_path=str(out))
    assert out.exists() and out.stat().st_size > 0
    assert isinstance(fig, Figure)


def test_missing_timeline_raises(result):
    stripped = result.model_copy(update={"timeline": []})
    with pytest.raises(ValueError):
        viz.plot_stability_risk_over_time(stripped)


def test_monte_carlo_plot_handles_degenerate_distribution():
    # All-identical samples (e.g. capsize probability pinned at 1.0) must not
    # crash the histogram (zero-width bin range).
    from ship_sim.simulation.monte_carlo import MonteCarloResult

    n = 10
    mc = MonteCarloResult(
        n_runs=n, random_seed=0,
        samples={
            "max_stability_risk": [0.9] * n,
            "cumulative_capsize_probability": [1.0] * n,
            "time_of_max_risk_s": [3600.0] * n,
            "n_warnings": [5.0] * n,
        },
        corrosion_by_component={"bottom": [0.0] * n},
        input_samples={"gm_mult": [1.0] * n},
    )
    fig = viz.plot_monte_carlo_distributions(mc)
    assert isinstance(fig, Figure)
