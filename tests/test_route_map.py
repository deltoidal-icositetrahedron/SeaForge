"""Tests for the interactive route-map helpers (no Streamlit needed)."""

from __future__ import annotations

import numpy as np
import pytest

from ship_sim.gui import route_map as rm
from ship_sim.generation.procedural import (
    ProceduralEnvironmentProvider,
    ProceduralWaveProvider,
    ProceduralWeatherProvider,
)


def test_frame_pixel_geo_roundtrip():
    frame = rm.RouteFrame(center_lat=25.0, center_lon=-40.0, size_miles=100.0,
                          width_px=640, height_px=640)
    for x, y in [(0, 0), (320, 320), (640, 640), (100, 500)]:
        lat, lon = frame.px_to_lonlat(x, y)
        x2, y2 = frame.lonlat_to_px(lat, lon)
        assert x2 == pytest.approx(x, abs=1e-6)
        assert y2 == pytest.approx(y, abs=1e-6)


def test_frame_orientation():
    frame = rm.RouteFrame(25.0, -40.0)
    # Center maps to image center.
    cx, cy = frame.lonlat_to_px(25.0, -40.0)
    assert cx == pytest.approx(frame.width_px / 2)
    assert cy == pytest.approx(frame.height_px / 2)
    # North (higher lat) is nearer the top (smaller y).
    _, y_north = frame.lonlat_to_px(25.5, -40.0)
    _, y_south = frame.lonlat_to_px(24.5, -40.0)
    assert y_north < y_south
    # East (higher lon) is nearer the right (larger x).
    x_east, _ = frame.lonlat_to_px(25.0, -39.5)
    x_west, _ = frame.lonlat_to_px(25.0, -40.5)
    assert x_east > x_west


def test_square_spans_100_miles():
    frame = rm.RouteFrame(0.0, 0.0, size_miles=100.0)  # equator: simple lon scale
    # Left-to-right edge spans size_miles east-west.
    lat_l, lon_l = frame.px_to_lonlat(0, frame.height_px / 2)
    lat_r, lon_r = frame.px_to_lonlat(frame.width_px, frame.height_px / 2)
    assert rm.path_distance_miles([(lat_l, lon_l), (lat_r, lon_r)]) == pytest.approx(100.0, rel=1e-3)


def test_path_distance_one_degree_lat():
    # 1 degree of latitude is ~69 miles.
    assert rm.path_distance_miles([(0.0, 0.0), (1.0, 0.0)]) == pytest.approx(69.0, rel=0.01)


def test_segment_distances_and_total():
    pts = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    segs = rm.segment_distances_miles(pts)
    assert len(segs) == 2
    assert rm.path_distance_miles(pts) == pytest.approx(sum(segs))


def test_cumulative_times_increase_with_distance():
    pts = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
    times = rm.cumulative_times_s(pts, speed_m_s=5.0)
    assert times[0] == 0.0
    assert times[1] < times[2]
    # Equal legs => equal increments.
    assert times[1] == pytest.approx(times[2] - times[1], rel=1e-6)


def test_cumulative_times_rejects_bad_speed():
    with pytest.raises(ValueError):
        rm.cumulative_times_s([(0.0, 0.0), (1.0, 0.0)], speed_m_s=0.0)


def test_metric_options_and_units():
    opts = rm.metric_options()
    assert opts[0].startswith("None")
    assert "Water temperature" in opts
    assert rm.metric_unit("Water temperature") == "°C"


def test_sample_metric_grid_shape_and_range():
    frame = rm.RouteFrame(25.0, -40.0)
    env = ProceduralEnvironmentProvider(1)
    wx = ProceduralWeatherProvider(1)
    wave = ProceduralWaveProvider(1)
    grid = rm.sample_metric_grid("Water temperature", env, wx, wave, frame, 0.0, n=12)
    assert grid.shape == (12, 12)
    assert np.all(np.isfinite(grid))
    assert grid.min() >= -2.0 and grid.max() <= 40.0


def test_sample_metric_grid_wave_uses_weather():
    frame = rm.RouteFrame(25.0, -40.0)
    env = ProceduralEnvironmentProvider(2)
    wx = ProceduralWeatherProvider(2)
    wave = ProceduralWaveProvider(2)
    grid = rm.sample_metric_grid("Wave height", env, wx, wave, frame, 0.0, n=8)
    assert grid.shape == (8, 8)
    assert np.all(grid >= 0.0)


def test_sample_metric_unknown_raises():
    frame = rm.RouteFrame(25.0, -40.0)
    with pytest.raises(KeyError):
        rm.sample_metric_grid("Nonsense", None, None, None, frame, 0.0, n=4)


def test_fabric_points_roundtrip():
    frame = rm.RouteFrame(25.0, -40.0)
    pts_px = [frame.lonlat_to_px(25.0, -40.0), frame.lonlat_to_px(25.3, -39.8)]
    drawing = rm.make_initial_drawing(pts_px, radius=7)
    assert len(drawing["objects"]) == 2
    parsed = rm.parse_points_px(drawing, radius=7)
    for (a, b) in zip(pts_px, parsed):
        assert a[0] == pytest.approx(b[0], abs=1e-6)
        assert a[1] == pytest.approx(b[1], abs=1e-6)


def test_parse_points_handles_empty():
    assert rm.parse_points_px(None) == []
    assert rm.parse_points_px({"objects": []}) == []


def test_render_background_sizes():
    pytest.importorskip("PIL")
    frame = rm.RouteFrame(25.0, -40.0, width_px=200, height_px=200)
    plain = rm.render_background(frame, path_px=[(10, 10), (190, 190)])
    assert plain.size == (200, 200)
    grid = np.random.default_rng(0).random((10, 10))
    heat = rm.render_background(frame, metric="Water temperature", grid=grid,
                               path_px=[(10, 10), (100, 50), (190, 190)])
    assert heat.size == (200, 200)
