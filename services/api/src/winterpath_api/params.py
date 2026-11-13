"""Bbox validation, coverage checks and opaque pagination cursors."""

from __future__ import annotations

import base64
import json
import re
from typing import Any

from .errors import ApiError
from .settings import MAX_BBOX_AREA_DEG2, PILOT_BBOX

BBOX_RE = re.compile(r"^-?\d+(\.\d+)?,-?\d+(\.\d+)?,-?\d+(\.\d+)?,-?\d+(\.\d+)?$")

Bbox = tuple[float, float, float, float]


def parse_bbox(raw: str | None, coverage: Bbox = PILOT_BBOX) -> Bbox:
    if not raw or not BBOX_RE.match(raw):
        raise ApiError(400, "VALIDATION_ERROR", "bbox must be 'minLon,minLat,maxLon,maxLat'.")
    w, s, e, n = (float(x) for x in raw.split(","))
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise ApiError(
            400, "VALIDATION_ERROR", "bbox bounds invalid (need minLon<maxLon, minLat<maxLat)."
        )
    area = (e - w) * (n - s)
    if area > MAX_BBOX_AREA_DEG2:
        raise ApiError(
            422,
            "BBOX_TOO_LARGE",
            f"bbox area {area:.5f} deg² exceeds {MAX_BBOX_AREA_DEG2} deg².",
            {"max_area_deg2": MAX_BBOX_AREA_DEG2},
        )
    pw, ps, pe, pn = coverage
    if e < pw or w > pe or n < ps or s > pn:
        raise ApiError(
            422,
            "OUTSIDE_COVERAGE",
            "bbox does not intersect the coverage area.",
            {"coverage_bbox": list(coverage)},
        )
    return w, s, e, n


def in_coverage(lon: float, lat: float, coverage: Bbox = PILOT_BBOX) -> bool:
    w, s, e, n = coverage
    return w <= lon <= e and s <= lat <= n


def bbox_intersects(geom: dict[str, Any], bbox: Bbox) -> bool:
    from shapely.geometry import box, shape

    return shape(geom).intersects(box(*bbox))


def encode_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps({"v": 1, **payload}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> dict[str, Any] | None:
    if not cursor:
        return None
    try:
        pad = "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(cursor + pad))
        if not isinstance(data, dict) or data.get("v") != 1:
            raise ValueError
        return data
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid pagination cursor.") from exc


def paginate_by_id(items: list, key, limit: int, cursor: str | None) -> tuple[list, str | None]:
    """Keyset pagination over items sorted by ``key(item)`` (a string)."""
    c = decode_cursor(cursor)
    after = c.get("after") if c else None
    if after is not None and not isinstance(after, str):
        raise ApiError(400, "VALIDATION_ERROR", "Invalid pagination cursor.")
    items = sorted(items, key=key)
    if after is not None:
        items = [i for i in items if key(i) > after]
    page = items[:limit]
    nxt = encode_cursor({"after": key(page[-1])}) if len(items) > limit else None
    return page, nxt
