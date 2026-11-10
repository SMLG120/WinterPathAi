"""Community reports: repository interface, in-memory and PostGIS implementations.

Lifecycle (data-model.md ``wp.community_report``): created ``pending`` with ``expires_at`` = +72 h;
only ``approved`` + unexpired reports are ever shown publicly; reporter deletion → ``deleted`` with
description scrubbed; rows are hard-deleted 30 days after reaching a terminal status.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol

REPORT_TTL = timedelta(hours=72)
HARD_DELETE_AFTER = timedelta(days=30)
TERMINAL = frozenset({"rejected", "expired", "deleted"})
DECISION_STATUS = {"approve": "approved", "reject": "rejected", "expire": "expired"}


@dataclass(frozen=True, slots=True)
class StoredReport:
    id: uuid.UUID
    category: str
    lon: float
    lat: float
    description: str | None
    status: str
    created_at: datetime
    expires_at: datetime
    deletion_token_hash: str
    client_hash: str
    moderated_at: datetime | None = None
    moderation_note: str | None = None
    terminal_at: datetime | None = None


class ReportRepository(Protocol):
    def create(
        self,
        *,
        category: str,
        lon: float,
        lat: float,
        description: str | None,
        deletion_token_hash: str,
        client_hash: str,
        now: datetime,
    ) -> StoredReport: ...

    def get(self, report_id: uuid.UUID, now: datetime) -> StoredReport | None: ...

    def delete_own(self, report_id: uuid.UUID, now: datetime) -> bool: ...

    def list(
        self,
        status: str | None,
        limit: int,
        after: tuple[datetime, uuid.UUID] | None,
        now: datetime,
    ) -> list[StoredReport]: ...

    def moderate(
        self, report_id: uuid.UUID, decision: str, note: str | None, now: datetime
    ) -> StoredReport | None: ...

    def approved_active(self, now: datetime) -> list[StoredReport]: ...

    def purge(self, now: datetime) -> int: ...

    def ping(self) -> bool: ...


class InMemoryReportRepository:
    def __init__(self) -> None:
        self._rows: dict[uuid.UUID, StoredReport] = {}
        self._lock = threading.Lock()

    def _expire(self, r: StoredReport, now: datetime) -> StoredReport:
        if r.status in ("pending", "approved") and r.expires_at <= now:
            r = replace(r, status="expired", terminal_at=now)
            self._rows[r.id] = r
        return r

    def create(self, *, category, lon, lat, description, deletion_token_hash, client_hash, now):
        r = StoredReport(
            id=uuid.uuid4(),
            category=category,
            lon=lon,
            lat=lat,
            description=description,
            status="pending",
            created_at=now,
            expires_at=now + REPORT_TTL,
            deletion_token_hash=deletion_token_hash,
            client_hash=client_hash,
        )
        with self._lock:
            self._rows[r.id] = r
        return r

    def get(self, report_id, now):
        with self._lock:
            r = self._rows.get(report_id)
            return self._expire(r, now) if r else None

    def delete_own(self, report_id, now):
        with self._lock:
            r = self._rows.get(report_id)
            if r is None or r.status == "deleted":
                return False
            self._rows[report_id] = replace(r, status="deleted", description=None, terminal_at=now)
            return True

    def list(self, status, limit, after, now):
        with self._lock:
            rows = [self._expire(r, now) for r in list(self._rows.values())]
        rows = [r for r in rows if status is None or r.status == status]
        rows.sort(key=lambda r: (r.created_at, r.id))
        if after is not None:
            rows = [r for r in rows if (r.created_at, r.id) > after]
        return rows[:limit]

    def moderate(self, report_id, decision, note, now):
        with self._lock:
            r = self._rows.get(report_id)
            if r is None or r.status == "deleted":
                return None
            r = self._expire(r, now)
            new = DECISION_STATUS[decision]
            r = replace(
                r,
                status=new,
                moderated_at=now,
                moderation_note=note,
                terminal_at=now if new in TERMINAL else None,
            )
            self._rows[report_id] = r
            return r

    def approved_active(self, now):
        with self._lock:
            return [
                r
                for r in (self._expire(x, now) for x in list(self._rows.values()))
                if r.status == "approved"
            ]

    def purge(self, now):
        with self._lock:
            for r in list(self._rows.values()):
                self._expire(r, now)
            dead = [
                k
                for k, r in self._rows.items()
                if r.terminal_at is not None and r.terminal_at + HARD_DELETE_AFTER <= now
            ]
            for k in dead:
                del self._rows[k]
            return len(dead)

    def ping(self) -> bool:
        return True


class PostgisReportRepository:
    """``wp.community_report`` (schema owned by the Data agent's migrations).

    ``terminal_at`` is not a contract column; the 30-day hard delete uses ``moderated_at`` for
    moderated rows and ``expires_at`` for expired/deleted rows (see change request in the report).
    """

    COLS = (
        "report_id, category, ST_X(geom) AS lon, ST_Y(geom) AS lat, description, status, "
        "created_at, expires_at, deletion_token_hash, client_hash, moderated_at, moderation_note"
    )

    def __init__(self, engine) -> None:
        self.engine = engine

    @staticmethod
    def _row(m) -> StoredReport:
        return StoredReport(
            id=m["report_id"],
            category=m["category"],
            lon=float(m["lon"]) if m["lon"] is not None else 0.0,
            lat=float(m["lat"]) if m["lat"] is not None else 0.0,
            description=m["description"],
            status=m["status"],
            created_at=m["created_at"],
            expires_at=m["expires_at"],
            deletion_token_hash=m["deletion_token_hash"],
            client_hash=m["client_hash"],
            moderated_at=m["moderated_at"],
            moderation_note=m["moderation_note"],
        )

    def _expire_sql(self, conn, now) -> None:
        from sqlalchemy import text

        conn.execute(
            text(
                "UPDATE wp.community_report SET status='expired' "
                "WHERE status IN ('pending','approved') AND expires_at <= :now"
            ),
            {"now": now},
        )

    def create(self, *, category, lon, lat, description, deletion_token_hash, client_hash, now):
        from sqlalchemy import text

        rid = uuid.uuid4()
        with self.engine.begin() as conn:
            m = (
                conn.execute(
                    text(
                        "INSERT INTO wp.community_report (report_id, category, geom, description,"
                        " status, created_at, expires_at, deletion_token_hash, client_hash) VALUES"
                        " (:id, :cat, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :desc,"
                        " 'pending', :now, :exp, :dth, :ch) RETURNING " + self.COLS
                    ),
                    {
                        "id": rid,
                        "cat": category,
                        "lon": lon,
                        "lat": lat,
                        "desc": description,
                        "now": now,
                        "exp": now + REPORT_TTL,
                        "dth": deletion_token_hash,
                        "ch": client_hash,
                    },
                )
                .mappings()
                .one()
            )
        return self._row(m)

    def get(self, report_id, now):
        from sqlalchemy import text

        with self.engine.begin() as conn:
            self._expire_sql(conn, now)
            m = (
                conn.execute(
                    text(f"SELECT {self.COLS} FROM wp.community_report WHERE report_id = :id"),  # noqa: S608
                    {"id": report_id},
                )
                .mappings()
                .first()
            )
        return self._row(m) if m else None

    def delete_own(self, report_id, now):
        from sqlalchemy import text

        with self.engine.begin() as conn:
            res = conn.execute(
                text(
                    "UPDATE wp.community_report SET status='deleted', description=NULL "
                    "WHERE report_id=:id AND status <> 'deleted'"
                ),
                {"id": report_id},
            )
        return res.rowcount == 1

    def list(self, status, limit, after, now):
        from sqlalchemy import text

        where = ["(:status IS NULL OR status = :status)"]
        params: dict = {"status": status, "limit": limit}
        if after is not None:
            where.append("(created_at, report_id) > (:a_ts, :a_id)")
            params.update(a_ts=after[0], a_id=after[1])
        sql = (
            f"SELECT {self.COLS} FROM wp.community_report WHERE {' AND '.join(where)} "  # noqa: S608
            "ORDER BY created_at, report_id LIMIT :limit"
        )
        with self.engine.begin() as conn:
            self._expire_sql(conn, now)
            rows = conn.execute(text(sql), params).mappings().all()
        return [self._row(m) for m in rows]

    def moderate(self, report_id, decision, note, now):
        from sqlalchemy import text

        with self.engine.begin() as conn:
            m = (
                conn.execute(
                    text(
                        # COLS is a class constant (no user input); values are bound params.
                        "UPDATE wp.community_report SET status=:st, moderated_at=:now,"  # noqa: S608
                        " moderation_note=:note WHERE report_id=:id AND status <> 'deleted'"
                        " RETURNING " + self.COLS
                    ),
                    {"st": DECISION_STATUS[decision], "now": now, "note": note, "id": report_id},
                )
                .mappings()
                .first()
            )
        return self._row(m) if m else None

    def approved_active(self, now):
        from sqlalchemy import text

        with self.engine.begin() as conn:
            rows = (
                conn.execute(
                    text(
                        f"SELECT {self.COLS} FROM wp.community_report "  # noqa: S608
                        "WHERE status='approved' AND expires_at > :now"
                    ),
                    {"now": now},
                )
                .mappings()
                .all()
            )
        return [self._row(m) for m in rows]

    def purge(self, now):
        from sqlalchemy import text

        with self.engine.begin() as conn:
            self._expire_sql(conn, now)
            res = conn.execute(
                text(
                    "DELETE FROM wp.community_report WHERE status IN ('rejected','expired',"
                    "'deleted') AND COALESCE(moderated_at, expires_at) + interval '30 days' <= :now"
                ),
                {"now": now},
            )
        return res.rowcount

    def ping(self) -> bool:
        from sqlalchemy import text

        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
