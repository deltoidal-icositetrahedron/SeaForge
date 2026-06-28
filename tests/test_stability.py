"""Tests for the stability / seakeeping / capsizing model."""

from __future__ import annotations


import pytest

from ship_sim.config import SimulationConfig
from ship_sim.models import (
    Material,
    Ship,
    ShipComponent,
    WaveCondition,
    WeatherCondition,
)
from ship_sim.simulation.seakeeping import estimate_wave_encounter
from ship_sim.simulation.stability import (
    estimate_stability_risk,
    estimate_structural_weakening,
    estimate_wind_heeling_moment,
)

CFG = SimulationConfig.default()


# --- builders --------------------------------------------------------------

def make_material() -> Material:
    return Material(
        name="EH36",
        density_kg_m3=7850.0,
        yield_strength_pa=355e6,
        ultimate_strength_pa=490e6,
        elastic_modulus_pa=210e9,
        base_corrosion_rate_m_per_year=0.0001,
        galvanic_potential_v=-0.6,
    )


def make_ship(gm: float = 0.85, **overrides) -> Ship:
    base = dict(
        name="PV Test",
        length_m=72.0,
        beam_m=12.5,
        draft_m=4.2,
        displacement_mass_kg=2.4e6,
        center_of_gravity_height_m=5.1,
        metacentric_height_m=gm,
        projected_lateral_area_m2=540.0,
        roll_natural_period_s=10.0,
        components=[
            ShipComponent(
                name="bottom_plating",
                material=make_material(),
                thickness_m=0.014,
                area_m2=500.0,
                structural_importance=1.0,
                original_thickness_m=0.014,
            ),
            ShipComponent(
                name="deck",
                material=make_material(),
                thickness_m=0.010,
                area_m2=300.0,
                structural_importance=0.6,
                original_thickness_m=0.010,
            ),
        ],
    )
    base.update(overrides)
    return Ship(**base)


def make_weather(wind=10.0, storm=0.2, **overrides) -> WeatherCondition:
    base = dict(
        wind_speed_m_s=wind,
        wind_direction_deg=90.0,
        air_temperature_c=15.0,
        relative_humidity_0_1=0.7,
        storm_intensity_0_1=storm,
    )
    base.update(overrides)
    return WeatherCondition(**base)


def make_wave(hs=2.0, tp=8.0, **overrides) -> WaveCondition:
    base = dict(
        significant_wave_height_m=hs,
        peak_period_s=tp,
        mean_wave_direction_deg=0.0,
        current_speed_m_s=0.0,
    )
    base.update(overrides)
    return WaveCondition(**base)


def risk(ship=None, eff=None, weather=None, wave=None, speed=5.0, dt=3600.0,
         heading=None, cfg=CFG):
    return estimate_stability_risk(
        ship=ship or make_ship(),
        effective_thickness_by_component=eff or {},
        weather=weather or make_weather(),
        wave=wave or make_wave(),
        speed_m_s=speed,
        dt_s=dt,
        config=cfg,
        heading_degrees=heading,
    )


# --- seakeeping ------------------------------------------------------------

def test_encounter_head_seas_shorter_than_following():
    wave = make_wave(tp=8.0, hs=2.0)
    # mean_wave_direction = 0 (waves travel north).
    head = estimate_wave_encounter(6.0, 180.0, wave)  # ship north-> waves from ahead
    following = estimate_wave_encounter(6.0, 0.0, wave)  # ship north with the waves
    assert head.relative_heading_deg == pytest.approx(180.0)
    assert following.relative_heading_deg == pytest.approx(0.0)
    # Head seas => higher encounter frequency => shorter encounter period.
    assert head.encounter_period_s < following.encounter_period_s


def test_steepness_increases_with_height_and_decreases_with_period():
    steep = estimate_wave_encounter(0.0, 90.0, make_wave(hs=4.0, tp=6.0)).wave_steepness
    mild = estimate_wave_encounter(0.0, 90.0, make_wave(hs=1.0, tp=12.0)).wave_steepness
    assert steep > mild


def test_default_heading_is_beam_seas():
    enc = estimate_wave_encounter(6.0, None, make_wave())
    assert enc.relative_heading_deg == pytest.approx(90.0)


# --- wind heeling ----------------------------------------------------------

def test_wind_heeling_increases_with_wind_speed():
    ship = make_ship()
    low = estimate_wind_heeling_moment(ship, make_weather(wind=5.0), None, CFG)
    high = estimate_wind_heeling_moment(ship, make_weather(wind=20.0), None, CFG)
    assert high > low > 0.0
    # Quadratic in wind speed (4x speed -> ~16x moment, beam wind both).
    assert high == pytest.approx(low * 16.0, rel=1e-6)


def test_wind_heeling_uses_fallback_area_without_lateral_area():
    ship = make_ship(projected_lateral_area_m2=None)
    moment = estimate_wind_heeling_moment(ship, make_weather(wind=15.0), None, CFG)
    assert moment > 0.0


# --- structural weakening --------------------------------------------------

