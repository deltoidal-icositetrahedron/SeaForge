"""Procedural scenario generation and environmental providers.

Mode A (segmented user conditions) and Mode B (procedural generation) share the
``WeatherProvider`` / ``WaveProvider`` / ``EnvironmentProvider`` interfaces.
"""

from __future__ import annotations

from .procedural import (
    DEFAULT_RANGES,
    EnvironmentProvider,
    ProceduralEnvironmentProvider,
    ProceduralRanges,
    ProceduralWaveProvider,
    ProceduralWeatherProvider,
    Segment,
    SegmentedEnvironmentProvider,
    SegmentedWaveProvider,
    SegmentedWeatherProvider,
    WaveProvider,
    WeatherProvider,
    generate_environment,
    generate_waves,
    generate_weather,
)

__all__ = [
    "WeatherProvider",
    "WaveProvider",
    "EnvironmentProvider",
    "Segment",
    "SegmentedWeatherProvider",
    "SegmentedWaveProvider",
    "SegmentedEnvironmentProvider",
    "ProceduralRanges",
    "DEFAULT_RANGES",
    "generate_weather",
    "generate_waves",
    "generate_environment",
    "ProceduralWeatherProvider",
    "ProceduralWaveProvider",
    "ProceduralEnvironmentProvider",
]
