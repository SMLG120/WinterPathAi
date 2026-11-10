"""311 requests -> privacy-preserving H3 res-9 daily aggregates.

The output of `aggregate_report_cells` has exactly the schema of the Data agent's
`wp.report_311_cell` table (h3, day, category, n), so the CSV path can be swapped for
`read_report_cells_sql` once that table exists. Raw points never leave this module:
only cell-level counts are returned or written to disk.
"""

from __future__ import annotations

from pathlib import Path

import h3
import numpy as np
import pandas as pd

from . import config

RAW_COLS = [
    "NATURE",
    "ACTI_NOM",
    "TYPE_LIEU_INTERV",
    "ARRONDISSEMENT",
    "ARRONDISSEMENT_GEO",
    "DDS_DATE_CREATION",
    "LOC_LONG",
    "LOC_LAT",
    "LOC_ERREUR_GDT",
    "PROVENANCE_ORIGINALE",
]


def read_raw_311(path: Path = config.RAW_311_CSV) -> pd.DataFrame:
    """Read the public CSV (columns needed only). In-memory only; never persisted."""
    df = pd.read_csv(path, usecols=RAW_COLS, dtype=str, engine="pyarrow")
    df["lon"] = pd.to_numeric(df["LOC_LONG"], errors="coerce")
    df["lat"] = pd.to_numeric(df["LOC_LAT"], errors="coerce")
    # DDS_DATE_CREATION is a naive local timestamp (America/Montreal); the local calendar day is the unit.
    df["created"] = pd.to_datetime(df["DDS_DATE_CREATION"], errors="coerce")
    df["day"] = df["created"].dt.normalize()
    return df.drop(columns=["LOC_LONG", "LOC_LAT", "DDS_DATE_CREATION"])


def valid_location(df: pd.DataFrame) -> pd.Series:
    w, s, e, n = config.MTL_ENVELOPE
    return (
        df["lon"].between(w, e)
        & df["lat"].between(s, n)
        & (df["LOC_ERREUR_GDT"].fillna("0") != "1")
    )


def winter_reports(df: pd.DataFrame) -> pd.DataFrame:
    """Rows that count as winter-related reports, with a normalised `category`."""
    m = df["ACTI_NOM"].isin(list(config.WINTER_CATEGORIES)) & df["NATURE"].isin(
        config.REPORT_NATURES
    )
    out = df[m].copy()
    out["category"] = out["ACTI_NOM"].map(config.WINTER_CATEGORIES)
    return out


def to_cells(lon: pd.Series, lat: pd.Series, res: int = config.H3_RES) -> np.ndarray:
    return np.array(
        [
            h3.latlng_to_cell(la, lo, res)
            for lo, la in zip(lon.to_numpy(), lat.to_numpy())
        ],
        dtype=object,
    )


def aggregate_report_cells(winter: pd.DataFrame) -> pd.DataFrame:
    """(h3, day, category, n) — same shape as `wp.report_311_cell`."""
    w = winter[valid_location(winter) & winter["day"].notna()].copy()
    w["h3"] = to_cells(w["lon"], w["lat"])
    agg = (
        w.groupby(["h3", "day", "category"], observed=True)
        .size()
        .rename("n")
        .reset_index()
    )
    agg["day"] = pd.to_datetime(agg["day"])
    return agg


def aggregate_all_requests(df: pd.DataFrame) -> pd.DataFrame:
    """All geolocated requests (any category) per (h3, day): used for coverage and borough mapping."""
    a = df[valid_location(df) & df["day"].notna()].copy()
    a["h3"] = to_cells(a["lon"], a["lat"])
    borough = a["ARRONDISSEMENT_GEO"].fillna(a["ARRONDISSEMENT"]).fillna("UNKNOWN")
    a["borough"] = borough
    return a.groupby(["h3", "day", "borough"]).size().rename("n").reset_index()


def read_report_cells_sql(conn) -> pd.DataFrame:
    """Swap-in for the Data agent's `wp.report_311_cell` (any DBAPI/SQLAlchemy connection)."""
    df = pd.read_sql("SELECT h3, day, category, n FROM wp.report_311_cell", conn)
    df["day"] = pd.to_datetime(df["day"])
    return df


def build_interim(
    raw_path: Path = config.RAW_311_CSV, out_dir: Path = config.INTERIM_DIR
) -> dict[str, Path]:
    """Write aggregated (non-identifying) tables to the git-ignored cache."""
    out_dir.mkdir(parents=True, exist_ok=True)
    df = read_raw_311(raw_path)
    paths = {
        "report_cells": out_dir / "report_311_cell.parquet",
        "all_cells": out_dir / "all_requests_cell.parquet",
    }
    aggregate_report_cells(winter_reports(df)).to_parquet(
        paths["report_cells"], index=False
    )
    aggregate_all_requests(df).to_parquet(paths["all_cells"], index=False)
    return paths
