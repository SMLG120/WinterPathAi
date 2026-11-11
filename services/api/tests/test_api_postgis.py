"""Whole API on PostGIS backends (agent's own DB, wp schema from Data agent's migration 0001).

Loads the REAL pilot_mini fixture into wp.node/wp.edge, exercises every DB-backed path, and
deletes exactly the rows it created. Skipped (with reason) when the DB/schema is unavailable or
wp.edge already holds data.
"""

from __future__ import annotations

import os
import sys

import pytest
from api_testlib import (
    ADMIN_TOKEN,
    PILOT_MINI,
    REPO,
    pilot_bbox_param,
    pilot_center,
    pilot_meta,
    pilot_route_points,
    validate_response,
)

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

        with create_engine(url, connect_args={"connect_timeout": 10}).connect() as c:
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
    o, d = pilot_route_points()
    r = pg.post("/api/v1/routes/compare", json={"origin": o, "destination": d})
    validate_response(r, "/routes/compare", "post")
    assert r.status_code == 200, r.text
    bbox = pilot_bbox_param()
    seg = pg.get(f"/api/v1/map/segments?bbox={bbox}&limit=1000")
    validate_response(seg, "/map/segments", "get")
    assert len(seg.json()["features"]) == pilot_meta()["edge_count"]
    hz = pg.get(f"/api/v1/hazards?bbox={bbox}")  # closures / 311 tables queried (empty here)
    validate_response(hz, "/hazards", "get")


