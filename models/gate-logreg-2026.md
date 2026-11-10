# Pre-registered gate — logistic regression as the risk model, test winter 2026-27

**Status: PRE-REGISTERED, NOT EVALUATED.** Written 2026-11-10 at the request of the coordinator.
No metric of this candidate on winter 2026-27 exists: the winter has not happened yet. This document must be committed **before 2026-11-11 00:00 America/Montréal** (the first test day's prediction time). Its commit timestamp is the evidence for that.

This gate is separate from `models/gate.md`. That gate (HGB, test winter 2025-26) stays failed and is not re-opened.

## Why this exists, and the bias it carries
On the 2025-26 test winter, the *baseline* logistic regression (c) had the best PR-AUC on both holdouts (`models/evaluation/v2-8d19aa86.json`). Enabling it on the strength of that result would be a choice made after seeing the test data. So the 2025-26 numbers are treated as **hypothesis-generating only**. The decision rests entirely on a winter nobody has seen. We know LR looked best on 2025-26, and this protocol is designed so that knowledge cannot leak into the 2026-27 verdict.

## Target and labels (unchanged from v2)
- Target: P(≥1 winter-related 311 report in an H3 res-9 cell during local day D), using data available at 00:00 America/Montréal on D. This is reporting behaviour, not ice or sidewalk safety.
- Labels: `ACTI_NOM ∈ {Trottoir glissant, Chaussée glissante, Opération déneigement, Dépôt Illégal - Neige}` with `NATURE ∈ {Requete, Plainte}`. Rows with `LOC_ERREUR_GDT = 1`, missing coordinates, or coordinates outside the envelope in `config.MTL_ENVELOPE` are excluded. Days use `DDS_DATE_CREATION` read as local time.
- The label is computed by ML's own CSV aggregation (`data_311.py`), whatever the outcome of CR-ML-1. If CR-ML-1 changes `wp.report_311_cell`, this gate still uses the definition above. Changing the label requires a new pre-registration.

## Data
- 311: Ville de Montréal « Requêtes 3-1-1 (2022 à ce jour) » CSV (`config.URL_311_2022_PRESENT`), one snapshot downloaded **on or after 2027-05-08**. Its sha256 is recorded in the evaluation output.
  - If the publisher has split or moved the file so that 2022-02-01 … 2027-04-30 isn't in one resource, the files are concatenated and deduplicated on `ID_UNIQUE`. No other change is allowed.
- Weather: ECCC climate-daily, stations 7025251 (primary) + 702S006 (fallback temps/precip), observed values only, missing stays NaN.
  - If 702S006 has ended, 7025251 alone is used.
  - If 7025251 lacks `TOTAL_SNOW` for more than 10 % of test days, the run is **void** (see "No decision").

## Coverage and spatial blocks (frozen = v2)
- Coverage: the 2,930 cells in `models/artifacts/v2-8d19aa86/coverage_cells.parquet` (sha256 `f7519df54d64d5d8734add8b4c3aa0631093007ffdd29de62432b729f8dc12cd`). These are cells with any geolocated 311 request before 2024-11-01 whose modal borough is one of the 19 City of Montréal boroughs. Coverage is **not** recomputed.
- Spatial holdout: the 5 H3 res-6 blocks returned by `splits.holdout_blocks(cells)` for those cells (seed 20261110, fraction 0.2). These are the same blocks as v2's `test_spatial`.

## Splits
| role | winters (Nov–Apr) | cells |
|---|---|---|
| train | 2021 (Feb–Apr 2022 only), 2022, 2023, 2024 | non-holdout blocks |
| calibration (isotonic) | 2025 (2025-11-01 … 2026-04-30) | non-holdout blocks |
| **test_chrono** | **2026 (2026-11-01 … 2027-04-30)** | non-holdout blocks |
| **test_spatial** | **2026** | holdout blocks |

- Winter 2024 moves from calibration to training. Winter 2025 (the old test winter) becomes calibration only.
- Holdout-block rows in train and calibration winters are unused.
- The panel starts at 2022-02-01, as in v2.

## Candidate and comparators (frozen)
- **Candidate `winter311-logreg-v1`:** `models.Logistic` exactly as at the commit that adds this file: `FunctionTransformer(log1p on count features) → SimpleImputer(median, add_indicator=True) → StandardScaler → LogisticRegression(C=1.0, max_iter=2000)`, on `features.FEATURES` (24 features), wrapped by `models.Calibrated` (isotonic on the calibration winter).
- **Comparators (gating):** (a) `HistoricalFrequency`, (b) `FrequencyWeatherHeuristic` (the currently shipped layer), both isotonic-calibrated on the same calibration winter.
- **Reported, not gating:** `GradientBoosting` with the same fixed parameters, for reference only. Its result cannot enable anything.
- No hyper-parameter search, feature selection, class reweighting or threshold tuning on any data.

Source files pinned (sha256 at commit `fa8b4ea`). The evaluation must run with byte-identical copies:
```text
2199140353e2d9f741674907bdbc85c7b802147d391eae33a729d705e420b605  services/ml/src/winterpath_ml/features.py
49884b4dd63e9aac96b8ec4e0365dfa05d93335d121c8c725dc3f8418c459165  services/ml/src/winterpath_ml/models.py
8e9b43290338c50020e2ebec3a66f079bdd2fa81b9670f303e61fe7078920844  services/ml/src/winterpath_ml/metrics.py
1aea7d1beb9a28ddb6778b3982122cd5d54bec134ff6ffdbbcdf3940a27ce07b  services/ml/src/winterpath_ml/splits.py
b5ec7019ed198adb52931ac0aa1e831248b3590f04a2323514d71602d379d848  services/ml/src/winterpath_ml/weather.py
dd114f6bb3371a6c19bb57c9c6bd03fb954f19f2153d876fdb2a4fad0c27f032  services/ml/src/winterpath_ml/data_311.py
```
The split constants above replace `config.TRAIN_WINTERS / VALID_WINTER / TEST_WINTER` in a new runner. Only that runner and config may change. If a pinned file must change to fix a bug, the fix is written up in a dated addendum here **before 2027-05-01**, with a test showing the v2 results are unchanged. Otherwise the run is void.

## Gate — all must hold on **both** test_chrono and test_spatial
1. `PR-AUC(candidate) − max(PR-AUC(a), PR-AUC(b)) ≥ 0.010` (absolute; uncalibrated ranking scores).
2. Lower bound of the 95 % day-block bootstrap CI of that difference > 0 (`metrics.bootstrap_pr_auc_diff`, 200 resamples, seed 0).
3. `Brier(candidate, calibrated) < min(Brier(a), Brier(b))`, calibrated.
4. **Per-borough calibration** (test_chrono): for every borough with ≥ 100 positive cell-days, `mean_pred / obs_rate ∈ [0.5, 2.0]`. Borough = modal borough before 2024-11-01, as in v2.

Metric definitions: `metrics.summary` / `metrics.calibration_curve` (precision/recall@k with k = 50 cells/day, pooled), reported for all methods.

## No decision (void run → model stays disabled)
- 311 snapshot doesn't cover through 2027-04-30.
- test_chrono has < 5,000 positive cell-days.
- Weather completeness rule above is violated.
- Any pinned file differs without a timely addendum.
- Anyone computes a candidate metric on winter-2026 rows before the official run. Development runs must use `--no-test`-style paths that never score the test winter.

## Decision effect
- **PASS:** `models/registry.json` → `active_layer = "model"`, `layers.model = winter311-logreg-v1`, `enabled = true`, `expose_probability = true`. A new model card is generated from the evaluation JSON. Level thresholds are recomputed with the existing rule (`r` = calibration-winter positive rate; moderate ≥ r, elevated ≥ 2r, high ≥ 4r).
- **FAIL or void:** no change. The heuristic layer stays active with `probability = null`, and the result is published in the report and card either way.
- In both cases the full metrics table (all methods, both holdouts) is committed to `models/evaluation/`.

## Earliest run date
2027-05-08: one week after the test winter ends, so the daily 311 file has caught up.
