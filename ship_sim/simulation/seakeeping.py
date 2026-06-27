"""Wave-encounter kinematics (a small, transparent seakeeping helper).

This module computes the quantities a ship "feels" from a seaway given its
speed and heading relative to the waves:

- the **relative heading** between the ship and the wave propagation direction,
- the **encounter frequency / period** (the Doppler-shifted wave period the
  hull actually experiences), and
- the **wave steepness** (a key danger indicator).

Conventions
-----------
- Wave direction (``mean_wave_direction_deg``) is the direction the waves
  *travel toward*; ship heading is the direction the ship *points toward*.
- The relative heading ``mu`` is ``(wave_dir - heading) mod 360``:
  ``0`` = following seas, ``180`` = head seas, ``90``/``270`` = beam seas.
- Deep-water dispersion is assumed: ``omega^2 = g*k`` so the wavelength is
  ``L = g*T^2/(2*pi)``. This is accurate for typical open-ocean conditions but
  not for shallow water (a documented simplification).

This is NOT a substitute for a proper seakeeping / strip-theory or CFD analysis,
model-basin testing, or classification-society rules. It is a simplified,
physically interpretable approximation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

from ..models.waves import WaveCondition
from ..units import GRAVITY

# Heading assumed when none is provided: beam seas (90 deg), the conservative
# case for wave-excited rolling.
_DEFAULT_RELATIVE_HEADING_DEG = 90.0


@dataclass(frozen=True)
class WaveEncounterEstimate:
    """Kinematics of how a ship encounters a given sea state."""

    relative_heading_deg: float
    encounter_frequency_rad_s: float
    encounter_period_s: float
    wave_steepness: float
    assumptions: List[str] = field(default_factory=list)


def estimate_wave_encounter(
    ship_speed_m_s: float,
    ship_heading_deg: Optional[float],
    wave: WaveCondition,
) -> WaveEncounterEstimate:
    """Compute encounter frequency/period, relative heading, and wave steepness.

    Parameters
    ----------
    ship_speed_m_s:
        Ship speed over ground (m/s).
    ship_heading_deg:
        Ship heading (deg from true north), or ``None`` to assume beam seas.
    wave:
        The sea state (uses ``peak_period_s``, ``significant_wave_height_m``,
        and ``mean_wave_direction_deg``).

    Returns
    -------
    WaveEncounterEstimate
    """
    assumptions: List[str] = [
        "Deep-water dispersion (omega^2 = g*k); not valid in shallow water.",
        "Single peak period/direction represents the sea state (no spreading).",
    ]

    if ship_heading_deg is None:
        mu_deg = _DEFAULT_RELATIVE_HEADING_DEG
        assumptions.append("Heading unknown: assumed beam seas (mu = 90 deg).")
    else:
        mu_deg = (wave.mean_wave_direction_deg - ship_heading_deg) % 360.0
    mu_rad = math.radians(mu_deg)

    # Absolute wave angular frequency and (deep-water) wavenumber.
    omega = 2.0 * math.pi / wave.peak_period_s
    k = omega * omega / GRAVITY

    # Encounter frequency: omega_e = omega - k*U*cos(mu).
    #   following seas (mu=0):  omega_e = omega - k*U   (slower encounters)
    #   head seas    (mu=180):  omega_e = omega + k*U   (faster encounters)
    omega_e = omega - k * ship_speed_m_s * math.cos(mu_rad)

    # Encounter period; guard the near-zero crossing (ship "surfing" the wave).
    if abs(omega_e) < 1.0e-6:
        encounter_period = math.inf
        assumptions.append(
            "Encounter frequency ~ 0 (ship matching wave celerity); period -> inf."
        )
    else:
        encounter_period = 2.0 * math.pi / abs(omega_e)

    # Wave steepness Hs/L with L = g*Tp^2/(2*pi)  ->  steepness = 2*pi*Hs/(g*Tp^2).
    wavelength = GRAVITY * wave.peak_period_s ** 2 / (2.0 * math.pi)
    wave_steepness = (
        wave.significant_wave_height_m / wavelength if wavelength > 0 else 0.0
    )

    return WaveEncounterEstimate(
        relative_heading_deg=mu_deg,
        encounter_frequency_rad_s=omega_e,
        encounter_period_s=encounter_period,
        wave_steepness=wave_steepness,
        assumptions=assumptions,
    )


__all__ = ["WaveEncounterEstimate", "estimate_wave_encounter"]