def test_report_lifecycle_and_pilot_request_in_postgis(pg) -> None:
    admin = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
    r = pg.post(
        "/api/v1/reports",
        json={
            "category": "ice",
            "location": dict(zip(("lon", "lat"), pilot_center(), strict=True)),
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
    hz = pg.get(f"/api/v1/hazards?bbox={pilot_bbox_param()}")
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


# ----------------------------------------------------------------------------- closure activity
# data-model v1.4: wp.closure_active_at(c, t) (Data agent migration 0004) is three-valued.
# TEST-RT-* rows are test fixtures in this agent's own DB, deleted afterwards.
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
AT_ISO = "2026-12-15T15:00:00Z"  # Tuesday 10:00 America/Montreal


def _sched(active=True, all_day=True, start=None, end=None, only=None):
    import json

    return json.dumps(
        {
            d: {
                "active": active if (only is None or d == only) else False,
                "all_day": all_day,
                "start": start,
                "end": end,
            }
            for d in DAYS
        }
    )


CLOSURE_CASES = {
    # id: (status, valid_from, valid_to, weekly_schedule json | None, expected active)
    "TEST-RT-active": ("permit_issued", "2026-12-01", "2027-01-01", _sched(), True),
    "TEST-RT-window": (
        "permit_issued",
        "2026-12-01",
        "2027-01-01",
        _sched(all_day=False, start="09:00", end="17:00"),
        True,
    ),
    "TEST-RT-nosched": ("permit_issued", "2026-12-01", "2027-01-01", None, None),
    "TEST-RT-status": ("unknown", "2026-12-01", "2027-01-01", _sched(), None),
    "TEST-RT-weekday": ("permit_issued", "2026-12-01", "2027-01-01", _sched(only="sat"), False),
    "TEST-RT-ended": ("permit_issued", "2026-11-01", "2026-12-01", _sched(), False),
    # valid_to is exclusive (data-model v1.4 `t < valid_to`, migration 0005): ends exactly at t
    "TEST-RT-ends-at-t": ("permit_issued", "2026-12-01", AT_ISO, _sched(), False),
    "TEST-RT-cancel": ("cancelled", "2026-12-01", "2027-01-01", _sched(), False),
    "TEST-RT-evening": (
        "permit_issued",
        "2026-12-01",
        "2027-01-01",
        _sched(all_day=False, start="19:00", end="23:59"),
        False,
    ),
}


@pytest.fixture
def closures(db):
    """Insert closures on demand at a point; always delete TEST-RT-* afterwards."""
    from sqlalchemy import text

    with db.begin() as c:
        inserted_source = c.execute(
            text(
                "INSERT INTO wp.source (source_id, name, publisher, license, license_url,"
                " commercial_use, attribution, url, status) VALUES ('mtl-entraves',"
                " 'Entraves et travaux en cours', 'Ville de Montréal', 'CC BY 4.0',"
                " 'https://creativecommons.org/licenses/by/4.0/', 'allowed_with_conditions',"
                " 'Ville de Montréal (CC BY 4.0)', 'https://donnees.montreal.ca', 'disabled')"
                " ON CONFLICT (source_id) DO NOTHING RETURNING source_id"
            )
        ).first()

    def put(ids, lonlat, blocks=True):
        with db.begin() as c:
            c.execute(text("DELETE FROM wp.closure WHERE closure_id LIKE 'TEST-RT-%'"))
            for cid in ids:
                status, vf, vt, sched, _ = CLOSURE_CASES[cid]
                c.execute(
                    text(
                        "INSERT INTO wp.closure (closure_id, geom, sidewalk_blockedtype,"
                        " blocks_passage, valid_from, valid_to, status, source_id, attrs)"
                        " VALUES (:id, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 'TEST',"
                        " :blocks, CAST(:vf AS timestamptz), CAST(:vt AS timestamptz), :st,"
                        " 'mtl-entraves', CAST(:attrs AS jsonb))"
                    ),
                    {
                        "id": cid,
                        "lon": lonlat[0],
                        "lat": lonlat[1],
                        "blocks": blocks,
                        "vf": vf if "T" in vf else vf + "T05:00:00Z",
                        "vt": vt if "T" in vt else vt + "T05:00:00Z",
                        "st": status,
                        "attrs": "{}" if sched is None else '{"weekly_schedule": ' + sched + "}",
                    },
                )

    yield put
    with db.begin() as c:
        c.execute(text("DELETE FROM wp.closure WHERE closure_id LIKE 'TEST-RT-%'"))
        if inserted_source:
            c.execute(text("DELETE FROM wp.source WHERE source_id = 'mtl-entraves'"))


def _midpoint(db, edge_id):
    from sqlalchemy import text

    with db.connect() as c:
        r = c.execute(
            text(
                "SELECT ST_X(p), ST_Y(p) FROM (SELECT ST_LineInterpolatePoint(geom, 0.5) AS p"
                " FROM wp.edge WHERE edge_id = :e) s"
            ),
            {"e": edge_id},
        ).one()
    return float(r[0]), float(r[1])


ROUTE = {
    "origin": pilot_route_points()[0] if (PILOT_MINI / "nodes.geojson").exists() else None,
    "destination": pilot_route_points()[1] if (PILOT_MINI / "nodes.geojson").exists() else None,
    "departure_time": AT_ISO,
}


def test_closure_active_at_three_valued_in_repository(db, closures) -> None:
    from datetime import datetime

    from winterpath_api.repositories.hazards import PostgisHazardRepository
    from winterpath_api.repositories.reports import InMemoryReportRepository

    closures(list(CLOSURE_CASES), pilot_center())
    at = datetime.fromisoformat(AT_ISO.replace("Z", "+00:00"))
    got = {
        h.hazard_id: h
        for h in PostgisHazardRepository(db, InMemoryReportRepository()).list(at)
        if h.hazard_id.startswith("TEST-RT-")
    }
    expected = {cid: v[4] for cid, v in CLOSURE_CASES.items() if v[4] is not False}
    assert {k: h.active for k, h in got.items()} == expected  # false rows are dropped
    assert got["TEST-RT-active"].is_hard_closure
    for cid in ("TEST-RT-nosched", "TEST-RT-status"):
        h = got[cid]
        assert not h.is_hard_closure and h.is_possible_closure
        assert "unknown" in h.evidence.note and "schedule at this time unknown" in h.title_en


def test_unknown_activity_flagged_and_active_excluded_via_api(pg, db, closures) -> None:
    base = pg.post("/api/v1/routes/compare", json=ROUTE)
    assert base.status_code == 200, base.text
    short_ids = base.json()["routes"][0]["edge_ids"]
    target = short_ids[len(short_ids) // 2]
    point = _midpoint(db, target)

    closures(["TEST-RT-nosched"], point)
    r = pg.post("/api/v1/routes/compare", json=ROUTE)
    validate_response(r, "/routes/compare", "post")
    assert r.status_code == 200, r.text
    short = r.json()["routes"][0]
    assert target in short["edge_ids"]  # not excluded …
    assert "TEST-RT-nosched" in short["hazards_on_route"]  # … but flagged
    assert "PASSES_POSSIBLE_CLOSURE" in [x["code"] for x in short["explanation"]]
    assert any("schedule at this time is unknown" in w for w in r.json()["warnings"])
    assert short["generalized_cost_s"] > base.json()["routes"][0]["generalized_cost_s"]

    closures(["TEST-RT-active"], point)
    r = pg.post("/api/v1/routes/compare", json=ROUTE)
    validate_response(r, "/routes/compare", "post")
    if r.status_code == 404:  # removing the edge disconnected the pair: still never relaxed
        assert r.json()["code"] == "NO_ROUTE"
        return
    for route in r.json()["routes"]:
        assert target not in route["edge_ids"]
        assert "EXCLUDES_CONFIRMED_CLOSURE" in [x["code"] for x in route["explanation"]]


# ----------------------------------------------------------------------------- terminal_at
def test_terminal_at_written_and_drives_30_day_purge(db) -> None:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import text

    from winterpath_api.repositories.reports import PostgisReportRepository

    repo = PostgisReportRepository(db)
    now = datetime(2026, 12, 15, 15, 0, tzinfo=UTC)
    kw = dict(
        category="ice",
        lon=-73.5760,
        lat=45.5043,
        description="terminal_at test",
        deletion_token_hash="0" * 64,
        client_hash="test",
    )
    rej = repo.create(**kw, now=now)
    dele = repo.create(**kw, now=now)
    old = repo.create(**kw, now=now - timedelta(days=40))  # expired 72 h after creation
    CREATED_REPORT_IDS.extend(str(r.id) for r in (rej, dele, old))
    repo.moderate(rej.id, "reject", None, now)
    assert repo.delete_own(dele.id, now)
    repo.list(None, 100, None, now)  # triggers expiry on read

    def terminal(rid):
        with db.connect() as c:
            return c.execute(
                text("SELECT status, terminal_at FROM wp.community_report WHERE report_id=:i"),
                {"i": rid},
            ).first()

    assert tuple(terminal(rej.id)) == ("rejected", now)
    assert tuple(terminal(dele.id)) == ("deleted", now)
    assert tuple(terminal(old.id)) == ("expired", old.expires_at)  # time it expired, not "now"

    # (rowcounts are not asserted: other tests' terminal reports in this DB may also qualify)
    repo.purge(now + timedelta(days=29))
    assert terminal(old.id) is None  # 30 days after it expired
    assert terminal(rej.id) is not None and terminal(dele.id) is not None
    repo.purge(now + timedelta(days=30))
    assert terminal(rej.id) is None and terminal(dele.id) is None


# ----------------------------------------------------------------------------- 311 natures (v1.5)
# No migration adds report_311_cell.nature yet, so the v1.5 SQL is exercised on a session TEMP
# table with the v1.5 shape (single-connection engine). TEST cells only; nothing persists.
def test_311_sums_natures_then_applies_floor() -> None:
    from datetime import UTC, date, datetime

    import h3
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import StaticPool

    from winterpath_api.repositories.hazards import PostgisHazardRepository
    from winterpath_api.repositories.reports import InMemoryReportRepository

    eng = create_engine(os.environ["DATABASE_URL"], poolclass=StaticPool)
    a, b, c = (h3.latlng_to_cell(45.5043, -73.5760 + i * 0.003, 9) for i in range(3))
    d = date(2026, 12, 15)
    rows = [
        # cell a: 1 requete + 2 plainte = 3 on one day → shown (floor after summing)
        (a, d, "sidewalk_slippery", "requete", 1),
        (a, d, "sidewalk_slippery", "plainte", 2),
        # cell b: 2 requete + 5 information → 2 public → suppressed (information not counted)
        (b, d, "sidewalk_slippery", "requete", 2),
        (b, d, "sidewalk_slippery", "information", 5),
        # cell c: 2 + 2 on two different days → each day < 3 → suppressed (floor is per day)
        (c, d, "snow_clearing", "requete", 2),
        (c, date(2026, 12, 14), "snow_clearing", "plainte", 2),
    ]
    with eng.begin() as conn:
        conn.execute(
            text(
                "CREATE TEMP TABLE report_311_cell (h3 text, day date, category text,"
                " nature text, n int, PRIMARY KEY (h3, day, category, nature))"
            )
        )
        conn.execute(
            text("INSERT INTO pg_temp.report_311_cell VALUES (:h, :d, :c, :na, :n)"),
            [dict(zip(("h", "d", "c", "na", "n"), r, strict=True)) for r in rows],
        )
    try:
        repo = PostgisHazardRepository(
            eng, InMemoryReportRepository(), report_311_table="pg_temp.report_311_cell"
        )
        at = datetime(2026, 12, 15, 18, tzinfo=UTC)
        got = {h.hazard_id: h for h in repo.list(at) if h.hazard_id.startswith("311:")}
        assert set(got) == {f"311:{a}:sidewalk_slippery"}
        h = got[f"311:{a}:sidewalk_slippery"]
        assert h.report_count == 3
        assert h.evidence.state.value == "unverified_report"
        assert h.title_en == "311 reports: slippery sidewalk"
        assert h.title_fr == "Requêtes 311 : trottoir glissant"
    finally:
        eng.dispose()


def test_311_nature_detection_matches_real_table(db) -> None:
    """The repository uses the v1.5 nature filter exactly when wp.report_311_cell has `nature`
    (migration 0006); the query runs on the real table either way."""
    from datetime import UTC, datetime

    from sqlalchemy import text

    from winterpath_api.repositories.hazards import PostgisHazardRepository
    from winterpath_api.repositories.reports import InMemoryReportRepository

    with db.connect() as c:
        has = c.execute(
            text(
                "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'wp'"
                " AND table_name = 'report_311_cell' AND column_name = 'nature'"
            )
        ).scalar()
    repo = PostgisHazardRepository(db, InMemoryReportRepository())
    repo.list(datetime(2026, 12, 15, 18, tzinfo=UTC))
    assert repo._has_nature is bool(has)


# ------------------------------------------------------------------------- read-only role (v1.7)
def test_report_reads_under_read_only_session(db, make_client) -> None:
    """Production runs wp_api with default_transaction_read_only=on. Reads (get/list, and so
    DELETE /reports/{id}'s token check) must return correct statuses without the expiry UPDATE,
    which a read-only session cannot run; with writes allowed, expiry is still persisted."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import DBAPIError

    from winterpath_api.repositories.reports import PostgisReportRepository

    rw = PostgisReportRepository(db)
    now = datetime(2026, 12, 15, 15, 0, tzinfo=UTC)
    kw = dict(
        category="ice",
        lon=-73.5760,
        lat=45.5043,
        description="read-only test",
        deletion_token_hash="1" * 64,
        client_hash="test",
    )
    old = rw.create(**kw, now=now - timedelta(days=5))  # pending, expired 2 days ago
    fresh = rw.create(**kw, now=now)  # pending, not expired
    CREATED_REPORT_IDS.extend(str(r.id) for r in (old, fresh))

    def stored(rid):
        with db.connect() as c:
            return c.execute(
                text("SELECT status, terminal_at FROM wp.community_report WHERE report_id=:i"),
                {"i": rid},
            ).first()

    ro = create_engine(
        os.environ["DATABASE_URL"],
        connect_args={"options": "-c default_transaction_read_only=on"},
    )
    try:
        with ro.begin() as c:
            assert c.execute(text("SHOW default_transaction_read_only")).scalar() == "on"
        # The session really is read-only: the expiry UPDATE itself fails there.
        with pytest.raises(DBAPIError) as ei, ro.begin() as c:
            rw._expire_sql(c, now)
        assert ei.value.orig.sqlstate == "25006"

        for persist in (True, False):  # tolerated (savepoint) and skipped (writes disabled)
            repo = PostgisReportRepository(ro, persist_expiry=persist)
            assert repo.get(old.id, now).status == "expired"
            assert repo.get(fresh.id, now).status == "pending"
            pending = {r.id for r in repo.list("pending", 1000, None, now)}
            expired = {r.id for r in repo.list("expired", 1000, None, now)}
            assert fresh.id in pending and old.id not in pending
            assert old.id in expired and fresh.id not in expired
            assert tuple(stored(old.id)) == ("pending", None)  # nothing was written

            # API: DELETE's token check reads the report → 404 for a wrong token, not 500.
            c = make_client(reports=repo)
            r = c.delete(f"/api/v1/reports/{old.id}", headers={"X-Deletion-Token": "x" * 43})
            assert r.status_code == 404, r.text
            validate_response(r, "/reports/{reportId}", "delete")
    finally:
        ro.dispose()

    # Writes allowed: unchanged behaviour — the read persists expiry with terminal_at.
    assert rw.get(old.id, now).status == "expired"
    assert tuple(stored(old.id)) == ("expired", old.expires_at)
    assert tuple(stored(fresh.id)) == ("pending", None)
