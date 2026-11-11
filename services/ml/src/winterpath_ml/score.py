"""Batch scoring: write per-day score tables that inference providers read.

    uv run python -m winterpath_ml.score --start 2026-11-12 [--end ...] [--layer heuristic|model] [--fetch-311]

Headless contract (GitHub Actions or any cron):

Inputs read
- `models/registry.json` (committed).
- Scorer `<MODEL_ARTIFACT_DIR>/<run_id>/<layer artifact>.joblib` and coverage
  `<MODEL_ARTIFACT_DIR>/<run_id>/coverage_cells.parquet`. Both are git-ignored, so the runner must
  provide them. Each is checked against the sha256 in the registry before it is opened. A mismatch
  stops the run before anything is deserialised.
- 311 aggregates. With `--fetch-311`, the job downloads the Ville de Montréal « Requêtes 3-1-1 »
  CSV (`config.URL_311_2022_PRESENT`, ~850 MB) into `<WP_ML_CACHE_DIR>/score/` and aggregates it
  there. Without it, the job reads the existing `<WP_ML_CACHE_DIR>/interim/*.parquet`. The pinned
  evaluation snapshot is never overwritten.
- Weather. ECCC GeoMet `climate-daily` for stations 7025251 and 702S006 is always fetched fresh
  into a temporary directory, never from a cache.

Failure policy: every requested in-season day is prepared and validated before any file is
written. If any day lacks inputs or fails validation, nothing is written and the exit status is 1.
Each table is written to a temp file and renamed into place, so a reader never sees a half-written
day. Out-of-season days are reported and skipped (the layer is undefined there; providers return
`unknown`).

Exit status: 0 written (or nothing in season), 1 inputs incomplete or invalid, 2 artifact or
registry error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, data_311, features, inference, weather

SCORE_CACHE = config.CACHE_DIR / "score"


class ScoreError(RuntimeError):
    """Artifact or registry problem (exit 2)."""


class InputsIncomplete(RuntimeError):
    """A requested day cannot be scored from complete inputs (exit 1)."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def verified(reg: dict, entry: dict) -> Path:
    """Artifact path, only if its bytes match the registry's sha256."""
    path = inference.artifact_path(reg, entry)
    if not path.exists():
        raise ScoreError(
            f"artifact missing: {path} (MODEL_ARTIFACT_DIR={config.ARTIFACT_DIR})"
        )
    got = sha256(path)
    if got != entry["sha256"]:
        raise ScoreError(
            f"artifact sha256 mismatch for {path}: {got} != registry {entry['sha256']}"
        )
    return path


def inputs_ready(
    day: pd.Timestamp,
    report_cells: pd.DataFrame,
    all_cells: pd.DataFrame,
    wdaily: pd.DataFrame,
) -> str | None:
    """None when ready, else a reason string."""
    if day.month not in config.SEASON_MONTHS:
        return "out of season"
    prev = day - pd.Timedelta(days=1)
    if all_cells["day"].max() < prev:
        return f"311 data ends {all_cells['day'].max().date()} < {prev.date()}"
    need = pd.date_range(day - pd.Timedelta(days=3), prev)
    w = wdaily.reindex(need)
    if w[["tmax", "tmin", "precip"]].isna().any().any():
        return "weather observations for D-3..D-1 incomplete"
    return None


def validate(out: pd.DataFrame, cells: list[str], day: pd.Timestamp) -> None:
    """A day table must cover every coverage cell exactly once with a probability in [0, 1]."""
    problems = []
    if (
        len(out) != len(cells)
        or set(out["h3"]) != set(cells)
        or out["h3"].duplicated().any()
    ):
        problems.append(
            f"{len(out)} rows / {out['h3'].nunique()} cells, expected {len(cells)}"
        )
    p = out["p"].to_numpy(dtype=float)
    if not np.isfinite(p).all():
        problems.append(f"{int((~np.isfinite(p)).sum())} non-finite p")
    elif ((p < 0) | (p > 1)).any():
        problems.append("p outside [0, 1]")
    if problems:
        raise InputsIncomplete(
            f"{day.date()}: invalid score table ({'; '.join(problems)})"
        )


