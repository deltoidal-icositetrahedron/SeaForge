"""Small shared numeric helpers used across the physics and generation modules.

These are deliberately tiny, dependency-free, and pure so they can be reused
without coupling the modules to each other. They are imported (rather than
re-defined) by the corrosion/stability physics, the procedural generator, and
the Monte Carlo driver to avoid duplicated clamp/logistic logic.
"""

from __future__ import annotations

import math


def clamp(x: float, lo: float, hi: float) -> float:
    """Clamp ``x`` to the closed interval ``[lo, hi]``."""
    return lo if x < lo else hi if x > hi else x


def clamp01(x: float) -> float:
    """Clamp ``x`` to ``[0, 1]`` (common for normalized factors/probabilities)."""
    return clamp(x, 0.0, 1.0)


def logistic(x: float) -> float:
    """Numerically stable logistic ``1 / (1 + exp(-x))`` in the open range (0, 1)."""
    if x >= 0.0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def saturating(value: float, scale: float) -> float:
    """Saturating ratio ``value / (value + scale)`` in ``[0, 1)``.

    Monotonically increasing in ``value`` (negative inputs are floored at 0) and
    levels off for ``value >> scale``. Used for danger indices that should grow
    but plateau (e.g. wave height relative to beam).
    """
    value = max(0.0, value)
    denom = value + scale
    return value / denom if denom > 0 else 0.0


__all__ = ["clamp", "clamp01", "logistic", "saturating"]
