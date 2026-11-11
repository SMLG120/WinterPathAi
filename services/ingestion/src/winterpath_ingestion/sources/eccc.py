"""ECCC MSC GeoMet OGC API → wp.weather_obs.

Licence: ECCC Data Servers End-use Licence (commercial use allowed, attribution
"Data Source: Environment and Climate Change Canada").

Stations (looked up 2026-11-10 via collections/climate-stations, hourly data, nearest to McGill):
  * 7025251 MONTREAL INTL A (STN_ID 51157), hourly 2013-02-13 → present, ≈13.6 km from McGill.
    Used for both climate-hourly and swob-realtime (manual CYUL SWOB carries the same id), so
    station_id is consistent across collections.
    Its climate-hourly PRECIP_AMOUNT is NULL for every row checked (2022–2026).
  * 702S006 MONTREAL/PIERRE ELLIOTT TRUDEAU INTL (STN_ID 30165), hourly 2008 → 2026-10-01 per
    station metadata; carries hourly PRECIP_AMOUNT. Ingested as its own station_id (no merging).
No downtown station with hourly data was found in the Montréal bbox query.

climate-daily (contract v1.2.0, wp.weather_daily) is ingested for the same stations because
7025251's hourly precipitation is NULL throughout, while its daily TOTAL_PRECIPITATION /
TOTAL_SNOW / SNOW_ON_GROUND are populated. SNOW_ON_GROUND is NULL outside winter upstream; it
stays NULL here (never filled with 0).

Missing values stay NULL (never 0). SWOB uses negative sentinels (e.g. snw_dpth = -1) → NULL.
climate-hourly has no snow-depth field → NULL.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from ..config import Settings
from ..http import download
from ..runs import RunResult, run_atomic

SOURCE_ID = "eccc-geomet"
API = "https://api.weather.gc.ca/collections"
STATIONS = ("7025251", "702S006")
TRAINING_START_YEAR = 2022  # matches the 311 file (2022-01-01 → present)
PAGE = 10000

COLUMNS = [
    "station_id",
    "observed_at",
    "temperature_c",
    "precip_mm",
    "snow_depth_cm",
    "wind_kmh",
    "source_collection",
]

DAILY_COLUMNS = [
    "station_id",
    "day",
    "total_precip_mm",
    "total_snow_cm",
    "snow_on_ground_cm",
    "min_temp_c",
    "max_temp_c",
    "source_collection",
]


def _num(v, *, nonneg: bool = False):
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if nonneg and x < 0:
        return None
    return x


def climate_hourly_row(p: dict) -> dict:
    return {
        "station_id": str(p["CLIMATE_IDENTIFIER"]),
        "observed_at": p["UTC_DATE"] + "Z" if not p["UTC_DATE"].endswith("Z") else p["UTC_DATE"],
        "temperature_c": _num(p.get("TEMP")),
        "precip_mm": _num(p.get("PRECIP_AMOUNT"), nonneg=True),
        "snow_depth_cm": None,
        "wind_kmh": _num(p.get("WIND_SPEED"), nonneg=True),
        "source_collection": "climate-hourly",
    }


def climate_daily_row(p: dict) -> dict:
    return {
        "station_id": str(p["CLIMATE_IDENTIFIER"]),
        "day": str(p["LOCAL_DATE"])[:10],  # station-local calendar day as published
        "total_precip_mm": _num(p.get("TOTAL_PRECIPITATION"), nonneg=True),
        "total_snow_cm": _num(p.get("TOTAL_SNOW"), nonneg=True),
        "snow_on_ground_cm": _num(p.get("SNOW_ON_GROUND"), nonneg=True),
        "min_temp_c": _num(p.get("MIN_TEMPERATURE")),
        "max_temp_c": _num(p.get("MAX_TEMPERATURE")),
        "source_collection": "climate-daily",
    }


def swob_row(p: dict) -> dict:
    ts = p.get("date_tm-value") or p.get("obs_date_tm")
    ts = ts.replace(".000Z", "Z") if ts else ts
    return {
        "station_id": str(p.get("msc_id-value") or p.get("clim_id-value")),
        "observed_at": ts,
        "temperature_c": _num(p.get("air_temp")),
        "precip_mm": _num(p.get("pcpn_amt_pst1hr"), nonneg=True),
        "snow_depth_cm": _num(p.get("snw_dpth"), nonneg=True),
        "wind_kmh": _num(
            p.get("avg_wnd_spd_10m_pst1hr") or p.get("avg_wnd_spd_10m_pst2mts"), nonneg=True
        ),
        "source_collection": "swob-realtime",
    }


def _pages(settings: Settings, collection: str, params: dict, tag: str, refresh: bool):
    """Yield (RawFile, features) for each page; pages cached under data/raw/eccc/."""
    offset = 0
    while True:
        q = {**params, "f": "json", "limit": PAGE, "offset": offset}
        dest = settings.raw_dir / "eccc" / f"{collection}_{tag}_{offset}.json"
        raw = download(
            f"{API}/{collection}/items",
            dest,
            params=q,
            user_agent=settings.user_agent,
            refresh=refresh,
            timeout=300,
        )
        feats = json.loads(raw.path.read_text())["features"]
        yield raw, feats
        if len(feats) < PAGE:
            return
        offset += PAGE


def fetch_all(settings: Settings, refresh: bool) -> tuple[list[dict], list[dict], list[str], dict]:
    rows: list[dict] = []
    daily: list[dict] = []
    shas: list[str] = []
    now = datetime.now(UTC)
    for st in STATIONS:
        for year in range(TRAINING_START_YEAR, now.year + 1):
            # past years are immutable → cached; the current year is refreshed each run
            for raw, feats in _pages(
                settings,
                "climate-hourly",
                {"CLIMATE_IDENTIFIER": st, "LOCAL_YEAR": year},
                f"{st}_{year}",
                refresh or year == now.year,
            ):
                shas.append(raw.sha256)
                rows.extend(climate_hourly_row(f["properties"]) for f in feats)
            for raw, feats in _pages(
                settings,
                "climate-daily",
                {"CLIMATE_IDENTIFIER": st, "LOCAL_YEAR": year},
                f"{st}_{year}",
                refresh or year == now.year,
            ):
                shas.append(raw.sha256)
                daily.extend(climate_daily_row(f["properties"]) for f in feats)
        for raw, feats in _pages(
            settings,
            "swob-realtime",
            {"msc_id-value": st, "sortby": "-date_tm-value"},
            f"{st}_latest",
            True,
        ):
            shas.append(raw.sha256)
            rows.extend(swob_row(f["properties"]) for f in feats)
            break  # adapter keeps only the latest page (realtime, ≤30 days retained upstream)
    return rows, daily, shas, {"stations": list(STATIONS)}


def dedupe(rows: list[dict]) -> list[dict]:
    """PK(station_id, observed_at). climate-hourly (QC'd archive) wins over swob-realtime."""
    best: dict[tuple[str, str], dict] = {}
    for r in rows:
        k = (r["station_id"], r["observed_at"])
        if k not in best or (
            best[k]["source_collection"] == "swob-realtime"
            and r["source_collection"] == "climate-hourly"
        ):
            best[k] = r
    return [best[k] for k in sorted(best)]


def run(settings: Settings, *, refresh: bool = False, force: bool = False) -> RunResult:
    rows, daily, shas, info = fetch_all(settings, refresh)
    checksum = hashlib.sha256("|".join(shas).encode()).hexdigest()

    def build(staging: Path, run_id: str) -> dict:
        out = dedupe(rows)
        with (staging / "weather_obs.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS + ["ingest_run_id"])
            w.writeheader()
            for r in out:
                w.writerow({**r, "ingest_run_id": run_id})
        daily_out = sorted(
            {(r["station_id"], r["day"]): r for r in daily}.values(),
            key=lambda r: (r["station_id"], r["day"]),
        )
        with (staging / "weather_daily.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=DAILY_COLUMNS + ["ingest_run_id"])
            w.writeheader()
            for r in daily_out:
                w.writerow({**r, "ingest_run_id": run_id})
        daily_stats = {
            "rows": len(daily_out),
            "non_null": {
                c: sum(1 for r in daily_out if r[c] is not None) for c in DAILY_COLUMNS[2:7]
            },
            "day_range": [daily_out[0]["day"], max(r["day"] for r in daily_out)]
            if daily_out
            else None,
        }
        by_coll: dict[str, int] = {}
        for r in out:
            by_coll[r["source_collection"]] = by_coll.get(r["source_collection"], 0) + 1
        nulls = {c: sum(1 for r in out if r[c] is None) for c in COLUMNS[2:6]}
        return {
            "source_id": SOURCE_ID,
            **info,
            "stats": {
                "rows": len(out),
                "rows_by_collection": by_coll,
                "null_counts": nulls,
                "observed_range": [
                    min(r["observed_at"] for r in out),
                    max(r["observed_at"] for r in out),
                ]
                if out
                else None,
                "daily": daily_stats,
            },
        }

    return run_atomic("weather_obs", settings.processed_dir, checksum, build, force=force)
