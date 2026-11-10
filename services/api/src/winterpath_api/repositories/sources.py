"""Data-source inventory (``/data-sources``) and pilot enquiries.

The static registry transcribes docs/data-sources-and-licenses.md (verified 2026-11-10). Without a
database, no source has been ingested by this API instance, so status is ``disabled`` (or
``requires_credentials``) and ``last_success_at``/``record_count`` are null — never invented.
When PostGIS is configured, ``wp.source`` (Data agent) is authoritative.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

CC_BY_4 = "https://creativecommons.org/licenses/by/4.0/"
MTL_ATTR = "Contient des données de la Ville de Montréal, sous licence CC BY 4.0"
NOT_INGESTED = "Not ingested by this API instance (no database configured)."

STATIC_SOURCES: list[dict[str, Any]] = [
    {
        "id": "osm",
        "name": "OpenStreetMap data",
        "publisher": "OpenStreetMap Foundation / contributors",
        "license": "ODbL 1.0",
        "license_url": "https://opendatacommons.org/licenses/odbl/1-0/",
        "commercial_use": "allowed_with_conditions",
        "attribution": "© OpenStreetMap contributors (ODbL)",
        "url": "https://www.openstreetmap.org/copyright",
        "status": "disabled",
    },
    {
        "id": "mtl-voirie",
        "name": "Trottoir et îlot (Voirie)",
        "publisher": "Ville de Montréal",
        "license": "CC BY 4.0",
        "license_url": CC_BY_4,
        "commercial_use": "allowed_with_conditions",
        "attribution": MTL_ATTR,
        "url": "https://www.donneesquebec.ca/recherche/dataset/vmtl-voirie-trottoir-ilot",
        "status": "disabled",
    },
    {
        "id": "mtl-311",
        "name": "Requêtes 311",
        "publisher": "Ville de Montréal",
        "license": "CC BY 4.0",
        "license_url": CC_BY_4,
        "commercial_use": "allowed_with_conditions",
        "attribution": MTL_ATTR,
        "url": "https://www.donneesquebec.ca/recherche/dataset/vmtl-requete-311",
        "status": "disabled",
    },
    {
        "id": "mtl-entraves",
        "name": "Entraves et travaux en cours",
        "publisher": "Ville de Montréal",
        "license": "CC BY 4.0",
        "license_url": CC_BY_4,
        "commercial_use": "allowed_with_conditions",
        "attribution": MTL_ATTR,
        "url": "https://www.donneesquebec.ca/recherche/dataset/vmtl-info-travaux",
        "status": "disabled",
    },
    {
        "id": "mtl-planif-neige",
        "name": "Déneigement / Planif-Neige",
        "publisher": "Ville de Montréal",
        "license": "CC BY 4.0",
        "license_url": CC_BY_4,
        "commercial_use": "allowed_with_conditions",
        "attribution": MTL_ATTR,
        "url": "https://www.donneesquebec.ca/recherche/dataset/vmtl-deneigement",
        "status": "requires_credentials",
        "notes": "Token required. Street snow-loading plans do not certify sidewalk clearance.",
    },
    {
        "id": "eccc-geomet",
        "name": "MSC GeoMet OGC API",
        "publisher": "Environment and Climate Change Canada",
        "license": "ECCC Data Servers End-use Licence",
        "license_url": "https://eccc-msc.github.io/open-data/licence/readme_en/",
        "commercial_use": "allowed_with_conditions",
        "attribution": "Data Source: Environment and Climate Change Canada",
        "url": "https://api.weather.gc.ca/",
        "status": "disabled",
        "notes": "Licence version mismatch noted (page header v2.1.1 vs §9 v2.1). Alerts are "
        "reproduced without alteration.",
    },
]


def static_sources() -> list[dict[str, Any]]:
    out = []
    for s in STATIC_SOURCES:
        row = {"last_success_at": None, "record_count": None, "notes": NOT_INGESTED, **s}
        if "notes" in s:
            row["notes"] = f"{s['notes']} {NOT_INGESTED}"
        out.append(row)
    return out


class SourceRepository(Protocol):
    def list(self) -> list[dict[str, Any]]: ...


class StaticSourceRepository:
    def list(self) -> list[dict[str, Any]]:
        return static_sources()


class PostgisSourceRepository:
    SQL = (
        "SELECT source_id AS id, name, publisher, license, license_url, commercial_use,"
        " attribution, url, status, last_success_at, notes FROM wp.source ORDER BY source_id"
    )

    def __init__(self, engine) -> None:
        self.engine = engine

    def list(self) -> list[dict[str, Any]]:
        from sqlalchemy import text

        with self.engine.connect() as conn:
            rows = [dict(m) for m in conn.execute(text(self.SQL)).mappings()]
        for r in rows:
            r.setdefault("record_count", None)
        return rows


# ----------------------------------------------------------------------------- pilot requests
@dataclass(frozen=True, slots=True)
class PilotRequestRow:
    id: uuid.UUID
    organization: str
    contact_name: str | None
    contact_email: str
    segment: str
    message: str | None
    locale: str | None
    created_at: datetime


class PilotRequestRepository(Protocol):
    def create(self, row: PilotRequestRow) -> None: ...


class InMemoryPilotRequestRepository:
    def __init__(self) -> None:
        self.rows: list[PilotRequestRow] = []
        self._lock = threading.Lock()

    def create(self, row: PilotRequestRow) -> None:
        with self._lock:
            self.rows.append(row)


class PostgisPilotRequestRepository:
    def __init__(self, engine) -> None:
        self.engine = engine

    def create(self, row: PilotRequestRow) -> None:
        from sqlalchemy import text

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO wp.pilot_request (id, organization, contact_name, contact_email,"
                    " segment, message, locale, created_at) VALUES (:id, :org, :name, :email,"
                    " :seg, :msg, :loc, :ts)"
                ),
                {
                    "id": row.id,
                    "org": row.organization,
                    "name": row.contact_name,
                    "email": row.contact_email,
                    "seg": row.segment,
                    "msg": row.message,
                    "loc": row.locale,
                    "ts": row.created_at,
                },
            )
