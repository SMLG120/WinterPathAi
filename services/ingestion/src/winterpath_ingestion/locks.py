"""ETL advisory locks — implements Platform's scheme (infra/ETL-LOCKS.md, v2 Wave 1).

Two-key Postgres advisory locks `(classid, objid)` with classid WPET = 1464878420 ("WPET").
- objid 0 = schema gate: every ETL writer takes it SHARED, first; migrations take it EXCLUSIVE
  (db/migrations/env.py, session-level on a dedicated connection for the whole run).
- objid 1..5 = one per source (table below); never two resource locks in one transaction.
- Island builds use the reserved 1000–1999 range: the island graph load is 1000 + osm (1001).

Loads take the locks TRANSACTION-scoped inside their existing single staging + swap transaction,
so COMMIT / ROLLBACK / a lost connection always releases them (safe on Supabase poolers).

Contention: default is try-lock → `Locked` → the caller skips cleanly (scheduled runs exit 0 and
print `::notice::lock (1464878420,<objid>) held by another run — skipping`). With `wait=True`
(manual `--wait`) the blocking form is used under `SET LOCAL lock_timeout`, and a timeout is an
error (psycopg.errors.LockNotAvailable), never a silent skip.

Advisory locks are per database: wp_data and wp_island never contend with each other.
"""

from __future__ import annotations

WPET = 1464878420  # 0x57504554 "WPET" — never change
SCHEMA_GATE = 0
SOURCE_LOCKS = {"osm": 1, "mtl-voirie": 2, "mtl-entraves": 3, "mtl-311": 4, "eccc-geomet": 5}
ISLAND_OFFSET = 1000
DEFAULT_WAIT_TIMEOUT = "5min"


class Locked(Exception):
    """Another run holds (WPET, objid). Raised inside the load transaction → rolled back."""

    def __init__(self, objid: int):
        super().__init__(f"lock ({WPET},{objid}) held by another run")
        self.objid = objid

    @property
    def notice(self) -> str:
        return f"::notice::lock ({WPET},{self.objid}) held by another run — skipping"


def objid_for(source_id: str, *, island: bool = False) -> int:
    base = SOURCE_LOCKS[source_id]
    return ISLAND_OFFSET + base if island else base


def acquire(cur, objid: int | None, *, wait: bool = False, timeout: str | None = None):
    """Inside an open transaction: schema gate (shared), then the resource lock (exclusive).
    objid None → schema gate only (e.g. the wp.source registry upsert)."""
    if wait:
        t = timeout or DEFAULT_WAIT_TIMEOUT
        cur.execute("SELECT set_config('lock_timeout', %s, true)", (t,))
        cur.execute("SELECT pg_advisory_xact_lock_shared(%s, %s)", (WPET, SCHEMA_GATE))
        if objid is not None:
            cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (WPET, objid))
        return
    cur.execute("SELECT pg_try_advisory_xact_lock_shared(%s, %s)", (WPET, SCHEMA_GATE))
    if not cur.fetchone()[0]:
        raise Locked(SCHEMA_GATE)
    if objid is not None:
        cur.execute("SELECT pg_try_advisory_xact_lock(%s, %s)", (WPET, objid))
        if not cur.fetchone()[0]:
            raise Locked(objid)
