"""Writer for `wp.risk_cell_score` (contract v1.7.0, Data migration 0007).

One run is one transaction:
0. take the ETL advisory locks (infra/ETL-LOCKS.md): the shared schema gate (WPET, 0), then the
   try-lock (WPET, 100) for wp.risk_cell_score. If either is held, `locks.Locked` is raised,
   nothing is written and no ingest_run row is recorded (the caller skips with a notice, exit 0),
1. insert the `wp.ingest_run` row,
2. for every scored day, DELETE that (day, model_id) partition and COPY the new rows,
3. delete rows whose day is more than RETENTION_DAYS before today (America/Montreal),
4. mark the run succeeded with record_count and a provenance log.
If anything fails, the transaction rolls back (the previous partitions stay intact) and a
`failed` ingest_run row is recorded in a separate transaction (best effort).

`input_checksum` is namespaced (`winterpath_ml.score:<sha256>`) so it can never match a 311
load's file checksum. Data's loader skips a source whose (source_id, input_checksum) already
succeeded. `wp.source.last_success_at` is not touched: it describes the 311 source, not this job.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import date, datetime, timedelta

from . import inference, locks

log = logging.getLogger(__name__)
TABLE = "wp.risk_cell_score"
INGEST_TABLE = "wp.ingest_run"
RETENTION_DAYS = 30
# ingest_run.source_id is an FK to wp.source; the scores derive from 311 (labels/history) + ECCC.
SOURCE_ID = os.environ.get("WP_ML_SCORE_SOURCE_ID", "mtl-311")
COLUMNS = (
    "h3",
    "day",
    "model_id",
    "layer",
    "p",
    "scored_at",
    "data_through",
    "ingest_run_id",
)


def connect(url: str):
    import psycopg

    return psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://", 1))


def run_checksum(model_id: str, days: list[str], source_311: dict | None) -> str:
    basis = json.dumps(
        {"model_id": model_id, "days": sorted(days), "source_311": source_311},
        sort_keys=True,
    )
    return "winterpath_ml.score:" + hashlib.sha256(basis.encode()).hexdigest()


def write_scores(
    conn,
    plan: dict,
    *,
    today: date | None = None,
    table: str = TABLE,
    ingest_table: str = INGEST_TABLE,
    source_id: str = SOURCE_ID,
) -> dict:
    """Replace each scored (day, model_id) partition atomically; returns a summary dict."""
    reg, layer = plan["registry"], plan["layer"]
    model_id = reg["layers"][layer]["id"]
    today = today or datetime.now(inference.LOCAL_TZ).date()
    cutoff = today - timedelta(days=RETENTION_DAYS)
    run_id = uuid.uuid4()
    days = sorted(plan["tables"])
    checksum = run_checksum(model_id, days, plan.get("source_311"))
    prov = {
        "job": "winterpath_ml.score",
        "model_id": model_id,
        "layer": layer,
        "run_id": reg["run_id"],
        "days": days,
        "not_ready": plan.get("not_ready", {}),
        "source_311": plan.get("source_311"),
        "retention_cutoff": str(cutoff),
    }
    try:
        with conn.transaction(), conn.cursor() as cur:
            locks.acquire(cur, locks.RISK_CELL_SCORE)
            cur.execute(
                f"INSERT INTO {ingest_table} (ingest_run_id, source_id, status, started_at, input_checksum)"
                " VALUES (%s, %s, 'running', now(), %s)",
                (run_id, source_id, checksum),
            )
            n = 0
            replaced = {}
            for day in days:
                d = date.fromisoformat(day)
                cur.execute(
                    f"DELETE FROM {table} WHERE day = %s AND model_id = %s",
                    (d, model_id),
                )
                replaced[day] = cur.rowcount
                t = plan["tables"][day]
                with cur.copy(f"COPY {table} ({', '.join(COLUMNS)}) FROM STDIN") as cp:
                    for h, p, at, thru in zip(
                        t["h3"], t["p"], t["scored_at"], t["data_through"]
                    ):
                        cp.write_row(
                            (
                                h,
                                d,
                                model_id,
                                layer,
                                float(p),
                                datetime.fromisoformat(str(at)),
                                datetime.fromisoformat(str(thru)),
                                run_id,
                            )
                        )
                n += len(t)
            cur.execute(f"DELETE FROM {table} WHERE day < %s", (cutoff,))
            expired = cur.rowcount
            prov.update(rows_replaced=replaced, rows_expired=expired)
            cur.execute(
                f"UPDATE {ingest_table} SET status='succeeded', finished_at=now(),"
                " record_count=%s, log=%s::jsonb WHERE ingest_run_id=%s",
                (n, json.dumps(prov), run_id),
            )
    except locks.Locked:
        raise  # another run is doing this work: nothing written, nothing to record
    except Exception as e:
        try:
            with conn.transaction(), conn.cursor() as cur:
                locks.acquire(cur, None)  # schema gate only; Locked → skip recording
                cur.execute(
                    f"INSERT INTO {ingest_table} (ingest_run_id, source_id, status, started_at,"
                    " finished_at, input_checksum, record_count, log)"
                    " VALUES (%s, %s, 'failed', now(), now(), %s, 0, %s::jsonb)",
                    (
                        run_id,
                        source_id,
                        checksum,
                        json.dumps({**prov, "error": f"{type(e).__name__}: {e}"}),
                    ),
                )
        except Exception as rec:  # noqa: BLE001 - incl. Locked; recording the failure must not mask the original error
            log.warning("score_ingest_run_failed_record_error: %s", type(rec).__name__)
        raise
    return {
        "ingest_run_id": str(run_id),
        "model_id": model_id,
        "rows_written": n,
        "rows_replaced": replaced,
        "rows_expired": expired,
        "retention_cutoff": str(cutoff),
    }


def newest_day(conn, model_id: str, table: str = TABLE) -> date | None:
    with conn.cursor() as cur:
        cur.execute(f"SELECT max(day) FROM {table} WHERE model_id = %s", (model_id,))
        return cur.fetchone()[0]
