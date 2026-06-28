"""Environmental providers and procedural condition generation.

Two ways to supply the weather / waves / seawater conditions a voyage
experiences:

**Mode A -- user-segmented conditions.** The caller supplies a list of
:class:`Segment` objects (optionally bounded in time and/or by a lat/lon box),
and a :class:`SegmentedWeatherProvider` / :class:`SegmentedWaveProvider` /
:class:`SegmentedEnvironmentProvider` returns the matching segment's condition.
With ``fallback_nearest=True`` the nearest segment is returned when none matches.

**Mode B -- procedural generation.** :func:`generate_weather`,
:func:`generate_waves`, and :func:`generate_environment` synthesize physically
plausible, mutually correlated conditions from position, time, and a seed. The
:class:`ProceduralWeatherProvider` etc. wrap these as providers.

All providers share a small, clean interface (see the ``*Provider`` protocols)
so the engine can consume either mode interchangeably.

Procedural design notes / simplifications
-----------------------------------------
- Determinism: each "field" (storm, wind, etc.) draws its random
  frequencies/phases from a NumPy ``SeedSequence`` built from ``[seed,
  channel_id]``, then evaluates a smooth sum-of-sines in time and position.
  Same ``(seed, position, time)`` always yields the same condition.
- Correlation: waves are generated *from* the weather (wind + storm), so
  stronger wind / higher storm intensity produce higher seas; wave direction
  follows the wind.
- Climatology proxies: water/air temperature decrease with latitude and vary
  seasonally; dissolved oxygen decreases with temperature; salinity and pH are
  kept within plausible open-ocean ranges (tunable via :class:`ProceduralRanges`).
- This is a synthetic generator for scenario exploration, not a forecast or a
  reanalysis dataset.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional, Protocol, Sequence, Tuple, runtime_checkable

import numpy as np

from .._math import clamp
from ..models.environment import RegionEnvironment
from ..models.results import GeoPosition
from ..models.waves import WaveCondition
from ..models.weather import WeatherCondition
from ..units import SECONDS_PER_YEAR


# ---------------------------------------------------------------------------
# Provider interfaces
# ---------------------------------------------------------------------------

@runtime_checkable
class WeatherProvider(Protocol):
    """Supplies atmospheric weather at a position and time."""

    def at(self, position: GeoPosition, time_s: float) -> WeatherCondition: ...


@runtime_checkable
class WaveProvider(Protocol):
    """Supplies the sea state, optionally correlated with the weather."""

    def at(
        self, position: GeoPosition, time_s: float, weather: WeatherCondition
    ) -> WaveCondition: ...


@runtime_checkable
class EnvironmentProvider(Protocol):
    """Supplies seawater chemistry/conditions at a position and time."""

    def at(self, position: GeoPosition, time_s: float) -> RegionEnvironment: ...


# ---------------------------------------------------------------------------
# Mode A: segmented providers
# ---------------------------------------------------------------------------

@dataclass
class Segment:
    """A condition that applies over an optional time window and/or region.

    ``value`` is the condition object (WeatherCondition / WaveCondition /
    RegionEnvironment). A segment *matches* a query if the time falls within
    ``[start_time_s, end_time_s]`` (when given) and the position falls within
    ``lat_bounds`` / ``lon_bounds`` (when given). A segment with no bounds is a
    catch-all that always matches.
    """

    value: Any
    start_time_s: Optional[float] = None
    end_time_s: Optional[float] = None
    lat_bounds: Optional[Tuple[float, float]] = None
    lon_bounds: Optional[Tuple[float, float]] = None

    def matches(self, position: GeoPosition, time_s: float) -> bool:
        if self.start_time_s is not None and time_s < self.start_time_s:
            return False
        if self.end_time_s is not None and time_s > self.end_time_s:
            return False
        if self.lat_bounds is not None and not (
            self.lat_bounds[0] <= position.latitude_deg <= self.lat_bounds[1]
        ):
            return False
        if self.lon_bounds is not None and not (
            self.lon_bounds[0] <= position.longitude_deg <= self.lon_bounds[1]
        ):
            return False
        return True

    def _distance(self, position: GeoPosition, time_s: float) -> float:
        """A simple match-distance used for nearest fallback (lower = closer)."""
        dist = 0.0
        start = self.start_time_s if self.start_time_s is not None else self.end_time_s
        end = self.end_time_s if self.end_time_s is not None else self.start_time_s
        if start is not None and end is not None:
            center = 0.5 * (start + end)
            # Scale time by a day so it is comparable to degrees of position.
            dist += abs(time_s - center) / 86400.0
        if self.lat_bounds is not None:
            center = 0.5 * (self.lat_bounds[0] + self.lat_bounds[1])
            dist += abs(position.latitude_deg - center)
        if self.lon_bounds is not None:
            center = 0.5 * (self.lon_bounds[0] + self.lon_bounds[1])
            dist += abs(position.longitude_deg - center)
        return dist


def _select_segment(
    segments: Sequence[Segment],
    position: GeoPosition,
    time_s: float,
    fallback_nearest: bool,
) -> Any:
    """Return the value of the first matching segment, or nearest if configured."""
    for seg in segments:
        if seg.matches(position, time_s):
            return seg.value
    if fallback_nearest and segments:
        nearest = min(segments, key=lambda s: s._distance(position, time_s))
        return nearest.value
    raise LookupError(
        f"No segment matches position={position} time_s={time_s} "
        "and fallback_nearest is disabled."
    )


class _SegmentedProviderBase:
    def __init__(self, segments: Sequence[Segment], *, fallback_nearest: bool = False):
        if not segments:
            raise ValueError("at least one segment is required.")
        self.segments = list(segments)
        self.fallback_nearest = fallback_nearest


class SegmentedWeatherProvider(_SegmentedProviderBase):
    """Mode-A weather provider backed by user-supplied segments."""

    def at(self, position: GeoPosition, time_s: float) -> WeatherCondition:
        return _select_segment(self.segments, position, time_s, self.fallback_nearest)


class SegmentedWaveProvider(_SegmentedProviderBase):
    """Mode-A wave provider (the ``weather`` argument is accepted but unused)."""

    def at(
        self,
        position: GeoPosition,
        time_s: float,
        weather: Optional[WeatherCondition] = None,
    ) -> WaveCondition:
        return _select_segment(self.segments, position, time_s, self.fallback_nearest)


class SegmentedEnvironmentProvider(_SegmentedProviderBase):
    """Mode-A seawater-environment provider backed by user-supplied segments."""

    def at(self, position: GeoPosition, time_s: float) -> RegionEnvironment:
        return _select_segment(self.segments, position, time_s, self.fallback_nearest)


# ---------------------------------------------------------------------------
# Mode B: procedural generation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProceduralRanges:
    """Tunable bounds/parameters for procedural generation (all documented)."""

    # Water temperature climatology (deg C)
    equator_water_temp_c: float = 28.0
    water_temp_lat_lapse: float = 0.55  # per degree |latitude|
    water_temp_seasonal_amp_c: float = 3.0
    water_temp_min_c: float = -2.0
    water_temp_max_c: float = 32.0
    # Air temperature climatology (deg C)
    equator_air_temp_c: float = 27.0
    air_temp_lat_lapse: float = 0.65
    air_temp_seasonal_amp_c: float = 8.0
    air_temp_min_c: float = -40.0
    air_temp_max_c: float = 45.0
    # Salinity (ppt)
    salinity_mean_ppt: float = 35.0
    salinity_span_ppt: float = 2.0
    salinity_min_ppt: float = 30.0
    salinity_max_ppt: float = 40.0
    # pH
    ph_mean: float = 8.1
    ph_span: float = 0.25
    ph_min: float = 7.6
    ph_max: float = 8.4
    # Dissolved oxygen (mg/L): decreases with temperature
    do_intercept_mg_l: float = 14.0
    do_temp_slope_mg_l_per_c: float = 0.28
    do_noise_mg_l: float = 1.0
    do_min_mg_l: float = 4.0
    do_max_mg_l: float = 13.0
    # Wind (m/s)
    wind_base_m_s: float = 9.0
    wind_storm_m_s: float = 28.0
    wind_max_m_s: float = 45.0
    # Waves
    pm_height_coeff: float = 0.0214  # Hs ~ coeff * U^2 (Pierson-Moskowitz-like)
    swell_base_m: float = 0.6
    swell_amp_m: float = 1.2
    wave_height_max_m: float = 16.0
    wave_dir_spread_deg: float = 30.0
    current_max_m_s: float = 1.5
    # Pollution / biofouling (0-1)
    pollution_max: float = 0.3
    biofouling_max: float = 0.5


DEFAULT_RANGES = ProceduralRanges()

# Stable per-channel ids so SeedSequence([seed, id]) is reproducible.
_CHANNELS = {
    "storm": 1, "wind": 2, "wind_dir": 3, "air_temp": 4, "humidity": 5,
    "precip": 6, "pressure": 7, "water_temp": 8, "salinity": 9, "ph": 10,
    "oxygen": 11, "pollution": 12, "biofouling": 13, "season": 14,
    "wave_dir": 15, "swell": 16, "current": 17, "current_dir": 18, "period": 19,
}


def _field(seed: int, channel: str, time_s: float, position: GeoPosition) -> float:
    """Deterministic smooth pseudo-field in [0, 1].

    Builds a sum of sinusoids in time (synoptic, ~2-10 day scales) with
    seed-derived frequencies/phases, gently modulated by position so different
    places differ. Same ``(seed, channel, time, position)`` -> same value.
    """
    ss = np.random.SeedSequence([int(seed) & 0xFFFFFFFF, _CHANNELS[channel]])
    rng = np.random.default_rng(ss)
    t_days = time_s / 86400.0
    n = 3
    freqs = rng.uniform(0.1, 0.6, n)          # cycles/day
    phases = rng.uniform(0.0, 2.0 * math.pi, n)
    spatial = rng.uniform(0.0, 0.3, n)
    amps = rng.uniform(0.5, 1.0, n)
    geo = position.latitude_deg + position.longitude_deg
    total = float(
        np.sum(amps * np.sin(2.0 * math.pi * freqs * t_days + phases + spatial * geo))
    )
    return 0.5 * (total / float(np.sum(amps)) + 1.0)


def _seasonal(seed: int, time_s: float, position: GeoPosition) -> float:
    """Seasonal signal in [-1, 1], hemisphere-flipped by latitude sign."""
    phase = 2.0 * math.pi * _field(seed, "season", 0.0, position)
    hemis = 0.0 if position.latitude_deg >= 0.0 else math.pi
    return math.sin(2.0 * math.pi * (time_s / SECONDS_PER_YEAR) + phase + hemis)


def generate_weather(
    position: GeoPosition,
    time_s: float,
    seed: int,
    ranges: ProceduralRanges = DEFAULT_RANGES,
) -> WeatherCondition:
    """Generate plausible, deterministic weather correlated via storm intensity.

    Stronger storms raise wind speed, humidity, and precipitation and lower
    pressure. Air temperature follows a latitude + seasonal climatology.
    """
    storm = _field(seed, "storm", time_s, position)
    wind_field = _field(seed, "wind", time_s, position)

    # Storm dominates wind; squaring sharpens the storm contribution.
    wind_speed = clamp(
        2.0 + ranges.wind_base_m_s * wind_field + ranges.wind_storm_m_s * storm ** 1.5,
        0.0,
        ranges.wind_max_m_s,
    )
    wind_direction = (360.0 * _field(seed, "wind_dir", time_s, position)) % 360.0

    base_air = ranges.equator_air_temp_c - ranges.air_temp_lat_lapse * abs(
        position.latitude_deg
    )
    air_temp = clamp(
        base_air
        + ranges.air_temp_seasonal_amp_c * _seasonal(seed, time_s, position)
        + 4.0 * (_field(seed, "air_temp", time_s, position) - 0.5),
        ranges.air_temp_min_c,
        ranges.air_temp_max_c,
    )

    humidity = clamp(
        0.6 + 0.3 * storm + 0.1 * (_field(seed, "humidity", time_s, position) - 0.5),
        0.0,
        1.0,
    )
    precipitation = max(
        0.0,
        30.0 * (storm - 0.2) * _field(seed, "precip", time_s, position),
    )
    pressure = clamp(
        101325.0 - 4500.0 * storm + 800.0 * (_field(seed, "pressure", time_s, position) - 0.5),
        90000.0,
        108000.0,
    )

    return WeatherCondition(
        wind_speed_m_s=float(wind_speed),
        wind_direction_deg=float(wind_direction),
        air_temperature_c=float(air_temp),
        relative_humidity_0_1=float(humidity),
        precipitation_rate_mm_hr=float(precipitation),
        storm_intensity_0_1=float(storm),
        atmospheric_pressure_pa=float(pressure),
    )


def generate_waves(
    position: GeoPosition,
    time_s: float,
    weather: WeatherCondition,
    seed: int,
    ranges: ProceduralRanges = DEFAULT_RANGES,
) -> WaveCondition:
    """Generate a sea state correlated with the weather.

    Wind sea height follows a Pierson-Moskowitz-like ``Hs ~ coeff * U^2`` scaled
    by a development factor that grows with storm intensity, plus a swell
    background. Waves travel roughly downwind; the peak period grows with wind.
    """
    u = weather.wind_speed_m_s
    development = 0.4 + 0.6 * weather.storm_intensity_0_1
    wind_sea = development * ranges.pm_height_coeff * u * u
    swell = ranges.swell_base_m + ranges.swell_amp_m * _field(
        seed, "swell", time_s, position
    )
    hs = clamp(wind_sea + swell, 0.0, ranges.wave_height_max_m)

    # Peak period grows with wind; kept consistent so steepness stays sub-breaking.
    peak_period = clamp(
        3.0 + 0.55 * u + 2.0 * _field(seed, "period", time_s, position),
        3.0,
        20.0,
    )

    # Waves travel downwind: wind blows FROM wind_direction, so toward +180.
    spread = ranges.wave_dir_spread_deg * (
        2.0 * _field(seed, "wave_dir", time_s, position) - 1.0
    )
    wave_dir = (weather.wind_direction_deg + 180.0 + spread) % 360.0

    current_speed = ranges.current_max_m_s * _field(seed, "current", time_s, position)
    current_dir = (360.0 * _field(seed, "current_dir", time_s, position)) % 360.0

    return WaveCondition(
        significant_wave_height_m=float(hs),
        peak_period_s=float(peak_period),
        mean_wave_direction_deg=float(wave_dir),
        current_speed_m_s=float(current_speed),
        current_direction_deg=float(current_dir),
        wave_spectrum_type="pierson_moskowitz",
    )


def generate_environment(
    position: GeoPosition,
    time_s: float,
    seed: int,
    ranges: ProceduralRanges = DEFAULT_RANGES,
) -> RegionEnvironment:
    """Generate plausible, deterministic seawater chemistry.

    Water temperature decreases with latitude and varies seasonally; dissolved
    oxygen decreases with temperature; salinity and pH stay within plausible
    open-ocean ranges.
    """
    base_water = ranges.equator_water_temp_c - ranges.water_temp_lat_lapse * abs(
        position.latitude_deg
    )
    water_temp = clamp(
        base_water
        + ranges.water_temp_seasonal_amp_c * _seasonal(seed, time_s, position)
        + 2.0 * (_field(seed, "water_temp", time_s, position) - 0.5),
        ranges.water_temp_min_c,
        ranges.water_temp_max_c,
    )

    salinity = clamp(
        ranges.salinity_mean_ppt
        + ranges.salinity_span_ppt * (2.0 * _field(seed, "salinity", time_s, position) - 1.0),
        ranges.salinity_min_ppt,
        ranges.salinity_max_ppt,
    )
    ph = clamp(
        ranges.ph_mean + ranges.ph_span * (2.0 * _field(seed, "ph", time_s, position) - 1.0),
        ranges.ph_min,
        ranges.ph_max,
    )

    # Cooler water holds more dissolved oxygen.
    oxygen = clamp(
        ranges.do_intercept_mg_l
        - ranges.do_temp_slope_mg_l_per_c * water_temp
        + ranges.do_noise_mg_l * (2.0 * _field(seed, "oxygen", time_s, position) - 1.0),
        ranges.do_min_mg_l,
        ranges.do_max_mg_l,
    )

    pollution = ranges.pollution_max * _field(seed, "pollution", time_s, position)
    biofouling = ranges.biofouling_max * _field(seed, "biofouling", time_s, position)

    return RegionEnvironment(
        salinity_ppt=float(salinity),
        water_temperature_c=float(water_temp),
        pH=float(ph),
        dissolved_oxygen_mg_l=float(oxygen),
        pollution_factor_0_1=float(clamp(pollution, 0.0, 1.0)),
        biofouling_factor_0_1=float(clamp(biofouling, 0.0, 1.0)),
    )


# ---------------------------------------------------------------------------
# Procedural providers (wrap the generators behind the provider interface)
# ---------------------------------------------------------------------------

class ProceduralWeatherProvider:
    """Mode-B weather provider wrapping :func:`generate_weather`."""

    def __init__(self, seed: int, ranges: ProceduralRanges = DEFAULT_RANGES):
        self.seed = seed
        self.ranges = ranges

    def at(self, position: GeoPosition, time_s: float) -> WeatherCondition:
        return generate_weather(position, time_s, self.seed, self.ranges)


class ProceduralWaveProvider:
    """Mode-B wave provider wrapping :func:`generate_waves`."""

    def __init__(self, seed: int, ranges: ProceduralRanges = DEFAULT_RANGES):
        self.seed = seed
        self.ranges = ranges

    def at(
        self, position: GeoPosition, time_s: float, weather: WeatherCondition
    ) -> WaveCondition:
        return generate_waves(position, time_s, weather, self.seed, self.ranges)


class ProceduralEnvironmentProvider:
    """Mode-B seawater-environment provider wrapping :func:`generate_environment`."""

    def __init__(self, seed: int, ranges: ProceduralRanges = DEFAULT_RANGES):
        self.seed = seed
        self.ranges = ranges

    def at(self, position: GeoPosition, time_s: float) -> RegionEnvironment:
        return generate_environment(position, time_s, self.seed, self.ranges)


__all__ = [
    # interfaces
    "WeatherProvider",
    "WaveProvider",
    "EnvironmentProvider",
    # mode A
    "Segment",
    "SegmentedWeatherProvider",
    "SegmentedWaveProvider",
    "SegmentedEnvironmentProvider",
    # mode B
    "ProceduralRanges",
    "DEFAULT_RANGES",
    "generate_weather",
    "generate_waves",
    "generate_environment",
    "ProceduralWeatherProvider",
    "ProceduralWaveProvider",
    "ProceduralEnvironmentProvider",
]
