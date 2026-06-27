"""Serialize scenarios, configs, and results to JSON.

Writing goes through Pydantic so output round-trips back through the loader.
Files use stable 2-space indentation and a trailing newline to be diff- and
version-control-friendly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

from ..config import SimulationConfig
from ..models.results import SimulationResult
from ..models.scenario import Scenario

PathLike = Union[str, Path]


def _write_json(obj, path: PathLike, indent: int) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(obj.model_dump_json(indent=indent) + "\n", encoding="utf-8")
    return out


def save_scenario(scenario: Scenario, path: PathLike, *, indent: int = 2) -> Path:
    """Write a :class:`Scenario` to JSON; returns the written path."""
    return _write_json(scenario, path, indent)


def save_result(
    result: SimulationResult,
    path: PathLike,
    *,
    include_timeline: bool = True,
    indent: int = 2,
) -> Path:
    """Write a :class:`SimulationResult` to JSON; returns the written path.

    The corrosion/stability summaries, cumulative capsize probability, warnings,
    and assumptions are always written. The (potentially large) per-timestep
    ``timeline`` is included only when ``include_timeline`` is True; otherwise it
    is written as an empty list (the summaries are unaffected).
    """
    if not include_timeline:
        result = result.model_copy(update={"timeline": []})
    return _write_json(result, path, indent)


def save_config(config: SimulationConfig, path: PathLike, *, indent: int = 2) -> Path:
    """Write a :class:`SimulationConfig` to JSON; returns the written path."""
    return _write_json(config, path, indent)


__all__ = ["save_scenario", "save_result", "save_config"]
