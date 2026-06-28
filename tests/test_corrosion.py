"""Tests for the marine-corrosion model in ship_sim.simulation.corrosion.

These check the *physical behavior* of the model (monotonicity, saturation,
limits) rather than exact magnitudes, plus unit-conversion consistency.
"""

from __future__ import annotations


import pytest

from ship_sim.config import SimulationConfig
from ship_sim.models import (
    Material,
    RegionEnvironment,
    ShipComponent,
    WaveCondition,
    WeatherCondition,
)
from ship_sim.simulation.corrosion import (
    estimate_corrosion_rate,
    update_component_corrosion,
)
from ship_sim.units import m_per_s_to_mm_per_year


# --- fixtures / builders ---------------------------------------------------

def make_material(**overrides) -> Material:
    base = dict(
        name="EH36",
        density_kg_m3=7850.0,
        yield_strength_pa=355e6,
        ultimate_strength_pa=490e6,
        elastic_modulus_pa=210e9,
        base_corrosion_rate_m_per_year=0.0001,  # 0.1 mm/year
        corrosion_resistance_factor=1.0,
        galvanic_potential_v=-0.6,
        coating_breakdown_factor=1.0,
    )
    base.update(overrides)
    return Material(**base)


def make_env(**overrides) -> RegionEnvironment:
    base = dict(
        salinity_ppt=35.0,
        water_temperature_c=15.0,
        pH=8.1,
        dissolved_oxygen_mg_l=8.0,
        pollution_factor_0_1=0.0,
    )
    base.update(overrides)
    return RegionEnvironment(**base)


def make_weather(**overrides) -> WeatherCondition:
    base = dict(
        wind_speed_m_s=5.0,
        wind_direction_deg=0.0,
        air_temperature_c=15.0,
        relative_humidity_0_1=0.7,
        storm_intensity_0_1=0.0,
    )
    base.update(overrides)
    return WeatherCondition(**base)


def make_wave(**overrides) -> WaveCondition:
    base = dict(
        significant_wave_height_m=0.0,
        peak_period_s=8.0,
        mean_wave_direction_deg=0.0,
        current_speed_m_s=0.0,
    )
    base.update(overrides)
    return WaveCondition(**base)


CFG = SimulationConfig.default()


def rate(material=None, env=None, weather=None, wave=None, speed=0.0, exposure=1.0):
    """Convenience: instantaneous corrosion rate (m/s) for given conditions."""
    est = estimate_corrosion_rate(
        material=material or make_material(),
        environment=env or make_env(),
        weather=weather or make_weather(),
        wave=wave or make_wave(),
        speed_m_s=speed,
        exposure_fraction=exposure,
        config=CFG,
    )
    return est.corrosion_rate_m_per_s


# --- physics behavior ------------------------------------------------------

def test_reference_condition_recovers_base_rate():
    # At all reference values, no flow, no waves, full exposure, bare metal
    # (coating_breakdown so coating factor applies): only the coating factor
    # differs from 1, so the rate equals base_rate * coating_factor.
    est = estimate_corrosion_rate(
        material=make_material(),
        environment=make_env(),
        weather=make_weather(),
        wave=make_wave(),
        speed_m_s=0.0,
        exposure_fraction=1.0,
        config=CFG,
    )
    assert est.salinity_factor == pytest.approx(1.0)
    assert est.temperature_factor == pytest.approx(1.0)
    assert est.pH_factor == pytest.approx(1.0)
    assert est.oxygen_factor == pytest.approx(1.0)
    assert est.pollution_factor == pytest.approx(1.0)
    assert est.speed_erosion_factor == pytest.approx(1.0)
    assert est.splash_factor == pytest.approx(1.0)


def test_corrosion_increases_with_salinity():
    assert rate(env=make_env(salinity_ppt=40.0)) > rate(env=make_env(salinity_ppt=30.0))


def test_corrosion_increases_with_temperature():
    assert rate(env=make_env(water_temperature_c=28.0)) > rate(
        env=make_env(water_temperature_c=10.0)
    )


def test_acidic_ph_increases_corrosion():
    assert rate(env=make_env(pH=7.2)) > rate(env=make_env(pH=8.3))


def test_oxygen_increases_corrosion_with_saturation():
    low = rate(env=make_env(dissolved_oxygen_mg_l=4.0))
    mid = rate(env=make_env(dissolved_oxygen_mg_l=8.0))
    high = rate(env=make_env(dissolved_oxygen_mg_l=12.0))
    very_high = rate(env=make_env(dissolved_oxygen_mg_l=20.0))
    # Monotonic increasing ...
    assert low < mid < high < very_high
    # ... but saturating: the increment for a big O2 jump near saturation is
    # smaller than the increment for an equal jump near the reference.
    near_ref_increment = mid - low  # +4 mg/L around the reference
    near_sat_increment = very_high - rate(env=make_env(dissolved_oxygen_mg_l=16.0))
    assert near_sat_increment < near_ref_increment


