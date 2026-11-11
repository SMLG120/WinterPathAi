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


ADMIN_REPORT = "/admin/reports/6f1c1f1e-8f4e-4d8a-9a51-0c1d2e3f4a5b/moderation"


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("GET", "/admin/reports", {"params": {"status": "bogus"}}),
        ("GET", "/admin/reports", {"params": {"limit": "0"}}),
        ("POST", ADMIN_REPORT, {"json": {"decision": "delete-everything"}}),
        ("POST", "/admin/reports/not-a-uuid/moderation", {"json": {"decision": "approve"}}),
    ],
)
def test_admin_invalid_input_rejected_when_authorized(client, target, method, path, kwargs) -> None:
    """Contract v1.1.0 (CR-PLAT-1): authorized but invalid admin input → declared 400/422."""
    if not target.admin_token:
        pytest.skip("API_ADMIN_TOKEN not set: cannot exercise authorized admin validation")
    r = client.request(method, path, headers={"Authorization": f"Bearer {target.admin_token}"}, **kwargs)
    assert r.status_code in (400, 422), r.text
    assert r.json()["code"] == "VALIDATION_ERROR"


# Optional properties the contract declares as plain (non-nullable) strings. An explicit JSON
# `null` is schema-invalid and must be rejected, not treated as "absent". Found by Schemathesis
# at CONTRACT_MAX_EXAMPLES=150 against the merged real API (integration/winterpath 2d37f32);
# this deterministic check stops it depending on random generation.
PILOT_BASE = {"organization": "x", "contact_email": "a@example.org", "segment": "other", "consent": True}
REPORT_BASE = {
    "category": "other",
    "location": {"lon": -73.575, "lat": 45.505},  # pilot bbox centre, 3 dp (not a user location)
    "location_consent": True,
}


@pytest.mark.parametrize(
    ("path", "base", "field"),
    [
        ("/pilot-requests", PILOT_BASE, "contact_name"),
        ("/pilot-requests", PILOT_BASE, "message"),
        ("/pilot-requests", PILOT_BASE, "locale"),
        ("/reports", REPORT_BASE, "description"),
        ("/reports", REPORT_BASE, "locale"),
    ],
)
def test_explicit_null_rejected_for_non_nullable_optional(client, path, base, field) -> None:
    r = client.post(path, json={**base, field: None})
    assert r.status_code in (400, 422), f"{path} {field}=null -> {r.status_code}"
    assert r.json()["code"] == "VALIDATION_ERROR"
