"""ship_sim -- modular ship corrosion & stability simulation.

This package estimates ship corrosion, structural degradation, and
capsizing/stability risk over a route using physically motivated, tunable
models.

ENGINEERING APPROXIMATION -- NOT A CERTIFIED SAFETY TOOL.
The models here are simplified engineering approximations intended for
exploration, education, and comparative studies. They must not be used as the
basis for real-world safety, classification, or operational decisions.

Conventions: SI units internally (see :mod:`ship_sim.units`); all data models
are validated Pydantic v2 models (see :mod:`ship_sim.models`); every empirical
coefficient is exposed for tuning (see :mod:`ship_sim.config`).
"""

from __future__ import annotations

from . import units
from .config import SimulationConfig
from .models import (
    GeoPosition,
    Material,
    RegionEnvironment,
    Scenario,
    Ship,
    ShipComponent,
    SimulationResult,
    SimulationState,
    Trajectory,
    WaveCondition,
    Waypoint,
    WeatherCondition,
)

__version__ = "0.1.0"

#: Standard disclaimer string for reports and CLI output.
DISCLAIMER = (
    "ship_sim is an ENGINEERING APPROXIMATION, not a certified naval safety "
    "tool. Do not use it for real-world safety, classification, or operational "
    "decisions."
)

__all__ = [
    "units",
    "SimulationConfig",
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
    "DISCLAIMER",
    "__version__",
]
