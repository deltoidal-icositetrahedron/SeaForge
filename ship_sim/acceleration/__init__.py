"""Optional compute-backend abstraction for batch/accelerated updates.

Pure-Python and NumPy backends are implemented; compiled backends (numba/rust/
cpp) are planned and gated behind benchmarks. See :mod:`ship_sim.acceleration.backend`.
"""

from __future__ import annotations

from .backend import (
    PLANNED_BACKENDS,
    AccelerationBackend,
    ComponentBatch,
    NumpyBackend,
    PythonBackend,
    choose_backend,
    list_available_backends,
)

__all__ = [
    "AccelerationBackend",
    "PythonBackend",
    "NumpyBackend",
    "ComponentBatch",
    "list_available_backends",
    "choose_backend",
    "PLANNED_BACKENDS",
]
