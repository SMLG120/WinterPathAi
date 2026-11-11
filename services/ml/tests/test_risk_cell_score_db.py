"""wp.risk_cell_score writer + PostGIS provider (contract v1.7) against a real DB at migration 0007.

Live tests are opt-in: WP_ML_TEST_DB_URL must point at a database migrated to
0007_risk_cell_score with the canonical wp.source rows (the ML agent uses its own wp_ml).
Each test writes under a unique SYNTHETIC model_id and deletes its rows and ingest_run rows
afterwards. Writer and reader use separate connections with real commits, as in production.
DB-free tests at the bottom always run.
"""

import importlib.util
import os
import uuid
from datetime import UTC, date, datetime

import pandas as pd
import pytest

from winterpath_ml import inference, score_db

URL = os.environ.get("WP_ML_TEST_DB_URL")
_MISSING = [m for m in ("sqlalchemy", "psycopg") if importlib.util.find_spec(m) is None]
needs_db_extra = pytest.mark.skipif(
    bool(_MISSING),
    reason=f"{', '.join(_MISSING)} not installed: optional 'db' extra (uv sync --extra db)",
)


def live(f):
    return needs_db_extra(
        pytest.mark.skipif(not URL, reason="WP_ML_TEST_DB_URL not set")(f)
    )


MODEL_ID = "winter311-heuristic-v1"
CELLS = ["892baa441b3ffff", "892baa441a7ffff", "892baa4418fffff"]


def _reg(model_id=MODEL_ID):
    return {
        "run_id": "v2-8d19aa86",
        "active_layer": "heuristic",
        "season_months": [11, 12, 1, 2, 3, 4],
        "levels": {"thresholds": {"moderate": 0.03, "elevated": 0.06, "high": 0.12}},
        "layers": {
            "heuristic": {"id": model_id, "enabled": True},
            "model": {"id": "winter311-hgb-v1", "enabled": False},
        },
    }


REG = _reg()


def _plan(days: dict[str, list[float]], model_id=MODEL_ID) -> dict:
    tables = {}
    for d, ps in days.items():
        tables[d] = pd.DataFrame(
            {
                "h3": CELLS[: len(ps)],
                "day": pd.Timestamp(d),
                "p": ps,
                "scored_at": "2026-12-02T06:00:00+00:00",
                "data_through": f"{d}T05:00:00+00:00",
            }
        )
    return {
        "registry": _reg(model_id),
        "layer": "heuristic",
        "tables": tables,
        "not_ready": {},
        "out_of_season": [],
        "source_311": {"sha256": "SYNTHETIC"},
    }


@pytest.fixture
def db():
    """(psycopg autocommit connection, unique SYNTHETIC model_id); cleans up after itself."""
    conn = score_db.connect(URL)
    conn.autocommit = True
    mid = f"SYNTHETIC-test-{uuid.uuid4().hex[:8]}"
    yield conn, mid
    runs = [
        r[0]
        for r in conn.execute(
            "SELECT ingest_run_id FROM wp.ingest_run WHERE log->>'model_id' = %s",
            (mid,),
        )
    ]
    conn.execute("DELETE FROM wp.risk_cell_score WHERE model_id = %s", (mid,))
    conn.execute("DELETE FROM wp.ingest_run WHERE ingest_run_id = ANY(%s)", (runs,))
    conn.close()


def _rows(conn, sql, *args):
    return conn.execute(sql, args).fetchall()


@live
def test_write_replaces_partition_and_records_run(db):
    conn, mid = db
    s1 = score_db.write_scores(
        conn, _plan({"2026-12-02": [0.01, 0.05, 0.2]}, mid), today=date(2026, 12, 2)
    )
    s2 = score_db.write_scores(
        conn, _plan({"2026-12-02": [0.02, 0.04]}, mid), today=date(2026, 12, 2)
    )
    assert s1["rows_written"] == 3 and s2["rows_replaced"] == {"2026-12-02": 3}
    rows = _rows(
        conn,
        "SELECT h3, p, layer, ingest_run_id::text FROM wp.risk_cell_score WHERE model_id=%s ORDER BY p",
        mid,
    )
    assert [(h, p, lay) for h, p, lay, _ in rows] == [
        (CELLS[0], 0.02, "heuristic"),
        (CELLS[1], 0.04, "heuristic"),
    ]
    assert {r[3] for r in rows} == {s2["ingest_run_id"]}
    runs = _rows(
        conn,
        "SELECT status, record_count, source_id, input_checksum, finished_at IS NOT NULL"
        " FROM wp.ingest_run WHERE log->>'model_id'=%s ORDER BY record_count",
        mid,
    )
    assert [r[:3] for r in runs] == [
        ("succeeded", 2, "mtl-311"),
        ("succeeded", 3, "mtl-311"),
    ]
    assert all(r[3].startswith("winterpath_ml.score:") and r[4] for r in runs)


