"""Phase 5 EXPLORATORY model comparison on the v2 snapshot. Hypothesis-generating only.

    uv run --extra phase5 python -m winterpath_ml.phase5_explore

- Data: the v2 panel `models/artifacts/v2-8d19aa86/features.parquet` (sha256 checked against
  `models/registry.json`) and the v2 interim 311 aggregates (snapshot 8d19aa86) for daily counts.
- Embargo (`models/gate-island-2027.DRAFT.md`): every input frame is filtered to day < 2026-11-01
  and the run asserts the maximum day read. Winter 2026-27 is never read.
- Splits: exactly v2's. Fit on `train` (Feb 2022 – Apr 2024), isotonic-calibrate on `valid`
  (2024-25), report on `test_chrono` and `test_spatial` (2025-26). Winter 2025-26 was already seen
  (v2 test), so every number here is **hypothesis-generating, not a validation claim**.
- Frozen files are imported read-only (`models`, `metrics`, `features`, `config`); nothing in the
  registry or the gates changes, and nothing is published to the API.
- Hyper-parameters below were fixed before the first run; there is no search.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import PoissonRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

from . import config, features, metrics, models
from .features import FEATURES

RUN_ID = "phase5-explore-8d19aa86"
EMBARGO = pd.Timestamp("2026-11-01")
PANEL = config.ARTIFACT_DIR / "v2-8d19aa86" / "features.parquet"
OUT = config.MODELS_DIR / "artifacts" / RUN_ID
ALERT_RATES = (0.01, 0.05)  # share of cell-days flagged each day
GATING = ("baseline_hist_freq", "baseline_freq_x_weather")
SPLITS = ("test_chrono", "test_spatial")
LABEL = "EXPLORATORY: hypothesis-generating; winter 2025-26 was already seen (v2 test). Not a validation claim."


@dataclass
class Poisson:
    """Poisson regression on the daily report count; score = predicted mean count."""

    name: str = "poisson_count"
    params: dict = field(default_factory=lambda: {"alpha": 1e-4, "max_iter": 1000})
    model: object = None

    def fit(self, df: pd.DataFrame) -> Poisson:
        self.model = make_pipeline(
            FunctionTransformer(models._log_counts),
            SimpleImputer(strategy="median", add_indicator=True),
            StandardScaler(),
            PoissonRegressor(**self.params),
        )
        self.model.fit(df[FEATURES], df["count"].to_numpy(dtype=float))
        return self

    def score(self, df: pd.DataFrame) -> np.ndarray:
        return self.model.predict(df[FEATURES])


@dataclass
class RandomForest:
    name: str = "random_forest"
    params: dict = field(
        default_factory=lambda: {
            "n_estimators": 300,
            "min_samples_leaf": 100,
            "max_features": "sqrt",
            "max_samples": 0.5,
            "n_jobs": -1,
            "random_state": 0,
        }
    )
    model: object = None

    def fit(self, df: pd.DataFrame) -> RandomForest:
        self.model = make_pipeline(
            SimpleImputer(strategy="median", add_indicator=True),
            RandomForestClassifier(**self.params),
        )
        self.model.fit(df[FEATURES], df["label"].to_numpy())
        return self

    def score(self, df: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(df[FEATURES])[:, 1]


@dataclass
class XGBoost:
    name: str = "xgboost"
    params: dict = field(
        default_factory=lambda: {
            "n_estimators": 400,
            "max_depth": 6,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "min_child_weight": 50,
            "reg_lambda": 1.0,
            "tree_method": "hist",
            "random_state": 0,
            "n_jobs": -1,
            "eval_metric": "logloss",
        }
    )
    model: object = None

    def fit(self, df: pd.DataFrame) -> XGBoost:
        import xgboost

        self.model = xgboost.XGBClassifier(**self.params)
        self.model.fit(df[FEATURES], df["label"].to_numpy())
        return self

    def score(self, df: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(df[FEATURES])[:, 1]


def methods() -> list:
    """Owner's candidate list plus v2's HGB as a reference (it was the failed v2 candidate)."""
    return [
        models.HistoricalFrequency(),
        models.FrequencyWeatherHeuristic(),
        models.Logistic(),
        Poisson(),
        RandomForest(),
        XGBoost(),
        models.GradientBoosting(),
    ]


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while b := f.read(1 << 20):
            h.update(b)
    return h.hexdigest()


def at_alert_rate(day: np.ndarray, y: np.ndarray, s: np.ndarray, rate: float) -> dict:
    """Flag the top ceil(rate × cells that day) each day; pooled precision and recall."""
    df = pd.DataFrame({"day": day, "y": y, "s": s})
    df["r"] = df.groupby("day")["s"].rank(method="first", ascending=False)
    k = np.ceil(rate * df.groupby("day")["s"].transform("size"))
    flag = df["r"] <= k
    hits, flagged, pos = (
        int(df.loc[flag, "y"].sum()),
        int(flag.sum()),
        int(df["y"].sum()),
    )
    return {
        "alert_rate": rate,
        "flagged": flagged,
        "precision": hits / flagged if flagged else float("nan"),
        "recall": hits / pos if pos else float("nan"),
    }


def load_inputs() -> tuple[pd.DataFrame, pd.Series, dict]:
    reg = json.loads(config.REGISTRY_PATH.read_text())
    sha = _sha(PANEL)
    if sha != reg["features"]["sha256"]:
        raise RuntimeError(
            f"v2 panel sha256 {sha} != registry {reg['features']['sha256']}"
        )
    panel = pd.read_parquet(PANEL)
    panel = panel[panel["day"] < EMBARGO]
    rc = pd.read_parquet(config.INTERIM_DIR / "report_311_cell.parquet")
    ac = pd.read_parquet(config.INTERIM_DIR / "all_requests_cell.parquet")
    src = (config.INTERIM_DIR / "source_sha256.txt").read_text().strip()
    if not src.startswith("8d19aa86"):
        raise RuntimeError(f"interim snapshot {src[:8]} is not v2's 8d19aa86")
    rc, ac = rc[rc["day"] < EMBARGO], ac[ac["day"] < EMBARGO]
    counts = rc.groupby(["h3", "day"])["n"].sum()
    panel = panel.join(counts.rename("count"), on=["h3", "day"])
    panel["count"] = panel["count"].fillna(0).astype(int)
    if not ((panel["count"] > 0).astype(int) == panel["label"]).all():
        raise RuntimeError("count>0 does not reproduce the v2 label")
    boro = features.modal_borough(ac, pd.Timestamp(2024, 11, 1))
    max_day = max(panel["day"].max(), rc["day"].max(), ac["day"].max())
    assert max_day < EMBARGO, max_day
    meta = {
        "panel_sha256": sha,
        "source_311_sha256": src,
        "max_day_read": str(max_day.date()),
        "embargo_before": str(EMBARGO.date()),
    }
    return panel, boro, meta


def run(n_boot: int = 200) -> dict:
    t0 = time.monotonic()
    panel, boro, meta = load_inputs()
    parts = {k: panel[panel["split"] == k] for k in ("train", "valid", *SPLITS)}
    fitted, fit_s = {}, {}
    for m in methods():
        t = time.monotonic()
        fitted[m.name] = models.Calibrated(m.fit(parts["train"])).calibrate(
            parts["valid"]
        )
        fit_s[m.name] = round(time.monotonic() - t, 1)
        print(f"fitted {m.name} in {fit_s[m.name]} s", file=sys.stderr)

    results, reliability, borough = {}, [], []
    for split in SPLITS:
        d = parts[split]
        y, day = d["label"].to_numpy(), d["day"].to_numpy()
        res = {}
        scores = {n: f.score(d) for n, f in fitted.items()}
        probas = {n: f.proba(d) for n, f in fitted.items()}
        best = max(GATING, key=lambda b: metrics.pr_auc(y, scores[b]))
        for n in fitted:
            r = metrics.summary(day, y, scores[n], probas[n])
            r["alert"] = [at_alert_rate(day, y, scores[n], a) for a in ALERT_RATES]
            if n != best:
                lo, hi = metrics.bootstrap_pr_auc_diff(
                    day, y, scores[n], scores[best], n_boot
                )
                r["pr_auc_diff_vs_best_baseline"] = r["pr_auc"] - metrics.pr_auc(
                    y, scores[best]
                )
                r["pr_auc_diff_ci95"] = [lo, hi]
            res[n] = r
            cc = metrics.calibration_curve(y, probas[n], n_bins=10)
            for i, row in cc.iterrows():
                reliability.append(
                    {"split": split, "method": n, "bin": i, **row.to_dict()}
                )
            b = pd.DataFrame(
                {
                    "borough": d["h3"].map(boro).fillna("UNKNOWN").to_numpy(),
                    "y": y,
                    "p": probas[n],
                    "s": scores[n],
                    "day": day,
                }
            )
            k = np.ceil(0.05 * b.groupby("day")["s"].transform("size"))
            b["flag"] = b.groupby("day")["s"].rank(method="first", ascending=False) <= k
            for name, g in b.groupby("borough"):
                pos = int(g["y"].sum())
                borough.append(
                    {
                        "split": split,
                        "method": n,
                        "borough": name,
                        "n": len(g),
                        "positives": pos,
                        "obs_rate": float(g["y"].mean()),
                        "mean_pred": float(g["p"].mean()),
                        "pred_obs_ratio": float(g["p"].mean() / g["y"].mean())
                        if pos
                        else None,
                        "brier": float(np.mean((g["p"] - g["y"]) ** 2)),
                        "pr_auc": metrics.pr_auc(g["y"].to_numpy(), g["s"].to_numpy())
                        if pos >= 30
                        else None,
                        "recall_at_5pct_citywide": float(
                            g.loc[g["y"] == 1, "flag"].mean()
                        )
                        if pos
                        else None,
                    }
                )
        results[split] = {"best_gating_baseline": best, "methods": res}

    out = {
        "run_id": RUN_ID,
        "label": LABEL,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "inputs": meta,
        "splits": {
            k: {
                "rows": len(v),
                "positives": int(v["label"].sum()),
                "days": f"{v['day'].min().date()}..{v['day'].max().date()}",
            }
            for k, v in parts.items()
        },
        "params": {
            m.name: getattr(m, "params", None)
            for m in methods()
            if hasattr(m, "params")
        },
        "fit_seconds": fit_s,
        "results": results,
        "versions": _versions(),
        "wall_s": round(time.monotonic() - t0, 1),
    }
    return {"out": out, "reliability": reliability, "borough": borough}


def _versions() -> dict:
    import importlib.metadata as md

    v = {"python": platform.python_version(), "platform": platform.platform()}
    for p in ("scikit-learn", "numpy", "pandas", "xgboost", "xgboost-cpu"):
        try:
            v[p] = md.version(p)
        except md.PackageNotFoundError:
            pass
    return v


def write(res: dict, out_dir: Path = OUT) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "results.json": json.dumps(res["out"], indent=2, default=float) + "\n",
        "reliability.csv": pd.DataFrame(res["reliability"]).to_csv(index=False),
        "borough.csv": pd.DataFrame(res["borough"]).to_csv(index=False),
    }
    for name, text in files.items():
        (out_dir / name).write_text(text)
    manifest = {
        "run_id": RUN_ID,
        "label": LABEL,
        "generated_at": res["out"]["generated_at"],
        "inputs": res["out"]["inputs"],
        "files": {
            n: {"bytes": (out_dir / n).stat().st_size, "sha256": _sha(out_dir / n)}
            for n in files
        },
        "not_included": "fitted models (pickles) are not saved; re-run the module to reproduce",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> int:
    res = run()
    man = write(res)
    print(json.dumps(man, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
