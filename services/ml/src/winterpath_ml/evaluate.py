"""End-to-end, reproducible evaluation from raw public data.

    uv run python -m winterpath_ml.evaluate            # full run: metrics table, gate, artifacts, registry, card
    uv run python -m winterpath_ml.evaluate --no-test  # development: validation PR-AUC only, writes nothing

Inputs (downloaded into the git-ignored cache if missing):
  - Ville de Montréal 311 requests 2022–present (CC BY 4.0)
  - ECCC climate-daily, stations 7025251 + 702S006
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from . import config, data_311, features, metrics, models, splits, weather

VALID_START = pd.Timestamp(config.VALID_WINTER, 11, 1)
TEST_START = pd.Timestamp(config.TEST_WINTER, 11, 1)
TEST_END = pd.Timestamp(config.TEST_WINTER + 1, 4, 30)
WEATHER_START = date(2021, 10, 1)
WEATHER_END = date(2026, 11, 9)
GATE_PR_AUC_MARGIN = 0.010
HEURISTIC_ID = "winter311-heuristic-v1"
MODEL_ID = "winter311-hgb-v1"
# v1 = first run (coverage incl. demerged municipalities; superseded, kept in models/evaluation/ for the record)
# v2 = coverage restricted to the 19 City boroughs (label-audit finding). Gate procedure unchanged.
RUN_VERSION = "v2"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_raw() -> Path:
    if not config.RAW_311_CSV.exists():
        config.RAW_DIR.mkdir(parents=True, exist_ok=True)
        print(f"downloading {config.URL_311_2022_PRESENT}", file=sys.stderr)
        req = urllib.request.Request(config.URL_311_2022_PRESENT, headers={"User-Agent": weather.USER_AGENT})
        with urllib.request.urlopen(req, timeout=600) as r, open(config.RAW_311_CSV, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
    return config.RAW_311_CSV


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    raw = ensure_raw()
    raw_sha = sha256(raw)
    stamp = config.INTERIM_DIR / "source_sha256.txt"
    if not stamp.exists() or stamp.read_text().strip() != raw_sha:
        data_311.build_interim(raw)
        stamp.write_text(raw_sha)
    rc = pd.read_parquet(config.INTERIM_DIR / "report_311_cell.parquet")
    ac = pd.read_parquet(config.INTERIM_DIR / "all_requests_cell.parquet")
    w = weather.load_weather(WEATHER_START, WEATHER_END)
    return rc, ac, w, raw_sha


def fmt_table(rows: list[dict], cols: list[str]) -> str:
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        cells = []
        for c in cols:
            v = r[c]
            cells.append(f"{v:.4f}" if isinstance(v, float) else str(v))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def level_thresholds(valid_rate: float) -> dict[str, float]:
    return {"moderate": valid_rate, "elevated": 2 * valid_rate, "high": 4 * valid_rate}


def run(no_test: bool = False) -> dict:
    rc, ac, w, raw_sha = load_inputs()
    cells = features.select_universe(ac, VALID_START)
    panel = features.build_panel(rc, ac, w, cells, pd.Timestamp(config.PANEL_START), TEST_END)
    panel["split"] = splits.assign(panel, cells).to_numpy()
    parts = {s: panel[panel["split"] == s] for s in ("train", "valid", "test_chrono", "test_spatial")}
    print("rows per split:", {k: len(v) for k, v in parts.items()}, file=sys.stderr)

    fitted: dict[str, models.Calibrated] = {}
    for m in models.all_methods():
        print(f"fitting {m.name}", file=sys.stderr)
        fitted[m.name] = models.Calibrated(m.fit(parts["train"])).calibrate(parts["valid"])

    if no_test:
        v = parts["valid"]
        for name, f in fitted.items():
            print(f"valid PR-AUC {name}: {metrics.pr_auc(v['label'].to_numpy(), f.score(v)):.4f}")
        return {}

    results: dict[str, dict[str, dict]] = {}
    rows = []
    for split in ("test_chrono", "test_spatial"):
        d = parts[split]
        y, day = d["label"].to_numpy(), d["day"].to_numpy()
        results[split] = {}
        for name, f in fitted.items():
            s = metrics.summary(day, y, f.score(d), f.proba(d))
            results[split][name] = s
            rows.append({"split": split, "method": name, **s})

    # ---- gate (pre-registered in models/gate.md) ----
    gate: dict[str, dict] = {}
    for split in ("test_chrono", "test_spatial"):
        r = results[split]
        best_b = max(models.BASELINES, key=lambda b: r[b]["pr_auc"])
        best_brier = min(r[b]["brier"] for b in models.BASELINES)
        d = parts[split]
        lo, hi = metrics.bootstrap_pr_auc_diff(
            d["day"].to_numpy(),
            d["label"].to_numpy(),
            fitted[models.CANDIDATE].score(d),
            fitted[best_b].score(d),
        )
        diff = r[models.CANDIDATE]["pr_auc"] - r[best_b]["pr_auc"]
        gate[split] = {
            "best_baseline": best_b,
            "pr_auc_diff": diff,
            "pr_auc_diff_ci95": [lo, hi],
            "best_baseline_brier": best_brier,
            "pass_margin": bool(diff >= GATE_PR_AUC_MARGIN),
            "pass_ci": bool(lo > 0),
            "pass_brier": bool(r[models.CANDIDATE]["brier"] < best_brier),
        }
        gate[split]["pass"] = all(gate[split][k] for k in ("pass_margin", "pass_ci", "pass_brier"))
    gate_pass = all(g["pass"] for g in gate.values())

    # ---- calibration + per-borough (candidate and shipped heuristic) ----
    boro = features.modal_borough(ac, VALID_START)
    calib, per_borough = {}, {}
    for split in ("test_chrono", "test_spatial"):
        d = parts[split]
        y = d["label"].to_numpy()
        for name in (models.CANDIDATE, "baseline_freq_x_weather"):
            p = fitted[name].proba(d)
            calib[f"{split}/{name}"] = metrics.calibration_curve(y, p).round(5).to_dict(orient="records")
            df = pd.DataFrame({"borough": d["h3"].map(boro).fillna("UNKNOWN").to_numpy(), "y": y, "p": p, "s": fitted[name].score(d)})
            tab = []
            for b, g in df.groupby("borough"):
                tab.append(
                    {
                        "borough": b,
                        "n": int(len(g)),
                        "positives": int(g["y"].sum()),
                        "obs_rate": float(g["y"].mean()),
                        "mean_pred": float(g["p"].mean()),
                        "brier": metrics.brier(g["y"].to_numpy(), g["p"].to_numpy()),
                        "pr_auc": metrics.pr_auc(g["y"].to_numpy(), g["s"].to_numpy()) if 0 < g["y"].sum() < len(g) else None,
                    }
                )
            per_borough[f"{split}/{name}"] = tab

    valid_rate = float(parts["valid"]["label"].mean())
    out = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "target": config.TARGET,
        "source_311_sha256": raw_sha,
        "data_window": {
            "panel_start": str(config.PANEL_START),
            "panel_end": str(TEST_END.date()),
            "train_winters": list(config.TRAIN_WINTERS),
            "valid_winter": config.VALID_WINTER,
            "test_winter": config.TEST_WINTER,
        },
        "n_cells": len(cells),
        "n_holdout_blocks": len(splits.holdout_blocks(cells)),
        "rows": {k: int(len(v)) for k, v in parts.items()},
        "positives": {k: int(v["label"].sum()) for k, v in parts.items()},
        "valid_positive_rate": valid_rate,
        "level_thresholds": level_thresholds(valid_rate),
        "k_per_day": metrics.K_PER_DAY,
        "results": results,
        "gate": gate,
        "gate_pass": gate_pass,
        "calibration": calib,
        "per_borough": per_borough,
    }

    table = fmt_table(rows, ["split", "method", "pr_auc", "brier", "precision_at_k", "recall_at_k", "base_rate", "n"])
    print(table)
    print()
    for split, g in gate.items():
        print(
            f"gate {split}: best_baseline={g['best_baseline']} diff={g['pr_auc_diff']:.4f} "
            f"ci95=[{g['pr_auc_diff_ci95'][0]:.4f}, {g['pr_auc_diff_ci95'][1]:.4f}] "
            f"margin={g['pass_margin']} ci={g['pass_ci']} brier={g['pass_brier']} -> {'PASS' if g['pass'] else 'FAIL'}"
        )
    print(f"GATE: {'PASS -> model enabled' if gate_pass else 'FAIL -> heuristic layer, model disabled'}")

    write_artifacts(out, table, panel, cells, fitted, w, rc, ac)
    return out


def _file_entry(path: Path) -> dict:
    return {"path": str(path.relative_to(config.REPO_ROOT)), "bytes": path.stat().st_size, "sha256": sha256(path)}


def write_artifacts(out, table, panel, cells, fitted, w, rc, ac) -> None:
    run_id = f"{RUN_VERSION}-{out['source_311_sha256'][:8]}"
    adir = config.ARTIFACT_DIR / run_id
    adir.mkdir(parents=True, exist_ok=True)

    feat_path = adir / "features.parquet"
    panel.drop(columns=["split"]).assign(split=panel["split"]).to_parquet(feat_path, index=False)
    cov_path = adir / "coverage_cells.parquet"
    pd.DataFrame({"h3": cells}).to_parquet(cov_path, index=False)
    heur_path = adir / f"{HEURISTIC_ID}.joblib"
    joblib.dump(fitted["baseline_freq_x_weather"], heur_path)
    model_path = adir / f"{MODEL_ID}.joblib"
    joblib.dump(fitted[models.CANDIDATE], model_path)
    metrics_path = adir / "metrics.json"
    metrics_path.write_text(json.dumps(out, indent=2, default=float))

    # Committed copy of the measured numbers (small, no raw data).
    eval_dir = config.MODELS_DIR / "evaluation"
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / f"{run_id}.json").write_text(json.dumps(out, indent=2, default=float))

    enabled = bool(out["gate_pass"])
    rc_ = out["results"]
    limitations = [
        "Predicts whether a winter-related 311 REPORT will be filed in a ~0.1 km² H3 cell on a day; it does not measure ice, snow or sidewalk safety.",
        "Reports reflect who reports and where (reporting bias); low predicted values do not mean a sidewalk is cleared or safe.",
        "Weather features use observed values from the previous days at one airport station (ECCC 7025251/702S006); same-day forecasts are not used.",
        "Trained on winters 2021-22 (partial) to 2023-24; evaluated on 2025-26. Behaviour under new city operations or reporting channels is untested.",
        "Coverage = cells in the City of Montréal's 19 boroughs with 311 activity before 2024-11-01; demerged municipalities (e.g. Westmount, Mont-Royal) are not in this 311 dataset and return unknown.",
    ]
    registry = {
        "schema_version": 1,
        "generated_at": out["generated_at"],
        "target": config.TARGET,
        "run_id": run_id,
        "active_layer": "model" if enabled else "heuristic",
        "season_months": list(config.SEASON_MONTHS),
        "h3_resolution": config.H3_RES,
        "levels": {
            "thresholds": out["level_thresholds"],
            "basis": "calibrated probability p vs validation-winter positive rate r: low<r<=moderate<2r<=elevated<4r<=high",
        },
        "coverage": _file_entry(cov_path),
        "features": _file_entry(feat_path),
        "evaluation": _file_entry(metrics_path),
        "training_window": "2022-02-01..2024-04-30 (train), 2024-11-01..2025-04-30 (calibration)",
        "layers": {
            "heuristic": {
                "id": HEURISTIC_ID,
                "enabled": True,
                "evidence_state": "model_estimate",
                "expose_probability": False,
                "artifact": _file_entry(heur_path),
                "description": "hist_rate × (1 + snow_3d/5 + 0.5·freeze_thaw_3d + 0.5·[precip_1d>0 ∧ tmin_1d<0]); isotonic-mapped for levels only",
            },
            "model": {
                "id": MODEL_ID,
                "enabled": enabled,
                "evidence_state": "model_estimate",
                "expose_probability": enabled,
                "artifact": _file_entry(model_path),
                "card": f"models/cards/{MODEL_ID}.md",
                "evaluation": {
                    "split": "chronological 2025-11..2026-04 holdout + spatial block holdout (H3 res-6)",
                    "pr_auc": rc_["test_chrono"][models.CANDIDATE]["pr_auc"],
                    "brier": rc_["test_chrono"][models.CANDIDATE]["brier"],
                    "precision_at_k": rc_["test_chrono"][models.CANDIDATE]["precision_at_k"],
                    "recall_at_k": rc_["test_chrono"][models.CANDIDATE]["recall_at_k"],
                    "baseline_pr_auc": max(rc_["test_chrono"][b]["pr_auc"] for b in models.BASELINES),
                    "n_test": rc_["test_chrono"][models.CANDIDATE]["n"],
                    "spatial_pr_auc": rc_["test_spatial"][models.CANDIDATE]["pr_auc"],
                    "spatial_baseline_pr_auc": max(rc_["test_spatial"][b]["pr_auc"] for b in models.BASELINES),
                    "spatial_n_test": rc_["test_spatial"][models.CANDIDATE]["n"],
                },
                "gate": out["gate"],
            },
        },
        "limitations": limitations,
    }
    config.REGISTRY_PATH.write_text(json.dumps(registry, indent=2, ensure_ascii=False, default=float) + "\n")
    write_card(out, table, registry, limitations)


def write_card(out, table, registry, limitations) -> None:
    g = out["gate"]
    gate_lines = "\n".join(
        f"- **{s}**: best baseline `{v['best_baseline']}`, ΔPR-AUC = {v['pr_auc_diff']:.4f} "
        f"(95% CI {v['pr_auc_diff_ci95'][0]:.4f} … {v['pr_auc_diff_ci95'][1]:.4f}); "
        f"margin {'✔' if v['pass_margin'] else '✘'}, CI {'✔' if v['pass_ci'] else '✘'}, Brier {'✔' if v['pass_brier'] else '✘'} → **{'PASS' if v['pass'] else 'FAIL'}**"
        for s, v in g.items()
    )
    cal = out["calibration"]
    cal_md = []
    for key, recs in cal.items():
        cal_md.append(f"**{key}** (10 quantile bins: mean predicted → observed)\n")
        cal_md.append("| bin | mean_pred | obs_rate | n |\n|---|---|---|---|")
        cal_md += [f"| {i} | {r['mean_pred']:.5f} | {r['obs_rate']:.5f} | {r['n']} |" for i, r in enumerate(recs)]
        cal_md.append("")
    boro_md = []
    for key, recs in out["per_borough"].items():
        boro_md.append(f"**{key}**\n")
        boro_md.append("| borough | n | positives | obs_rate | mean_pred | brier | pr_auc |\n|---|---|---|---|---|---|---|")
        for r in sorted(recs, key=lambda r: -r["n"]):
            pa = "n/a" if r["pr_auc"] is None else f"{r['pr_auc']:.4f}"
            boro_md.append(
                f"| {r['borough']} | {r['n']} | {r['positives']} | {r['obs_rate']:.4f} | {r['mean_pred']:.4f} | {r['brier']:.5f} | {pa} |"
            )
        boro_md.append("")
    card = f"""# Model card — `{MODEL_ID}` (run `{registry['run_id']}`)

