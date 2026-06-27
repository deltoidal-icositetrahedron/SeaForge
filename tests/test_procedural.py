"""Tests for procedural generation and segmented providers."""

from __future__ import annotations

import pytest

from ship_sim.generation.procedural import (
    DEFAULT_RANGES,
    ProceduralEnvironmentProvider,
    Segment,
    SegmentedWeatherProvider,
    generate_environment,
    generate_waves,
    generate_weather,
)
from ship_sim.models import GeoPosition, WeatherCondition

TROPICAL = GeoPosition(latitude_deg=5.0, longitude_deg=-30.0)
POLAR = GeoPosition(latitude_deg=68.0, longitude_deg=20.0)
SEED = 12345


# --- ranges ---------------------------------------------------------------

def test_generated_weather_in_plausible_ranges():
    for t in range(0, 7 * 86400, 9000):
        w = generate_weather(TROPICAL, float(t), SEED)
        assert 0.0 <= w.wind_speed_m_s <= DEFAULT_RANGES.wind_max_m_s
        assert 0.0 <= w.wind_direction_deg < 360.0
        assert -60.0 <= w.air_temperature_c <= 60.0
        assert 0.0 <= w.relative_humidity_0_1 <= 1.0
        assert w.precipitation_rate_mm_hr >= 0.0
        assert 0.0 <= w.storm_intensity_0_1 <= 1.0
        assert w.atmospheric_pressure_pa > 0.0


def test_generated_waves_in_plausible_ranges():
    for t in range(0, 7 * 86400, 9000):
        w = generate_weather(TROPICAL, float(t), SEED)
        s = generate_waves(TROPICAL, float(t), w, SEED)
        assert 0.0 <= s.significant_wave_height_m <= DEFAULT_RANGES.wave_height_max_m
        assert 3.0 <= s.peak_period_s <= 20.0
        assert 0.0 <= s.mean_wave_direction_deg < 360.0
        assert 0.0 <= s.current_speed_m_s <= DEFAULT_RANGES.current_max_m_s
        assert 0.0 <= s.current_direction_deg < 360.0


def test_generated_environment_in_plausible_ranges():
    for pos in (TROPICAL, POLAR):
        for t in range(0, 7 * 86400, 9000):
            e = generate_environment(pos, float(t), SEED)
            assert DEFAULT_RANGES.water_temp_min_c <= e.water_temperature_c <= DEFAULT_RANGES.water_temp_max_c
            assert DEFAULT_RANGES.salinity_min_ppt <= e.salinity_ppt <= DEFAULT_RANGES.salinity_max_ppt
            assert DEFAULT_RANGES.ph_min <= e.pH <= DEFAULT_RANGES.ph_max
            assert DEFAULT_RANGES.do_min_mg_l <= e.dissolved_oxygen_mg_l <= DEFAULT_RANGES.do_max_mg_l
            assert 0.0 <= e.pollution_factor_0_1 <= 1.0


# --- correlations / physics ------------------------------------------------

def test_storm_increases_wind_on_average():
    """Higher storm intensity should track higher wind speed across times."""
    pairs = [
        (lambda w: w.storm_intensity_0_1, lambda w: w.wind_speed_m_s)
    ]
    samples = [generate_weather(TROPICAL, float(t), SEED) for t in range(0, 30 * 86400, 6000)]
    storms = [w.storm_intensity_0_1 for w in samples]
    winds = [w.wind_speed_m_s for w in samples]
    # Positive correlation between storm and wind.
    import numpy as np
    corr = np.corrcoef(storms, winds)[0, 1]
    assert corr > 0.5


def test_stronger_wind_gives_higher_waves():
    pos, t = TROPICAL, 50000.0
    calm = WeatherCondition(wind_speed_m_s=4.0, wind_direction_deg=0.0,
                            air_temperature_c=25.0, relative_humidity_0_1=0.7,
                            storm_intensity_0_1=0.1)
    gale = WeatherCondition(wind_speed_m_s=25.0, wind_direction_deg=0.0,
                            air_temperature_c=25.0, relative_humidity_0_1=0.9,
                            storm_intensity_0_1=0.8)
    hs_calm = generate_waves(pos, t, calm, SEED).significant_wave_height_m
    hs_gale = generate_waves(pos, t, gale, SEED).significant_wave_height_m
    assert hs_gale > hs_calm


