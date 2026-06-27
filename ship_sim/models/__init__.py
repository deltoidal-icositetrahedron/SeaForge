"""Data models for the ship-corrosion / stability simulation.

All models are Pydantic v2 ``BaseModel`` subclasses with validation enabled.
SI units are used internally; see :mod:`ship_sim.units`.
"""

from __future__ import annotations

from .environment import RegionEnvironment
from .materials import Material, ShipComponent
from .results import GeoPosition, SimulationResult, SimulationState
from .scenario import (
    EnvironmentSegment,
    ProceduralSettings,
    Scenario,
    SimulationSettings,
    WaveSegment,
    WeatherSegment,
)
from .ship import Ship
from .trajectory import Trajectory, Waypoint
from .waves import WaveCondition
from .weather import WeatherCondition

__all__ = [
    "Material",
    "ShipComponent",
    "Ship",
    "Waypoint",
    "Trajectory",
    "RegionEnvironment",
    "WeatherCondition",
    "WaveCondition",
    "GeoPosition",
    "SimulationState",
    "SimulationResult",
    "Scenario",
    "SimulationSettings",
    "WeatherSegment",
    "WaveSegment",
    "EnvironmentSegment",
    "ProceduralSettings",
]
