"""Runner for the pre-registered gate in `models/gate-logreg-2026.md`.

    uv run python -m winterpath_ml.gate_logreg_2026 --check   # guards only; never fits or scores anything
    uv run python -m winterpath_ml.gate_logreg_2026           # the single official run (on/after 2027-05-08)

Hard guards (no override flag exists on purpose):
- refuses to run before EARLIEST_RUN;
- refuses if any pinned source file differs from the sha256 recorded in the gate document;
- refuses if the coverage cell list differs from the committed copy;
- declares the run VOID (model stays disabled) under the document's no-decision conditions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, data_311, features, metrics, models, splits, weather

GATE_DOC = config.MODELS_DIR / "gate-logreg-2026.md"
EARLIEST_RUN = date(2027, 5, 8)
CANDIDATE_ID = "winter311-logreg-v1"

PINNED_SHA256 = {
    "features.py": "2199140353e2d9f741674907bdbc85c7b802147d391eae33a729d705e420b605",
    "models.py": "49884b4dd63e9aac96b8ec4e0365dfa05d93335d121c8c725dc3f8418c459165",
    "metrics.py": "8e9b43290338c50020e2ebec3a66f079bdd2fa81b9670f303e61fe7078920844",
    "splits.py": "1aea7d1beb9a28ddb6778b3982122cd5d54bec134ff6ffdbbcdf3940a27ce07b",
    "weather.py": "b5ec7019ed198adb52931ac0aa1e831248b3590f04a2323514d71602d379d848",
    "data_311.py": "dd114f6bb3371a6c19bb57c9c6bd03fb954f19f2153d876fdb2a4fad0c27f032",
}
COVERAGE_TXT = config.MODELS_DIR / "coverage-v2-8d19aa86-cells.txt"
COVERAGE_TXT_SHA256 = "3e80a04b27c0a8b8ab80793260cc5627256cb892db7d0fbef2e4f743dfd95e58"

TRAIN_WINTERS = (2021, 2022, 2023, 2024)
CALIB_WINTER = 2025
TEST_WINTER = 2026
TEST_END = pd.Timestamp(2027, 4, 30)
MIN_TEST_POSITIVES = 5000
MAX_SNOW_MISSING = 0.10
MARGIN = 0.010
BOROUGH_MIN_POSITIVES = 100
BOROUGH_RATIO = (0.5, 2.0)
COMPARATORS = ("baseline_hist_freq", "baseline_freq_x_weather")
CANDIDATE = (
    "baseline_logistic"  # models.Logistic, promoted to CANDIDATE_ID if the gate passes
)

RAW_SNAPSHOT = config.RAW_DIR / "requetes311_gate2026.csv"
INTERIM = config.INTERIM_DIR / "gate2026"
SRC = Path(__file__).resolve().parent


class GuardError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_pins() -> None:
    bad = [f for f, h in PINNED_SHA256.items() if _sha(SRC / f) != h]
    if bad:
        raise GuardError(
            f"pinned files changed: {bad} — add a dated addendum to {GATE_DOC.name} or the run is void"
        )
    if _sha(COVERAGE_TXT) != COVERAGE_TXT_SHA256:
        raise GuardError("coverage cell list changed")


def check_date(today: date) -> None:
    if today < EARLIEST_RUN:
        raise GuardError(
            f"pre-registered earliest run date is {EARLIEST_RUN}; today is {today}. Test winter not evaluable."
        )


def load_coverage() -> list[str]:
    return [c for c in COVERAGE_TXT.read_text().split() if c]


def assign(panel: pd.DataFrame, cells: list[str]) -> np.ndarray:
    """Roles per the gate document: train | calib | test_chrono | test_spatial | unused."""
    hold = splits.holdout_blocks(cells)
    in_hold = panel["h3"].map(splits.spatial_blocks(cells)).isin(hold).to_numpy()
    w = panel["winter"].to_numpy()
    out = np.full(len(panel), "unused", dtype=object)
    out[np.isin(w, TRAIN_WINTERS) & ~in_hold] = "train"
    out[(w == CALIB_WINTER) & ~in_hold] = "calib"
    out[(w == TEST_WINTER) & ~in_hold] = "test_chrono"
    out[(w == TEST_WINTER) & in_hold] = "test_spatial"
    return out


def decide(results: dict, ci: dict, borough: list[dict]) -> dict:
    """Apply the four pre-registered criteria. Pure function of measured numbers."""
    out = {}
    for split in ("test_chrono", "test_spatial"):
        r = results[split]
        best = max(COMPARATORS, key=lambda b: r[b]["pr_auc"])
        diff = r[CANDIDATE]["pr_auc"] - r[best]["pr_auc"]
        out[split] = {
            "best_comparator": best,
            "pr_auc_diff": diff,
            "pr_auc_diff_ci95": list(ci[split]),
            "pass_margin": bool(diff >= MARGIN),
            "pass_ci": bool(ci[split][0] > 0),
            "pass_brier": bool(
                r[CANDIDATE]["brier"] < min(r[b]["brier"] for b in COMPARATORS)
            ),
        }
    lo, hi = BOROUGH_RATIO
    offenders = [
        b["borough"]
        for b in borough
        if b["positives"] >= BOROUGH_MIN_POSITIVES
        and not (lo <= b["mean_pred"] / b["obs_rate"] <= hi)
    ]
    out["borough_calibration"] = {"offenders": offenders, "pass": not offenders}
    out["pass"] = (
        all(
            out[s][k]
            for s in ("test_chrono", "test_spatial")
            for k in ("pass_margin", "pass_ci", "pass_brier")
        )
        and out["borough_calibration"]["pass"]
    )
    return out


def _download_snapshot() -> Path:
    if not RAW_SNAPSHOT.exists():
        RAW_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(
            config.URL_311_2022_PRESENT, headers={"User-Agent": weather.USER_AGENT}
        )
        with (
            urllib.request.urlopen(req, timeout=900) as r,
            open(RAW_SNAPSHOT, "wb") as f,
        ):
            while chunk := r.read(1 << 20):
                f.write(chunk)
    if date.fromtimestamp(RAW_SNAPSHOT.stat().st_mtime) < EARLIEST_RUN:
        raise GuardError(
            f"{RAW_SNAPSHOT} predates {EARLIEST_RUN}; delete it and re-run"
        )
    return RAW_SNAPSHOT


def run(today: date) -> dict:
    check_pins()
    check_date(today)
    raw = _download_snapshot()
    raw_sha = _sha(raw)
    paths = data_311.build_interim(raw, INTERIM)
    rc, ac = pd.read_parquet(paths["report_cells"]), pd.read_parquet(paths["all_cells"])
    w = weather.load_weather(date(2021, 10, 1), date(2027, 5, 7))
    cells = load_coverage()

    void = []
    if ac["day"].max() < TEST_END:
        void.append(f"311 snapshot ends {ac['day'].max().date()} < {TEST_END.date()}")
    test_days = pd.date_range(pd.Timestamp(TEST_WINTER, 11, 1), TEST_END)
    snow_missing = float(w["snow"].reindex(test_days).isna().mean())
    if snow_missing > MAX_SNOW_MISSING:
        void.append(f"TOTAL_SNOW missing on {snow_missing:.1%} of test days")

    panel = features.build_panel(
        rc, ac, w, cells, pd.Timestamp(config.PANEL_START), TEST_END
    )
    panel["role"] = assign(panel, cells)
    parts = {
        k: panel[panel["role"] == k]
        for k in ("train", "calib", "test_chrono", "test_spatial")
    }
    if int(parts["test_chrono"]["label"].sum()) < MIN_TEST_POSITIVES:
        void.append(
            f"test_chrono positives {int(parts['test_chrono']['label'].sum())} < {MIN_TEST_POSITIVES}"
        )

    fitted = {
        m.name: models.Calibrated(m.fit(parts["train"])).calibrate(parts["calib"])
        for m in models.all_methods()
    }
    results, ci = {}, {}
    for split in ("test_chrono", "test_spatial"):
        d = parts[split]
        y, day = d["label"].to_numpy(), d["day"].to_numpy()
        results[split] = {
            n: metrics.summary(day, y, f.score(d), f.proba(d))
            for n, f in fitted.items()
        }
        best = max(COMPARATORS, key=lambda b: results[split][b]["pr_auc"])
        ci[split] = metrics.bootstrap_pr_auc_diff(
            day, y, fitted[CANDIDATE].score(d), fitted[best].score(d)
        )

    boro = features.modal_borough(ac, pd.Timestamp(2024, 11, 1))
    d = parts["test_chrono"]
    bdf = pd.DataFrame(
        {
            "borough": d["h3"].map(boro).fillna("UNKNOWN").to_numpy(),
            "y": d["label"].to_numpy(),
            "p": fitted[CANDIDATE].proba(d),
        }
    )
    borough = [
        {
            "borough": b,
            "n": len(g),
            "positives": int(g["y"].sum()),
            "obs_rate": float(g["y"].mean()),
            "mean_pred": float(g["p"].mean()),
        }
        for b, g in bdf.groupby("borough")
    ]

    gate = decide(results, ci, borough)
    decision = "VOID" if void else ("PASS" if gate["pass"] else "FAIL")
    out = {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "protocol": GATE_DOC.name,
        "candidate": CANDIDATE_ID,
        "source_311_sha256": raw_sha,
        "rows": {k: len(v) for k, v in parts.items()},
        "positives": {k: int(v["label"].sum()) for k, v in parts.items()},
        "results": results,
        "gate": gate,
        "per_borough_test_chrono": borough,
        "void_reasons": void,
        "decision": decision,
    }
    path = config.MODELS_DIR / "evaluation" / f"logreg-2026-{raw_sha[:8]}.json"
    path.write_text(json.dumps(out, indent=2, default=float))
    rows = [
        {"split": s, "method": m, **v} for s in results for m, v in results[s].items()
    ]
    from .evaluate import fmt_table

    print(
        fmt_table(
            rows,
            [
                "split",
                "method",
                "pr_auc",
                "brier",
                "precision_at_k",
                "recall_at_k",
                "base_rate",
                "n",
            ],
        )
    )
    print(json.dumps(gate, indent=2, default=float))
    print(f"DECISION: {decision}" + (f" ({'; '.join(void)})" if void else ""))
    print(
        "Registry is NOT modified by this runner. On PASS, promote via a reviewed commit per the gate document.",
        file=sys.stderr,
    )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--check",
        action="store_true",
        help="verify guards only; fits and scores nothing",
    )
    a = ap.parse_args(argv)
    try:
        check_pins()
        print("pins OK; coverage list OK")
        if a.check:
            try:
                check_date(date.today())
                print(f"date OK (>= {EARLIEST_RUN})")
            except GuardError as e:
                print(f"date guard: {e}")
            return 0
        run(date.today())
    except GuardError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
