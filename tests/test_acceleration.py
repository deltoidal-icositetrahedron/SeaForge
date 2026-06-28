"""Tests for the acceleration backend abstraction and numpy equivalence."""

from __future__ import annotations

import pytest

from ship_sim.acceleration.backend import (
    ComponentBatch,
    NumpyBackend,
    PythonBackend,
    choose_backend,
    list_available_backends,
)
from ship_sim.config import SimulationConfig
from ship_sim.models import (
    Material,
    RegionEnvironment,
    ShipComponent,
    WaveCondition,
    WeatherCondition,
)
from ship_sim.simulation.corrosion import estimate_corrosion_rate

CFG = SimulationConfig.default()


def make_components(n=12):
    comps = []
    for i in range(n):
        mat = Material(
            name=f"mat{i}", density_kg_m3=7850.0, yield_strength_pa=355e6,
            ultimate_strength_pa=490e6, elastic_modulus_pa=210e9,
            base_corrosion_rate_m_per_year=0.0001 * (1 + 0.1 * i),
            corrosion_resistance_factor=1.0 + 0.2 * (i % 4),
            galvanic_potential_v=-0.6, coating_breakdown_factor=0.5 + 0.3 * (i % 3),
        )
        comps.append(ShipComponent(
            name=f"c{i}", material=mat, thickness_m=0.02, area_m2=10.0,
            exposed_fraction=0.4 + 0.05 * (i % 5), original_thickness_m=0.02,
        ))
    return comps


def conditions():
    env = RegionEnvironment(salinity_ppt=36.0, water_temperature_c=24.0, pH=7.8,
                            dissolved_oxygen_mg_l=9.0, pollution_factor_0_1=0.3)
    weather = WeatherCondition(wind_speed_m_s=15.0, wind_direction_deg=80.0,
                               air_temperature_c=20.0, relative_humidity_0_1=0.8,
                               storm_intensity_0_1=0.5)
    wave = WaveCondition(significant_wave_height_m=3.0, peak_period_s=8.0,
                         mean_wave_direction_deg=0.0, current_speed_m_s=0.8)
    return env, weather, wave, 6.0


# --- selection -------------------------------------------------------------

def test_list_available_includes_python_and_numpy():
    avail = list_available_backends()
    assert "python" in avail
    assert "numpy" in avail  # numpy is a project dependency


def test_choose_backend_variants():
    assert choose_backend("python").name == "python"
    assert choose_backend("numpy").name == "numpy"
    assert choose_backend("auto").name in ("numpy", "python")


def test_choose_planned_backend_raises():
    for name in ("numba", "rust", "cpp"):
        with pytest.raises(NotImplementedError):
            choose_backend(name)


def test_choose_unknown_backend_raises():
    with pytest.raises(ValueError):
        choose_backend("quantum")


# --- numerical equivalence -------------------------------------------------

def test_numpy_matches_python_batch():
    comps = make_components()
    batch = ComponentBatch.from_components(comps)
    env, weather, wave, speed = conditions()
    py = PythonBackend().corrosion_rate_batch(batch, env, weather, wave, speed, CFG)
    nb = NumpyBackend().corrosion_rate_batch(batch, env, weather, wave, speed, CFG)
    assert len(py) == len(nb) == len(comps)
    for a, b in zip(py, list(nb)):
        assert a == pytest.approx(b, rel=1e-12, abs=1e-24)


def test_batch_matches_per_component_estimate():
    comps = make_components()
    batch = ComponentBatch.from_components(comps)
    env, weather, wave, speed = conditions()
    nb = list(NumpyBackend().corrosion_rate_batch(batch, env, weather, wave, speed, CFG))
    for comp, batch_rate in zip(comps, nb):
        est = estimate_corrosion_rate(
            material=comp.material, environment=env, weather=weather, wave=wave,
            speed_m_s=speed, exposure_fraction=comp.exposed_fraction, config=CFG,
        )
        assert est.corrosion_rate_m_per_s == pytest.approx(batch_rate, rel=1e-12, abs=1e-24)


def test_zero_exposure_gives_zero_rate_in_batch():
    comps = make_components(3)
    for c in comps:
        c.exposed_fraction = 0.0
    batch = ComponentBatch.from_components(comps)
    env, weather, wave, speed = conditions()
    rates = list(NumpyBackend().corrosion_rate_batch(batch, env, weather, wave, speed, CFG))
    assert all(r == 0.0 for r in rates)
