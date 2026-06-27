"""Tests for trajectory interpolation utilities."""

from __future__ import annotations

import pytest

from ship_sim.models import Trajectory, Waypoint
from ship_sim.simulation.timestep import (
    get_time_bounds,
    interpolate_heading,
    interpolate_position,
    interpolate_speed,
)


def make_traj(headings=(None, None, None)) -> Trajectory:
    return Trajectory(
        waypoints=[
            Waypoint(latitude_deg=10.0, longitude_deg=20.0, time_s=0.0,
                     target_speed_m_s=4.0, heading_deg=headings[0]),
            Waypoint(latitude_deg=12.0, longitude_deg=24.0, time_s=100.0,
                     target_speed_m_s=8.0, heading_deg=headings[1]),
            Waypoint(latitude_deg=14.0, longitude_deg=20.0, time_s=200.0,
                     target_speed_m_s=6.0, heading_deg=headings[2]),
        ]
    )


def test_time_bounds():
    assert get_time_bounds(make_traj()) == (0.0, 200.0)


def test_exact_values_at_waypoints():
    traj = make_traj()
    for wp in traj.waypoints:
        pos = interpolate_position(traj, wp.time_s)
        assert pos.latitude_deg == pytest.approx(wp.latitude_deg)
        assert pos.longitude_deg == pytest.approx(wp.longitude_deg)
        assert interpolate_speed(traj, wp.time_s) == pytest.approx(wp.target_speed_m_s)


def test_midpoint_values_at_halfway_time():
    traj = make_traj()
    pos = interpolate_position(traj, 50.0)  # halfway in the first leg
    assert pos.latitude_deg == pytest.approx(11.0)
    assert pos.longitude_deg == pytest.approx(22.0)
    assert interpolate_speed(traj, 50.0) == pytest.approx(6.0)


def test_clamping_outside_bounds():
    traj = make_traj()
    before = interpolate_position(traj, -100.0)
    after = interpolate_position(traj, 9999.0)
    assert before.latitude_deg == pytest.approx(10.0)
    assert after.latitude_deg == pytest.approx(14.0)


def test_speed_never_negative():
    # Even with a fast deceleration to zero, interpolated speed stays >= 0.
    traj = Trajectory(
        waypoints=[
            Waypoint(latitude_deg=0.0, longitude_deg=0.0, time_s=0.0, target_speed_m_s=10.0),
            Waypoint(latitude_deg=1.0, longitude_deg=1.0, time_s=100.0, target_speed_m_s=0.0),
        ]
    )
    for t in range(0, 101, 5):
        assert interpolate_speed(traj, float(t)) >= 0.0


def test_heading_uses_waypoint_values_when_present():
    traj = make_traj(headings=(0.0, 90.0, 90.0))
    assert interpolate_heading(traj, 0.0) == pytest.approx(0.0)
    # Halfway between 0 and 90 deg -> 45 deg (shortest path).
    assert interpolate_heading(traj, 50.0) == pytest.approx(45.0)


def test_heading_falls_back_to_bearing():
    traj = make_traj()  # no headings -> use segment bearing
    h = interpolate_heading(traj, 50.0)
    assert 0.0 <= h < 360.0
    # First leg goes north-east, so bearing should be in the first quadrant.
    assert 0.0 < h < 90.0


def test_heading_angular_wrap_shortest_path():
    traj = Trajectory(
        waypoints=[
            Waypoint(latitude_deg=0.0, longitude_deg=0.0, time_s=0.0,
                     target_speed_m_s=5.0, heading_deg=350.0),
            Waypoint(latitude_deg=1.0, longitude_deg=0.0, time_s=100.0,
                     target_speed_m_s=5.0, heading_deg=10.0),
        ]
    )
    # 350 -> 10 should pass through 0, i.e. midpoint = 0 deg, not 180.
    assert interpolate_heading(traj, 50.0) == pytest.approx(0.0)
