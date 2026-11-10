"""Evaluation metrics. All functions are pure and deterministic."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss

K_PER_DAY = 50  # precision/recall@k: top-k cells per day


def pr_auc(y: np.ndarray, s: np.ndarray) -> float:
    return float(average_precision_score(y, s))


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(brier_score_loss(y, np.clip(p, 0, 1)))


def calibration_curve(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    """Quantile-binned reliability table (mean predicted vs observed rate)."""
    df = pd.DataFrame({"y": y, "p": p})
    df["bin"] = pd.qcut(df["p"].rank(method="first"), q=n_bins, labels=False)
    t = df.groupby("bin").agg(
        mean_pred=("p", "mean"), obs_rate=("y", "mean"), n=("y", "size")
    )
    return t.reset_index(drop=True)


def precision_recall_at_k(
    day: np.ndarray, y: np.ndarray, s: np.ndarray, k: int = K_PER_DAY
) -> tuple[float, float]:
    """Top-k cells each day; pooled precision = hits / (k * days), recall = hits / positives."""
    df = pd.DataFrame({"day": day, "y": y, "s": s})
    df["r"] = df.groupby("day")["s"].rank(method="first", ascending=False)
    top = df[df["r"] <= k]
    hits = top["y"].sum()
    n_days = df["day"].nunique()
    pos = df["y"].sum()
    return float(hits / (k * n_days)), float(hits / pos) if pos else float("nan")


def summary(
    day: np.ndarray, y: np.ndarray, score: np.ndarray, prob: np.ndarray
) -> dict[str, float]:
    p_at_k, r_at_k = precision_recall_at_k(day, y, score)
    return {
        "pr_auc": pr_auc(y, score),
        "brier": brier(y, prob),
        "precision_at_k": p_at_k,
        "recall_at_k": r_at_k,
        "base_rate": float(np.mean(y)),
        "n": len(y),
    }


def bootstrap_pr_auc_diff(
    day: np.ndarray,
    y: np.ndarray,
    s_a: np.ndarray,
    s_b: np.ndarray,
    n_boot: int = 200,
    seed: int = 0,
) -> tuple[float, float]:
    """95% CI of PR-AUC(a) - PR-AUC(b), resampling whole days (block bootstrap)."""
    rng = np.random.default_rng(seed)
    days, inv = np.unique(day, return_inverse=True)
    order = np.argsort(inv, kind="stable")
    bounds = np.searchsorted(inv[order], np.arange(len(days) + 1))
    diffs = []
    for _ in range(n_boot):
        pick = rng.integers(0, len(days), len(days))
        idx = np.concatenate([order[bounds[i] : bounds[i + 1]] for i in pick])
        yy = y[idx]
        if yy.sum() == 0:
            continue
        diffs.append(pr_auc(yy, s_a[idx]) - pr_auc(yy, s_b[idx]))
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return float(lo), float(hi)
