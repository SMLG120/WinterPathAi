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

Policy
- A day whose inputs are not published yet (311 does not reach D-1, or the D-3..D-1 weather is
  incomplete) is not written. The run prints a notice and continues. That alone is not a failure.
- Every day that is scored is validated: exactly one row per coverage cell, finite p in [0, 1].
  If any scored day fails validation, nothing at all is written.
- Each table is written to `.<day>.parquet.tmp` and renamed into place, so a reader never sees a
  half-written day.
- Staleness: after the run, if the season is on and the newest score table on disk is for a day
  that began (local midnight) more than STALE_HOURS ago, the run fails.
- Out-of-season days are skipped with a notice (the layer is undefined there; providers return
  `unknown`).

Exit status
- 0: written, or nothing ready yet (notice), or out of season.
- 1: validation failed (nothing written).
- 2: artifact or registry error (missing, sha256 mismatch, model disabled).
- 3: download failed (311 or ECCC).
- 4: stale, i.e. the newest scored day is more than STALE_HOURS old.
- 5: database write failed (`--write-db`); the transaction rolled back.

`--write-db` (contract v1.7) writes `wp.risk_cell_score` through `score_db.write_scores`: each
scored (day, model_id) partition is replaced in one transaction, rows older than 30 days are
deleted, and a `wp.ingest_run` row is recorded. Staleness is then checked against the table.

Under GitHub Actions (`GITHUB_ACTIONS=true`), notices and errors are also emitted as
`::notice::` / `::error::` annotations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, data_311, features, inference, weather

SCORE_CACHE = config.CACHE_DIR / "score"
STALE_HOURS = 36
NETWORK_ERRORS = (urllib.error.URLError, TimeoutError, ConnectionError, OSError)


class ScoreError(RuntimeError):
    """Artifact or registry problem (exit 2)."""


class ValidationFailed(RuntimeError):
    """A scored day's table is incomplete or invalid (exit 1)."""


class DownloadFailed(RuntimeError):
    """A source could not be downloaded (exit 3)."""


def _annotate(kind: str, msg: str) -> None:
    print(f"{kind.upper()}: {msg}", file=sys.stderr)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::{kind} title=winterpath_ml.score::{msg}", flush=True)


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
        raise ValidationFailed(
            f"{day.date()}: invalid score table ({'; '.join(problems)})"
        )


