# Agent 3 — Machine Learning Engineer

Branch `agent/ml` · worktree `../winterpath-ml` · port 8103, DB `wp_ml`, artifacts `models/artifacts/` (git-ignored; metadata committed).
**Owns:** `services/ml/`, `models/` (registry + model cards), `docs/agent-reports/ml.md`.
**Read first:** `CLAUDE.md`, `docs/architecture.md` ADR-5, `docs/contracts/*`, `docs/data-sources-and-licenses.md`.

## Target (fixed by contract)
P(≥1 winter-related 311 report in H3 res-9 cell within next 24 h). This is **reporting behaviour**, not physical ice. Never describe it as sidewalk safety.

## Dependencies & mocks
- Inputs: 311 CSVs (public, CC BY 4.0) and ECCC `climate-hourly`/`climate-daily`. You may download them yourself into git-ignored `data/raw/`-equivalent under `services/ml/.cache/` for research until Data agent's aggregated tables land; write your aggregation so it can be swapped for `wp.report_311_cell`.
- Unit tests use small synthetic frames marked `SYNTHETIC` in fixture names.

## Steps
1. Label audit: winter category list, counts by season/borough/cell, reporting-bias analysis (e.g. reports vs. population/arrondissement), share of rows lacking coordinates, location precision. Write `models/label-audit.md` with measured numbers.
2. Features (leakage-safe; only info available before the window): lagged report counts per cell (1/3/7/28 d), neighbour-cell lags, seasonal history, weather (snowfall, precip, temp min/max, freeze-thaw crossings in prior 24–72 h), day-of-week, holiday flag.
3. Splits: chronological (train older winters, test most recent complete winter) **and** spatial block holdout (H3 res-6 parents). No random row splits.
4. Baselines first: (a) historical cell frequency, (b) frequency × weather heuristic, (c) logistic regression. Then gradient boosting (sklearn HistGradientBoosting); XGBoost only if justified.
5. Metrics: PR-AUC, Brier, calibration curve (isotonic/Platt on validation only), precision/recall@k, per-borough error. Compare to baselines.
6. **Gate:** model enabled only if PR-AUC beats best baseline on both holdouts by a margin you document *before* looking at test results, and calibration is acceptable (Brier < baseline). Otherwise ship `heuristic` layer, `enabled=false` for model.
7. `winterpath_ml.inference.RiskProvider` protocol + `HeuristicRiskProvider` + `ModelRiskProvider`; maps cell probability → edge risk level via thresholds in `models/registry.json`; returns `unknown` outside trained coverage.
8. Artifacts: versioned Parquet features + joblib/skops model + `models/registry.json` + `models/cards/<model_id>.md` (data window, metrics, limitations).

## Acceptance criteria
- Reproducible `uv run python -m winterpath_ml.evaluate` producing the metrics table from raw public data.
- Model card numbers match evaluation output exactly.
- Inference never returns a probability for cells/time windows outside support.
- `pytest services/ml` green, including a leakage test (features at t use only data < t).

## Stop conditions
Labels too sparse/biased → document, ship heuristic, disable model. Never invent labels or metrics.

## Completion report — `docs/agent-reports/ml.md`
Status · SHA · literal evaluation output · gate decision · artifacts produced (paths, sizes, checksums) · blockers · review readiness.
