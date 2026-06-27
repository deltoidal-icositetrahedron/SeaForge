"""Tests for Waypoint / Trajectory models and time-ordering validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ship_sim.models import Trajectory, Waypoint
from ship_sim.units import hours_to_seconds, knots_to_mps


def wp(lat, lon, t_s, speed_mps):
    return Waypoint(
        latitude_deg=lat, longitude_deg=lon, time_s=t_s, target_speed_m_s=speed_mps
    )


def test_valid_trajectory_and_duration():
    traj = Trajectory(
        waypoints=[
            wp(36.0, -5.0, 0.0, knots_to_mps(12.0)),
            wp(36.5, -6.0, hours_to_seconds(10.0), knots_to_mps(12.0)),
            wp(37.0, -7.0, hours_to_seconds(20.0), knots_to_mps(10.0)),
        ]
    )
    assert len(traj.waypoints) == 3
    assert traj.duration_s == pytest.approx(hours_to_seconds(20.0))


def test_trajectory_requires_two_waypoints():
    with pytest.raises(ValidationError):
        Trajectory(waypoints=[wp(0.0, 0.0, 0.0, 5.0)])


def test_trajectory_rejects_non_increasing_times():
    with pytest.raises(ValidationError):
        Trajectory(
            waypoints=[
                wp(0.0, 0.0, 0.0, 5.0),
                wp(1.0, 1.0, 100.0, 5.0),
                wp(2.0, 2.0, 100.0, 5.0),  # equal time => not strictly increasing
            ]
        )


def test_trajectory_rejects_decreasing_times():
    with pytest.raises(ValidationError):
        Trajectory(
            waypoints=[
                wp(0.0, 0.0, 200.0, 5.0),
                wp(1.0, 1.0, 100.0, 5.0),
            ]
        )


def test_waypoint_rejects_negative_speed():
    with pytest.raises(ValidationError):
        wp(0.0, 0.0, 0.0, -1.0)


def test_waypoint_rejects_out_of_range_latitude():
    with pytest.raises(ValidationError):
        wp(120.0, 0.0, 0.0, 5.0)
