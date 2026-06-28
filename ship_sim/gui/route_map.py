"""Pure helpers for the interactive route map (no Streamlit dependency).

The Route tab draws a fixed **100 mi x 100 mi** square as a flat canvas: blue
ocean, a white path connecting draggable waypoints, and (optionally) the ocean
shaded by an environmental metric (dissolved O2, temperature, wind, etc.). This
module holds the dependency-light, testable pieces:

- :class:`RouteFrame` -- pixel <-> latitude/longitude mapping for the square.
- :func:`path_distance_miles` -- great-circle path length.
- :func:`cumulative_times_s` -- waypoint timestamps from a constant speed.
- :func:`sample_metric_grid` -- sample a provider metric over the square (this
  only *calls* the existing providers; it contains no physics).
- :func:`render_background` -- build the ocean / heatmap + white-path PNG (PIL).
- fabric.js helpers to seed / read the draggable points on the canvas.

Pixel convention: x increases west->east (lon), y increases north->south (lat),
so the image's top edge is north. Quantities are SI except where noted (miles
are used for the human-facing square size and distance readout).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..models.results import GeoPosition

_EARTH_RADIUS_MI = 3958.7615
# Exact mean miles per degree of latitude (keeps the frame mapping consistent
# with the haversine distance used for the on-screen distance readout).
MILES_PER_DEG_LAT = math.pi * _EARTH_RADIUS_MI / 180.0  # ~= 69.10


# ---------------------------------------------------------------------------
# Metric registry (which provider field to sample, and its display color)
# ---------------------------------------------------------------------------

# name -> (provider kind, attribute, strong RGB color, unit)
_METRICS: Dict[str, Tuple[str, str, Tuple[int, int, int], str]] = {
    "Dissolved O2": ("env", "dissolved_oxygen_mg_l", (40, 160, 70), "mg/L"),
    "Water temperature": ("env", "water_temperature_c", (200, 50, 40), "°C"),
    "Salinity": ("env", "salinity_ppt", (20, 150, 150), "ppt"),
    "pH": ("env", "pH", (150, 80, 180), ""),
    "Pollution": ("env", "pollution_factor_0_1", (120, 90, 40), "0-1"),
    "Wind speed": ("weather", "wind_speed_m_s", (110, 70, 180), "m/s"),
    "Storm intensity": ("weather", "storm_intensity_0_1", (220, 100, 30), "0-1"),
    "Wave height": ("wave", "significant_wave_height_m", (30, 110, 200), "m"),
}

OCEAN_BLUE = (30, 90, 160)
PATH_WHITE = (255, 255, 255)


def metric_options() -> List[str]:
    """Available ocean-coloring metrics (plus the plain-ocean option)."""
    return ["None (plain ocean)"] + list(_METRICS)


def metric_unit(name: str) -> str:
    return _METRICS[name][3] if name in _METRICS else ""


def is_metric(name: str) -> bool:
    """True if ``name`` is a real ocean-coloring metric (not the plain-ocean option)."""
    return name in _METRICS


# ---------------------------------------------------------------------------
# Pixel <-> geographic mapping
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RouteFrame:
    """A square geographic window mapped onto a pixel canvas.

    Centered at (``center_lat``, ``center_lon``), ``size_miles`` on a side,
    rendered at ``width_px`` x ``height_px``.
    """

    center_lat: float
    center_lon: float
    size_miles: float = 100.0
    width_px: int = 640
    height_px: int = 640

    @property
    def miles_per_deg_lon(self) -> float:
        return MILES_PER_DEG_LAT * max(1e-6, math.cos(math.radians(self.center_lat)))

    def lonlat_to_px(self, lat: float, lon: float) -> Tuple[float, float]:
        east_mi = (lon - self.center_lon) * self.miles_per_deg_lon
        north_mi = (lat - self.center_lat) * MILES_PER_DEG_LAT
        x = (east_mi / self.size_miles + 0.5) * self.width_px
        y = (0.5 - north_mi / self.size_miles) * self.height_px
        return x, y

    def px_to_lonlat(self, x: float, y: float) -> Tuple[float, float]:
        east_mi = (x / self.width_px - 0.5) * self.size_miles
        north_mi = (0.5 - y / self.height_px) * self.size_miles
        lat = self.center_lat + north_mi / MILES_PER_DEG_LAT
        lon = self.center_lon + east_mi / self.miles_per_deg_lon
        return lat, lon


def frame_for_waypoints(
    latlon: List[Tuple[float, float]],
    size_miles: float = 100.0,
    width_px: int = 640,
    height_px: int = 640,
    default: Tuple[float, float] = (25.0, -40.0),
) -> RouteFrame:
    """Build a frame centered on the mean of the given waypoints (or a default)."""
    if latlon:
        clat = sum(p[0] for p in latlon) / len(latlon)
        clon = sum(p[1] for p in latlon) / len(latlon)
    else:
        clat, clon = default
    return RouteFrame(clat, clon, size_miles, width_px, height_px)


# ---------------------------------------------------------------------------
# Distance / timing
# ---------------------------------------------------------------------------

def _haversine_mi(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2.0 * _EARTH_RADIUS_MI * math.asin(min(1.0, math.sqrt(h)))


def segment_distances_miles(latlon: List[Tuple[float, float]]) -> List[float]:
    """Per-leg great-circle distances (miles); length = len(latlon) - 1."""
    return [_haversine_mi(latlon[i], latlon[i + 1]) for i in range(len(latlon) - 1)]


def path_distance_miles(latlon: List[Tuple[float, float]]) -> float:
    """Total great-circle path length in miles."""
    return float(sum(segment_distances_miles(latlon)))


def cumulative_times_s(latlon: List[Tuple[float, float]], speed_m_s: float) -> List[float]:
    """Waypoint timestamps (s) from a constant speed along the path.

    The first waypoint is t=0; each subsequent time adds leg_distance / speed.
    """
    if speed_m_s <= 0:
        raise ValueError("speed_m_s must be positive.")
    times = [0.0]
    for d_mi in segment_distances_miles(latlon):
        times.append(times[-1] + (d_mi * 1609.34) / speed_m_s)
    return times


# ---------------------------------------------------------------------------
# Metric sampling over the square (calls providers only -- no physics here)
# ---------------------------------------------------------------------------

def sample_metric_grid(
    metric: str,
    env_provider: Any,
    weather_provider: Any,
    wave_provider: Any,
    frame: RouteFrame,
    time_s: float,
    n: int = 40,
) -> np.ndarray:
    """Sample ``metric`` on an ``n x n`` grid over the square at ``time_s``.

    Returns an ``(n, n)`` array with row 0 = north edge, col 0 = west edge.
    Raises ``KeyError`` for an unknown metric.
    """
    kind, attr, _rgb, _unit = _METRICS[metric]
    grid = np.empty((n, n), dtype=float)
    for i in range(n):  # north -> south
        y = (i + 0.5) / n * frame.height_px
        for j in range(n):  # west -> east
            x = (j + 0.5) / n * frame.width_px
            lat, lon = frame.px_to_lonlat(x, y)
            pos = GeoPosition(latitude_deg=_clip_lat(lat), longitude_deg=_wrap_lon(lon))
            if kind == "env":
                obj = env_provider.at(pos, time_s)
            elif kind == "weather":
                obj = weather_provider.at(pos, time_s)
            else:  # wave (needs weather)
                obj = wave_provider.at(pos, time_s, weather_provider.at(pos, time_s))
            grid[i, j] = getattr(obj, attr)
    return grid


def _clip_lat(lat: float) -> float:
    return max(-89.999, min(89.999, lat))


def _wrap_lon(lon: float) -> float:
    return ((lon + 180.0) % 360.0) - 180.0


# ---------------------------------------------------------------------------
# Background image (ocean / heatmap + white path)
# ---------------------------------------------------------------------------

def render_background(
    frame: RouteFrame,
    *,
    metric: str = "None (plain ocean)",
    grid: Optional[np.ndarray] = None,
    path_px: Optional[List[Tuple[float, float]]] = None,
):
    """Render the ocean (or metric heatmap) with the white path as a PIL image.

    If ``grid`` is given (and ``metric`` is a real metric) the ocean is shaded
    from pale to the metric's color by normalized strength; otherwise it is solid
    ocean blue. The path is drawn as a white polyline with point markers.
    """
    from PIL import Image, ImageDraw  # local import; Pillow ships with the GUI extra

    w, h = frame.width_px, frame.height_px

    if grid is not None and metric in _METRICS:
        rgb_strong = np.array(_METRICS[metric][2], dtype=float)
        finite = np.isfinite(grid)
        lo = float(np.min(grid[finite])) if finite.any() else 0.0
        hi = float(np.max(grid[finite])) if finite.any() else 1.0
        span = hi - lo
        norm = (grid - lo) / span if span > 1e-12 else np.full_like(grid, 0.5)
        norm = np.clip(norm, 0.0, 1.0)
        pale = np.array([235.0, 242.0, 248.0])
        small = pale[None, None, :] + norm[:, :, None] * (rgb_strong - pale)[None, None, :]
        img = Image.fromarray(small.astype(np.uint8), mode="RGB").resize(
            (w, h), Image.BILINEAR
        )
    else:
        img = Image.new("RGB", (w, h), OCEAN_BLUE)

    if path_px:
        draw = ImageDraw.Draw(img)
        if len(path_px) >= 2:
            draw.line([tuple(p) for p in path_px], fill=PATH_WHITE, width=3, joint="curve")
        for (px, py) in path_px:
            r = 5
            draw.ellipse([px - r, py - r, px + r, py + r], fill=PATH_WHITE,
                         outline=(0, 0, 0))
    return img


# ---------------------------------------------------------------------------
# fabric.js (drawable-canvas) point helpers
# ---------------------------------------------------------------------------

def make_initial_drawing(
    points_px: List[Tuple[float, float]], radius: int = 7
) -> Dict[str, Any]:
    """Build a fabric.js drawing dict seeding draggable point circles."""
    objects = []
    for (cx, cy) in points_px:
        objects.append({
            "type": "circle",
            "left": cx - radius,
            "top": cy - radius,
            "radius": radius,
            "fill": "rgba(255,80,80,0.9)",
            "stroke": "#000000",
            "strokeWidth": 1,
            "originX": "left",
            "originY": "top",
            "scaleX": 1,
            "scaleY": 1,
            "angle": 0,
        })
    return {"version": "4.4.0", "objects": objects}


def parse_points_px(
    json_data: Optional[Dict[str, Any]], radius: int = 7
) -> List[Tuple[float, float]]:
    """Read draggable point centers (px) from drawable-canvas JSON, in order.

    Handles circles whose ``left``/``top`` are the bounding-box corner (fabric
    default), accounting for any scaling applied while dragging.
    """
    if not json_data:
        return []
    pts: List[Tuple[float, float]] = []
    for obj in json_data.get("objects", []):
        if obj.get("type") != "circle":
            continue
        r = obj.get("radius", radius)
        cx = obj.get("left", 0.0) + r * obj.get("scaleX", 1.0)
        cy = obj.get("top", 0.0) + r * obj.get("scaleY", 1.0)
        pts.append((float(cx), float(cy)))
    return pts


__all__ = [
    "RouteFrame",
    "frame_for_waypoints",
    "metric_options",
    "metric_unit",
    "is_metric",
    "segment_distances_miles",
    "path_distance_miles",
    "cumulative_times_s",
    "sample_metric_grid",
    "render_background",
    "make_initial_drawing",
    "parse_points_px",
    "OCEAN_BLUE",
    "PATH_WHITE",
]
