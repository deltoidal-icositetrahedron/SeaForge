"""Trajectory interpolation utilities.

Helpers to query a :class:`~ship_sim.models.trajectory.Trajectory` at an
arbitrary time: position, speed, and heading. The (later) engine uses these to
march along a route; they are kept here, self-contained and independent of the
engine, so they can be tested in isolation.

Interpolation is **linear between waypoints**. For latitude/longitude this is an
acceptable approximation for short legs but is *not* great-circle accurate -- on
long routes a great-circle (slerp on the sphere) interpolation would be more
correct, and longitude wrap-around near +/-180 deg is not handled here. These
simplifications are intentional for this phase and documented.

Queries outside the trajectory's time span are clamped to the first/last
waypoint (documented), so the engine never raises at the exact end time.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from typing import Tuple

from ..models.results import GeoPosition
from ..models.trajectory import Trajectory, Waypoint


def get_time_bounds(trajectory: Trajectory) -> Tuple[float, float]:
    """Return ``(start_time_s, end_time_s)`` for the trajectory."""
    return trajectory.waypoints[0].time_s, trajectory.waypoints[-1].time_s


def _bracket(trajectory: Trajectory, time_s: float) -> Tuple[Waypoint, Waypoint, float]:
    """Return the two waypoints bracketing ``time_s`` and the interpolation fraction.

    Clamps to the endpoints outside the time span. The fraction is 0 at the
    earlier waypoint and 1 at the later one. When clamped, both returned
    waypoints are identical.
    """
    wps = trajectory.waypoints
    times = [wp.time_s for wp in wps]

    if time_s <= times[0]:
        return wps[0], wps[0], 0.0
    if time_s >= times[-1]:
        return wps[-1], wps[-1], 1.0

    i = bisect_right(times, time_s) - 1
    a, b = wps[i], wps[i + 1]
    frac = (time_s - a.time_s) / (b.time_s - a.time_s)
    return a, b, frac


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing (deg, 0-360) from point 1 to point 2."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
    return math.degrees(math.atan2(y, x)) % 360.0


def _interp_angle_deg(a_deg: float, b_deg: float, frac: float) -> float:
    """Interpolate between two headings along the shortest angular path."""
    diff = ((b_deg - a_deg + 180.0) % 360.0) - 180.0
    return (a_deg + frac * diff) % 360.0


def interpolate_position(trajectory: Trajectory, time_s: float) -> GeoPosition:
    """Linearly interpolate latitude/longitude at ``time_s``.

    NOTE: linear lat/lon interpolation; great-circle would be more accurate for
    long legs and +/-180 deg longitude wrap is not handled.
    """
    a, b, frac = _bracket(trajectory, time_s)
    lat = a.latitude_deg + frac * (b.latitude_deg - a.latitude_deg)
    lon = a.longitude_deg + frac * (b.longitude_deg - a.longitude_deg)
    return GeoPosition(latitude_deg=lat, longitude_deg=lon)


def interpolate_speed(trajectory: Trajectory, time_s: float) -> float:
    """Linearly interpolate the target speed (m/s) at ``time_s`` (never negative)."""
    a, b, frac = _bracket(trajectory, time_s)
    speed = a.target_speed_m_s + frac * (b.target_speed_m_s - a.target_speed_m_s)
    return max(0.0, speed)


def interpolate_heading(trajectory: Trajectory, time_s: float) -> float:
    """Interpolate the heading (deg, 0-360) at ``time_s``.

    Uses the waypoints' ``heading_deg`` when available (shortest-path angular
    interpolation); otherwise falls back to the great-circle bearing of the
    bracketing segment.
    """
    a, b, frac = _bracket(trajectory, time_s)

    if a is b:  # clamped to an endpoint
        if a.heading_deg is not None:
            return a.heading_deg
        # Derive from an adjacent segment if possible.
        wps = trajectory.waypoints
        idx = wps.index(a)
        if idx == 0 and len(wps) > 1:
            nxt = wps[1]
            return _bearing_deg(a.latitude_deg, a.longitude_deg,
                                nxt.latitude_deg, nxt.longitude_deg)
        prev = wps[idx - 1]
        return _bearing_deg(prev.latitude_deg, prev.longitude_deg,
                            a.latitude_deg, a.longitude_deg)

    if a.heading_deg is not None and b.heading_deg is not None:
        return _interp_angle_deg(a.heading_deg, b.heading_deg, frac)
    if a.heading_deg is not None:
        return a.heading_deg
    return _bearing_deg(a.latitude_deg, a.longitude_deg, b.latitude_deg, b.longitude_deg)


__all__ = [
    "get_time_bounds",
    "interpolate_position",
    "interpolate_speed",
    "interpolate_heading",
]
