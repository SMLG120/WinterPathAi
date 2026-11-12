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
EXPECTED_0002 = sorted([*EXPECTED_0001, "weather_daily"])  # contract v1.2.0 … v1.6.0
EXPECTED = sorted([*EXPECTED_0002, "risk_cell_score"])  # head = 0007 (contract v1.7.0)
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
    # one step down: 0007 removed, 0006 intact
    alembic(test_url, "downgrade", "0006_report_311_nature")
    assert wp_tables(test_url) == EXPECTED_0002
    assert report_311_pk(test_url) == V15_PK
    alembic(test_url, "upgrade", "head")
    assert wp_tables(test_url) == EXPECTED
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
    assert wp_tables(test_url) == EXPECTED_0002
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
        for alley in ("snow_clearing_alley", "snow_dumping_alley"):  # v1.6.0 (CR-ML-2)
            c.execute(ins, ("syn-alley", "2026-01-05", alley, "requete", 1))
        c.execute("DELETE FROM wp.report_311_cell WHERE h3='syn-alley'")
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


def test_weather_since_bounds_and_prunes(test_url, tmp_path):
    """`load --weather-since`: rows before local midnight (America/Montreal) are skipped and
    pruned; the cutoff is part of the checksum, so bounded and full loads never no-op each other.
    Synthetic station `TEST` in the throwaway DB only."""
    import json
    from datetime import date

    from winterpath_ingestion import db_load
    from winterpath_ingestion.config import Settings

    alembic(test_url, "upgrade", "head")
    d = tmp_path / "processed" / "weather_obs"
    d.mkdir(parents=True)
    hdr = "station_id,observed_at,temperature_c,precip_mm,snow_depth_cm,wind_kmh,source_collection"
    times = [
        "2025-12-31T04:59:00+00:00",  # 2025-12-30 23:59 local → before
        "2026-01-01T04:59:00+00:00",  # 2025-12-31 23:59 local → before
        "2026-01-01T05:00:00+00:00",  # 2026-01-01 00:00 local → kept (inclusive)
        "2026-06-01T00:00:00+00:00",
    ]
    (d / "weather_obs.csv").write_text(
        hdr + "\n" + "".join(f"TEST,{t},-5.0,,,,climate-hourly\n" for t in times)
    )
    (d / "manifest.json").write_text(
        json.dumps(
            {"input_checksum": "w-1", "ingest_run_id": "00000000-0000-0000-0000-0000000000a1"}
        )
    )
    s = Settings(data_dir=tmp_path, user_agent="test")

    def n_rows():
        with psycopg.connect(test_url) as c:
            return c.execute(
                "SELECT count(*) FROM wp.weather_obs WHERE station_id='TEST'"
            ).fetchone()[0]

    assert db_load.load(s, ["eccc"], url=test_url)[0]["counts"]["weather_obs"] == 4
    assert n_rows() == 4

    r = db_load.load(s, ["eccc"], url=test_url, weather_since=date(2026, 1, 1))[0]
    assert r["noop"] is False
    assert r["counts"] == {
        "weather_obs": 2,
        "_weather_obs_skipped_before_since": 2,
        "_weather_obs_pruned_before_since": 2,
    }
    assert n_rows() == 2
    with psycopg.connect(test_url) as c:
        rc = c.execute(
            "SELECT record_count FROM wp.ingest_run WHERE input_checksum=%s",
            ("w-1|weather_since=2026-01-01",),
        ).fetchone()[0]
    assert rc == 2
    assert db_load.load(s, ["eccc"], url=test_url, weather_since=date(2026, 1, 1))[0]["noop"]
    assert db_load.load(s, ["eccc"], url=test_url)[0]["noop"] is False  # full reload restores
    assert n_rows() == 4


RCS = "INSERT INTO wp.risk_cell_score (h3, day, model_id, layer, p{extra}) VALUES "


