"""Montréal 311 requests → privacy-preserving aggregate (H3 res-9 × day × winter category).

Licence: CC BY 4.0 (Ville de Montréal). Methodology (donnees.montreal.ca/dataset/requete-311,
read 2026-11-10): request locations are *relocated to the middle of the nearest street segment
longer than 45 m* ("Position obfusquée"); LOC_ERREUR_GDT=1 means the request was located at the
borough office (BAM), not at the request site; information requests are not geolocated.

311 rows are REPORTS, not confirmed obstacles. Raw rows are streamed from the git-ignored
data/raw/ file and never persisted elsewhere; only counts per (h3, day, category) are written.
"""

from __future__ import annotations

import csv
import hashlib
from collections import Counter
from pathlib import Path

import h3

from ..config import Settings
from ..http import download
from ..runs import RunResult, run_atomic

SOURCE_ID = "mtl-311"
DATASET = "https://donnees.montreal.ca/dataset/requete-311"
_B = "https://donnees.montreal.ca/dataset/5866f832-676d-4b07-be6a-e99c21eb17e4/resource/"
RESOURCES = {
    "requetes311.csv": _B + "2cfa0e06-9be4-49a6-b7f1-ee9f2363a872/download/requetes311.csv",
}
H3_RES = 9

# Documented winter category list. Chosen from the 996 distinct ACTI_NOM values observed in the
# 2022–2026-11-09 file (counts in the agent report). Only categories describing winter surface
# conditions or snow operations/obstruction relevant to pedestrians are kept. Excluded on purpose:
# bike-path clearing, towing, signage, permits, Info-Neige app support, generic sidewalk repair.
WINTER_CATEGORIES: dict[str, str] = {
    "Trottoir glissant": "sidewalk_slippery",
    "Chaussée glissante": "roadway_slippery",
    "Opération déneigement": "snow_clearing",
    "Déneigement ruelle": "snow_clearing",
    "Dépôt Illégal - Neige": "snow_dumping",
    "Dépôt neige-ruelle": "snow_dumping",
}


def classify(row: dict) -> tuple[str | None, str]:
    """Returns (category, reason). category None ⇒ row skipped for `reason`."""
    cat = WINTER_CATEGORIES.get((row.get("ACTI_NOM") or "").strip())
    if cat is None:
        return None, "not_winter_category"
    if row.get("LOC_ERREUR_GDT") == "1":
        return None, "located_at_borough_office"
    if not row.get("LOC_LAT") or not row.get("LOC_LONG"):
        return None, "no_location"
    day = (row.get("DDS_DATE_CREATION") or "")[:10]
    if len(day) != 10:
        return None, "no_date"
    return cat, "ok"


def aggregate_rows(rows) -> tuple[Counter, Counter]:
    counts: Counter[tuple[str, str, str]] = Counter()
    reasons: Counter[str] = Counter()
    for row in rows:
        cat, reason = classify(row)
        reasons[reason] += 1
        if cat is None:
            continue
        try:
            lat, lon = float(row["LOC_LAT"]), float(row["LOC_LONG"])
        except ValueError:
            reasons["bad_coordinates"] += 1
            continue
        cell = h3.latlng_to_cell(lat, lon, H3_RES)
        counts[(cell, row["DDS_DATE_CREATION"][:10], cat)] += 1
    return counts, reasons


def run(settings: Settings, *, refresh: bool = False, force: bool = False) -> RunResult:
    raws = [
        download(
            url,
            settings.raw_dir / "311" / name,
            user_agent=settings.user_agent,
            refresh=refresh,
            timeout=900,
        )
        for name, url in RESOURCES.items()
    ]
    cats = "|".join(f"{k}={v}" for k, v in sorted(WINTER_CATEGORIES.items()))
    checksum = hashlib.sha256(
        ("|".join(r.sha256 for r in raws) + f"|h3={H3_RES}|{cats}").encode()
    ).hexdigest()

    def build(staging: Path, run_id: str) -> dict:
        total: Counter = Counter()
        reasons: Counter = Counter()
        for r in raws:
            with r.path.open(encoding="utf-8-sig", newline="") as f:
                c, rs = aggregate_rows(csv.DictReader(f))
            total.update(c)
            reasons.update(rs)
        out = staging / "report_311_cell.csv"
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["h3", "day", "category", "n", "source_id", "ingest_run_id"])
            for (cell, day, cat), n in sorted(total.items()):
                w.writerow([cell, day, cat, n, SOURCE_ID, run_id])
        days = sorted({k[1] for k in total})
        per_cat = Counter()
        for (_, _, cat), n in total.items():
            per_cat[cat] += n
        return {
            "source_id": SOURCE_ID,
            "raw_sha256": {r.path.name: r.sha256 for r in raws},
            "fetched_at": {r.path.name: r.fetched_at for r in raws},
            "h3_resolution": H3_RES,
            "winter_categories": WINTER_CATEGORIES,
            "day_basis": "calendar date of DDS_DATE_CREATION as published (no timezone stated)",
            "stats": {
                "rows_by_reason": dict(sorted(reasons.items())),
                "reports_aggregated_by_category": dict(sorted(per_cat.items())),
                "cells_rows": len(total),
                "distinct_cells": len({k[0] for k in total}),
                "rows_with_n_lt_3": sum(1 for n in total.values() if n < 3),
                "day_range": [days[0], days[-1]] if days else None,
            },
        }

    return run_atomic("report_311", settings.processed_dir, checksum, build, force=force)
