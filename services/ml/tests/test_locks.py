"""ETL advisory lock 100 for wp.risk_cell_score (infra/ETL-LOCKS.md). SYNTHETIC plans.

DB-free tests always run. Live tests (two real connections contending) are opt-in via
WP_ML_TEST_DB_URL, like test_risk_cell_score_db.py.
"""

import re
from contextlib import contextmanager
from datetime import date

import pandas as pd
import pytest
from test_risk_cell_score_db import _plan, _rows, db, live  # noqa: F401 - fixture reuse

from winterpath_ml import config, locks, score, score_db

DATA_LOCKS = config.REPO_ROOT / "services/ingestion/src/winterpath_ingestion/locks.py"


def test_constants_match_data_copy():
    """Copied, not imported: fail loudly if Data's values ever drift from ours."""
    if not DATA_LOCKS.exists():
        pytest.skip("services/ingestion not in this checkout")
    src = DATA_LOCKS.read_text()
    assert int(re.search(r"^WPET = (\d+)", src, re.MULTILINE).group(1)) == locks.WPET
    assert (
        int(re.search(r"^SCHEMA_GATE = (\d+)", src, re.MULTILINE).group(1))
        == locks.SCHEMA_GATE
    )
    assert locks.WPET == 0x57504554 and locks.RISK_CELL_SCORE == 100


class FakeCursor:
    def __init__(self, grants):
        self.grants, self.sql = list(grants), []

    def execute(self, sql, params=None):
        self.sql.append((sql, params))

    def fetchone(self):
        return (self.grants.pop(0),)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_acquire_order_gate_shared_then_exclusive_100():
    cur = FakeCursor([True, True])
    locks.acquire(cur, locks.RISK_CELL_SCORE)
    assert cur.sql == [
        ("SELECT pg_try_advisory_xact_lock_shared(%s, %s)", (locks.WPET, 0)),
        ("SELECT pg_try_advisory_xact_lock(%s, %s)", (locks.WPET, 100)),
    ]


@pytest.mark.parametrize("grants,objid", [([False], 0), ([True, False], 100)])
def test_acquire_raises_locked(grants, objid):
    with pytest.raises(locks.Locked) as e:
        locks.acquire(FakeCursor(grants), locks.RISK_CELL_SCORE)
    assert e.value.objid == objid
    assert e.value.notice == f"lock (1464878420,{objid}) held by another run — skipping"


class FakeConn:
    def __init__(self, grants):
        self.cur = FakeCursor(grants)
        self.transactions = 0

    @contextmanager
    def transaction(self):
        self.transactions += 1
        yield

    def cursor(self):
        return self.cur


def test_write_scores_locked_writes_and_records_nothing():
    conn = FakeConn([True, False])  # gate ok, 100 held by another run
    with pytest.raises(locks.Locked):
        score_db.write_scores(
            conn, _plan({"2026-12-02": [0.01]}), today=date(2026, 12, 2)
        )
    assert conn.transactions == 1  # no second "failed" ingest_run transaction
    assert not any("INSERT" in s or "DELETE" in s for s, _ in conn.cur.sql)


def test_cli_lock_contention_is_notice_exit_0(monkeypatch, capsys):
    plan = _plan({"2026-12-02": [0.01]})
    monkeypatch.setattr(score, "prepare", lambda *a: plan)

    @contextmanager
    def fake_connect(url):
        yield object()

    def held(conn, plan):
        raise locks.Locked(100)

    monkeypatch.setattr(score_db, "connect", fake_connect)
    monkeypatch.setattr(score_db, "write_scores", held)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    rc = score.main(
        ["--start", "2026-12-02", "--write-db", "--database-url", "postgresql://x"]
    )
    out = capsys.readouterr()
    assert rc == 0
    assert "lock (1464878420,100) held by another run — skipping" in out.err
    assert "::notice title=winterpath_ml.score::lock (1464878420,100)" in out.out


# ---- live: real contention between two connections ------------------------------------


@contextmanager
def _holder(sql: str):
    """A second connection holding an advisory xact lock in an open transaction."""
    from test_risk_cell_score_db import URL

    other = score_db.connect(URL)
    try:
        with other.transaction():
            other.execute(sql, (locks.WPET,))
            yield
    finally:
        other.close()


@live
@pytest.mark.parametrize(
    "sql,objid",
    [
        ("SELECT pg_advisory_xact_lock(%s, 100)", 100),  # another scoring run
        ("SELECT pg_advisory_xact_lock(%s, 0)", 0),  # a migration (exclusive gate)
    ],
)
def test_live_contention_skips_cleanly(db, sql, objid):  # noqa: F811 - imported fixture
    conn, mid = db
    with _holder(sql):
        with pytest.raises(locks.Locked) as e:
            score_db.write_scores(
                conn, _plan({"2026-12-02": [0.01, 0.05]}, mid), today=date(2026, 12, 2)
            )
        assert e.value.objid == objid
    assert _rows(conn, "SELECT 1 FROM wp.risk_cell_score WHERE model_id=%s", mid) == []
    assert (
        _rows(conn, "SELECT 1 FROM wp.ingest_run WHERE log->>'model_id'=%s", mid) == []
    )
    # released on the holder's commit: the next run writes
    s = score_db.write_scores(
        conn, _plan({"2026-12-02": [0.01, 0.05]}, mid), today=date(2026, 12, 2)
    )
    assert s["rows_written"] == 2


@live
def test_live_shared_gate_does_not_block_writer(db):  # noqa: F811 - imported fixture
    """Another ETL writer holding the gate SHARED (e.g. a 311 load) does not block scoring."""
    conn, mid = db
    with _holder("SELECT pg_advisory_xact_lock_shared(%s, 0)"):
        s = score_db.write_scores(
            conn, _plan({"2026-12-02": [0.02]}, mid), today=date(2026, 12, 2)
        )
    assert s["rows_written"] == 1
    assert pd.notna(s["ingest_run_id"])
