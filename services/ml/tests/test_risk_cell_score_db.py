"""wp.risk_cell_score writer + PostGIS provider (contract v1.7) against TEMP tables.

Live tests are opt-in: WP_ML_TEST_DB_URL (e.g. the ML agent's own wp_ml). They create only
session-local TEMP tables with the v1.7 columns, so nothing persists. SYNTHETIC scores.
DB-free tests at the bottom always run.
"""

import os
from datetime import UTC, date, datetime

import pandas as pd
import pytest

from winterpath_ml import inference, score_db

URL = os.environ.get("WP_ML_TEST_DB_URL")
live = pytest.mark.skipif(not URL, reason="WP_ML_TEST_DB_URL not set")

MODEL_ID = "winter311-heuristic-v1"
CELLS = ["892baa441b3ffff", "892baa441a7ffff", "892baa4418fffff"]
REG = {
    "run_id": "v2-8d19aa86",
    "active_layer": "heuristic",
    "season_months": [11, 12, 1, 2, 3, 4],
    "levels": {"thresholds": {"moderate": 0.03, "elevated": 0.06, "high": 0.12}},
    "layers": {
        "heuristic": {"id": MODEL_ID, "enabled": True},
        "model": {"id": "winter311-hgb-v1", "enabled": False},
    },
}
T_SCORE, T_RUN = "pg_temp.risk_cell_score", "pg_temp.ingest_run"
DDL = """
CREATE TEMP TABLE ingest_run (
  ingest_run_id uuid PRIMARY KEY, source_id text NOT NULL,
  started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
  status text NOT NULL CHECK (status IN ('running','succeeded','failed')),
  input_checksum text, record_count int, log jsonb);
CREATE TEMP TABLE risk_cell_score (
  h3 text NOT NULL, day date NOT NULL, model_id text NOT NULL,
  layer text NOT NULL CHECK (layer IN ('heuristic','model')),
  p double precision NOT NULL, scored_at timestamptz NOT NULL,
  data_through timestamptz NOT NULL, ingest_run_id uuid NOT NULL,
  PRIMARY KEY (h3, day, model_id));
CREATE INDEX ON risk_cell_score (day, model_id);
"""


def _plan(days: dict[str, list[float]]) -> dict:
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
        "registry": REG,
        "layer": "heuristic",
        "tables": tables,
        "not_ready": {},
        "out_of_season": [],
        "source_311": {"sha256": "SYNTHETIC"},
    }


@pytest.fixture
def engine():
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    eng = create_engine(
        URL.replace("postgresql://", "postgresql+psycopg://", 1)
        if URL.startswith("postgresql://")
        else URL,
        poolclass=StaticPool,  # one session, so TEMP tables are visible to writer and reader
    )
    raw = eng.raw_connection().driver_connection
    raw.autocommit = True
    raw.execute(DDL)
    yield eng, raw
    eng.dispose()


def _write(raw, plan, today=date(2026, 12, 2)):
    return score_db.write_scores(
        raw, plan, today=today, table=T_SCORE, ingest_table=T_RUN
    )


def _rows(raw, sql):
    return raw.execute(sql).fetchall()


@live
def test_write_replaces_partition_and_records_run(engine):
    _, raw = engine
    s1 = _write(raw, _plan({"2026-12-02": [0.01, 0.05, 0.2]}))
    s2 = _write(raw, _plan({"2026-12-02": [0.02, 0.04]}))  # re-run: fewer cells
    assert s1["rows_written"] == 3 and s2["rows_replaced"] == {"2026-12-02": 3}
    rows = _rows(raw, f"SELECT h3, p FROM {T_SCORE} ORDER BY h3")
    assert rows == [(CELLS[1], 0.04), (CELLS[0], 0.02)] or sorted(rows) == sorted(
        [(CELLS[0], 0.02), (CELLS[1], 0.04)]
    )
    runs = _rows(
        raw, f"SELECT status, record_count, source_id, input_checksum FROM {T_RUN}"
    )
    assert [r[:3] for r in runs] == [("succeeded", 3, "mtl-311")] * 1 + [
        ("succeeded", 2, "mtl-311")
    ] or sorted(r[:3] for r in runs) == [
        ("succeeded", 2, "mtl-311"),
        ("succeeded", 3, "mtl-311"),
    ]
    assert all(r[3].startswith("winterpath_ml.score:") for r in runs)


@live
def test_retention_deletes_rows_older_than_30_days(engine):
    _, raw = engine
    _write(raw, _plan({"2026-11-01": [0.01], "2026-11-02": [0.01]}))
    s = _write(raw, _plan({"2026-12-02": [0.01]}), today=date(2026, 12, 2))
    days = [
        r[0] for r in _rows(raw, f"SELECT DISTINCT day FROM {T_SCORE} ORDER BY day")
    ]
    assert s["retention_cutoff"] == "2026-11-02" and s["rows_expired"] == 1
    assert days == [date(2026, 11, 2), date(2026, 12, 2)]


@live
def test_failed_run_rolls_back_and_records_failure(engine, monkeypatch):
    _, raw = engine
    _write(raw, _plan({"2026-12-02": [0.01, 0.05, 0.2]}))
    bad = _plan({"2026-12-02": [0.03]})
    bad["tables"]["2026-12-02"]["data_through"] = "not-a-timestamp"
    with pytest.raises(ValueError):
        _write(raw, bad)
    assert len(_rows(raw, f"SELECT 1 FROM {T_SCORE} WHERE day='2026-12-02'")) == 3
    st = sorted(r[0] for r in _rows(raw, f"SELECT status FROM {T_RUN}"))
    assert st == ["failed", "succeeded"]


@live
def test_postgis_provider_reads_requested_local_day(engine):
    eng, raw = engine
    _write(raw, _plan({"2026-12-02": [0.01, 0.07]}))
    raw.execute(
        f"INSERT INTO {T_SCORE} VALUES ('{CELLS[2]}', '2026-12-02', 'other-model', 'heuristic',"
        " 0.9, now(), now(), gen_random_uuid())"
    )
    db = inference.PostgisScores(eng, MODEL_ID, table=T_SCORE)
    prov = inference.HeuristicRiskProvider(
        REG,
        "heuristic",
        inference._read_scores(inference.Path("/x"), quiet=True),
        None,
        db,
    )
    # 2026-12-02 local (EST): 04:59 UTC on 12-03 is still 12-02 locally
    at = datetime(2026, 12, 3, 4, 59, tzinfo=UTC)
    assert prov.cell_risk(CELLS[0], at).level == "low"
    e = prov.cell_risk(CELLS[1], at)
    assert e.level == "elevated" and e.probability is None  # heuristic never exposes p
    assert e.evidence.state == "model_estimate"
    assert (
        prov.cell_risk(CELLS[2], at).level == "unknown"
    )  # only another model has a row
    assert (
        prov.cell_risk(CELLS[0], datetime(2026, 12, 3, 5, tzinfo=UTC)).level
        == "unknown"
    )
    assert newest(raw) == date(2026, 12, 2)


def newest(raw):
    return score_db.newest_day(raw, MODEL_ID, table=T_SCORE)


# ---------------------------------------------------------------- DB-free


class _BrokenEngine:
    def connect(self):
        raise OSError("connection refused")


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
