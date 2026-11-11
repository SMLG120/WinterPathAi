"""Migration + loader tests against the shared PostGIS container (integration-rules §4).

Runs in a throwaway database `wp_data_test_<pid>` (created and dropped here) so `wp_data` is
never touched and parallel runs from other worktrees cannot drop each other's database.
Skipped — not faked — when the server is unreachable.
"""

import os
import subprocess
from pathlib import Path

import psycopg
import pytest

from winterpath_ingestion.config import get_settings  # noqa: F401  (loads .env.local)

pytestmark = pytest.mark.postgis
ROOT = Path(__file__).resolve().parents[3]
TEST_DB = f"wp_data_test_{os.getpid()}"


def _base_url():
    url = os.environ.get("DATABASE_URL", "").replace("postgresql+psycopg://", "postgresql://")
    if not url:
        pytest.skip("DATABASE_URL not set")
    return url


@pytest.fixture(scope="module")
def test_url():
    base = _base_url()
    try:
        admin = psycopg.connect(base, autocommit=True, connect_timeout=5)
    except psycopg.OperationalError as e:
        pytest.skip(f"PostGIS unreachable: {type(e).__name__}")
    admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
    admin.execute(f"CREATE DATABASE {TEST_DB}")
    url = base.rsplit("/", 1)[0] + "/" + TEST_DB
    yield url
    admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    admin.close()


def alembic(url, *args):
    return subprocess.run(
        ["alembic", "-c", str(ROOT / "db" / "alembic.ini"), "-x", f"url={url}", *args],
        capture_output=True,
        text=True,
        check=True,
    )


def wp_tables(url):
    with psycopg.connect(url) as c:
        return sorted(
            r[0]
            for r in c.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='wp'"
            )
        )


EXPECTED_0001 = sorted(
    [
        "source",
        "ingest_run",
        "node",
        "edge",
        "sidewalk_polygon",
        "closure",
        "report_311_cell",
        "weather_obs",
        "community_report",
        "edge_risk",
        "pilot_request",
    ]
)
EXPECTED = sorted([*EXPECTED_0001, "weather_daily"])  # head = 0002 (contract v1.2.0)
V12_EDGE_COLS = {"crossing_type", "crossing_kerb", "highway", "osm_snapshot"}
V12_CLOSURE_COLS = {"attrs", "backsidewalk_blocks_passage"}
# v1.3.0 (migration 0003)
V13_COLS = {("edge", "name"), ("community_report", "terminal_at")}


def active_at_end_exclusive(url) -> bool:
    """True when wp.closure_active_at returns false at exactly t = valid_to (migration 0005)."""
    with psycopg.connect(url) as c:
        src = c.execute(
            "SELECT prosrc FROM pg_proc WHERE oid = "
            "to_regprocedure('wp.closure_active_at(wp.closure,timestamptz)')"
        ).fetchone()[0]
    return "t >= c.valid_to" in src


def report_311_pk(url) -> list[str]:
    with psycopg.connect(url) as c:
        return [
            r[0]
            for r in c.execute(
                "SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid=i.indrelid "
                "AND a.attnum = ANY(i.indkey) WHERE i.indrelid='wp.report_311_cell'::regclass "
                "AND i.indisprimary ORDER BY array_position(i.indkey, a.attnum)"
            )
        ]


V15_PK = ["h3", "day", "category", "nature"]


def has_v14(url) -> bool:
    with psycopg.connect(url) as c:
        fn = c.execute("SELECT to_regprocedure('wp.closure_active_at(wp.closure,timestamptz)')")
        ck = c.execute(
            "SELECT 1 FROM pg_constraint WHERE conname='closure_status_check'"
        ).fetchone()
        return fn.fetchone()[0] is not None and ck is not None


def has_v13(url) -> set[bool]:
    return {col in columns(url, table) for table, col in V13_COLS}


def columns(url, table):
    with psycopg.connect(url) as c:
        return {
            r[0]
            for r in c.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='wp' AND table_name=%s",
                (table,),
            )
        }