def test_colder_at_higher_latitude():
    # Average over time to remove seasonal/noise variation.
    def mean_temp(pos):
        temps = [generate_environment(pos, float(t), SEED).water_temperature_c
                 for t in range(0, 365 * 86400, 5 * 86400)]
        return sum(temps) / len(temps)
    assert mean_temp(POLAR) < mean_temp(TROPICAL)


def test_waves_travel_roughly_downwind():
    pos, t = TROPICAL, 12345.0
    w = WeatherCondition(wind_speed_m_s=15.0, wind_direction_deg=90.0,
                         air_temperature_c=25.0, relative_humidity_0_1=0.8,
                         storm_intensity_0_1=0.5)
    s = generate_waves(pos, t, w, SEED)
    # Wind FROM 90 deg -> waves travel toward ~270 deg (within the spread).
    diff = abs(((s.mean_wave_direction_deg - 270.0 + 180.0) % 360.0) - 180.0)
    assert diff <= DEFAULT_RANGES.wave_dir_spread_deg + 1e-6


# --- determinism ----------------------------------------------------------

def test_procedural_reproducible_with_same_seed():
    pos, t = TROPICAL, 42424.0
    w1 = generate_weather(pos, t, SEED)
    w2 = generate_weather(pos, t, SEED)
    assert w1 == w2
    s1 = generate_waves(pos, t, w1, SEED)
    s2 = generate_waves(pos, t, w2, SEED)
    assert s1 == s2
    e1 = generate_environment(pos, t, SEED)
    e2 = generate_environment(pos, t, SEED)
    assert e1 == e2


def test_different_seed_changes_output():
    pos, t = TROPICAL, 42424.0
    assert generate_weather(pos, t, 1) != generate_weather(pos, t, 2)


# --- segmented (Mode A) providers -----------------------------------------

def test_segmented_provider_selects_matching_segment():
    calm = WeatherCondition(wind_speed_m_s=5.0, wind_direction_deg=0.0,
                            air_temperature_c=20.0, relative_humidity_0_1=0.6,
                            storm_intensity_0_1=0.0)
    storm = WeatherCondition(wind_speed_m_s=30.0, wind_direction_deg=180.0,
                             air_temperature_c=12.0, relative_humidity_0_1=0.95,
                             storm_intensity_0_1=0.9)
    provider = SegmentedWeatherProvider(
        [
            Segment(calm, start_time_s=0.0, end_time_s=100.0),
            Segment(storm, start_time_s=100.0, end_time_s=200.0),
        ]
    )
    assert provider.at(TROPICAL, 50.0).wind_speed_m_s == 5.0
    assert provider.at(TROPICAL, 150.0).wind_speed_m_s == 30.0


def test_segmented_provider_nearest_fallback():
    calm = WeatherCondition(wind_speed_m_s=5.0, wind_direction_deg=0.0,
                            air_temperature_c=20.0, relative_humidity_0_1=0.6,
                            storm_intensity_0_1=0.0)
    provider = SegmentedWeatherProvider(
        [Segment(calm, start_time_s=0.0, end_time_s=100.0)],
        fallback_nearest=True,
    )
    # Outside any segment, but nearest fallback returns the only segment.
    assert provider.at(TROPICAL, 9999.0).wind_speed_m_s == 5.0


def test_segmented_provider_raises_without_fallback():
    calm = WeatherCondition(wind_speed_m_s=5.0, wind_direction_deg=0.0,
                            air_temperature_c=20.0, relative_humidity_0_1=0.6,
                            storm_intensity_0_1=0.0)
    provider = SegmentedWeatherProvider(
        [Segment(calm, start_time_s=0.0, end_time_s=100.0)]
    )
    with pytest.raises(LookupError):
        provider.at(TROPICAL, 9999.0)


def test_procedural_provider_matches_function():
    provider = ProceduralEnvironmentProvider(SEED)
    assert provider.at(TROPICAL, 1000.0) == generate_environment(TROPICAL, 1000.0, SEED)
