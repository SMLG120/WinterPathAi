"""Whole API on PostGIS backends (agent's own DB, wp schema from Data agent's migration 0001).

Loads the REAL pilot_mini fixture into wp.node/wp.edge, exercises every DB-backed path, and
deletes exactly the rows it created. Skipped (with reason) when the DB/schema is unavailable or
wp.edge already holds data.
"""

from __future__ import annotations

import os
import sys

import pytest
from api_testlib import ADMIN_TOKEN, PILOT_MINI, REPO, validate_response

sys.path.append(str(REPO / "services" / "routing" / "tests"))
from routing_testlib import (
    delete_pilot_mini_from_postgis,
    load_pilot_mini_into_postgis,
)


def _skip_reason() -> str | None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        return "DATABASE_URL not set"
    if not (PILOT_MINI / "edges.geojson").exists():
        return "data/fixtures/pilot_mini not present"
    try:
        from sqlalchemy import create_engine, text

        with create_engine(url, connect_args={"connect_timeout": 2}).connect() as c:
            if not c.execute(text("SELECT to_regclass('wp.edge') IS NOT NULL")).scalar():
                return "wp schema absent (Data agent migrations not applied)"
            if c.execute(text("SELECT count(*) FROM wp.edge")).scalar():
                return "wp.edge already has rows; refusing to modify existing data"
    except Exception as exc:
        return f"PostGIS unreachable ({type(exc).__name__})"
    return None


REASON = _skip_reason()
CREATED_REPORT_IDS: list[str] = []
pytestmark = pytest.mark.skipif(REASON is not None, reason=REASON or "")


@pytest.fixture(scope="module")
def db():
    from sqlalchemy import create_engine

    eng = create_engine(os.environ["DATABASE_URL"])
    with eng.begin() as c:
        load_pilot_mini_into_postgis(c)
    yield eng
    from sqlalchemy import text

    with eng.begin() as c:
        # Delete by id: reporter deletion scrubs the description, so match on what we created.
        c.execute(
            text("DELETE FROM wp.community_report WHERE report_id::text = ANY(:ids)"),
            {"ids": CREATED_REPORT_IDS},
        )
        c.execute(text("DELETE FROM wp.pilot_request WHERE organization = 'IT Org (test)'"))
        delete_pilot_mini_from_postgis(c)


@pytest.fixture
def pg(make_client, db):
    return make_client(
        graph_source="postgis", store_backend="postgis", database_url=os.environ["DATABASE_URL"]
    )


def test_health_coverage_sources(pg) -> None:
    h = pg.get("/api/v1/health")
    validate_response(h, "/health", "get")
    assert h.json()["checks"]["database"]["status"] == "ok"
    assert h.json()["checks"]["graph"]["status"] == "ok"
    c = pg.get("/api/v1/coverage")
    validate_response(c, "/coverage", "get")
    assert c.json()["graph"]["edge_count"] == 200
    s = pg.get("/api/v1/data-sources")
    validate_response(s, "/data-sources", "get")
    assert "osm" in {x["id"] for x in s.json()}


def test_routes_and_map_from_postgis(pg) -> None:
    body = {
        "origin": {"lon": -73.5765, "lat": 45.5045},
        "destination": {"lon": -73.5745, "lat": 45.5040},
    }
    r = pg.post("/api/v1/routes/compare", json=body)
    validate_response(r, "/routes/compare", "post")
    assert r.status_code == 200
    bbox = "-73.578035,45.503034,-73.573657,45.505518"
    seg = pg.get(f"/api/v1/map/segments?bbox={bbox}&limit=1000")
    validate_response(seg, "/map/segments", "get")
    assert len(seg.json()["features"]) == 200
    hz = pg.get(f"/api/v1/hazards?bbox={bbox}")  # closures / 311 tables queried (empty here)
    validate_response(hz, "/hazards", "get")


def test_report_lifecycle_and_pilot_request_in_postgis(pg) -> None:
    admin = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
    r = pg.post(
        "/api/v1/reports",
        json={
            "category": "ice",
            "location": {"lon": -73.5760, "lat": 45.5043},
            "location_consent": True,
            "description": "integration test",
        },
    )
    assert r.status_code == 201, r.text
    validate_response(r, "/reports", "post")
    rid, token = r.json()["id"], r.json()["deletion_token"]
    CREATED_REPORT_IDS.append(rid)
    lst = pg.get("/api/v1/admin/reports?status=pending", headers=admin)
    validate_response(lst, "/admin/reports", "get")
    assert rid in [i["id"] for i in lst.json()["items"]]
    m = pg.post(
        f"/api/v1/admin/reports/{rid}/moderation", headers=admin, json={"decision": "approve"}
    )
    validate_response(m, "/admin/reports/{reportId}/moderation", "post")
    hz = pg.get("/api/v1/hazards?bbox=-73.578035,45.503034,-73.573657,45.505518")
    assert f"community:{rid}" in [f["id"] for f in hz.json()["features"]]
    assert (
        pg.delete(f"/api/v1/reports/{rid}", headers={"X-Deletion-Token": "x" * 40}).status_code
        == 404
    )
    assert (
        pg.delete(f"/api/v1/reports/{rid}", headers={"X-Deletion-Token": token}).status_code == 204
    )
    p = pg.post(
        "/api/v1/pilot-requests",
        json={
            "organization": "IT Org (test)",
            "contact_email": "it@example.org",
            "segment": "campus",
            "consent": True,
        },
    )
    assert p.status_code == 201