def test_migration_up_down_up(test_url):
    alembic(test_url, "upgrade", "head")
    assert wp_tables(test_url) == EXPECTED
    with psycopg.connect(test_url) as c:
        gist = {
            r[0]
            for r in c.execute(
                "SELECT tablename FROM pg_indexes WHERE schemaname='wp' AND indexdef ILIKE '%gist%'"
            )
        }
        assert gist == {"node", "edge", "sidewalk_polygon", "closure", "community_report"}
        grants = {
            r
            for r in c.execute(
                "SELECT grantee, table_name FROM information_schema.role_table_grants "
                "WHERE table_schema='wp' AND privilege_type='SELECT' AND grantee='wp_reader'"
            )
        }
        assert ("wp_reader", "edge") in grants
        assert ("wp_reader", "pilot_request") not in grants
        assert ("wp_reader", "weather_daily") in grants
    assert V12_EDGE_COLS <= columns(test_url, "edge")
    assert V12_CLOSURE_COLS <= columns(test_url, "closure")
    assert has_v13(test_url) == {True}
    assert has_v14(test_url) and active_at_end_exclusive(test_url)
    assert report_311_pk(test_url) == V15_PK
    # one step down: 0006 removed (nature collapsed), 0005 intact
    alembic(test_url, "downgrade", "0005_closure_active_excl_end")
    assert report_311_pk(test_url) == ["h3", "day", "category"]
    assert "nature" not in columns(test_url, "report_311_cell")
    assert active_at_end_exclusive(test_url)
    alembic(test_url, "upgrade", "head")
    assert report_311_pk(test_url) == V15_PK
    # one step down: 0005 → 0004's inclusive body
    alembic(test_url, "downgrade", "0004_closure_status")
    assert has_v14(test_url) and not active_at_end_exclusive(test_url)
    alembic(test_url, "upgrade", "head")
    assert active_at_end_exclusive(test_url)
    # one step down: 0004 removed, v1.3 intact
    alembic(test_url, "downgrade", "0003_contract_v1_3_0")
    assert not has_v14(test_url)
    assert has_v13(test_url) == {True}
    alembic(test_url, "upgrade", "head")
    assert has_v14(test_url)
    # one step down: 0003 removed, v1.2 intact
    alembic(test_url, "downgrade", "0002_contract_v1_2_0")
    assert not has_v14(test_url)
    assert has_v13(test_url) == {False}
    assert V12_EDGE_COLS <= columns(test_url, "edge")
    assert wp_tables(test_url) == EXPECTED
    alembic(test_url, "upgrade", "head")
    assert has_v13(test_url) == {True} and has_v14(test_url)
    # one step down: back to exactly the v1 schema
    alembic(test_url, "downgrade", "0001_wp_schema_v1")
    assert wp_tables(test_url) == EXPECTED_0001
    assert not V12_EDGE_COLS & columns(test_url, "edge")
    assert not V12_CLOSURE_COLS & columns(test_url, "closure")
    alembic(test_url, "upgrade", "head")
    assert wp_tables(test_url) == EXPECTED
    alembic(test_url, "downgrade", "base")
    assert wp_tables(test_url) == []
    alembic(test_url, "upgrade", "head")
    assert wp_tables(test_url) == EXPECTED


def test_constraints_reject_bad_rows(test_url):
    alembic(test_url, "upgrade", "head")
    with psycopg.connect(test_url, autocommit=True) as c:  # each statement independent
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "INSERT INTO wp.edge_risk VALUES ('x', now(), null, 'safe', null, "
                "'confirmed', null)"
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "INSERT INTO wp.weather_daily (station_id, day, snow_on_ground_cm) "
                "VALUES ('x', '2026-01-01', -1)"
            )


# Synthetic schedules (not real permits). Monday 2026-11-16; America/Montreal = UTC-5 in Nov.
_DAY = {"active": True, "all_day": True, "start": None, "end": None}
_WIN = {"active": True, "all_day": False, "start": "09:00", "end": "17:00"}
_OFF = {"active": False, "all_day": False, "start": None, "end": None}


def _sched(mon):
    days = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    return {d: (mon if d == "mon" else _DAY) for d in days}