def test_risk_cell_score_schema_constraints_grants_roundtrip(test_url):
    """0007 (contract v1.7.0): exact columns, PK, (day, model_id) index, layer/p CHECKs, grants,
    partition replace in one transaction, and a downgrade/upgrade roundtrip. Synthetic h3 values
    in the throwaway DB only."""
    alembic(test_url, "upgrade", "head")
    with psycopg.connect(test_url) as c:
        cols = c.execute(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema='wp' AND table_name='risk_cell_score' ORDER BY ordinal_position"
        ).fetchall()
        assert cols == [
            ("h3", "text", "NO"),
            ("day", "date", "NO"),
            ("model_id", "text", "NO"),
            ("layer", "text", "NO"),
            ("p", "double precision", "NO"),
            ("scored_at", "timestamp with time zone", "NO"),
            ("data_through", "timestamp with time zone", "YES"),
            ("ingest_run_id", "uuid", "YES"),
        ]
        pk = [
            r[0]
            for r in c.execute(
                "SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid=i.indrelid "
                "AND a.attnum = ANY(i.indkey) WHERE i.indrelid='wp.risk_cell_score'::regclass "
                "AND i.indisprimary ORDER BY array_position(i.indkey, a.attnum)"
            )
        ]
        assert pk == ["h3", "day", "model_id"]
        idx = c.execute(
            "SELECT indexdef FROM pg_indexes WHERE schemaname='wp' "
            "AND indexname='risk_cell_score_day_model_idx'"
        ).fetchone()[0]
        assert "(day, model_id)" in idx
        grants = set(
            c.execute(
                "SELECT grantee, privilege_type FROM information_schema.role_table_grants "
                "WHERE table_schema='wp' AND table_name='risk_cell_score' "
                "AND grantee IN ('wp_reader','wp_writer')"
            ).fetchall()
        )
        assert ("wp_reader", "SELECT") in grants
        assert not {("wp_reader", x) for x in ("INSERT", "UPDATE", "DELETE")} & grants
        assert {("wp_writer", x) for x in ("SELECT", "INSERT", "DELETE")} <= grants

    ok = "('89283082803ffff', '2026-11-11', 'winter311-heuristic-v1', 'heuristic', 0.25)"
    bad = [
        "('h', '2026-11-11', 'm', 'other', 0.5)",  # layer
        "('h', '2026-11-11', 'm', 'model', 1.0000001)",  # p > 1
        "('h', '2026-11-11', 'm', 'model', -0.1)",  # p < 0
        "('h', '2026-11-11', 'm', 'model', 'NaN')",  # NaN
        "('h', '2026-11-11', 'm', 'model', NULL)",  # no score ⇒ no row, never NULL
    ]
    with psycopg.connect(test_url, autocommit=True) as c:
        c.execute(RCS.format(extra="") + ok)
        c.execute(
            RCS.format(extra="") + "('h', '2026-11-11', 'm', 'model', 0), "
            "('h2', '2026-11-11', 'm', 'model', 1)"
        )  # bounds inclusive
        with pytest.raises(psycopg.errors.UniqueViolation):
            c.execute(RCS.format(extra="") + ok)
        for b in bad:
            with pytest.raises((psycopg.errors.CheckViolation, psycopg.errors.NotNullViolation)):
                c.execute(RCS.format(extra="") + b)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            c.execute(
                RCS.format(extra=", ingest_run_id")
                + "('h3x', '2026-11-11', 'm', 'model', 0.5, gen_random_uuid())"
            )
        assert c.execute("SELECT scored_at IS NOT NULL FROM wp.risk_cell_score LIMIT 1").fetchone()[
            0
        ]
        # writer pattern: replace a (day, model_id) partition in one txn; failure keeps the old day
        with pytest.raises(psycopg.errors.CheckViolation):
            with c.transaction():
                c.execute("DELETE FROM wp.risk_cell_score WHERE day='2026-11-11' AND model_id='m'")
                c.execute(RCS.format(extra="") + "('h', '2026-11-11', 'm', 'model', 2)")
        assert (
            c.execute(
                "SELECT count(*) FROM wp.risk_cell_score WHERE day='2026-11-11' AND model_id='m'"
            ).fetchone()[0]
            == 2
        )
        # as the roles themselves (SET ROLE drops superuser rights)
        with c.transaction():
            c.execute("SET LOCAL ROLE wp_writer")
            c.execute("DELETE FROM wp.risk_cell_score WHERE day='2026-11-11' AND model_id='m'")
            c.execute(RCS.format(extra="") + "('h', '2026-11-11', 'm', 'model', 0.5)")
        with c.transaction():
            c.execute("SET LOCAL ROLE wp_reader")
            assert c.execute("SELECT count(*) FROM wp.risk_cell_score").fetchone()[0] == 2
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute("DELETE FROM wp.risk_cell_score")

    alembic(test_url, "downgrade", "0006_report_311_nature")
    assert "risk_cell_score" not in wp_tables(test_url)
    alembic(test_url, "upgrade", "head")
    with psycopg.connect(test_url) as c:
        assert c.execute("SELECT count(*) FROM wp.risk_cell_score").fetchone()[0] == 0