*Generated by `uv run python -m winterpath_ml.evaluate` at {out['generated_at']}. Every number below is copied programmatically from `models/evaluation/{registry['run_id']}.json`; do not edit by hand.*

- **Status:** `enabled = {str(registry['layers']['model']['enabled']).lower()}` · active layer: **{registry['active_layer']}**
- **Target:** {out['target']}. This is reporting behaviour, **not** ice, snow depth or sidewalk safety.
- **Data:** Ville de Montréal 311 requests (CC BY 4.0), file sha256 `{out['source_311_sha256']}`; ECCC climate-daily stations {config.STATION_PRIMARY} + {config.STATION_FALLBACK}.
- **Window:** panel {out['data_window']['panel_start']} … {out['data_window']['panel_end']} (Nov–Apr only). Train winters {out['data_window']['train_winters']} · calibration winter {out['data_window']['valid_winter']} · test winter {out['data_window']['test_winter']}.
- **Coverage:** {out['n_cells']} H3 res-9 cells (City of Montréal boroughs; any geolocated 311 request before 2024-11-01). Spatial holdout: {out['n_holdout_blocks']} H3 res-6 blocks.
- **Rows:** {out['rows']} · positives {out['positives']}.
- **Algorithm:** sklearn HistGradientBoostingClassifier (fixed hyper-parameters) + isotonic calibration on the validation winter.
- **Precision/recall@k:** top {out['k_per_day']} cells per day, pooled over test days. PR-AUC on uncalibrated scores; Brier on calibrated probabilities.

## Test metrics (all methods)

{table}

## Gate (pre-registered in `models/gate.md`)

{gate_lines}

**Decision:** {'model enabled' if out['gate_pass'] else 'model disabled; heuristic layer (baseline b) shipped with probability = null'}.

## Risk levels
Validation positive rate r = {out['valid_positive_rate']:.5f}. Thresholds on calibrated p: {json.dumps(out['level_thresholds'])}.

## Calibration

{chr(10).join(cal_md)}
## Per-borough error (test winter)

{chr(10).join(boro_md)}
## Limitations

{chr(10).join('- ' + x for x in limitations)}
"""
    path = config.MODELS_DIR / "cards" / f"{MODEL_ID}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(card)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-test", action="store_true", help="validation PR-AUC only; writes nothing")
    args = ap.parse_args(argv)
    run(no_test=args.no_test)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
