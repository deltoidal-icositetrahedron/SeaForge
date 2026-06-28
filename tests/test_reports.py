"""Tests for the Markdown report generators."""

from __future__ import annotations

from ship_sim.config import SimulationConfig
from ship_sim.generation.procedural import (
    ProceduralEnvironmentProvider,
    ProceduralWaveProvider,
    ProceduralWeatherProvider,
    Segment,
    SegmentedEnvironmentProvider,
    SegmentedWaveProvider,
    SegmentedWeatherProvider,
)
from ship_sim.models import (
    Material,
    RegionEnvironment,
    Ship,
    ShipComponent,
    Trajectory,
    WaveCondition,
    Waypoint,
    WeatherCondition,
)
from ship_sim.reporting.reports import (
    generate_corrosion_report,
    generate_overall_risk_report,
    generate_stability_report,
)
from ship_sim.simulation.engine import ShipSimulationEngine
from ship_sim.units import hours_to_seconds

CFG = SimulationConfig.default()


def make_ship(gm=0.85, thin=False) -> Ship:
    mat = Material(
        name="EH36", density_kg_m3=7850.0, yield_strength_pa=355e6,
        ultimate_strength_pa=490e6, elastic_modulus_pa=210e9,
        base_corrosion_rate_m_per_year=0.0002, galvanic_potential_v=-0.6,
        coating_breakdown_factor=1.5,
    )
    return Ship(
        name="PV Test", length_m=72.0, beam_m=12.5, draft_m=4.2,
        displacement_mass_kg=2.4e6, center_of_gravity_height_m=5.1,
        metacentric_height_m=gm, projected_lateral_area_m2=540.0,
        roll_natural_period_s=10.0,
        components=[
            ShipComponent(name="bottom_plating", material=mat,
                          thickness_m=0.004 if thin else 0.014, area_m2=500.0,
                          original_thickness_m=0.014, corrosion_allowance_m=0.003),
            ShipComponent(name="deck", material=mat,
                          thickness_m=0.003 if thin else 0.010, area_m2=300.0,
                          structural_importance=0.6, original_thickness_m=0.010,
                          corrosion_allowance_m=0.002),
        ],
    )


def make_trajectory(hours=12.0) -> Trajectory:
    return Trajectory(
        waypoints=[
            Waypoint(latitude_deg=36.0, longitude_deg=-5.0, time_s=0.0,
                     target_speed_m_s=6.0, heading_deg=300.0),
            Waypoint(latitude_deg=40.0, longitude_deg=-9.0, time_s=hours_to_seconds(hours),
                     target_speed_m_s=6.0, heading_deg=315.0),
        ]
    )


def run_normal():
    engine = ShipSimulationEngine(
        make_ship(), make_trajectory(12.0),
        ProceduralEnvironmentProvider(7), ProceduralWeatherProvider(7),
        ProceduralWaveProvider(7), CFG, dt_s=3600.0,
    )
    return engine.run()


def run_severe():
    env = RegionEnvironment(salinity_ppt=37.0, water_temperature_c=29.0, pH=7.6,
                            dissolved_oxygen_mg_l=10.0, pollution_factor_0_1=0.8)
    weather = WeatherCondition(wind_speed_m_s=35.0, wind_direction_deg=90.0,
                               air_temperature_c=10.0, relative_humidity_0_1=0.98,
                               storm_intensity_0_1=1.0)
    wave = WaveCondition(significant_wave_height_m=11.0, peak_period_s=10.0,
                         mean_wave_direction_deg=0.0, current_speed_m_s=1.5)
    engine = ShipSimulationEngine(
        make_ship(gm=-0.4, thin=True), make_trajectory(8.0),
        SegmentedEnvironmentProvider([Segment(env)]),
        SegmentedWeatherProvider([Segment(weather)]),
        SegmentedWaveProvider([Segment(wave)]),
        CFG, dt_s=1800.0,
    )
    return engine.run()


def test_corrosion_report_structure():
    report = generate_corrosion_report(run_normal())
    assert report.startswith("# Corrosion report")
    for heading in ("Most corroded", "When corrosion was fastest",
                    "Dominant environmental drivers", "Corrosion allowance",
                    "Assumptions"):
        assert heading in report
    assert "bottom_plating" in report


def test_stability_report_structure():
    report = generate_stability_report(run_normal())
    assert report.startswith("# Stability & capsizing report")
    for heading in ("Peak risk", "What drove the peak risk",
                    "Warning-level conditions", "Cumulative capsize probability",
                    "Strongest limitations"):
        assert heading in report


def test_overall_report_structure():
    report = generate_overall_risk_report(run_normal())
    assert report.startswith("# Overall risk report")
    for heading in ("Final risk summary", "Top 5 corrosion-critical components",
                    "Top 5 stability-critical timesteps", "Major warnings",
                    "Recommended model improvements",
                    "Recommended real-world data", "Limitations"):
        assert heading in report
    # Mandated limitations must be present.
    assert "CFD" in report
    assert "finite-element" in report.lower() or "finite element" in report.lower()
    assert "classification-society" in report.lower()


def test_reports_reflect_severe_scenario():
    result = run_severe()
    corr = generate_corrosion_report(result)
    stab = generate_stability_report(result)
    overall = generate_overall_risk_report(result)
    # Allowance exceeded should be reported (pre-thinned components).
    assert "exceeded" in corr.lower()
    # Negative GM => instability warning surfaced in stability/overall reports.
    assert "unstable" in stab.lower() or "unstable" in overall.lower()
    # Capsize probability appears.
    assert f"{result.cumulative_capsize_probability:.4f}" in stab


def test_reports_handle_missing_timeline():
    result = run_normal()
    result = result.model_copy(update={"timeline": []})
    # Should not crash and should note the timeline is unavailable.
    corr = generate_corrosion_report(result)
    overall = generate_overall_risk_report(result)
    assert "unavailable" in corr.lower() or "not saved" in corr.lower()
    assert "unavailable" in overall.lower() or "not saved" in overall.lower()