def test_load_source_cli_loads_only_that_source(test_url, tmp_path, monkeypatch):
    """`wp-ingest load --source eccc-geomet` loads only eccc-geomet (others untouched, even with
    processed output present), through the same transaction/checksum path; a rerun is a no-op."""
    import json
    import shutil

    from winterpath_ingestion import cli

    alembic(test_url, "upgrade", "head")
    proc = tmp_path / "processed"
    o = proc / "osm_pilot"
    o.mkdir(parents=True)
    for f in ("edges.geojson", "nodes.geojson"):
        shutil.copy(ROOT / "data" / "fixtures" / "pilot_mini" / f, o / f)
    (o / "manifest.json").write_text(
        json.dumps(
            {"input_checksum": "src-osm", "ingest_run_id": "00000000-0000-0000-0000-0000000000b1"}
        )
    )
    w = proc / "weather_obs"
    w.mkdir()
    (w / "weather_obs.csv").write_text(
        "station_id,observed_at,temperature_c,precip_mm,snow_depth_cm,wind_kmh,source_collection\n"
        "SRCTEST,2026-11-01T12:00:00+00:00,-1.0,,,,climate-hourly\n"
    )
    (w / "manifest.json").write_text(
        json.dumps(
            {"input_checksum": "src-w", "ingest_run_id": "00000000-0000-0000-0000-0000000000b2"}
        )
    )
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", test_url)

    def runs():
        with psycopg.connect(test_url) as c:
            return c.execute(
                "SELECT input_checksum, status FROM wp.ingest_run "
                "WHERE input_checksum IN ('src-osm','src-w') ORDER BY 1"
            ).fetchall()

    assert cli.main(["load", "--source", "eccc-geomet"]) == 0
    assert runs() == [("src-w", "succeeded")]
    with psycopg.connect(test_url) as c:
        assert (
            c.execute("SELECT count(*) FROM wp.weather_obs WHERE station_id='SRCTEST'").fetchone()[
                0
            ]
            == 1
        )
    assert cli.main(["load", "--source", "eccc-geomet"]) == 0  # same checksum → no-op
    with psycopg.connect(test_url) as c:
        assert (
            c.execute("SELECT count(*) FROM wp.ingest_run WHERE input_checksum='src-w'").fetchone()[
                0
            ]
            == 1
        )
    assert runs() == [("src-w", "succeeded")]  # osm still not loaded


def _r311_processed(tmp_path, checksum, run_id, n=5):
    import json

    d = tmp_path / "processed" / "report_311"
    d.mkdir(parents=True, exist_ok=True)
    (d / "report_311_cell.csv").write_text(
        "h3,day,category,nature,n,source_id\n"
        f"892b8b0a2b3ffff,2026-11-01,sidewalk_slippery,requete,{n},mtl-311\n"
    )
    (d / "manifest.json").write_text(
        json.dumps({"input_checksum": checksum, "ingest_run_id": run_id})
    )


def test_etl_locks_try_skip_wait_and_migration_gate(test_url, tmp_path, monkeypatch, capsys):
    """infra/ETL-LOCKS.md: a held source lock or schema gate makes a load skip cleanly (exit 0,
    notice, nothing written, no failed run); --wait blocks and times out as an error; Alembic
    takes the schema gate exclusively and fails rather than migrate under a load.
    Synthetic h3 cell in the throwaway DB only."""
    from winterpath_ingestion import cli, db_load, locks
    from winterpath_ingestion.config import Settings

    alembic(test_url, "upgrade", "head")
    _r311_processed(tmp_path, "lock-1", "00000000-0000-0000-0000-0000000000c1")
    s = Settings(data_dir=tmp_path, user_agent="test")

    def n_runs(chk):
        with psycopg.connect(test_url) as c:
            return c.execute(
                "SELECT count(*) FROM wp.ingest_run WHERE input_checksum=%s", (chk,)
            ).fetchone()[0]

    holder = psycopg.connect(test_url)
    try:
        # 1. resource lock held by another run → skipped, nothing written
        holder.execute("SELECT pg_advisory_xact_lock(%s, %s)", (locks.WPET, 4))
        r = db_load.load(s, ["311"], url=test_url)
        assert r == [{"source_id": "mtl-311", "skipped": "locked", "lock": [locks.WPET, 4]}]
        assert (
            "::notice::lock (1464878420,4) held by another run — skipping"
            in capsys.readouterr().out
        )
        assert n_runs("lock-1") == 0
        # other sources are not blocked by lock 4 (eccc has no processed output here)
        assert db_load.load(s, ["eccc"], url=test_url)[0].get("skipped") == "no processed output"
        # CLI exits 0 on contention
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.setenv("DATABASE_URL", test_url)
        assert cli.main(["load", "--source", "mtl-311"]) == 0
        assert "skipping" in capsys.readouterr().out
        # 2. --wait: blocks, then times out as an error (recorded as a failed run)
        monkeypatch.setattr(locks, "DEFAULT_WAIT_TIMEOUT", "300ms")
        with pytest.raises(psycopg.errors.LockNotAvailable):
            db_load.load(s, ["311"], url=test_url, wait=True)
        holder.rollback()  # release lock 4
        # 3. migration holds the schema gate → every source skips, even the registry upsert
        holder.execute("SELECT pg_advisory_xact_lock(%s, %s)", (locks.WPET, 0))
        r = db_load.load(s, ["311", "eccc"], url=test_url)
        assert {x["source_id"] for x in r} == {"mtl-311", "eccc-geomet"}
        assert all(x["skipped"] == "locked" and x["lock"] == [locks.WPET, 0] for x in r)
        holder.rollback()
        # 4. free → loads; and the re-check under the lock keeps it idempotent
        r = db_load.load(s, ["311"], url=test_url)[0]
        assert r["noop"] is False and r["counts"] == {"report_311_cell": 1}
        assert db_load.load(s, ["311"], url=test_url)[0]["noop"] is True
        # 5. Alembic: a load holding the shared gate makes the migration fail (lock_timeout)
        holder.execute("SELECT pg_advisory_xact_lock_shared(%s, %s)", (locks.WPET, 0))
        monkeypatch.setenv("WP_MIGRATION_LOCK_TIMEOUT", "500ms")
        with pytest.raises(subprocess.CalledProcessError) as e:
            alembic(test_url, "downgrade", "0006_report_311_nature")
        assert "lock timeout" in e.value.stderr.lower() or "LockNotAvailable" in e.value.stderr
        holder.rollback()
        assert "risk_cell_score" in wp_tables(test_url)  # nothing migrated
        alembic(test_url, "downgrade", "0006_report_311_nature")
        alembic(test_url, "upgrade", "head")
        with psycopg.connect(test_url) as c:  # gate released after the run
            assert (
                c.execute(
                    "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND classid=%s",
                    (locks.WPET,),
                ).fetchone()[0]
                == 0
            )
    finally:
        holder.close()