ACTIVE_CASES = [
    # id, status, valid_from, valid_to, monday schedule, t (UTC), expected
    ("allday", "permit_issued", "2026-11-01", "2026-12-01", _DAY, "2026-11-16T15:00Z", True),
    ("before", "permit_issued", "2026-11-20", "2026-12-01", _DAY, "2026-11-16T15:00Z", False),
    ("ended", "permit_issued", "2026-11-01", "2026-11-10", _DAY, "2026-11-16T15:00Z", False),
    # contract v1.4.0: t < valid_to (exclusive). valid_to = 2026-11-17 00:00 local = 05:00Z
    ("at_end", "permit_issued", "2026-11-01", "2026-11-17", _DAY, "2026-11-17T05:00Z", False),
    ("pre_end", "permit_issued", "2026-11-01", "2026-11-17", _DAY, "2026-11-17T04:59Z", True),
    ("win_in", "permit_issued", "2026-11-01", "2026-12-01", _WIN, "2026-11-16T15:00Z", True),
    # 08:30 local = 13:30Z → before the 09:00 window
    ("win_out", "permit_issued", "2026-11-01", "2026-12-01", _WIN, "2026-11-16T13:30Z", False),
    # 23:30Z Sunday 15th = 18:30 local Sunday → Sunday's all-day schedule, not Monday's
    ("tz_day", "permit_issued", "2026-11-01", "2026-12-01", _OFF, "2026-11-16T03:30Z", True),
    ("off", "permit_issued", "2026-11-01", "2026-12-01", _OFF, "2026-11-16T15:00Z", False),
    (
        "null_flag",
        "permit_issued",
        "2026-11-01",
        "2026-12-01",
        {**_DAY, "active": None},
        "2026-11-16T15:00Z",
        None,
    ),
    (
        "overnight",
        "permit_issued",
        "2026-11-01",
        "2026-12-01",
        {**_WIN, "start": "19:00", "end": "06:00"},
        "2026-11-16T15:00Z",
        None,
    ),
    (
        "eod",
        "permit_issued",
        "2026-11-01",
        "2026-12-01",
        {**_WIN, "start": "18:00", "end": "23:59"},
        "2026-11-17T04:59:30Z",
        True,
    ),
    ("unknown", "unknown", "2026-11-01", "2026-12-01", _DAY, "2026-11-16T15:00Z", None),
    ("cancel", "cancelled", "2026-11-01", "2026-12-01", _DAY, "2026-11-16T15:00Z", False),
]


def test_closure_status_and_active_at(test_url):
    import json

    alembic(test_url, "upgrade", "head")
    with psycopg.connect(test_url, autocommit=True) as c:
        c.execute(
            "INSERT INTO wp.source (source_id, name, publisher, license, license_url, "
            "commercial_use, attribution, url, status) VALUES ('syn','SYNTHETIC','t','t','t',"
            "'unverified','t','t','disabled') ON CONFLICT DO NOTHING"
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "INSERT INTO wp.closure (closure_id, geom, status, source_id) "
                "VALUES ('syn:bad', ST_Point(-73.57,45.50,4326), 'Permis émis', 'syn')"
            )
        got = {}
        for cid, st, vf, vt, mon, t, _ in ACTIVE_CASES:
            c.execute(
                "INSERT INTO wp.closure (closure_id, geom, status, valid_from, valid_to, attrs, "
                "source_id) VALUES (%s, ST_Point(-73.57,45.50,4326), %s, "
                "(%s::date::timestamp AT TIME ZONE 'America/Montreal'), "
                "(%s::date::timestamp AT TIME ZONE 'America/Montreal'), %s, 'syn')",
                (f"syn:{cid}", st, vf, vt, json.dumps({"weekly_schedule": _sched(mon)})),
            )
            got[cid] = c.execute(
                "SELECT wp.closure_active_at(c, %s::timestamptz) FROM wp.closure c "
                "WHERE closure_id=%s",
                (t, f"syn:{cid}"),
            ).fetchone()[0]
    assert got == {cid: exp for cid, *_, exp in ACTIVE_CASES}


