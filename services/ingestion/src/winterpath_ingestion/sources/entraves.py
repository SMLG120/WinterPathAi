"""Ville de Montréal "Entraves et travaux en cours" → closures.

Licence: CC BY 4.0 (CKAN `info-travaux`, license_id=cc-by, verified 2026-11-10).
Evidence state for rows: `confirmed` (official permit data) — but `blocks_passage` is True ONLY
when `sidewalk_blockedtype` explicitly says the sidewalk is barred. Roadwork alone never implies
a sidewalk closure.

Geometry: the main CSV publishes one point (longitude, latitude) per permit; the impacts CSV
names affected street sections (streetid, fromname, toname) without geometry. We store the point
and keep street names in attrs; we do not geocode or invent segment geometry.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

from ..config import PILOT_BBOX, Settings
from ..http import download
from ..osm.pipeline import write_geojson
from ..runs import RunResult, read_manifest, run_atomic

SOURCE_ID = "mtl-entraves"
DATASET = "https://donnees.montreal.ca/dataset/info-travaux"
_B = "https://donnees.montreal.ca/dataset/667342f7-f667-4c3c-9837-65e81312cd8d/resource/"
MAIN_URL = _B + "cc41b532-f12d-40fb-9f55-eb58c9a2b12b/download/entraves-travaux-en-cours.csv"
IMPACTS_URL = (
    _B + "a2bc8014-488c-495d-941b-e7ae1999d1bd/download/impacts-entraves-travaux-en-cours.csv"
)

# Every distinct value observed on 2026-11-10 (impacts CSV, 2 105 rows). Unknown → None.
SIDEWALK_BLOCKS_PASSAGE: dict[str, bool | None] = {
    "Barré": True,  # sidewalk barred
    "Obstrué (un passage piéton de 1,5 m est conservé)": False,  # 1.5 m passage kept
    "Aucun impact / non applicable": False,  # explicitly no impact
}
# Opposite-side sidewalk. "Obstrué" (no passage statement) is ambiguous → None.
BACKSIDEWALK_BLOCKS_PASSAGE: dict[str, bool | None] = {
    "Barré": True,
    "Obstrué": None,
    "Aucun impact / non applicable": False,
}


# CR-ROUTING-7 (accepted): wp.closure.status = publisher lifecycle only, never time-derived.
# Only "Permis émis" observed (1 974/1 974 on 2026-11-10); cancelled/completed are reserved.
# Unmapped raw values → "unknown" (raw kept in attrs.currentstatus) and reported in `unmapped`.
CLOSURE_STATUS: dict[str, str] = {"Permis émis": "permit_issued"}
CLOSURE_STATUS_VALUES = ("permit_issued", "cancelled", "completed", "unknown")


def map_status(raw: str | None) -> str:
    return CLOSURE_STATUS.get((raw or "").strip(), "unknown")


DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def weekly_schedule(m: dict) -> dict:
    """Publisher's per-weekday activity, verbatim semantics: active (t/f), all_day (t/f),
    start/end local times ('' → None). Unknown flag values → None (never assumed active)."""
    flag = {"t": True, "f": False}
    out = {}
    for d in DAYS:
        out[d] = {
            "active": flag.get(m.get(f"duration_days_{d}_active", "")),
            "all_day": flag.get(m.get(f"duration_days_{d}_all_day_round", "")),
            "start": m.get(f"duration_days_{d}_start_time") or None,
            "end": m.get(f"duration_days_{d}_end_time") or None,
        }
    return out


def map_blocked(value: str | None, table: dict[str, bool | None]) -> bool | None:
    if value is None:
        return None
    return table.get(value.strip(), None)


def aggregate(values: list[bool | None]) -> bool | None:
    """Permit-level: True if any impact explicitly bars; False only if all explicitly don't."""
    if any(v is True for v in values):
        return True
    if values and all(v is False for v in values):
        return False
    return None


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def build_closures(main_rows: list[dict], impact_rows: list[dict], bbox=PILOT_BBOX, keep=None):
    """keep(lon, lat) → bool overrides the bbox test (region=island: agglomeration land)."""
    impacts = defaultdict(list)
    for r in impact_rows:
        impacts[r["id_request"]].append(r)
    unmapped = Counter()
    rows = []
    w, s, e, n = bbox
    for m in main_rows:
        try:
            lon, lat = float(m["longitude"]), float(m["latitude"])
        except (TypeError, ValueError):
            unmapped["no_coordinates"] += 1
            continue
        if keep is not None:
            if not keep(lon, lat):
                continue
        elif not (w <= lon <= e and s <= lat <= n):
            continue
        imps = impacts.get(m["id"], [])
        side = [x["sidewalk_blockedtype"].strip() for x in imps]
        back = [x["backsidewalk_blockedtype"].strip() for x in imps]
        for v in side:
            if v not in SIDEWALK_BLOCKS_PASSAGE:
                unmapped[f"sidewalk_blockedtype={v!r}"] += 1
        bp = aggregate([map_blocked(v, SIDEWALK_BLOCKS_PASSAGE) for v in side])
        status = map_status(m.get("currentstatus"))
        if status == "unknown":
            unmapped[f"currentstatus={m.get('currentstatus')!r}"] += 1
        rows.append(
            {
                "closure_id": f"entrave:{m['id']}",
                "sidewalk_blockedtype": " | ".join(sorted(set(side))) or None,
                "blocks_passage": bp,
                "backsidewalk_blocks_passage": aggregate(
                    [map_blocked(v, BACKSIDEWALK_BLOCKS_PASSAGE) for v in back]
                ),
                "valid_from": m["duration_start_date"] or None,
                "valid_to": m["duration_end_date"] or None,
                "status": status,
                "evidence_state": "confirmed",
                "attrs": {
                    "permit_id": m.get("permit_permit_id"),
                    "reason_category": m.get("reason_category"),
                    # raw publisher status, kept verbatim (CR-ROUTING-7)
                    "currentstatus": m.get("currentstatus"),
                    "weekly_schedule": weekly_schedule(m),
                    "impacts": [
                        {
                            k: x.get(k)
                            for k in (
                                "streetid",
                                "name",
                                "fromname",
                                "toname",
                                "length",
                                "sidewalk_blockedtype",
                                "backsidewalk_blockedtype",
                            )
                        }
                        for x in imps
                    ],
                },
                "geometry_note": "permit point as published; not the affected segment",
                "source_id": SOURCE_ID,
                "geometry": Point(lon, lat),
            }
        )
    rows.sort(key=lambda r: r["closure_id"])
    if not rows:
        return gpd.GeoDataFrame(
            {"closure_id": [], "blocks_passage": []}, geometry=[], crs="EPSG:4326"
        ), unmapped
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326"), unmapped