def fetch_311(dest: Path) -> Path:
    """Download the 311 CSV to `dest/requetes311.csv` via a .part file (no partial file left)."""
    dest.mkdir(parents=True, exist_ok=True)
    final, part = dest / "requetes311.csv", dest / "requetes311.csv.part"
    url = config.URL_311_2022_PRESENT
    req = urllib.request.Request(url, headers={"User-Agent": weather.USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=900) as r, open(part, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
    except NETWORK_ERRORS as e:
        part.unlink(missing_ok=True)
        raise DownloadFailed(
            f"311 CSV download failed: GET {url} -> {type(e).__name__}: {e}. "
            "Check that this runner can reach donnees.montreal.ca (HTTPS, port 443). Nothing was written."
        ) from e
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
            raise ScoreError(f"311 aggregates missing: {p} (use --fetch-311)")
    rc, ac = pd.read_parquet(paths["report_cells"]), pd.read_parquet(paths["all_cells"])
    meta["last_day"] = str(ac["day"].max().date())
    return rc, ac, meta


def load_weather_fresh(start: date, end: date) -> pd.DataFrame:
    """ECCC observations fetched now; a cached file could predate the latest observations."""
    try:
        with tempfile.TemporaryDirectory() as td:
            prim = weather.fetch_climate_daily(
                config.STATION_PRIMARY, start, end, Path(td)
            )
            fb = weather.fetch_climate_daily(
                config.STATION_FALLBACK, start, end, Path(td)
            )
    except NETWORK_ERRORS as e:
        raise DownloadFailed(
            f"ECCC climate-daily download failed: {config.ECCC_API} -> {type(e).__name__}: {e}. "
            "Check that this runner can reach the ECCC GeoMet API. Nothing was written."
        ) from e
    return weather.build_daily_weather(prim, fb)


def prepare(start: date, end: date, layer: str | None, fetch: bool) -> dict:
    """Load inputs and score every ready day, validating each. Writes nothing."""
    reg = inference.load_registry()
    layer = layer or reg["active_layer"]
    entry = reg["layers"][layer]
    if layer == "model" and not entry["enabled"]:
        raise inference.ModelDisabledError("model layer is disabled in the registry")
    days = pd.date_range(start, end)
    in_season = [d for d in days if d.month in config.SEASON_MONTHS]
    plan = {
        "registry": reg,
        "layer": layer,
        "tables": {},
        "out_of_season": [str(d.date()) for d in days if d not in in_season],
        "not_ready": {},
    }
    if not in_season:
        return plan

    scorer_path = verified(reg, entry["artifact"])
    cells = pd.read_parquet(verified(reg, reg["coverage"]))["h3"].tolist()
    rc, ac, plan["source_311"] = load_311(fetch)
    wd = load_weather_fresh(date(2021, 10, 1), end)

    ready = []
    for d in in_season:
        why = inputs_ready(d, rc, ac, wd)
        if why:
            plan["not_ready"][str(d.date())] = why
        else:
            ready.append(d)
    if not ready:
        return plan

    import joblib  # sha-verified above; batch job only, never imported by the API path

    scorer = joblib.load(scorer_path)
    scored_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    for d in ready:
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


def newest_scored_day(out_dir: Path) -> date | None:
    days = []
    for f in out_dir.glob("*.parquet") if out_dir.exists() else []:
        try:
            days.append(date.fromisoformat(f.stem))
        except ValueError:
            continue
    return max(days, default=None)


def staleness(newest: date | None, now: datetime, where: str) -> str | None:
    """Reason string if the newest scored day began more than STALE_HOURS ago (in season only)."""
    local_now = now.astimezone(inference.LOCAL_TZ)
    if local_now.month not in config.SEASON_MONTHS:
        return None
    if newest is None:
        return f"no score tables in {where}"
    began = datetime(newest.year, newest.month, newest.day, tzinfo=inference.LOCAL_TZ)
    age_h = (now - began).total_seconds() / 3600
    if age_h > STALE_HOURS:
        return f"newest scored day {newest} began {age_h:.1f} h ago (> {STALE_HOURS} h)"
    return None


def score_days(
    start: date, end: date, layer: str | None = None, fetch_311: bool = False
) -> list[str]:
    return write(prepare(start, end, layer, fetch_311))


def main(argv: list[str] | None = None, now: datetime | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=date.fromisoformat, required=True)
    ap.add_argument("--end", type=date.fromisoformat)
    ap.add_argument("--layer", choices=["heuristic", "model"])
    ap.add_argument(
        "--fetch-311", action="store_true", help="download a fresh 311 CSV first"
    )
    ap.add_argument(
        "--write-db",
        action="store_true",
        help="write wp.risk_cell_score (DATABASE_URL) instead of parquet files",
    )
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    a = ap.parse_args(argv)
    if a.write_db and not a.database_url:
        _annotate("error", "--write-db needs DATABASE_URL or --database-url")
        return 2
    t0 = time.monotonic()
    try:
        plan = prepare(a.start, a.end or a.start, a.layer, a.fetch_311)
    except ValidationFailed as e:
        _annotate("error", f"validation failed; nothing written: {e}")
        return 1
    except (ScoreError, inference.ModelDisabledError, FileNotFoundError, KeyError) as e:
        _annotate("error", f"artifact/registry error; nothing written: {e}")
        return 2
    except DownloadFailed as e:
        _annotate("error", str(e))
        return 3
    model_id = plan["registry"]["layers"][plan["layer"]]["id"]
    db_summary = None
    if a.write_db:
        from . import score_db

        try:
            with score_db.connect(a.database_url) as conn:
                if plan["tables"] or not plan["out_of_season"]:
                    db_summary = score_db.write_scores(conn, plan)
                newest = score_db.newest_day(conn, model_id)
        except Exception as e:  # noqa: BLE001 - any DB failure is a loud failure
            _annotate(
                "error",
                f"database write failed; transaction rolled back, previous scores intact: "
                f"{type(e).__name__}: {e}",
            )
            return 5
        written, where = (
            [f"{score_db.TABLE} day={d}" for d in plan["tables"]],
            score_db.TABLE,
        )
    else:
        written = write(plan)
        out_dir = inference.scores_dir(plan["registry"], plan["layer"])
        newest, where = newest_scored_day(out_dir), str(out_dir)
    for d, why in plan["not_ready"].items():
        _annotate(
            "notice", f"{d} not scored yet: {why}. Will be scored on a later run."
        )
    if plan["out_of_season"]:
        _annotate(
            "notice", f"out of season, not scored: {', '.join(plan['out_of_season'])}"
        )
    stale = staleness(newest, now or datetime.now(UTC), where)
    print(
        json.dumps(
            {
                "layer": plan["layer"],
                "model_id": model_id,
                "written": written,
                "rows_per_day": {d: len(t) for d, t in plan["tables"].items()},
                "not_ready": plan["not_ready"],
                "out_of_season_skipped": plan["out_of_season"],
                "newest_scored_day": str(newest),
                "db": db_summary,
                "source_311": plan.get("source_311"),
                "wall_s": round(time.monotonic() - t0, 1),
            },
            indent=2,
        )
    )
    if stale:
        _annotate("error", f"score tables are stale: {stale}")
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
