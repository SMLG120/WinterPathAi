"""Ville de Laval "Chantiers routiers" (permis d'obstruction) → closures.

Licence: CC BY 4.0 (CKAN `chantiers-routiers`, organization ville-de-laval, license_id=cc-by,
verified 2026-11-17). Evidence state: `confirmed` for the obstruction record itself (official
city data) — NOT for any sidewalk status.

Honesty rules applied here:
* The feed has no pedestrian-passage field. `blocks_passage` is therefore always null
  (unknown); a roadway closure ("Rue barrée", "Fermeture complète") never implies a sidewalk
  closure, and free text (REMARQUE/LOCALISATION) is never parsed into certainty.
* The one explicit sidewalk signal is `ENTRAVE = "Trottoir"` (obstruction located on the
  sidewalk; 81 of 35,784 features in the 2026-11-17 file). It is kept verbatim in
  `sidewalk_blockedtype` so consumers see the sidewalk is affected; it does not say passage is
  blocked, so `blocks_passage` stays null (contract: null is flagged, never treated as clear).
* The feed has no identifier: `closure_id` = `laval:<sha1[:16] of the canonical feature>`
  (stable while the publisher's record is unchanged; byte-identical duplicate features are
  collapsed and counted).
* Geometry is the published (Multi)LineString, kept as is. Street names stay in attrs.
* Dates are published local `MM/DD/YYYY HH:MM:SS` (read as America/Montreal). Missing → null;
  implausible years (< 2000 or > 2100) → null, raw kept in attrs. The feed writes date-only
  values as midnight; a midnight DATE_FIN is read as the END of that day (the final day is not
  turned into a definite "inactive"), flagged `DATE_FIN_date_only_end_of_day`.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import geopandas as gpd
from shapely.geometry import box, shape

from ..config import Settings
from ..http import download
from ..osm.pipeline import write_geojson
from ..runs import RunResult, read_manifest, run_atomic

SOURCE_ID = "laval-chantiers"
DATASET = "https://www.donneesquebec.ca/recherche/dataset/chantiers-routiers"
GEOJSON_URL = (
    "https://www.donneesquebec.ca/recherche/dataset/d41f625c-1bd3-4202-a8c1-50b573b3ade4/"
    "resource/3272909c-7469-4d87-acd2-4831a33d50f4/download/permis-obstruction.geojson"
)
ATTRIBUTION = "Contient des données de la Ville de Laval, sous licence CC BY 4.0"
TZ = ZoneInfo("America/Montreal")
LAVAL_BBOX = (-73.90, 45.46, -73.47, 45.72)  # coarse fallback when the SDA product is absent
MIN_YEAR = 2000
MAX_YEAR = 2100
#: Part of the run checksum: a mapping change must rebuild even if the raw file is unchanged.
MAPPING_VERSION = "laval-chantiers-v2"  # v2: Trottoir, end-of-day DATE_FIN, year bounds

# STATUT values observed 2026-11-17 (35 784 features). Only "Existant" is a live permit; the
# publisher's "Abandonné" covers ~35k historic records (2000-2026), so it is NOT read as
# "cancelled" or "completed" (it may mean either, or archived) → unknown, raw kept.
CLOSURE_STATUS: dict[str, str] = {"Existant": "permit_issued"}
CLOSURE_STATUS_VALUES = ("permit_issued", "cancelled", "completed", "unknown")

# No published field says pedestrians/sidewalk are blocked. Kept as a table so a future field
# can be added explicitly; every raw ENTRAVE value maps to None today.
BLOCKS_PASSAGE_BY_ENTRAVE: dict[str, bool | None] = {}

ATTR_FIELDS = (
    "TYPE",
    "STATUT",
    "DATE_DEBUT",
    "DATE_FIN",
    "REMARQUE",
    "NATURE_TRAVAUX",
    "ALERTE511",
    "CIRCULATION",
    "PUBLIQUE",
    "ENTRAVE",
    "RESPONSABLE",
    "LOCALISATION",
)


def map_status(raw: str | None) -> str:
    return CLOSURE_STATUS.get((raw or "").strip(), "unknown")


#: ENTRAVE values that explicitly place the obstruction on the sidewalk (kept verbatim).
SIDEWALK_ENTRAVE = frozenset({"Trottoir"})


def map_sidewalk_blockedtype(props: dict) -> str | None:
    """The published ENTRAVE value when it names the sidewalk; else null (never inferred)."""
    raw = (props.get("ENTRAVE") or "").strip()
    return raw if raw in SIDEWALK_ENTRAVE else None


def map_blocks_passage(props: dict) -> bool | None:
    """True/False only if a table entry says so for the published ENTRAVE value; else null."""
    return BLOCKS_PASSAGE_BY_ENTRAVE.get((props.get("ENTRAVE") or "").strip())


def parse_date(raw: str | None) -> str | None:
    """`MM/DD/YYYY HH:MM:SS` local America/Montreal → ISO 8601 with offset; bad/absent → None."""
    if not raw or not raw.strip():
        return None
    try:
        dt = datetime.strptime(raw.strip(), "%m/%d/%Y %H:%M:%S")
    except ValueError:
        return None
    if not MIN_YEAR <= dt.year <= MAX_YEAR:
        return None
    return dt.replace(tzinfo=TZ).isoformat()


def parse_end(raw: str | None) -> tuple[str | None, bool]:
    """DATE_FIN → exclusive ``valid_to``. A midnight value is a date without a time: the permit may
    run through that day, so the end is the next local midnight (the cautious direction). Returns
    (iso, date_only)."""
    iso = parse_date(raw)
    if iso is None:
        return None, False
    dt = datetime.fromisoformat(iso)
    if (dt.hour, dt.minute, dt.second) != (0, 0, 0):
        return iso, False
    nxt = (dt.replace(tzinfo=None) + timedelta(days=1)).replace(tzinfo=TZ)
    return nxt.isoformat(), True


def closure_id(feature: dict) -> str:
    blob = json.dumps(
        {"p": feature.get("properties"), "g": feature.get("geometry")},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "laval:" + hashlib.sha1(blob.encode()).hexdigest()[:16]


#: Output columns, the same for an empty run.
COLUMNS = (
    "closure_id",
    "sidewalk_blockedtype",
    "blocks_passage",
    "backsidewalk_blocks_passage",
    "valid_from",
    "valid_to",
    "status",
    "evidence_state",
    "attrs",
    "geometry_note",
    "source_id",
    "geometry",
)


def build_closures(features: list[dict], keep=None, bbox=LAVAL_BBOX):
    """keep(geom) → bool overrides the bbox test (SDA Laval polygon). Returns (gdf, counters)."""
    stats: Counter = Counter()
    unmapped: Counter = Counter()
    region = box(*bbox)
    seen: set[str] = set()
    rows = []
    for f in features:
        g = f.get("geometry")
        if not g:
            stats["no_geometry"] += 1
            continue
        geom = shape(g)
        if geom.is_empty:
            stats["empty_geometry"] += 1
            continue
        if not (keep(geom) if keep else geom.intersects(region)):
            stats["outside_region"] += 1
            continue
        cid = closure_id(f)
        if cid in seen:
            stats["duplicate_features_collapsed"] += 1
            continue
        seen.add(cid)
        p = f.get("properties") or {}
        status = map_status(p.get("STATUT"))
        if status == "unknown":
            unmapped[f"STATUT={p.get('STATUT')!r}"] += 1
        vf = parse_date(p.get("DATE_DEBUT"))
        vt, end_date_only = parse_end(p.get("DATE_FIN"))
        flags = []
        if end_date_only:
            flags.append("DATE_FIN_date_only_end_of_day")
        if p.get("DATE_DEBUT") and vf is None:
            flags.append("DATE_DEBUT_unparsed_or_implausible")
        if p.get("DATE_FIN") and vt is None:
            flags.append("DATE_FIN_unparsed_or_implausible")
        if vf and vt and datetime.fromisoformat(vt) < datetime.fromisoformat(vf):
            flags.append("end_before_start")
        rows.append(
            {
                "closure_id": cid,
                "sidewalk_blockedtype": map_sidewalk_blockedtype(p),
                "blocks_passage": map_blocks_passage(p),
                "backsidewalk_blocks_passage": None,
                "valid_from": vf,
                "valid_to": vt,
                "status": status,
                "evidence_state": "confirmed",
                "attrs": {
                    **{k: p.get(k) for k in ATTR_FIELDS},
                    "currentstatus": p.get("STATUT"),  # raw publisher status (CR-ROUTING-7)
                    "date_flags": flags,
                    "weekly_schedule": None,  # not published: activity within the window unknown
                },
                "geometry_note": "published line geometry; affected roadway, not sidewalk",
                "source_id": SOURCE_ID,
                "geometry": geom,
            }
        )
    rows.sort(key=lambda r: r["closure_id"])
    stats["rows"] = len(rows)
    if not rows:
        cols = {c: [] for c in COLUMNS if c != "geometry"}
        return gpd.GeoDataFrame(cols, geometry=[], crs="EPSG:4326"), {**stats, **unmapped}
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326"), {**stats, **unmapped}


def run(settings: Settings, *, refresh: bool = False, force: bool = False, **_) -> RunResult:
    keep, extra = None, ""
    sda_dir = settings.processed_dir / "boundaries_sda"
    sm = read_manifest(sda_dir)
    if sm is not None:
        import shapely

        from .sda import load_municipalities

        land = load_municipalities(settings, ("65005",)).geometry.union_all()
        shapely.prepare(land)

        def keep(geom):
            return bool(land.intersects(geom))

        extra = f"|sda={sm['input_checksum']}"
    raw = download(
        GEOJSON_URL,
        settings.raw_dir / "laval-chantiers" / "permis-obstruction.geojson",
        user_agent=settings.user_agent,
        refresh=refresh,
    )
    checksum = hashlib.sha256(f"{raw.sha256}{extra}|{MAPPING_VERSION}".encode()).hexdigest()

    def build(staging: Path, run_id: str) -> dict:
        features = json.loads(raw.path.read_text(encoding="utf-8"))["features"]
        closures, counters = build_closures(features, keep=keep)
        closures["ingest_run_id"] = run_id
        write_geojson(closures, staging / "closures.geojson")
        return {
            "source_id": SOURCE_ID,
            "raw_sha256": {"geojson": raw.sha256},
            "fetched_at": {"geojson": raw.fetched_at},
            "region": "laval-sda" if keep else "laval-bbox",
            "attribution": ATTRIBUTION,
            "mapping_version": MAPPING_VERSION,
            "stats": {
                "features_total": len(features),
                "closures": len(closures),
                "blocks_passage_counts": {
                    str(k): v for k, v in Counter(map(str, closures["blocks_passage"])).items()
                }
                if len(closures)
                else {},
                "counters": counters,
            },
        }

    return run_atomic("laval_chantiers", settings.processed_dir, checksum, build, force=force)
