"""Load, validate, and assemble scenarios into engine-ready objects.

Loading goes through the Pydantic :class:`~ship_sim.models.scenario.Scenario`
schema, so every file is validated (types, units, ranges, required fields) with
precise, field-level error messages. :func:`load_scenario` then turns the
validated scenario into the concrete objects
:class:`~ship_sim.simulation.engine.ShipSimulationEngine` needs: the ship,
trajectory, the three condition providers (segmented where the user supplied
segments, otherwise procedural), the resolved config, timestep, and backend.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Sequence, Union

from pydantic import ValidationError

from ..config import SimulationConfig
from ..generation.procedural import (
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
)
from ..models.scenario import Scenario, _SegmentSpec

PathLike = Union[str, Path]


@dataclass
class LoadedScenario:
    """Engine-ready objects assembled from a validated :class:`Scenario`."""

    name: str
    description: str
    ship: Any
    trajectory: Any
    environment_provider: Any
    weather_provider: Any
    wave_provider: Any
    config: SimulationConfig
    dt_s: float
    backend: str
    scenario: Scenario  # the validated source scenario, for reference

    def build_engine(self):
        """Construct a :class:`ShipSimulationEngine` from this scenario."""
        from ..simulation.engine import ShipSimulationEngine

        return ShipSimulationEngine(
            ship=self.ship,
            trajectory=self.trajectory,
            environment_provider=self.environment_provider,
            weather_provider=self.weather_provider,
            wave_provider=self.wave_provider,
            config=self.config,
            dt_s=self.dt_s,
            backend=self.backend,
        )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def read_scenario(path: PathLike) -> Scenario:
    """Validate and return a :class:`Scenario` from a JSON file (no assembly)."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        return Scenario.model_validate_json(text)
    except ValidationError as exc:
        raise ValueError(f"Invalid scenario file '{path}':\n{exc}") from exc


def read_scenario_dict(data: dict) -> Scenario:
    """Validate a :class:`Scenario` from an already-parsed dict."""
    try:
        return Scenario.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Invalid scenario data:\n{exc}") from exc


def _resolve_ranges(overrides: Optional[dict]) -> ProceduralRanges:
    """Apply ProceduralRanges overrides, rejecting unknown keys clearly."""
    if not overrides:
        return DEFAULT_RANGES
    valid = {f.name for f in dataclasses.fields(ProceduralRanges)}
    unknown = set(overrides) - valid
    if unknown:
        raise ValueError(
            f"Unknown procedural range override(s): {sorted(unknown)}. "
            f"Valid keys: {sorted(valid)}."
        )
    return dataclasses.replace(DEFAULT_RANGES, **overrides)


def _to_runtime_segments(specs: Sequence[_SegmentSpec]) -> List[Segment]:
    # All concrete segment subclasses (Weather/Wave/Environment) define `condition`.
    return [
        Segment(
            value=spec.condition,  # type: ignore[attr-defined]
            start_time_s=spec.resolved_start_s,
            end_time_s=spec.resolved_end_s,
            lat_bounds=spec.lat_bounds,
            lon_bounds=spec.lon_bounds,
        )
        for spec in specs
    ]


def build_providers(scenario: Scenario):
    """Build (environment, weather, wave) providers from a validated scenario.

    For each channel: use a segmented provider if the user supplied segments,
    otherwise a procedural provider seeded from ``scenario.procedural``.
    """
    ranges = _resolve_ranges(scenario.procedural.ranges)
    seed = scenario.procedural.seed
    fallback = scenario.simulation.fallback_nearest

    env_provider: EnvironmentProvider
    weather_provider: WeatherProvider
    wave_provider: WaveProvider

    if scenario.environment_segments:
        env_provider = SegmentedEnvironmentProvider(
            _to_runtime_segments(scenario.environment_segments),
            fallback_nearest=fallback,
        )
    else:
        env_provider = ProceduralEnvironmentProvider(seed, ranges)

    if scenario.weather_segments:
        weather_provider = SegmentedWeatherProvider(
            _to_runtime_segments(scenario.weather_segments),
            fallback_nearest=fallback,
        )
    else:
        weather_provider = ProceduralWeatherProvider(seed, ranges)

    if scenario.wave_segments:
        wave_provider = SegmentedWaveProvider(
            _to_runtime_segments(scenario.wave_segments),
            fallback_nearest=fallback,
        )
    else:
        wave_provider = ProceduralWaveProvider(seed, ranges)

    return env_provider, weather_provider, wave_provider


def loaded_from_scenario(scenario: Scenario) -> LoadedScenario:
    """Assemble engine-ready objects from an in-memory (validated) Scenario.

    This is the shared assembly step used by both file loading and any caller
    that already holds a :class:`Scenario` (e.g. the GUI editing inputs live).
    """
    env_provider, weather_provider, wave_provider = build_providers(scenario)
    return LoadedScenario(
        name=scenario.name,
        description=scenario.description,
        ship=scenario.ship,
        trajectory=scenario.trajectory,
        environment_provider=env_provider,
        weather_provider=weather_provider,
        wave_provider=wave_provider,
        config=scenario.config,
        dt_s=scenario.simulation.resolved_dt_s,
        backend=scenario.simulation.backend,
        scenario=scenario,
    )


def load_scenario(path: PathLike) -> LoadedScenario:
    """Load a scenario JSON and assemble the objects the engine needs.

    Returns a :class:`LoadedScenario`; call ``.build_engine()`` to get a ready
    :class:`ShipSimulationEngine`.
    """
    return loaded_from_scenario(read_scenario(path))


def load_config(path: PathLike) -> SimulationConfig:
    """Load and validate a standalone :class:`SimulationConfig` from JSON."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        return SimulationConfig.model_validate_json(text)
    except ValidationError as exc:
        raise ValueError(f"Invalid config file '{path}':\n{exc}") from exc


__all__ = [
    "LoadedScenario",
    "loaded_from_scenario",
    "read_scenario",
    "read_scenario_dict",
    "build_providers",
    "load_scenario",
    "load_config",
]
