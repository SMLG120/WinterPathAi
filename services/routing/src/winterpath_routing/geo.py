"""Geometry helpers. Wire CRS EPSG:4326 ``(lon, lat)``; metric work in EPSG:32188."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, Point, shape
from shapely.geometry.base import BaseGeometry

WGS84 = "EPSG:4326"
METRIC_CRS = "EPSG:32188"  # NAD83 / MTM zone 8

_TO_METRIC = Transformer.from_crs(WGS84, METRIC_CRS, always_xy=True)
_TO_WGS84 = Transformer.from_crs(METRIC_CRS, WGS84, always_xy=True)

EARTH_RADIUS_M = 6_371_008.8


def warm_thread() -> None:
    """Initialise this thread's pyproj transformers.

    pyproj creates a transformer per thread on first use, which costs tens of milliseconds
    (it opens proj.db). Call this from a worker-pool initializer so requests never pay it.
    """
    _TO_METRIC.transform(-73.57, 45.50)
    _TO_WGS84.transform(300_000.0, 5_040_000.0)


def to_metric_xy(lon: float, lat: float) -> tuple[float, float]:
    x, y = _TO_METRIC.transform(lon, lat)
    return float(x), float(y)


def to_wgs84_lonlat(x: float, y: float) -> tuple[float, float]:
    lon, lat = _TO_WGS84.transform(x, y)
    return float(lon), float(lat)


def line_to_metric(coords: Sequence[tuple[float, float]]) -> LineString:
    xs, ys = _TO_METRIC.transform([c[0] for c in coords], [c[1] for c in coords])
    return LineString(list(zip(xs, ys, strict=True)))


def line_to_wgs84(line: LineString) -> list[tuple[float, float]]:
    xs, ys = line.xy
    lons, lats = _TO_WGS84.transform(list(xs), list(ys))
    return [(float(a), float(b)) for a, b in zip(lons, lats, strict=True)]


def geojson_to_metric(geom: dict) -> BaseGeometry:
    def _xy(coords):
        xs, ys = _TO_METRIC.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([xs, ys])

    return shapely.transform(shape(geom), _xy)


def point_to_metric(lon: float, lat: float) -> Point:
    return Point(*to_metric_xy(lon, lat))


def metric_length_m(coords: Sequence[tuple[float, float]]) -> float:
    return float(line_to_metric(coords).length)


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def bearing_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Planar bearing (0 = grid north, clockwise) between two EPSG:32188 points."""
    return (math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) + 360.0) % 360.0


def turn_angle_deg(prev_bearing: float, next_bearing: float) -> float:
    """Signed turn in (-180, 180]; positive = right turn."""
    d = (next_bearing - prev_bearing + 540.0) % 360.0 - 180.0
    return 180.0 if d == -180.0 else d


def dedupe_consecutive(coords: Iterable[tuple[float, float]], eps: float = 1e-9) -> list:
    out: list[tuple[float, float]] = []
    for c in coords:
        if out and abs(out[-1][0] - c[0]) < eps and abs(out[-1][1] - c[1]) < eps:
            continue
        out.append(c)
    return out
