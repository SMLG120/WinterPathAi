"""ECCC climate-daily download + daily weather frame.

Source: ECCC MSC GeoMet OGC API `climate-daily` (Data Source: Environment and Climate Change Canada).
Only observed values are used. Missing values stay NaN (never filled with 0).
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import config

FIELDS = [
    "LOCAL_DATE",
    "MAX_TEMPERATURE",
    "MIN_TEMPERATURE",
    "TOTAL_PRECIPITATION",
    "TOTAL_SNOW",
    "TOTAL_RAIN",
    "SNOW_ON_GROUND",
]
USER_AGENT = os.environ.get(
    "HTTP_USER_AGENT", "WinterPathAI-dev/0.1 (local development)"
)


def fetch_climate_daily(
    station: str, start: date, end: date, cache_dir: Path | None = None
) -> pd.DataFrame:
    """Download (or read cached) daily climate rows for one station; returns raw ECCC columns."""
    cache_dir = cache_dir or config.RAW_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"eccc_climate_daily_{station}_{start}_{end}.json"
    if not path.exists():
        rows: list[dict] = []
        offset = 0
        while True:
            q = urllib.parse.urlencode(
                {
                    "f": "json",
                    "CLIMATE_IDENTIFIER": station,
                    "datetime": f"{start}/{end}",
                    "limit": 5000,
                    "offset": offset,
                    "properties": ",".join(FIELDS),
                }
            )
            req = urllib.request.Request(
                f"{config.ECCC_API}/collections/climate-daily/items?{q}",
                headers={"User-Agent": USER_AGENT},
            )
            with urllib.request.urlopen(req, timeout=120) as r:
                page = json.load(r)
            feats = page.get("features", [])
            rows.extend(f["properties"] for f in feats)
            if len(feats) < 5000:
                break
            offset += 5000
        path.write_text(json.dumps(rows))
    df = pd.DataFrame(json.loads(path.read_text()))
    if df.empty:
        return pd.DataFrame(columns=FIELDS)
    df["day"] = pd.to_datetime(df["LOCAL_DATE"]).dt.normalize()
    return df


def build_daily_weather(
    primary: pd.DataFrame, fallback: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Merge stations into one observed daily frame indexed by local day.

    Temperature/precipitation from the primary station; gaps filled from the fallback
    station (same airport site). Snowfall and snow-on-ground only exist at the primary.
    """
    cols = {
        "MAX_TEMPERATURE": "tmax",
        "MIN_TEMPERATURE": "tmin",
        "TOTAL_PRECIPITATION": "precip",
        "TOTAL_SNOW": "snow",
        "SNOW_ON_GROUND": "snow_ground",
    }
    p = primary.set_index("day")[list(cols)].rename(columns=cols).astype(float)
    p = p[~p.index.duplicated()]
    if fallback is not None and not fallback.empty:
        f = fallback.set_index("day")[list(cols)].rename(columns=cols).astype(float)
        f = f[~f.index.duplicated()]
        p = p.reindex(p.index.union(f.index))
        for c in ("tmax", "tmin", "precip"):
            p[c] = p[c].fillna(f[c].reindex(p.index))
    p = p.sort_index()
    full = pd.date_range(p.index.min(), p.index.max(), freq="D")
    return p.reindex(full).rename_axis("day")


def weather_features(daily: pd.DataFrame, days: pd.DatetimeIndex) -> pd.DataFrame:
    """Features for target day D using only observations from days strictly before D."""
    d = daily.reindex(daily.index.union(days)).sort_index()
    d["freeze_thaw"] = np.where(
        d["tmax"].notna() & d["tmin"].notna(),
        ((d["tmax"] > 0) & (d["tmin"] < 0)).astype(float),
        np.nan,
    )
    s = d.shift(1)  # row D now holds D-1 observations
    out = pd.DataFrame(index=d.index)
    out["w_tmax_1d"] = s["tmax"]
    out["w_tmin_1d"] = s["tmin"]
    out["w_precip_1d"] = s["precip"]
    out["w_precip_3d"] = s["precip"].rolling(3, min_periods=3).sum()
    out["w_snow_1d"] = s["snow"]
    out["w_snow_3d"] = s["snow"].rolling(3, min_periods=3).sum()
    out["w_snow_ground_1d"] = s["snow_ground"]
    out["w_freeze_thaw_3d"] = s["freeze_thaw"].rolling(3, min_periods=3).sum()
    out["w_freeze_thaw_1d"] = s["freeze_thaw"]
    return out.reindex(days)


def load_weather(start: date, end: date) -> pd.DataFrame:
    prim = fetch_climate_daily(config.STATION_PRIMARY, start, end)
    fb = fetch_climate_daily(config.STATION_FALLBACK, start, end)
    return build_daily_weather(prim, fb)