def test_pollution_increases_corrosion():
    assert rate(env=make_env(pollution_factor_0_1=1.0)) > rate(
        env=make_env(pollution_factor_0_1=0.0)
    )


def test_speed_increases_corrosion():
    assert rate(speed=10.0) > rate(speed=0.0)


def test_waves_increase_corrosion_via_splash():
    assert rate(wave=make_wave(significant_wave_height_m=4.0)) > rate(
        wave=make_wave(significant_wave_height_m=0.0)
    )


def test_better_coating_reduces_corrosion():
    better = make_material(coating_breakdown_factor=0.5)  # better coating
    worse = make_material(coating_breakdown_factor=2.0)  # worse coating
    assert rate(material=better) < rate(material=worse)


def test_more_resistant_material_corrodes_less():
    resistant = make_material(corrosion_resistance_factor=4.0)
    assert rate(material=resistant) < rate(material=make_material())


def test_zero_exposure_gives_zero_corrosion():
    est = estimate_corrosion_rate(
        material=make_material(),
        environment=make_env(),
        weather=make_weather(),
        wave=make_wave(),
        speed_m_s=10.0,
        exposure_fraction=0.0,
        config=CFG,
    )
    assert est.corrosion_rate_m_per_s == 0.0
    assert est.total_multiplier == 0.0


def test_unit_conversion_consistency():
    est = estimate_corrosion_rate(
        material=make_material(),
        environment=make_env(water_temperature_c=25.0),
        weather=make_weather(),
        wave=make_wave(),
        speed_m_s=5.0,
        exposure_fraction=1.0,
        config=CFG,
    )
    assert est.corrosion_rate_mm_per_year == pytest.approx(
        m_per_s_to_mm_per_year(est.corrosion_rate_m_per_s)
    )
    # total_multiplier definition is exact w.r.t. the base rate.
    base_rate_m_s = make_material().base_corrosion_rate_m_per_year / (
        365.25 * 24 * 3600.0
    )
    assert est.corrosion_rate_m_per_s == pytest.approx(
        base_rate_m_s * est.total_multiplier
    )


# --- per-component update ---------------------------------------------------

def make_component(**overrides) -> ShipComponent:
    base = dict(
        name="bottom_plating",
        material=make_material(coating_breakdown_factor=2.0),
        thickness_m=0.020,
        area_m2=100.0,
        exposed_fraction=1.0,
        original_thickness_m=0.020,
        corrosion_allowance_m=0.003,
        safety_factor_required=1.5,
    )
    base.update(overrides)
    return ShipComponent(**base)


def _update(comp, accumulated, dt_s, **cond):
    return update_component_corrosion(
        component=comp,
        accumulated_corrosion_m=accumulated,
        environment=cond.get("env", make_env(water_temperature_c=25.0)),
        weather=cond.get("weather", make_weather()),
        wave=cond.get("wave", make_wave(significant_wave_height_m=3.0)),
        speed_m_s=cond.get("speed", 6.0),
        dt_s=dt_s,
        config=CFG,
    )


def test_longer_timestep_gives_larger_thickness_loss():
    comp = make_component()
    short = _update(comp, 0.0, dt_s=3600.0)
    long = _update(comp, 0.0, dt_s=3600.0 * 24)
    assert long.thickness_loss_m > short.thickness_loss_m
    # Same rate, so loss scales linearly with dt.
    assert long.thickness_loss_m == pytest.approx(short.thickness_loss_m * 24.0)


def test_accumulation_reduces_effective_thickness():
    comp = make_component()
    upd = _update(comp, accumulated=0.004, dt_s=3600.0)
    assert upd.effective_thickness_m < comp.original_thickness_m
    assert upd.accumulated_corrosion_m > 0.004
    assert 0.0 <= upd.remaining_thickness_fraction <= 1.0


def test_warning_when_allowance_exceeded_and_below_min_fraction():
    comp = make_component()
    # Consume more than the allowance (0.003 m) and drop below 75% of original.
    upd = _update(comp, accumulated=0.006, dt_s=0.0)
    assert any("allowance exceeded" in w for w in upd.warnings)
    assert any("minimum acceptable" in w for w in upd.warnings)


def test_safety_margin_drops_below_required():
    comp = make_component(safety_factor_required=1.5)
    # Heavy loss => low effective thickness => low safety margin.
    upd = _update(comp, accumulated=0.010, dt_s=0.0)
    assert upd.safety_margin < comp.safety_factor_required
    assert any("safety margin" in w for w in upd.warnings)


def test_intact_component_has_no_warnings():
    comp = make_component()
    upd = _update(comp, accumulated=0.0, dt_s=0.0)
    assert upd.warnings == []
    assert upd.effective_thickness_m == pytest.approx(comp.original_thickness_m)
    assert upd.safety_margin > comp.safety_factor_required