def test_structural_weakening_zero_when_intact():
    ship = make_ship()
    est = estimate_structural_weakening(ship, {}, CFG)
    assert est.weakening_factor_0_1 == pytest.approx(0.0)
    assert est.most_critical_components == []


def test_structural_weakening_increases_with_thinning():
    ship = make_ship()
    mild = estimate_structural_weakening(
        ship, {"bottom_plating": 0.012}, CFG
    ).weakening_factor_0_1
    severe = estimate_structural_weakening(
        ship, {"bottom_plating": 0.006}, CFG
    ).weakening_factor_0_1
    assert severe > mild > 0.0


# --- stability risk: required behaviors ------------------------------------

def test_larger_wave_height_increases_risk():
    assert risk(wave=make_wave(hs=6.0)).risk_score_0_1 > risk(
        wave=make_wave(hs=1.0)
    ).risk_score_0_1


def test_lower_gm_increases_risk():
    assert risk(ship=make_ship(gm=0.3)).risk_score_0_1 > risk(
        ship=make_ship(gm=1.5)
    ).risk_score_0_1


def test_negative_gm_high_risk_or_warning():
    est = risk(ship=make_ship(gm=-0.2))
    assert est.risk_score_0_1 > 0.5 or any("unstable" in w for w in est.warnings)
    # gm_factor should be near the top of its range.
    assert est.gm_factor > 0.8


def test_stronger_wind_increases_risk():
    calm = risk(weather=make_weather(wind=4.0, storm=0.0))
    blow = risk(weather=make_weather(wind=28.0, storm=0.0))
    assert blow.risk_score_0_1 > calm.risk_score_0_1
    assert blow.wind_heeling_moment_nm > calm.wind_heeling_moment_nm


def test_more_structural_weakening_increases_risk():
    intact = risk(eff={})
    weak = risk(eff={"bottom_plating": 0.004, "deck": 0.003})
    assert weak.risk_score_0_1 > intact.risk_score_0_1
    assert weak.structural_weakening_factor > intact.structural_weakening_factor


def test_resonance_increases_resonance_factor_near_roll_period():
    # Beam seas => encounter period equals wave period; roll period = 10 s.
    ship = make_ship(gm=0.85)  # roll_natural_period_s=10.0 set explicitly
    near = risk(ship=ship, wave=make_wave(hs=2.0, tp=10.0), heading=90.0, speed=0.0)
    far = risk(ship=ship, wave=make_wave(hs=2.0, tp=5.0), heading=90.0, speed=0.0)
    assert near.resonance_risk_factor > far.resonance_risk_factor


def test_resonance_increases_risk_score_isolated():
    # Isolate resonance: zero every other risk weight, keep resonance.
    cfg = SimulationConfig.default()
    s = cfg.stability
    for field_name in (
        "risk_weight_gm", "risk_weight_wind", "risk_weight_wave",
        "risk_weight_speed", "risk_weight_structural", "risk_weight_storm",
        "risk_weight_cg", "risk_weight_misalignment",
    ):
        setattr(s, field_name, 0.0)
    ship = make_ship(gm=0.85)
    near = risk(ship=ship, wave=make_wave(hs=2.0, tp=10.0), heading=90.0,
                speed=0.0, cfg=cfg)
    far = risk(ship=ship, wave=make_wave(hs=2.0, tp=5.0), heading=90.0,
               speed=0.0, cfg=cfg)
    assert near.risk_score_0_1 > far.risk_score_0_1


# --- bounds ---------------------------------------------------------------

def test_risk_and_probability_always_in_unit_interval():
    cases = [
        dict(ship=make_ship(gm=-1.0), weather=make_weather(wind=40.0, storm=1.0),
             wave=make_wave(hs=12.0, tp=6.0), speed=12.0, dt=7200.0,
             eff={"bottom_plating": 0.001, "deck": 0.001}),
        dict(ship=make_ship(gm=3.0), weather=make_weather(wind=0.0, storm=0.0),
             wave=make_wave(hs=0.0, tp=12.0), speed=0.0, dt=0.0),
        dict(ship=make_ship(gm=0.85), weather=make_weather(), wave=make_wave(),
             speed=6.0, dt=3600.0, heading=45.0),
    ]
    for kw in cases:
        est = risk(**kw)
        assert 0.0 <= est.risk_score_0_1 <= 1.0
        assert 0.0 <= est.capsize_probability_timestep <= 1.0


def test_capsize_probability_scales_with_dt():
    ship = make_ship(gm=0.4)
    weather = make_weather(wind=30.0, storm=0.8)
    wave = make_wave(hs=7.0, tp=7.0)
    short = risk(ship=ship, weather=weather, wave=wave, dt=600.0).capsize_probability_timestep
    long = risk(ship=ship, weather=weather, wave=wave, dt=3600.0).capsize_probability_timestep
    zero = risk(ship=ship, weather=weather, wave=wave, dt=0.0).capsize_probability_timestep
    assert zero == 0.0
    assert long > short > 0.0
