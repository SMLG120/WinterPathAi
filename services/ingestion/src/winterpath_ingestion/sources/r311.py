"""Montréal 311 requests → privacy-preserving aggregate (H3 res-9 × day × category × nature).

Licence: CC BY 4.0 (Ville de Montréal). Methodology (donnees.montreal.ca/dataset/requete-311,
read 2026-11-10): request locations are *relocated to the middle of the nearest street segment
longer than 45 m* ("Position obfusquée"); LOC_ERREUR_GDT=1 means the request was located at the
borough office (BAM), not at the request site; information requests are not geolocated.

311 rows are REPORTS, not confirmed obstacles. Raw rows are streamed from the git-ignored
data/raw/ file and never persisted elsewhere; only counts per (h3, day, category, nature) are
written. Contract v1.5.0 (CR-ML-1): consumers SUM(n) over the natures they need (ML labels and
public counts use requete + plainte), and the k-anonymity floor (n<3) applies AFTER summing.
"""

from __future__ import annotations

import csv
import hashlib
import unicodedata
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
    "Déneigement ruelle": "snow_clearing_alley",  # v1.6.0 (CR-ML-2)
    "Dépôt Illégal - Neige": "snow_dumping",
    "Dépôt neige-ruelle": "snow_dumping_alley",  # v1.6.0 (CR-ML-2)
}


# 311 `NATURE` → contract value. Observed 2026-11-10 (whole file): Requete 1 725 024,
# Information 1 487 690, Commentaire 29 967, Plainte 28 936. Matching ignores case and accents
# ("Requête"). Any other value is skipped and counted, never guessed.
NATURES: dict[str, str] = {
    "requete": "requete",
    "plainte": "plainte",
    "information": "information",
    "commentaire": "commentaire",
}
CATEGORY_VALUES = (
    "sidewalk_slippery",
    "roadway_slippery",
    "snow_clearing",
    "snow_dumping",
    "snow_clearing_alley",  # v1.6.0 (CR-ML-2); SUM into snow_clearing for the v1.5 meaning
    "snow_dumping_alley",  # v1.6.0 (CR-ML-2); SUM into snow_dumping for the v1.5 meaning
)
NATURE_VALUES = ("requete", "plainte", "information", "commentaire")
LABEL_NATURES = ("requete", "plainte")  # contract v1.5.0 default for ML labels / public counts
K_ANON = 3


def normalize_nature(raw: str | None) -> str | None:
    s = unicodedata.normalize("NFKD", (raw or "").strip().lower())
    return NATURES.get("".join(c for c in s if not unicodedata.combining(c)))


def classify(row: dict) -> tuple[tuple[str, str] | None, str]:
    """Returns ((category, nature), reason). None ⇒ row skipped for `reason`."""
    cat = WINTER_CATEGORIES.get((row.get("ACTI_NOM") or "").strip())
    if cat is None:
        return None, "not_winter_category"
    nature = normalize_nature(row.get("NATURE"))
    if nature is None:
        return None, "unknown_nature"
    if row.get("LOC_ERREUR_GDT") == "1":
        return None, "located_at_borough_office"
    if not row.get("LOC_LAT") or not row.get("LOC_LONG"):
        return None, "no_location"
    day = (row.get("DDS_DATE_CREATION") or "")[:10]
    if len(day) != 10:
        return None, "no_date"
    return (cat, nature), "ok"


