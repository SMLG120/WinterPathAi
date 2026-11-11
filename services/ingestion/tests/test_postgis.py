"""Migration + loader tests against the shared PostGIS container (integration-rules §4).

Runs in a throwaway database `wp_data_test` (created and dropped here) so `wp_data` is never
touched. Skipped — not faked — when the server is unreachable.
"""

import os
import subprocess
from pathlib import Path

import psycopg
import pytest

from winterpath_ingestion.config import get_settings  # noqa: F401  (loads .env.local)

pytestmark = pytest.mark.postgis
ROOT = Path(__file__).resolve().parents[3]
TEST_DB = "wp_data_test"


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
    # one step down: 0003 removed, v1.2 intact
    alembic(test_url, "downgrade", "0002_contract_v1_2_0")
    assert has_v13(test_url) == {False}
    assert V12_EDGE_COLS <= columns(test_url, "edge")
    assert wp_tables(test_url) == EXPECTED
    alembic(test_url, "upgrade", "head")
    assert has_v13(test_url) == {True}
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