def fetch_311(dest: Path) -> Path:
    """Download the 311 CSV to `dest/requetes311.csv` via a .part file (no partial file left)."""
    dest.mkdir(parents=True, exist_ok=True)
    final, part = dest / "requetes311.csv", dest / "requetes311.csv.part"
    req = urllib.request.Request(
        config.URL_311_2022_PRESENT, headers={"User-Agent": weather.USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=900) as r, open(part, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    os.replace(part, final)
    return final


def load_311(fetch: bool) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    if fetch:
        raw = fetch_311(SCORE_CACHE / "raw")
        paths = data_311.build_interim(raw, SCORE_CACHE / "interim")
        meta = {"source": config.URL_311_2022_PRESENT, "sha256": sha256(raw)}
    else:
        paths = {
            "report_cells": config.INTERIM_DIR / "report_311_cell.parquet",
            "all_cells": config.INTERIM_DIR / "all_requests_cell.parquet",
        }
        meta = {"source": str(config.INTERIM_DIR), "sha256": None}
    for p in paths.values():
        if not p.exists():
            raise InputsIncomplete(f"311 aggregates missing: {p} (use --fetch-311)")
    rc, ac = pd.read_parquet(paths["report_cells"]), pd.read_parquet(paths["all_cells"])
    meta["last_day"] = str(ac["day"].max().date())
    return rc, ac, meta


def load_weather_fresh(start: date, end: date) -> pd.DataFrame:
    """ECCC observations fetched now; a cached file could predate the latest observations."""
    with tempfile.TemporaryDirectory() as td:
        prim = weather.fetch_climate_daily(config.STATION_PRIMARY, start, end, Path(td))
        fb = weather.fetch_climate_daily(config.STATION_FALLBACK, start, end, Path(td))
    return weather.build_daily_weather(prim, fb)


def prepare(start: date, end: date, layer: str | None, fetch: bool) -> dict:
    """Load and validate everything; returns the tables to write. Writes nothing."""
    reg = inference.load_registry()
    layer = layer or reg["active_layer"]
    entry = reg["layers"][layer]
    if layer == "model" and not entry["enabled"]:
        raise inference.ModelDisabledError("model layer is disabled in the registry")
    days = pd.date_range(start, end)
    in_season = [d for d in days if d.month in config.SEASON_MONTHS]
    skipped = [str(d.date()) for d in days if d.month not in config.SEASON_MONTHS]
    plan = {"registry": reg, "layer": layer, "tables": {}, "out_of_season": skipped}
    if not in_season:
        return plan

    scorer_path = verified(reg, entry["artifact"])
    cells = pd.read_parquet(verified(reg, reg["coverage"]))["h3"].tolist()
    rc, ac, plan["source_311"] = load_311(fetch)
    wd = load_weather_fresh(date(2021, 10, 1), end)

    not_ready = [
        f"{d.date()}: {why}" for d in in_season if (why := inputs_ready(d, rc, ac, wd))
    ]
    if not_ready:
        raise InputsIncomplete("; ".join(not_ready))

    import joblib  # sha-verified above; batch job only, never imported by the API path

    scorer = joblib.load(scorer_path)
    scored_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    for d in in_season:
        panel = features.build_panel(
            rc[rc["day"] < d], ac[ac["day"] < d], wd[wd.index < d], cells, d, d
        )
        # build_panel needs `end` inside the history range; day D itself carries no 311 rows (filtered above)
        panel = panel[panel["day"] == d]
        out = pd.DataFrame(
            {
                "h3": panel["h3"].to_numpy(),
                "day": panel["day"].to_numpy(),
                "p": scorer.proba(panel),
                "scored_at": scored_at,
                # inputs are observations up to the end of D-1 (local)
                "data_through": datetime(
                    d.year, d.month, d.day, tzinfo=inference.LOCAL_TZ
                )
                .astimezone(UTC)
                .isoformat(),
            }
        )
        validate(out, cells, d)
        plan["tables"][str(d.date())] = out
    return plan


def write(plan: dict) -> list[str]:
    out_dir = inference.scores_dir(plan["registry"], plan["layer"])
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for day, out in plan["tables"].items():
        path = out_dir / f"{day}.parquet"
        tmp = (
            out_dir / f".{day}.parquet.tmp"
        )  # not matched by the provider's *.parquet glob
        out.to_parquet(tmp, index=False)
        os.replace(tmp, path)
        written.append(str(path))
    return written


def score_days(
    start: date, end: date, layer: str | None = None, fetch_311: bool = False
) -> list[str]:
    return write(prepare(start, end, layer, fetch_311))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=date.fromisoformat, required=True)
    ap.add_argument("--end", type=date.fromisoformat)
    ap.add_argument("--layer", choices=["heuristic", "model"])
    ap.add_argument(
        "--fetch-311", action="store_true", help="download a fresh 311 CSV first"
    )
    a = ap.parse_args(argv)
    t0 = time.monotonic()
    try:
        plan = prepare(a.start, a.end or a.start, a.layer, a.fetch_311)
        written = write(plan)
    except InputsIncomplete as e:
        print(
            f"SCORE FAILED (inputs incomplete; nothing written): {e}", file=sys.stderr
        )
        return 1
    except (ScoreError, inference.ModelDisabledError, FileNotFoundError, KeyError) as e:
        print(
            f"SCORE FAILED (artifact/registry; nothing written): {e}", file=sys.stderr
        )
        return 2
    summary = {
        "layer": plan["layer"],
        "written": written,
        "rows_per_day": {d: len(t) for d, t in plan["tables"].items()},
        "out_of_season_skipped": plan["out_of_season"],
        "source_311": plan.get("source_311"),
        "wall_s": round(time.monotonic() - t0, 1),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
