"""Smoke tests: /health and /coverage respond, conform, and respect contract invariants."""

from __future__ import annotations

import pytest

from stub_server.contract import component_schema, schema_errors

pytestmark = pytest.mark.smoke

PILOT_BBOX = [-73.5880, 45.4960, -73.5620, 45.5130]  # docs/architecture.md §3


def test_health(client) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert schema_errors(component_schema("Health"), body) == []
    assert body["status"] in ("ok", "degraded"), body
    for name, check in body["checks"].items():
        detail = check.get("detail", "")
        assert "postgresql://" not in detail and "Traceback" not in detail, name


def test_health_is_fast(client) -> None:
    r = client.get("/health")
    assert r.elapsed.total_seconds() < 1.0


def test_coverage(client) -> None:
    r = client.get("/coverage")
    assert r.status_code == 200
    body = r.json()
    assert schema_errors(component_schema("Coverage"), body) == []
    assert body["bbox"] == pytest.approx(PILOT_BBOX, abs=1e-6)
    ring = body["area"]["coordinates"][0]
    assert ring[0] == ring[-1], "polygon ring must be closed"
    for lon, lat in ring:  # [lon, lat] order inside the pilot bbox
        assert PILOT_BBOX[0] - 1e-9 <= lon <= PILOT_BBOX[2] + 1e-9
        assert PILOT_BBOX[1] - 1e-9 <= lat <= PILOT_BBOX[3] + 1e-9


def test_route_outside_coverage_is_422(client) -> None:
    r = client.post(
        "/routes/compare",
        json={"origin": {"lon": -73.60, "lat": 45.53}, "destination": {"lon": -73.5698, "lat": 45.5017}},
    )
    assert r.status_code == 422
    assert r.json()["code"] == "OUTSIDE_COVERAGE"


def test_bbox_too_large_is_422(client) -> None:
    r = client.get("/map/segments", params={"bbox": "-73.70,45.40,-73.50,45.60"})
    assert r.status_code == 422
    assert r.json()["code"] == "BBOX_TOO_LARGE"


def test_admin_requires_auth(client) -> None:
    r = client.get("/admin/reports")
    assert r.status_code == 401
    assert r.json()["code"] == "UNAUTHORIZED"
