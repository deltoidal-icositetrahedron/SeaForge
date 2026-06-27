"""Tests for unit conversion helpers in ship_sim.units."""

from __future__ import annotations

import math

import pytest

from ship_sim import units


def test_knots_roundtrip():
    assert units.knots_to_mps(1.0) == pytest.approx(0.5144444, rel=1e-6)
    for v in (0.0, 1.0, 12.5, 30.0):
        assert units.mps_to_knots(units.knots_to_mps(v)) == pytest.approx(v)


def test_known_speed_values():
    # 10 knots is a common cruise speed ~5.144 m/s.
    assert units.knots_to_mps(10.0) == pytest.approx(5.144444, rel=1e-6)


def test_time_conversions():
    assert units.hours_to_seconds(1.0) == 3600.0
    assert units.seconds_to_hours(7200.0) == 2.0
    # Julian year used throughout the project.
    assert units.years_to_seconds(1.0) == pytest.approx(365.25 * 24 * 3600.0)
    assert units.seconds_to_years(units.years_to_seconds(3.0)) == pytest.approx(3.0)


def test_corrosion_rate_roundtrip():
    # 0.1 mm/year is a representative protected-steel rate.
    mpy = 0.1
    m_per_s = units.mm_per_year_to_m_per_s(mpy)
    assert m_per_s > 0.0
    assert units.m_per_s_to_mm_per_year(m_per_s) == pytest.approx(mpy)


def test_corrosion_rate_magnitude():
    # 1 mm/year should be ~3.17e-11 m/s.
    assert units.mm_per_year_to_m_per_s(1.0) == pytest.approx(3.168e-11, rel=1e-3)


def test_m_per_year_helpers():
    assert units.m_per_year_to_m_per_s(1.0) == pytest.approx(1.0 / units.SECONDS_PER_YEAR)
    assert units.m_per_s_to_m_per_year(units.m_per_year_to_m_per_s(0.005)) \
        == pytest.approx(0.005)


def test_temperature_conversions():
    assert units.celsius_to_kelvin(0.0) == pytest.approx(273.15)
    assert units.kelvin_to_celsius(273.15) == pytest.approx(0.0)
    for c in (-2.0, 15.0, 30.0):
        assert units.kelvin_to_celsius(units.celsius_to_kelvin(c)) == pytest.approx(c)


def test_angle_conversions():
    assert units.deg_to_rad(180.0) == pytest.approx(math.pi)
    assert units.rad_to_deg(math.pi) == pytest.approx(180.0)
    for d in (0.0, 45.0, 90.0, 359.0):
        assert units.rad_to_deg(units.deg_to_rad(d)) == pytest.approx(d)