def test_r311_recent_window_load_replaces_only_the_window(test_url, tmp_path):
    """`load --source mtl-311 --recent`: upsert the window, prune only inside it, never touch
    older days; idempotent; runs as wp_writer (the scheduled job's privileges)."""
    import json

    from winterpath_ingestion import db_load
    from winterpath_ingestion.config import Settings

    alembic(test_url, "upgrade", "head")
    s = Settings(data_dir=tmp_path, user_agent="test")
    full = tmp_path / "processed" / "report_311"
    full.mkdir(parents=True)
    (full / "report_311_cell.csv").write_text(
        "h3,day,category,nature,n,source_id\n"
        "892b8b0a2b3ffff,2026-10-01,sidewalk_slippery,requete,4,mtl-311\n"  # outside window
        "892b8b0a2b3ffff,2026-11-05,sidewalk_slippery,requete,1,mtl-311\n"  # in window, gone
        "892b8b0a2b3ffff,2026-11-06,snow_clearing,plainte,2,mtl-311\n"  # in window, updated
    )
    (full / "manifest.json").write_text(
        json.dumps(
            {"input_checksum": "full-1", "ingest_run_id": "00000000-0000-0000-0000-0000000000d1"}
        )
    )
    assert db_load.load(s, ["311"], url=test_url)[0]["counts"] == {"report_311_cell": 3}

    rec = tmp_path / "processed" / "report_311_recent"
    rec.mkdir()
    (rec / "report_311_cell.csv").write_text(
        "h3,day,category,nature,n,source_id\n"
        "892b8b0a2b3ffff,2026-11-06,snow_clearing,plainte,3,mtl-311\n"
        "892b8b0a2b3ffff,2026-11-11,sidewalk_slippery,requete,1,mtl-311\n"
    )
    (rec / "manifest.json").write_text(
        json.dumps(
            {
                "input_checksum": "recent-1",
                "ingest_run_id": "00000000-0000-0000-0000-0000000000d2",
                "window": ["2026-10-30", "2026-11-12"],
            }
        )
    )
    writer = test_url + "?options=-c%20role%3Dwp_writer"
    r = db_load.load(s, ["311"], url=writer, r311_recent=True)[0]
    assert r["noop"] is False and r["counts"] == {"report_311_cell": 2}
    with psycopg.connect(test_url) as c:
        got = c.execute(
            "SELECT day::text, category, nature, n FROM wp.report_311_cell ORDER BY day"
        ).fetchall()
    assert got == [
        ("2026-10-01", "sidewalk_slippery", "requete", 4),  # outside: untouched
        ("2026-11-06", "snow_clearing", "plainte", 3),  # updated
        ("2026-11-11", "sidewalk_slippery", "requete", 1),  # new
    ]  # 2026-11-05 (in window, no longer reported) pruned
    assert db_load.load(s, ["311"], url=writer, r311_recent=True)[0]["noop"] is True