def run(
    settings: Settings, *, refresh: bool = False, force: bool = False, region: str = "pilot"
) -> RunResult:
    """region=pilot: permits in PILOT_BBOX (unchanged). region=island: permits whose point lies
    on agglomeration land (boundaries product) → data/processed/entraves_island."""
    if region not in ("pilot", "island"):
        raise ValueError(f"unknown region {region!r}")
    keep, extra = None, ""
    if region == "island":
        import shapely

        from .boundaries import load_land

        bm = read_manifest(settings.processed_dir / "boundaries")
        if bm is None:
            raise RuntimeError("run `wp-ingest boundaries` first")
        land = load_land(settings)
        shapely.prepare(land)

        def keep(lon, lat):
            return bool(shapely.contains_xy(land, lon, lat))

        extra = f"|region=island|{bm['input_checksum']}"
    d = settings.raw_dir / "entraves"
    main = download(
        MAIN_URL,
        d / "entraves-travaux-en-cours.csv",
        user_agent=settings.user_agent,
        refresh=refresh,
    )
    imp = download(
        IMPACTS_URL,
        d / "impacts-entraves-travaux-en-cours.csv",
        user_agent=settings.user_agent,
        refresh=refresh,
    )
    checksum = hashlib.sha256(f"{main.sha256}|{imp.sha256}{extra}".encode()).hexdigest()

    def build(staging: Path, run_id: str) -> dict:
        main_rows, impact_rows = _read_csv(main.path), _read_csv(imp.path)
        closures, unmapped = build_closures(main_rows, impact_rows, keep=keep)
        closures["ingest_run_id"] = run_id
        write_geojson(closures, staging / "closures.geojson")
        distinct = {
            c: dict(Counter(r[c].strip() for r in impact_rows).most_common())
            for c in ("sidewalk_blockedtype", "backsidewalk_blockedtype")
        }
        mapping = {
            "sidewalk_blockedtype": SIDEWALK_BLOCKS_PASSAGE,
            "backsidewalk_blockedtype": BACKSIDEWALK_BLOCKS_PASSAGE,
        }
        (staging / "blocked_type_mapping.json").write_text(
            json.dumps(
                {"mapping": mapping, "observed_values": distinct}, ensure_ascii=False, indent=2
            )
        )
        return {
            "source_id": SOURCE_ID,
            "raw_sha256": {"main": main.sha256, "impacts": imp.sha256},
            "fetched_at": {"main": main.fetched_at, "impacts": imp.fetched_at},
            "region": region,
            "stats": {
                "permits_total": len(main_rows),
                "impact_rows_total": len(impact_rows),
                "closures_in_bbox": len(closures),
                "blocks_passage_counts": {
                    str(k): v for k, v in Counter(map(str, closures["blocks_passage"])).items()
                },
                "unmapped": dict(unmapped),
                "observed_values": distinct,
            },
        }

    out_name = "entraves" if region == "pilot" else "entraves_island"
    return run_atomic(out_name, settings.processed_dir, checksum, build, force=force)