def aggregate_rows(rows) -> tuple[Counter, Counter]:
    counts: Counter[tuple[str, str, str, str]] = Counter()
    reasons: Counter[str] = Counter()
    for row in rows:
        key, reason = classify(row)
        reasons[reason] += 1
        if key is None:
            continue
        cat, nature = key
        try:
            lat, lon = float(row["LOC_LAT"]), float(row["LOC_LONG"])
        except ValueError:
            reasons["bad_coordinates"] += 1
            continue
        cell = h3.latlng_to_cell(lat, lon, H3_RES)
        counts[(cell, row["DDS_DATE_CREATION"][:10], cat, nature)] += 1
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
    nat = "|".join(f"{k}={v}" for k, v in sorted(NATURES.items()))
    checksum = hashlib.sha256(
        ("|".join(r.sha256 for r in raws) + f"|h3={H3_RES}|{cats}|nature:{nat}").encode()
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
            w.writerow(["h3", "day", "category", "nature", "n", "source_id", "ingest_run_id"])
            for (cell, day, cat, nature), n in sorted(total.items()):
                w.writerow([cell, day, cat, nature, n, SOURCE_ID, run_id])
        days = sorted({k[1] for k in total})
        per_cat: Counter = Counter()
        per_cat_nature: Counter = Counter()
        labels: Counter = Counter()  # summed over LABEL_NATURES, k-anon checked after summing
        for (cell, day, cat, nature), n in total.items():
            per_cat[cat] += n
            per_cat_nature[f"{cat}/{nature}"] += n
            if nature in LABEL_NATURES:
                labels[(cell, day, cat)] += n
        return {
            "source_id": SOURCE_ID,
            "raw_sha256": {r.path.name: r.sha256 for r in raws},
            "fetched_at": {r.path.name: r.fetched_at for r in raws},
            "h3_resolution": H3_RES,
            "winter_categories": WINTER_CATEGORIES,
            "natures": NATURES,
            "label_natures": list(LABEL_NATURES),
            "day_basis": "calendar date of DDS_DATE_CREATION as published (no timezone stated)",
            "stats": {
                "rows_by_reason": dict(sorted(reasons.items())),
                "reports_aggregated_by_category": dict(sorted(per_cat.items())),
                "reports_by_category_nature": dict(sorted(per_cat_nature.items())),
                "cells_rows": len(total),
                "distinct_cells": len({k[0] for k in total}),
                "label_cell_days": len(labels),
                f"label_cell_days_n_lt_{K_ANON}_after_sum": sum(
                    1 for n in labels.values() if n < K_ANON
                ),
                "day_range": [days[0], days[-1]] if days else None,
            },
        }

    return run_atomic("report_311", settings.processed_dir, checksum, build, force=force)


# ------------------------------------------------------------------ incremental (rolling window)
# Daily refresh (v2 Wave 2b): instead of re-downloading the ~850 MB file, query the portal's CKAN
# DataStore for the same resource, restricted to the winter categories, the last N days and only
# the columns `classify` / `aggregate_rows` read. Same classification, same H3 resolution, same
# (h3, day, category, nature) counts → the n<3 rule is unchanged (consumers apply it after SUM).
RESOURCE_ID = "2cfa0e06-9be4-49a6-b7f1-ee9f2363a872"  # "Requêtes 3-1-1 (2022 à ce jour)"
DATASTORE_SQL = "https://donnees.montreal.ca/api/3/action/datastore_search_sql"
RECENT_FIELDS = ("NATURE", "ACTI_NOM", "LOC_ERREUR_GDT", "LOC_LAT", "LOC_LONG", "DDS_DATE_CREATION")
PAGE = 5000
LOCAL_TZ = "America/Montreal"


def window(days: int, today=None) -> tuple[str, str]:
    """[start, end] calendar days, end = today in America/Montreal (inclusive)."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    if days < 1:
        raise ValueError("days must be ≥ 1")
    end = today or datetime.now(ZoneInfo(LOCAL_TZ)).date()
    return (end - timedelta(days=days - 1)).isoformat(), end.isoformat()


def _sql_window(start: str, select: str, tail: str = "") -> str:
    cats = ",".join("'" + c.replace("'", "''") + "'" for c in sorted(WINTER_CATEGORIES))
    return (
        f'SELECT {select} FROM "{RESOURCE_ID}" WHERE "DDS_DATE_CREATION" >= \'{start}\' '
        f'AND "ACTI_NOM" IN ({cats}){tail}'
    )


def fetch_recent(settings: Settings, start: str, *, post=None) -> tuple[list[dict], dict]:
    """All winter-category rows created on/after `start` (ISO date; validated). Pages ordered by
    `_id`; the page sum must equal a COUNT(*) of the same filter or the fetch fails."""
    import json
    import time
    from datetime import date

    import requests

    date.fromisoformat(start)  # refuses anything but a plain date (it is inlined into SQL)
    headers = {"User-Agent": settings.user_agent}

    def call(sql: str) -> tuple[list[dict], int]:
        last = None
        for attempt in range(3):
            try:
                r = (post or requests.post)(
                    DATASTORE_SQL, json={"sql": sql}, headers=headers, timeout=120
                )
                r.raise_for_status()
                body = r.json()
                if not body.get("success"):
                    raise RuntimeError(f"datastore error: {body.get('error')}")
                return body["result"]["records"], len(r.content)
            except Exception as e:  # noqa: BLE001 — retried, then re-raised
                last = e
                time.sleep(2**attempt)
        raise RuntimeError(f"311 DataStore query failed after 3 attempts: {last}")

    t0 = time.perf_counter()
    (cnt,), nbytes = call(_sql_window(start, "count(*) AS n"))
    expected = int(cnt["n"])
    cols = ", ".join(f'"{c}"' for c in RECENT_FIELDS)
    rows: list[dict] = []
    offset = 0
    while True:
        page, b = call(_sql_window(start, cols, f' ORDER BY "_id" LIMIT {PAGE} OFFSET {offset}'))
        nbytes += b
        rows.extend(page)
        if len(page) < PAGE:
            break
        offset += PAGE
    if len(rows) != expected:
        raise RuntimeError(f"311 window fetch inconsistent: {len(rows)} rows vs COUNT {expected}")
    # freshness of the SOURCE (all categories), so "no winter report since X" is not mistaken for
    # a stale pipeline
    (mx,), b = call(f'SELECT max("DDS_DATE_CREATION") AS mx FROM "{RESOURCE_ID}"')
    nbytes += b
    raw = settings.raw_dir / "311" / "recent_window.jsonl"  # git-ignored; overwritten each run
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows))
    info = {
        "resource_id": RESOURCE_ID,
        "endpoint": DATASTORE_SQL,
        "rows": len(rows),
        "response_bytes": nbytes,
        "fetch_s": round(time.perf_counter() - t0, 2),
        "source_data_through": mx.get("mx"),
        "latest_winter_row": max((r.get("DDS_DATE_CREATION") or "" for r in rows), default=None),
    }
    return rows, info


def run_recent(
    settings: Settings, *, days: int = 14, force: bool = False, today=None, post=None
) -> RunResult:
    import json
    from datetime import UTC, datetime

    start, end = window(days, today)
    rows, info = fetch_recent(settings, start, post=post)
    rows = [r for r in rows if (r.get("DDS_DATE_CREATION") or "")[:10] <= end]
    cats = "|".join(f"{k}={v}" for k, v in sorted(WINTER_CATEGORIES.items()))
    nat = "|".join(f"{k}={v}" for k, v in sorted(NATURES.items()))
    canon = json.dumps(sorted(json.dumps(r, sort_keys=True) for r in rows))
    checksum = hashlib.sha256(
        f"recent|{start}|{end}|{canon}|h3={H3_RES}|{cats}|nature:{nat}".encode()
    ).hexdigest()

    def build(staging: Path, run_id: str) -> dict:
        counts, reasons = aggregate_rows(rows)
        with (staging / "report_311_cell.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["h3", "day", "category", "nature", "n", "source_id", "ingest_run_id"])
            for (cell, day, cat, nature), n in sorted(counts.items()):
                w.writerow([cell, day, cat, nature, n, SOURCE_ID, run_id])
        per_cat: Counter = Counter()
        for (_, _, cat, _), n in counts.items():
            per_cat[cat] += n
        return {
            "source_id": SOURCE_ID,
            "mode": "recent_window",
            "window": [start, end],
            "window_days": days,
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "fetch": info,
            "h3_resolution": H3_RES,
            "winter_categories": WINTER_CATEGORIES,
            "natures": NATURES,
            "day_basis": "calendar date of DDS_DATE_CREATION as published (no timezone stated)",
            "stats": {
                "rows_by_reason": dict(sorted(reasons.items())),
                "reports_aggregated_by_category": dict(sorted(per_cat.items())),
                "cells_rows": len(counts),
            },
        }

    r = run_atomic("report_311_recent", settings.processed_dir, checksum, build, force=force)
    # this run's fetch (freshness) is reported even when the content is unchanged (noop)
    return RunResult(r.name, r.out_dir, r.noop, {**r.manifest, "fetch_this_run": info})