def test_report_311_nature_constraints_and_exact_downgrade(test_url):
    """CR-ML-1: nature in the PK; canonical categories; downgrade = SUM over natures.
    Rows are SYNTHETIC."""
    alembic(test_url, "upgrade", "head")
    ins = "INSERT INTO wp.report_311_cell (h3, day, category, nature, n) VALUES (%s,%s,%s,%s,%s)"
    with psycopg.connect(test_url, autocommit=True) as c:
        c.execute(
            "INSERT INTO wp.source (source_id, name, publisher, license, license_url, "
            "commercial_use, attribution, url, status) VALUES ('mtl-311','SYNTHETIC','t','t','t',"
            "'unverified','t','t','disabled') ON CONFLICT DO NOTHING"
        )
        c.execute("DELETE FROM wp.report_311_cell")
        for nat, n in (("requete", 2), ("plainte", 1), ("information", 5)):
            c.execute(ins, ("syn-cell", "2026-01-05", "sidewalk_slippery", nat, n))
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(ins, ("syn-cell", "2026-01-05", "sidewalk_slippery", "autre", 1))
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(ins, ("syn-cell", "2026-01-05", "Trottoir glissant", "requete", 1))
        with pytest.raises(psycopg.errors.UniqueViolation):
            c.execute(ins, ("syn-cell", "2026-01-05", "sidewalk_slippery", "requete", 1))
        # consumer pattern from the contract: SUM over label natures, k-anon after summing
        labels = c.execute(
            "SELECT sum(n) FROM wp.report_311_cell WHERE nature IN ('requete','plainte') "
            "GROUP BY h3, day, category"
        ).fetchone()[0]
        assert labels == 3  # each nature alone is < 3; the sum passes the floor
    alembic(test_url, "downgrade", "0005_closure_active_excl_end")
    with psycopg.connect(test_url) as c:
        assert c.execute("SELECT n FROM wp.report_311_cell").fetchall() == [(8,)]
    alembic(test_url, "upgrade", "head")
    with psycopg.connect(test_url) as c:  # mixed-nature aggregates cannot be split → removed
        assert c.execute("SELECT count(*) FROM wp.report_311_cell").fetchone()[0] == 0


def test_loader_atomic_and_idempotent(test_url, tmp_path):
    """Fixture-sized real data: load pilot_mini as the OSM graph, then a failing load must not
    change it, and an identical load is a no-op."""
    import json
    import shutil

    from winterpath_ingestion import db_load
    from winterpath_ingestion.config import Settings

    alembic(test_url, "upgrade", "head")
    src = ROOT / "data" / "fixtures" / "pilot_mini"
    d = tmp_path / "processed" / "osm_pilot"
    d.mkdir(parents=True)
    for f in ("edges.geojson", "nodes.geojson"):
        shutil.copy(src / f, d / f)
    (d / "manifest.json").write_text(
        json.dumps(
            {"input_checksum": "fixture-1", "ingest_run_id": "00000000-0000-0000-0000-000000000001"}
        )
    )
    s = Settings(data_dir=tmp_path, user_agent="test")

    r1 = db_load.load(s, ["osm"], url=test_url)
    assert r1[0]["counts"]["edge"] == 200
    with psycopg.connect(test_url) as c:
        n_cross, typed, foreign, no_hw = c.execute(
            "SELECT count(*) FILTER (WHERE edge_kind='crossing'), "
            "count(*) FILTER (WHERE edge_kind='crossing' AND crossing_type IS NOT NULL), "
            "count(*) FILTER (WHERE edge_kind<>'crossing' AND crossing_type IS NOT NULL), "
            "count(*) FILTER (WHERE highway IS NULL OR osm_snapshot IS NULL) FROM wp.edge"
        ).fetchone()
        assert n_cross > 0 and typed == n_cross and foreign == 0 and no_hw == 0
    assert db_load.load(s, ["osm"], url=test_url)[0]["noop"] is True

    # corrupt input → load fails, previous graph intact, failed run recorded
    (d / "edges.geojson").write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature",'
        '"geometry":{"type":"LineString","coordinates":[[0,0],[1,1]]},'
        '"properties":{"edge_id":"bad"}}]}'
    )
    (d / "manifest.json").write_text(
        json.dumps(
            {"input_checksum": "fixture-2", "ingest_run_id": "00000000-0000-0000-0000-000000000002"}
        )
    )
    with pytest.raises((KeyError, AttributeError, psycopg.Error)):
        db_load.load(s, ["osm"], url=test_url)
    with psycopg.connect(test_url) as c:
        assert c.execute("SELECT count(*) FROM wp.edge").fetchone()[0] == 200
        st = dict(c.execute("SELECT input_checksum, status FROM wp.ingest_run").fetchall())
        assert st["fixture-1"] == "succeeded" and st["fixture-2"] == "failed"
