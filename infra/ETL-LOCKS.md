# ETL advisory locks — proposal (Platform, v2 Wave 1)

**Status:** proposal for **Data** (owner of `services/ingestion` and the migrations) and **ML** (owner of `score_db.write_scores`). Platform does not edit their code. Nothing here is implemented yet.

## Why
GitHub `concurrency:` groups (`scheduled.yml`) only stop a job from overlapping **with itself** inside one workflow. They do not cover:
- a manual operator run (`wp-ingest load` from a laptop);
- a second workflow, such as a future 311 or entraves job or a backfill;
- a migration running while a load is in progress;
- weather and scoring running at the same time if they ever share tables.

The database is the one place every writer passes through, so exclusion belongs there.

## Mechanism
Postgres advisory locks in the two-key form `(classid int4, objid int4)`, **transaction-scoped**:
- `pg_try_advisory_xact_lock(classid, objid)` for exclusive access;
- `pg_try_advisory_xact_lock_shared(...)` for shared access.

Why transaction-scoped:
- **Supabase poolers.** On the *transaction* pooler (port 6543) a session-level lock is unsafe: the server connection goes back to the pool after each transaction, so the lock either outlives the job or is held by an unrelated client. Transaction-scoped locks are correct on both the session pooler (5432) and the transaction pooler.
- They release automatically on `COMMIT`, `ROLLBACK` or connection loss, so a crashed runner never leaves a lock behind.
- Loads already run as "staging + swap in one transaction" (data-model.md), so the lock lives inside that transaction.

**Exception:** if a load must span several transactions (e.g. a long staging COPY committed separately), use a session-level `pg_try_advisory_lock` on **one dedicated connection through the session pooler (5432)**. Release it in `finally` with `pg_advisory_unlock`. The ETL secret already points at the session pooler (render.yaml and scheduled.yml comments).

## Key scheme
`classid = 1464878420` (`0x57504554`, ASCII "WPET": the WinterPath ETL namespace). This avoids colliding with any other advisory-lock user in the same database. Never change it.

| objid | Resource | Taken by | Mode |
|---|---|---|---|
| 0 | **schema gate** | every ETL/ML writer, first | shared (`…_xact_lock_shared`) |
| 0 | **schema gate** | Alembic migrations (`env.py`) | exclusive (`pg_advisory_xact_lock`, blocking, with `lock_timeout`) |
| 1 | `osm` (wp.node / wp.edge swap) | `wp-ingest load --source osm` | exclusive |
| 2 | `mtl-voirie` | `--source mtl-voirie` | exclusive |
| 3 | `mtl-entraves` | `--source mtl-entraves` | exclusive |
| 4 | `mtl-311` (wp.report_311_cell) | `--source mtl-311` | exclusive |
| 5 | `eccc-geomet` (wp.weather_obs / wp.weather_daily) | `--source eccc-geomet` (scheduled weather job) | exclusive |
| 100 | `wp.risk_cell_score` | `winterpath_ml.score --write-db` | exclusive |
| 101 | `wp.edge_risk` | ML, if ever written | exclusive |
| 900 | community-report retention purge (future) | retention job | exclusive |
| 1000–1999 | reserved: v2 island builds (`wp_island`, staging DBs) | Data/Routing | exclusive |

Rules:
- **Fixed acquisition order:** the schema gate (shared) first, then the resource lock. Never two resource locks in one transaction. This rules out deadlocks.
- Ids are **stable and never reused**. New sources get the next free id in this table, through the coordinator.
- **Contention:**
  - **Scheduled runs:** try-lock. If not acquired, print `::notice::lock (1464878420,<objid>) held by another run — skipping` and **exit 0**: the other run is doing the same work.
  - **Manual runs:** a `--wait` option uses the blocking form under `SET LOCAL lock_timeout = '5min'`.
  - **Migrations:** block on the exclusive schema gate with `lock_timeout`. If it expires, fail; never run a migration under a live load.

## Sketch (psycopg 3, for Data/ML)
```python
WPET = 1464878420

def guarded(conn, objid: int) -> bool:
    """Call inside the load's transaction. False = another writer holds the lock: skip cleanly."""
    with conn.cursor() as cur:
        cur.execute("select pg_try_advisory_xact_lock_shared(%s, 0)", (WPET,))
        if not cur.fetchone()[0]:
            return False  # a migration holds the schema gate
        cur.execute("select pg_try_advisory_xact_lock(%s, %s)", (WPET, objid))
        return cur.fetchone()[0]
```

## Observability
```sql
select l.objid, l.mode, l.granted, a.pid, a.application_name, now() - a.xact_start as held_for
from pg_locks l join pg_stat_activity a using (pid)
where l.locktype = 'advisory' and l.classid = 1464878420;
```
The daily integrity job (infra/MONITORING.md) reports any WPET lock held for longer than 2 h. That signals a stuck runner.

## Open questions for Data / ML
1. Does every loader's staging + swap fit in one transaction (→ xact lock), or does any source need the session-lock exception?
2. Should `wp.ingest_run` record `skipped_locked` as a status, so contention is visible in the run history?
3. ML: does `write_scores` replace a (day, model_id) partition in one transaction (the docstring says yes)? Then lock 100 goes inside that transaction.
