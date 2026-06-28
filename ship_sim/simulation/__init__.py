"""Simulation engine package.

Implemented so far:

- ``corrosion``  -- physically motivated marine-corrosion rate model.
- ``seakeeping`` -- wave-encounter kinematics (frequency, period, steepness).
- ``stability`` -- structural weakening, wind heeling, and capsize-risk model.
- ``timestep``  -- trajectory interpolation utilities (position/speed/heading).
- ``engine``    -- ShipSimulationEngine orchestrating the timestep loop.
"""

from __future__ import annotations

from .corrosion import (
    ComponentCorrosionUpdate,
    CorrosionEstimate,
    estimate_corrosion_rate,
    update_component_corrosion,
)
from .engine import ShipSimulationEngine
from .monte_carlo import MonteCarloResult, PerturbationSpec, run_monte_carlo
from .seakeeping import WaveEncounterEstimate, estimate_wave_encounter
from .stability import (
    StabilityEstimate,
    StructuralWeakeningEstimate,
    estimate_stability_risk,
    estimate_structural_weakening,
    estimate_wind_heeling_moment,
)
from .timestep import (
    get_time_bounds,
    interpolate_heading,
    interpolate_position,
    interpolate_speed,
)

__all__ = [
    # corrosion
    "CorrosionEstimate",
    "ComponentCorrosionUpdate",
    "estimate_corrosion_rate",
    "update_component_corrosion",
    # seakeeping
    "WaveEncounterEstimate",
    "estimate_wave_encounter",
    # stability
    "StructuralWeakeningEstimate",
    "StabilityEstimate",
    "estimate_structural_weakening",
    "estimate_wind_heeling_moment",
    "estimate_stability_risk",
    # trajectory interpolation
    "get_time_bounds",
    "interpolate_position",
    "interpolate_speed",
    "interpolate_heading",
    # engine
    "ShipSimulationEngine",
    # monte carlo
    "run_monte_carlo",
    "MonteCarloResult",
    "PerturbationSpec",
]
