"""SI unit conventions and conversion helpers.

This project works in **SI base units internally** at all times:

- length:          meters (m)
- mass:            kilograms (kg)
- time:            seconds (s)
- speed:           meters per second (m/s)
- stress/strength: pascals (Pa)
- temperature:     kelvin (K) for physics; Celsius is used only for
                   *user-facing* environmental input and is converted on entry.
- corrosion rate:  meters per second (m/s) internally; mm/year and m/year are
                   provided only as human-friendly conversions.

All conversion helpers are pure functions with no side effects so they can be
used freely inside vectorized code (they pass NumPy arrays through unchanged
because they are simple arithmetic).

The module also exposes the small set of physical constants used elsewhere in
the project, kept here so there is a single source of truth.
"""

from __future__ import annotations

import math
from typing import Final

# ---------------------------------------------------------------------------
# Fundamental conversion factors (exact unless noted)
# ---------------------------------------------------------------------------

#: One international knot in meters per second (1 nautical mile = 1852 m / 3600 s).
KNOT_IN_MPS: Final[float] = 1852.0 / 3600.0  # = 0.5144444...

#: Seconds in one hour.
SECONDS_PER_HOUR: Final[float] = 3600.0

#: Days per Julian year (the convention used throughout this project so that
#: "per year" corrosion rates are reproducible and unambiguous).
DAYS_PER_YEAR: Final[float] = 365.25

#: Seconds in one Julian year.
SECONDS_PER_YEAR: Final[float] = DAYS_PER_YEAR * 24.0 * SECONDS_PER_HOUR

#: Offset between the Celsius and Kelvin scales.
KELVIN_OFFSET: Final[float] = 273.15

# ---------------------------------------------------------------------------
# Physical constants (single source of truth for the rest of the codebase)
# ---------------------------------------------------------------------------

#: Universal gas constant (J / (mol * K)) -- used by Arrhenius temperature models.
GAS_CONSTANT_R: Final[float] = 8.314462618

#: Standard gravitational acceleration (m / s^2).
GRAVITY: Final[float] = 9.80665

#: Nominal density of seawater (kg / m^3). A representative value; the actual
#: density depends on temperature and salinity and may be refined later.
SEAWATER_DENSITY: Final[float] = 1025.0

#: Nominal density of air at sea level (kg / m^3).
AIR_DENSITY: Final[float] = 1.225


# ---------------------------------------------------------------------------
# Speed
# ---------------------------------------------------------------------------

def knots_to_mps(knots: float) -> float:
    """Convert speed in knots to meters per second."""
    return knots * KNOT_IN_MPS


def mps_to_knots(mps: float) -> float:
    """Convert speed in meters per second to knots."""
    return mps / KNOT_IN_MPS


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def hours_to_seconds(hours: float) -> float:
    """Convert a duration in hours to seconds."""
    return hours * SECONDS_PER_HOUR


def seconds_to_hours(seconds: float) -> float:
    """Convert a duration in seconds to hours."""
    return seconds / SECONDS_PER_HOUR


def years_to_seconds(years: float) -> float:
    """Convert a duration in (Julian) years to seconds."""
    return years * SECONDS_PER_YEAR


def seconds_to_years(seconds: float) -> float:
    """Convert a duration in seconds to (Julian) years."""
    return seconds / SECONDS_PER_YEAR


# ---------------------------------------------------------------------------
# Corrosion rate
# ---------------------------------------------------------------------------

def mm_per_year_to_m_per_s(mm_per_year: float) -> float:
    """Convert a corrosion rate from mm/year to m/s (the internal unit)."""
    return (mm_per_year * 1.0e-3) / SECONDS_PER_YEAR


def m_per_s_to_mm_per_year(m_per_s: float) -> float:
    """Convert a corrosion rate from m/s (internal unit) to mm/year."""
    return (m_per_s * SECONDS_PER_YEAR) * 1.0e3


def m_per_year_to_m_per_s(m_per_year: float) -> float:
    """Convert a corrosion rate from m/year to m/s (the internal unit)."""
    return m_per_year / SECONDS_PER_YEAR


def m_per_s_to_m_per_year(m_per_s: float) -> float:
    """Convert a corrosion rate from m/s (internal unit) to m/year."""
    return m_per_s * SECONDS_PER_YEAR


# ---------------------------------------------------------------------------
# Temperature
# ---------------------------------------------------------------------------

def celsius_to_kelvin(celsius: float) -> float:
    """Convert a temperature from degrees Celsius to kelvin."""
    return celsius + KELVIN_OFFSET


def kelvin_to_celsius(kelvin: float) -> float:
    """Convert a temperature from kelvin to degrees Celsius."""
    return kelvin - KELVIN_OFFSET


# ---------------------------------------------------------------------------
# Angles
# ---------------------------------------------------------------------------

def deg_to_rad(degrees: float) -> float:
    """Convert an angle from degrees to radians."""
    return degrees * (math.pi / 180.0)


def rad_to_deg(radians: float) -> float:
    """Convert an angle from radians to degrees."""
    return radians * (180.0 / math.pi)


__all__ = [
    # constants
    "KNOT_IN_MPS",
    "SECONDS_PER_HOUR",
    "DAYS_PER_YEAR",
    "SECONDS_PER_YEAR",
    "KELVIN_OFFSET",
    "GAS_CONSTANT_R",
    "GRAVITY",
    "SEAWATER_DENSITY",
    "AIR_DENSITY",
    # speed
    "knots_to_mps",
    "mps_to_knots",
    # time
    "hours_to_seconds",
    "seconds_to_hours",
    "years_to_seconds",
    "seconds_to_years",
    # corrosion rate
    "mm_per_year_to_m_per_s",
    "m_per_s_to_mm_per_year",
    "m_per_year_to_m_per_s",
    "m_per_s_to_m_per_year",
    # temperature
    "celsius_to_kelvin",
    "kelvin_to_celsius",
    # angles
    "deg_to_rad",
    "rad_to_deg",
]
