"""Hazards for the map and for routing.

* closures/impacts (``wp.closure``) → evidence ``confirmed``; ``blocks_passage`` only as the source
  states it.
* 311 aggregates (``wp.report_311_cell``) → evidence ``unverified_report``; cells with n < 3 per
  day are suppressed (k-anonymity floor, data-model.md).
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


class PostgisHazardRepository:
    def __init__(self, engine, reports: ReportRepository) -> None:
        self.engine = engine
        self.reports = reports

    def list(self, at: datetime) -> list[Hazard]:
        import json

        import h3
        from sqlalchemy import text

        out: list[Hazard] = []
        with self.engine.connect() as conn:
            for m in conn.execute(
                text(
                    "SELECT closure_id, ST_AsGeoJSON(geom) AS g, sidewalk_blockedtype,"
                    " blocks_passage, valid_from, valid_to, status, source_id FROM wp.closure"
                    " WHERE (valid_from IS NULL OR valid_from <= :at)"
                    " AND (valid_to IS NULL OR valid_to >= :at)"
                ),
                {"at": at},
            ).mappings():
                blocks = m["blocks_passage"]
                out.append(
                    Hazard(
                        hazard_id=m["closure_id"],
                        kind=HazardKind.SIDEWALK_CLOSURE
                        if blocks is True
                        else HazardKind.CONSTRUCTION_IMPACT,
                        geometry=json.loads(m["g"]),
                        evidence=Evidence(
                            EvidenceState.CONFIRMED,
                            (m["source_id"],),
                            observed_at=m["valid_from"],
                            note=f"sidewalk_blockedtype={m['sidewalk_blockedtype']}",
                        ),
                        blocks_passage=blocks,
                        valid_from=m["valid_from"],
                        valid_to=m["valid_to"],
                        title_en="Permitted work zone",
                        title_fr="Zone de travaux autorisée",
                    )
                )
            rows = conn.execute(
                text(
                    "SELECT h3, category, SUM(n) AS n, MIN(day) AS d0, MAX(day) AS d1"
                    " FROM wp.report_311_cell WHERE day > :d0 AND day <= :d1 AND n >= :k"
                    " GROUP BY h3, category"
                ),
                {"d0": (at - REPORT_311_WINDOW).date(), "d1": at.date(), "k": K_ANONYMITY_FLOOR},
            ).mappings()
            for m in rows:
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
                        title_en=f"311 reports: {m['category']}",
                        title_fr=f"Requêtes 311 : {m['category']}",
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
