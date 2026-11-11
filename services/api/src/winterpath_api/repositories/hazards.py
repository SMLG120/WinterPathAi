"""Hazards for the map and for routing.

* closures/impacts (``wp.closure``) → evidence ``confirmed``; ``blocks_passage`` only as the source
  states it. Activity at the requested time comes from ``wp.closure_active_at(c, t)``
  (data-model v1.4, three-valued): ``false`` rows are dropped, ``true`` → ``Hazard.active=True``,
  ``NULL`` → ``Hazard.active=None`` (unknown — flagged and penalised by routing, never clear).
  Databases without the function (pre-migration 0004) fall back to the validity window only.
* 311 aggregates (``wp.report_311_cell``) → evidence ``unverified_report``. Data-model v1.5: rows
  are per ``nature``; we ``SUM(n)`` over ``nature IN ('requete','plainte')`` per (cell, day,
  category) and only then apply the k-anonymity floor (sums < 3 suppressed). Tables without the
  ``nature`` column (pre-v1.5) are summed as they are.
* approved community reports → evidence ``unverified_report``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Protocol

from winterpath_routing import Evidence, EvidenceState, Hazard, HazardKind

from .reports import ReportRepository, StoredReport

K_ANONYMITY_FLOOR = 3
REPORT_311_WINDOW = timedelta(days=3)

CATEGORY_TITLES = {
    "snow": ("Community report: snow", "Signalement citoyen : neige"),
    "ice": ("Community report: ice", "Signalement citoyen : glace"),
    "obstructed_ramp": (
        "Community report: obstructed ramp",
        "Signalement citoyen : rampe obstruée",
    ),
    "construction": ("Community report: construction", "Signalement citoyen : travaux"),
    "other": ("Community report", "Signalement citoyen"),
}


def community_hazard(r: StoredReport) -> Hazard:
    en, fr = CATEGORY_TITLES.get(r.category, CATEGORY_TITLES["other"])
    return Hazard(
        hazard_id=f"community:{r.id}",
        kind=HazardKind.COMMUNITY_REPORT,
        geometry={"type": "Point", "coordinates": [round(r.lon, 6), round(r.lat, 6)]},
        evidence=Evidence(
            EvidenceState.UNVERIFIED_REPORT,
            ("community",),
            observed_at=r.created_at,
            note="Moderated community report; not verified on site.",
        ),
        blocks_passage=None,
        valid_from=r.created_at,
        valid_to=r.expires_at,
        title_en=en,
        title_fr=fr,
    )


class HazardRepository(Protocol):
    def list(self, at: datetime) -> list[Hazard]:
        """All hazards relevant at ``at`` (any kind), for map display and routing."""
        ...

    def freshness(self) -> dict[str, datetime | None]: ...


class InMemoryHazardRepository:
    """Static hazard list (empty by default — no invented hazards) + approved community reports."""

    def __init__(self, reports: ReportRepository, hazards: Sequence[Hazard] = ()) -> None:
        self.reports = reports
        self.hazards = list(hazards)

    def list(self, at: datetime) -> list[Hazard]:
        out = [h for h in self.hazards if h.active_at(at)]
        out.extend(community_hazard(r) for r in self.reports.approved_active(at))
        return out

    def freshness(self) -> dict[str, datetime | None]:
        return {}


REPORT_311_NATURES = ("requete", "plainte")
#: data-model canonical categories (v1.5; alley categories v1.6, CR-ML-2) → (en, fr) titles;
#: unknown names are shown verbatim.
CATEGORY_311_TITLES = {
    "sidewalk_slippery": ("311 reports: slippery sidewalk", "Requêtes 311 : trottoir glissant"),
    "roadway_slippery": ("311 reports: slippery roadway", "Requêtes 311 : chaussée glissante"),
    "snow_clearing": ("311 reports: snow clearing", "Requêtes 311 : déneigement"),
    "snow_dumping": ("311 reports: snow dumping", "Requêtes 311 : dépôt de neige"),
    "snow_clearing_alley": (
        "311 reports: snow clearing (alley)",
        "Requêtes 311 : déneigement (ruelle)",
    ),
    "snow_dumping_alley": (
        "311 reports: snow dumping (alley)",
        "Requêtes 311 : dépôt de neige (ruelle)",
    ),
}


def report_311_sql(table: str, has_nature: bool) -> str:
    """Per-day sums over the public natures, floor applied after summing, then the window sum."""
    nature = " AND nature IN ('requete','plainte')" if has_nature else ""
    return (
        "SELECT h3, category, SUM(n) AS n, MIN(day) AS d0, MAX(day) AS d1 FROM ("  # noqa: S608
        f" SELECT h3, day, category, SUM(n) AS n FROM {table}"
        f" WHERE day > :d0 AND day <= :d1{nature}"
        " GROUP BY h3, day, category HAVING SUM(n) >= :k"
        ") per_day GROUP BY h3, category"
    )


CLOSURE_COLS = (
    "c.closure_id, ST_AsGeoJSON(c.geom) AS g, c.sidewalk_blockedtype, c.blocks_passage,"
    " c.valid_from, c.valid_to, c.status, c.source_id"
)
CLOSURE_SQL_V14 = (
    f"SELECT {CLOSURE_COLS}, wp.closure_active_at(c, :at) AS active FROM wp.closure c"  # noqa: S608
    " WHERE wp.closure_active_at(c, :at) IS DISTINCT FROM false"
)
CLOSURE_SQL_LEGACY = (
    f"SELECT {CLOSURE_COLS}, TRUE AS active FROM wp.closure c"  # noqa: S608
    " WHERE (c.valid_from IS NULL OR c.valid_from <= :at)"
    " AND (c.valid_to IS NULL OR c.valid_to >= :at)"
)
HAS_ACTIVE_FN = (
    "SELECT to_regprocedure('wp.closure_active_at(wp.closure, timestamp with time zone)')"
    " IS NOT NULL"
)


def closure_hazard(m) -> Hazard:
    import json

    blocks, active = m["blocks_passage"], m["active"]
    note = f"sidewalk_blockedtype={m['sidewalk_blockedtype']}"
    title_en, title_fr = "Permitted work zone", "Zone de travaux autorisée"
    if active is None:
        note += "; activity at the requested time unknown (permit schedule not established)"
        title_en += " — schedule at this time unknown"
        title_fr += " — horaire à ce moment inconnu"
    return Hazard(
        hazard_id=m["closure_id"],
        kind=HazardKind.SIDEWALK_CLOSURE if blocks is True else HazardKind.CONSTRUCTION_IMPACT,
        geometry=json.loads(m["g"]),
        evidence=Evidence(
            EvidenceState.CONFIRMED,
            (m["source_id"],),
            observed_at=m["valid_from"],
            note=note,
        ),
        blocks_passage=blocks,
        valid_from=m["valid_from"],
        valid_to=m["valid_to"],
        title_en=title_en,
        title_fr=title_fr,
        active=None if active is None else bool(active),
    )


class PostgisHazardRepository:
    def __init__(
        self, engine, reports: ReportRepository, report_311_table: str = "wp.report_311_cell"
    ) -> None:
        self.engine = engine
        self.reports = reports
        self.report_311_table = report_311_table  # constant (tests may point it at a temp table)
        self._has_active_fn: bool | None = None
        self._has_nature: bool | None = None

    def list(self, at: datetime) -> list[Hazard]:

        import h3
        from sqlalchemy import text

        out: list[Hazard] = []
        with self.engine.connect() as conn:
            if self._has_active_fn is None:
                self._has_active_fn = bool(conn.execute(text(HAS_ACTIVE_FN)).scalar())
            sql = CLOSURE_SQL_V14 if self._has_active_fn else CLOSURE_SQL_LEGACY
            for m in conn.execute(text(sql), {"at": at}).mappings():
                out.append(closure_hazard(m))
            if self._has_nature is None:
                cols = conn.execute(text(f"SELECT * FROM {self.report_311_table} LIMIT 0"))  # noqa: S608
                self._has_nature = "nature" in cols.keys()
            rows = conn.execute(
                text(report_311_sql(self.report_311_table, self._has_nature)),
                {"d0": (at - REPORT_311_WINDOW).date(), "d1": at.date(), "k": K_ANONYMITY_FLOOR},
            ).mappings()
            for m in rows:
                cat = m["category"]
                titles = CATEGORY_311_TITLES.get(
                    cat, (f"311 reports: {cat}", f"Requêtes 311 : {cat}")
                )
                ring = [[lng, lat] for lat, lng in h3.cell_to_boundary(m["h3"])]
                ring.append(ring[0])
                d0 = datetime.combine(m["d0"], datetime.min.time(), tzinfo=at.tzinfo)
                d1 = datetime.combine(m["d1"], datetime.max.time(), tzinfo=at.tzinfo)
                out.append(
                    Hazard(
                        hazard_id=f"311:{m['h3']}:{m['category']}",
                        kind=HazardKind.REPORT_311_AGGREGATE,
                        geometry={"type": "Polygon", "coordinates": [ring]},
                        evidence=Evidence(
                            EvidenceState.UNVERIFIED_REPORT,
                            ("mtl-311",),
                            observed_at=d1,
                            note="Aggregated 311 requests (reports, not confirmed obstacles).",
                        ),
                        blocks_passage=None,
                        valid_from=d0,
                        valid_to=d1,
                        title_en=titles[0],
                        title_fr=titles[1],
                        report_count=int(m["n"]),
                    )
                )
        out.extend(community_hazard(r) for r in self.reports.approved_active(at))
        return out

    def freshness(self) -> dict[str, datetime | None]:
        from sqlalchemy import text

        with self.engine.connect() as conn:
            rows = conn.execute(text("SELECT source_id, last_success_at FROM wp.source")).all()
        return {r[0]: r[1] for r in rows}
