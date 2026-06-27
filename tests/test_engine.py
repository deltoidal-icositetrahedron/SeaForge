"""End-to-end tests for ShipSimulationEngine."""

from __future__ import annotations

import pytest

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
from ship_sim.simulation.engine import ShipSimulationEngine
from ship_sim.units import hours_to_seconds


def make_material() -> Material:
    return Material(
        name="EH36",
        density_kg_m3=7850.0,
        yield_strength_pa=355e6,
        ultimate_strength_pa=490e6,
        elastic_modulus_pa=210e9,
        base_corrosion_rate_m_per_year=0.0002,
        galvanic_potential_v=-0.6,
        coating_breakdown_factor=1.5,
    )


def make_ship(gm: float = 0.85, thin: bool = False) -> Ship:
    bottom = ShipComponent(
        name="bottom_plating",
        material=make_material(),
        thickness_m=0.004 if thin else 0.014,
        area_m2=500.0,
        original_thickness_m=0.014,
        corrosion_allowance_m=0.003,
        vertical_position_m=0.3,
    )
    deck = ShipComponent(
        name="deck",
        material=make_material(),
        thickness_m=0.003 if thin else 0.010,
        area_m2=300.0,
        structural_importance=0.6,
        original_thickness_m=0.010,
        corrosion_allowance_m=0.002,
        vertical_position_m=8.0,
    )
    return Ship(
        name="PV Test",
        length_m=72.0,
        beam_m=12.5,
        draft_m=4.2,
        displacement_mass_kg=2.4e6,
        center_of_gravity_height_m=5.1,
        metacentric_height_m=gm,
        projected_lateral_area_m2=540.0,
        roll_natural_period_s=10.0,
        components=[bottom, deck],
    )


def make_trajectory(hours: float = 4.0) -> Trajectory:
    return Trajectory(
        waypoints=[
            Waypoint(latitude_deg=36.0, longitude_deg=-5.0, time_s=0.0,
                     target_speed_m_s=6.0, heading_deg=300.0),
            Waypoint(latitude_deg=38.0, longitude_deg=-8.0,
                     time_s=hours_to_seconds(hours), target_speed_m_s=6.0,
                     heading_deg=315.0),
        ]
    )


def procedural_providers(seed=7):
    return (
        ProceduralEnvironmentProvider(seed),
        ProceduralWeatherProvider(seed),
        ProceduralWaveProvider(seed),
    )


def constant_providers(env, weather, wave):
    return (
        SegmentedEnvironmentProvider([Segment(env)]),
        SegmentedWeatherProvider([Segment(weather)]),
        SegmentedWaveProvider([Segment(wave)]),
    )


CFG = SimulationConfig.default()


# --- basic end-to-end ------------------------------------------------------

def test_engine_runs_end_to_end():
    env_p, wx_p, wave_p = procedural_providers()
    engine = ShipSimulationEngine(
        make_ship(), make_trajectory(4.0), env_p, wx_p, wave_p, CFG, dt_s=3600.0
    )
    result = engine.run()
    assert len(result.timeline) == 4
    assert result.final_corrosion_summary["most_corroded_component"] in (
        "bottom_plating", "deck",
    )
    assert "max_risk_score" in result.final_stability_summary
    assert result.assumptions  # non-empty assumptions list
    # Every state has all components recorded.
    for state in result.timeline:
        assert set(state.effective_thickness_m_by_component) == {"bottom_plating", "deck"}


def test_timeline_length_matches_step_count():
    traj = make_trajectory(5.5)  # non-integer multiple of dt
    dt = 3600.0
    env_p, wx_p, wave_p = procedural_providers()
    engine = ShipSimulationEngine(make_ship(), traj, env_p, wx_p, wave_p, CFG, dt_s=dt)
    result = engine.run()
    assert len(result.timeline) == ShipSimulationEngine.n_steps(traj, dt) == 6


def test_cumulative_capsize_probability_in_unit_interval():
    # Severe conditions to push probability up; must still be bounded.
    env = RegionEnvironment(salinity_ppt=37.0, water_temperature_c=28.0, pH=7.7,
                            dissolved_oxygen_mg_l=9.0, pollution_factor_0_1=0.6)
    weather = WeatherCondition(wind_speed_m_s=32.0, wind_direction_deg=90.0,
                               air_temperature_c=12.0, relative_humidity_0_1=0.95,
                               storm_intensity_0_1=0.9)
    wave = WaveCondition(significant_wave_height_m=9.0, peak_period_s=10.0,
                         mean_wave_direction_deg=0.0, current_speed_m_s=1.0)
    env_p, wx_p, wave_p = constant_providers(env, weather, wave)
    engine = ShipSimulationEngine(
        make_ship(gm=-0.3, thin=True), make_trajectory(6.0),
        env_p, wx_p, wave_p, CFG, dt_s=1800.0,
    )
    result = engine.run()
    assert 0.0 <= result.cumulative_capsize_probability <= 1.0


def test_component_thickness_never_increases():
    env_p, wx_p, wave_p = procedural_providers()
    # A long voyage so corrosion is measurable.
    engine = ShipSimulationEngine(
        make_ship(), make_trajectory(24.0 * 60),  # 60 days
        env_p, wx_p, wave_p, CFG, dt_s=hours_to_seconds(12),
    )
    result = engine.run()
    for name in ("bottom_plating", "deck"):
        thicknesses = [
            s.effective_thickness_m_by_component[name] for s in result.timeline
        ]
        for earlier, later in zip(thicknesses, thicknesses[1:]):
            assert later <= earlier + 1e-15
        # And final is at or below original.
        original = next(c.original_thickness_m for c in engine.ship.components
                        if c.name == name)
        assert thicknesses[-1] <= original + 1e-15


def test_warnings_for_severe_scenario():
    env = RegionEnvironment(salinity_ppt=37.0, water_temperature_c=29.0, pH=7.6,
                            dissolved_oxygen_mg_l=10.0, pollution_factor_0_1=0.8)
    weather = WeatherCondition(wind_speed_m_s=35.0, wind_direction_deg=90.0,
                               air_temperature_c=10.0, relative_humidity_0_1=0.98,
                               storm_intensity_0_1=1.0)
    wave = WaveCondition(significant_wave_height_m=11.0, peak_period_s=10.0,
                         mean_wave_direction_deg=0.0, current_speed_m_s=1.5)
    env_p, wx_p, wave_p = constant_providers(env, weather, wave)
    engine = ShipSimulationEngine(
        make_ship(gm=-0.4, thin=True), make_trajectory(6.0),
        env_p, wx_p, wave_p, CFG, dt_s=1800.0,
    )
    result = engine.run()
    assert result.warnings  # something was flagged
    joined = " ".join(result.warnings).lower()
    assert "unstable" in joined  # negative GM
    assert "allowance" in joined or "minimum acceptable" in joined  # structural


# --- input validation ------------------------------------------------------

def test_rejects_nonpositive_dt():
    env_p, wx_p, wave_p = procedural_providers()
    with pytest.raises(ValueError):
        ShipSimulationEngine(make_ship(), make_trajectory(), env_p, wx_p, wave_p,
                             CFG, dt_s=0.0)


def test_rejects_unknown_backend():
    env_p, wx_p, wave_p = procedural_providers()
    with pytest.raises(NotImplementedError):
        ShipSimulationEngine(make_ship(), make_trajectory(), env_p, wx_p, wave_p,
                             CFG, dt_s=3600.0, backend="rust")
