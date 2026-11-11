"""Batch scoring: write per-day score tables that inference providers read.

    uv run python -m winterpath_ml.score --start 2026-01-10 --end 2026-01-12 [--layer heuristic|model]

Refuses (writes nothing for) a day when its inputs are incomplete: 311 aggregates must reach
D-1 and the D-1…D-3 weather observations must exist. Missing days stay `unknown` downstream.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime

import joblib
import pandas as pd

from . import config, features, inference, weather


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


def score_days(start: date, end: date, layer: str | None = None) -> list[str]:
    reg = inference.load_registry()
    layer = layer or reg["active_layer"]
    entry = reg["layers"][layer]
    if layer == "model" and not entry["enabled"]:
        raise inference.ModelDisabledError("model layer is disabled in the registry")
    scorer = joblib.load(inference.artifact_path(reg, entry["artifact"]))
    cells = pd.read_parquet(inference.artifact_path(reg, reg["coverage"]))[
        "h3"
    ].tolist()
    rc = pd.read_parquet(config.INTERIM_DIR / "report_311_cell.parquet")
    ac = pd.read_parquet(config.INTERIM_DIR / "all_requests_cell.parquet")
    wd = weather.load_weather(date(2021, 10, 1), end)
    out_dir = inference.scores_dir(reg, layer)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for d in pd.date_range(start, end):
        why = inputs_ready(d, rc, ac, wd)
        if why:
            print(f"{d.date()}: skipped ({why})", file=sys.stderr)
            continue
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
                "scored_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                # inputs are observations up to the end of D-1 (local)
                "data_through": datetime(
                    d.year, d.month, d.day, tzinfo=inference.LOCAL_TZ
                )
                .astimezone(UTC)
                .isoformat(),
            }
        )
        path = out_dir / f"{d.date()}.parquet"
        out.to_parquet(path, index=False)
        written.append(str(path))
        print(f"{d.date()}: {len(out)} cells -> {path}", file=sys.stderr)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=date.fromisoformat, required=True)
    ap.add_argument("--end", type=date.fromisoformat)
    ap.add_argument("--layer", choices=["heuristic", "model"])
    a = ap.parse_args(argv)
    score_days(a.start, a.end or a.start, a.layer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
