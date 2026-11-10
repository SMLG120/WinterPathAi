# Model enablement gate — pre-registered

Written and committed **before** any metric on the test winter (Nov 2025 – Apr 2026) was computed.
The commit containing this file precedes the first full `winterpath_ml.evaluate` run; see `git log -- models/gate.md`.

## Target
P(≥1 winter-related 311 report in an H3 res-9 cell during local calendar day D), predicted with data
available at 00:00 local on D. This is **reporting behaviour**, not physical ice or sidewalk safety.

## Holdouts
- **test_chrono** — winter 2025 (2025-11-01 … 2026-04-30), cells in non-holdout H3 res-6 blocks.
- **test_spatial** — winter 2025, cells in the seeded 20 % of H3 res-6 blocks excluded from training *and* calibration.
- Training: winters 2021 (Feb–Apr 2022 only), 2022, 2023 on non-holdout blocks. Calibration (isotonic): winter 2024 on non-holdout blocks only.

## Baselines
(a) historical cell frequency, (b) frequency × fixed weather multiplier, (c) logistic regression. Candidate: sklearn `HistGradientBoostingClassifier` with fixed hyper-parameters in `services/ml/src/winterpath_ml/models.py` (no tuning on test).

## Gate (all must hold on **both** test_chrono and test_spatial)
1. `PR-AUC(candidate) − max(PR-AUC of baselines a,b,c) ≥ 0.010` (absolute; PR-AUC computed on the uncalibrated ranking score).
2. The 95 % day-block bootstrap CI (200 resamples, seed 0) of that difference has a lower bound > 0.
3. `Brier(candidate, calibrated) < min(Brier of calibrated baselines a,b,c)`.

If any condition fails: `model.enabled = false`, `active_layer = "heuristic"` (baseline b). If the gate passes: `active_layer = "model"`.
The heuristic layer is baseline (b) regardless of how (a)/(c) rank; it is never presented as a validated probability (`probability = null`).

## Risk levels (both layers, applied to the isotonic-calibrated probability p)
With `r` = observed positive rate on the validation winter (non-holdout cells):
`low` p < r · `moderate` r ≤ p < 2r · `elevated` 2r ≤ p < 4r · `high` p ≥ 4r. Outside coverage or outside Nov–Apr, or no scored day → `unknown`.