@live
def test_retention_deletes_rows_older_than_30_days(db):
    conn, mid = db
    score_db.write_scores(
        conn,
        _plan({"2026-11-01": [0.01], "2026-11-02": [0.01]}, mid),
        today=date(2026, 11, 2),
    )
    s = score_db.write_scores(
        conn, _plan({"2026-12-02": [0.01]}, mid), today=date(2026, 12, 2)
    )
    days = [
        r[0]
        for r in _rows(
            conn,
            "SELECT DISTINCT day FROM wp.risk_cell_score WHERE model_id=%s ORDER BY day",
            mid,
        )
    ]
    assert s["retention_cutoff"] == "2026-11-02" and s["rows_expired"] >= 1
    assert days == [date(2026, 11, 2), date(2026, 12, 2)]


@live
def test_failed_run_rolls_back_and_records_failure(db):
    conn, mid = db
    score_db.write_scores(
        conn, _plan({"2026-12-02": [0.01, 0.05, 0.2]}, mid), today=date(2026, 12, 2)
    )
    import psycopg

    bad = _plan({"2026-12-02": [0.03, 1.5]}, mid)  # p > 1 violates 0007's CHECK
    with pytest.raises(psycopg.errors.CheckViolation):
        score_db.write_scores(conn, bad, today=date(2026, 12, 2))
    ps = sorted(
        r[0]
        for r in _rows(conn, "SELECT p FROM wp.risk_cell_score WHERE model_id=%s", mid)
    )
    assert ps == [0.01, 0.05, 0.2]  # previous partition intact
    st = _rows(
        conn,
        "SELECT status, log->>'error' FROM wp.ingest_run WHERE log->>'model_id'=%s ORDER BY status",
        mid,
    )
    assert [r[0] for r in st] == ["failed", "succeeded"] and "CheckViolation" in st[0][
        1
    ]


@live
def test_postgis_provider_reads_requested_local_day(db):
    from sqlalchemy import create_engine

    conn, mid = db
    score_db.write_scores(
        conn, _plan({"2026-12-02": [0.01, 0.07]}, mid), today=date(2026, 12, 2)
    )
    other = mid + "-other"
    conn.execute(
        "INSERT INTO wp.risk_cell_score (h3, day, model_id, layer, p) VALUES (%s, '2026-12-02', %s, 'heuristic', 0.9)",
        (CELLS[2], other),
    )
    try:
        eng = create_engine(
            URL.replace("postgresql://", "postgresql+psycopg://", 1)
            if URL.startswith("postgresql://")
            else URL
        )
        p = inference.load_provider(engine=eng, score_source="postgis")
        prov = inference.HeuristicRiskProvider(
            _reg(mid), "heuristic", p.scores, None, inference.PostgisScores(eng, mid)
        )
        at = datetime(
            2026, 12, 3, 4, 59, tzinfo=UTC
        )  # still 2026-12-02 in Montréal (EST)
        assert prov.cell_risk(CELLS[0], at).level == "low"
        e = prov.cell_risk(CELLS[1], at)
        assert (
            e.level == "elevated" and e.probability is None
        )  # heuristic never exposes p
        assert (
            e.evidence.state == "model_estimate"
            and e.evidence.observed_at.startswith("2026-12-02")
        )
        assert (
            prov.cell_risk(CELLS[2], at).level == "unknown"
        )  # only another model_id has a row
        nxt = prov.cell_risk(
            CELLS[0], datetime(2026, 12, 3, 5, tzinfo=UTC)
        )  # local 12-03: no rows
        assert nxt.level == "unknown"
        edge = prov.edge_risk([[-73.5772, 45.5048], [-73.5772, 45.5049]], at)
        assert edge.level in ("low", "unknown")
        assert score_db.newest_day(conn, mid) == date(2026, 12, 2)
        eng.dispose()
    finally:
        conn.execute("DELETE FROM wp.risk_cell_score WHERE model_id = %s", (other,))


# ---------------------------------------------------------------- DB-free


class _BrokenEngine:
    def connect(self):
        raise OSError("connection refused")


@needs_db_extra
def test_postgis_db_error_is_unknown_never_low():
    db = inference.PostgisScores(_BrokenEngine(), MODEL_ID)
    prov = inference.HeuristicRiskProvider(
        REG,
        "heuristic",
        inference._read_scores(inference.Path("/x"), quiet=True),
        None,
        db,
    )
    e = prov.cell_risk(CELLS[0], datetime(2026, 12, 2, 15, tzinfo=UTC))
    assert e.level == "unknown" and "unreachable" in e.evidence.note


def test_postgis_without_engine_is_null_provider(monkeypatch):
    monkeypatch.setenv("RISK_SCORE_SOURCE", "postgis")
    assert isinstance(inference.load_provider(), inference.NullRiskProvider)


def test_invalid_score_source_is_null_provider():
    assert isinstance(
        inference.load_provider(score_source="s3"), inference.NullRiskProvider
    )


@needs_db_extra
def test_postgis_provider_built_from_engine(monkeypatch):
    p = inference.load_provider(engine=_BrokenEngine(), score_source="postgis")
    assert isinstance(p, inference.HeuristicRiskProvider) and p.db is not None
    assert (
        p.cell_risk(CELLS[0], datetime(2026, 12, 2, 15, tzinfo=UTC)).level == "unknown"
    )


def test_run_checksum_namespaced():
    c = score_db.run_checksum(MODEL_ID, ["2026-12-02"], {"sha256": "abc"})
    assert (
        c.startswith("winterpath_ml.score:")
        and len(c) == len("winterpath_ml.score:") + 64
    )
