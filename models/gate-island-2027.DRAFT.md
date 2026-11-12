# DRAFT pre-registration: island-coverage risk model, test winter 2027-28

**Status: DRAFT, NOT REGISTERED.** Written 2026-11-11 for coordinator review. This file has no force until it is renamed `gate-island-2027.md` in a commit that also fixes every `TBD` below. That commit must land **before 2027-11-01 00:00 America/Montréal** (the first test day's prediction time); its timestamp is the evidence.

It does not change, re-open or depend on the outcome of:
- `models/gate.md` (HGB, failed);
- `models/gate-logreg-2026.md` (logistic regression, test winter 2026-27, earliest run 2027-05-08);
- the frozen v2 files: `models/registry.json`, `models/evaluation/v2-8d19aa86.json`, `models/coverage-v2-8d19aa86-cells.txt`, `models/artifacts/v2-8d19aa86/*`, and the pinned sources `features.py`, `models.py`, `metrics.py`, `splits.py`, `weather.py`, `data_311.py`.

## Embargo on winter 2026-27 rows (applies from now)
Rows with day ≥ 2026-11-01 are **not read for any modelling purpose** before the logistic-regression gate has run (on or after 2027-05-08). That covers training, selection, calibration, coverage, metrics and exploration.
- Development code filters `day < 2026-11-01` explicitly.
- Exception, not evaluation: the operational scoring job (`winterpath_ml.score`) reads recent days to produce live scores. It computes no metric and writes nothing used by this protocol.
- After 2027-05-08, winter 2026-27 becomes this protocol's **calibration** winter (it is never a test winter here).

## Why a new protocol
- The island expansion changes coverage, from the v2 2,930 cells (19 City boroughs, modal-borough rule) to cells inside the island polygon.
- A model's numbers on winters already seen (≤ 2025-26) are hypothesis-generating only. The first winter nobody has seen and that this protocol can still pre-register is **2027-28**.

## Target and labels (unchanged from v2)
- Target: P(≥ 1 winter-related 311 report in an H3 res-9 cell during local day D), using data available at 00:00 America/Montréal on D. This measures reporting behaviour, not ice or sidewalk safety.
- Labels: `ACTI_NOM ∈ {Trottoir glissant, Chaussée glissante, Opération déneigement, Dépôt Illégal - Neige}` and `NATURE ∈ {Requete, Plainte}`, computed by ML's CSV aggregation (`data_311.py`, read-only).
- Alley categories (`snow_clearing_alley`, `snow_dumping_alley`) are excluded, as in v2.
- Label counts known today (snapshot 8d19aa86; positive cell-days, all cells):

| Winter | Reports | Positive cell-days |
|---|---|---|
| 2021 (Jan–Apr 2022) | 11,250 | 8,901 |
| 2022 | 15,125 | 12,568 |
| 2023 | 11,050 | 9,076 |
| 2024 | 17,595 | 13,992 |
| 2025 | 17,974 | 14,970 |

## Coverage (frozen at registration)
A cell is **in coverage** if all three hold:
1. its H3 res-9 centroid lies in Data's **main-island polygon**, with sha256 `TBD`. Data's Wave 1 deliverable is not yet published, and Laval and Longueuil are never in it;
2. the centroid lies in one of the **19 City of Montréal boroughs**, using the borough polygons from `limites-administratives-agglomeration`, sha256 `TBD`. These are the only areas the 311 dataset covers;
3. the cell has ≥ 1 geolocated 311 request of any type with `DDS_DATE_CREATION < 2026-11-01`.

Out of coverage means `unknown` and is never scored:
- cells in the **15 linked municipalities**, which have no labels and so cannot be trained or tested;
- island cells with no 311 history;
- the other islands, unless Data's polygon includes them through mapped pedestrian links. Each such island is listed separately in the registration.

The coverage list is committed as text, sorted H3 ids with its sha256, like v2 Addendum 1.

## Splits
| Role | Days | Cells |
|---|---|---|
| train | 2022-02-01 … 2026-04-30 (winters 2021 partial – 2025), Nov–Apr only | non-holdout blocks |
| selection (validation) | 2025-11-01 … 2026-04-30, models refit on 2022-02-01 … 2025-04-30 | non-holdout blocks |
| calibration (isotonic) | 2026-11-01 … 2027-04-30, **read only after 2027-05-08** | non-holdout blocks |
| **test_chrono** | **2027-11-01 … 2028-04-30** | non-holdout blocks |
| **test_spatial** | **2027-11-01 … 2028-04-30** | holdout blocks |

- Holdout blocks: H3 res-6 parents of the coverage cells, chosen by the v2 algorithm (`splits.holdout_blocks`, read-only) with a **new seed** `20271101` and fraction 0.2. The block list is committed at registration.
- Holdout-block rows in the train, selection and calibration periods are unused.

## Candidates and comparators
- **Comparators (gating):**
  - (a) historical frequency;
  - (b) the shipped frequency × weather heuristic.
- **Candidates:**
  - (c) logistic regression (same pipeline as `models.Logistic`);
  - (d) Poisson count regression on the daily report count, its score mapped to P(≥ 1) by isotonic calibration;
  - (e) random forest;
  - (f) gradient boosting (`HistGradientBoosting`). XGBoost is only added if the coordinator approves the dependency.
- **One primary candidate**, to avoid multiple comparisons: the candidate with the highest PR-AUC on the selection winter (2025-26, already seen). The choice is made and written into this file **before registration**. The other candidates are reported, never gating.
- **Features:** the v2 24 features (`features.FEATURES`), computed by the pinned `features.py` unchanged.
- **Forecast features are excluded.** The City Page forecast archive can start no earlier than 2026-10-13 (Datamart retention), so no training winter has them. A forecast-aware model needs its own later protocol with ≥ 2 archived training winters.
- Fixed hyper-parameters are written here at registration. There is no search on calibration or test data, and no class reweighting or threshold tuning.
- New model code goes in **new files** (e.g. `models_island.py`, `gate_island_2027.py`). Their sha256 values are pinned at registration. The v2-pinned files are imported, never edited.

## Gate (all must hold on both test_chrono and test_spatial)
1. `PR-AUC(primary) − max(PR-AUC(a), PR-AUC(b)) ≥ 0.010`, on uncalibrated ranking scores.
2. The lower bound of the 95 % day-block bootstrap CI of that difference is > 0 (`metrics.bootstrap_pr_auc_diff`, 200 resamples, seed 0).
3. `Brier(primary) < min(Brier(a), Brier(b))`, all calibrated.
4. Per-borough calibration on test_chrono: for every borough with ≥ 100 positive cell-days, `mean_pred / obs_rate ∈ [0.5, 2.0]`. Borough = the polygon in coverage rule 2.

Metrics are also reported per borough and for precision/recall@50 cells/day.

## No decision (run is void; nothing changes)
- The 311 snapshot doesn't cover through 2028-04-30.
- test_chrono has < 5,000 positive cell-days.
- Station 7025251 `TOTAL_SNOW` is missing on > 10 % of test days.
- Any pinned file, the coverage list, the block list, or the polygon sha differs without a dated addendum written before 2028-04-01.
- Any candidate metric is computed on 2027-28 rows before the official run.
- The embargo above was broken (any modelling read of rows ≥ 2026-11-01 before 2027-05-08).

## Decision effect
- **PASS:** a registry change (new run id, island coverage, `active_layer = "model"`, `expose_probability = true`) in a separate, reviewed commit, with a new model card.
- **FAIL or void:** the island heuristic layer (if shipped) stays, with probability null. All metrics are committed either way.

## Earliest run
2028-05-08.

## TBD before registration
- [ ] Island polygon and borough polygons: Data commit and sha256.
- [ ] Coverage list (text, sha256) and holdout block list.
- [ ] Primary candidate (selection result) and every fixed hyper-parameter.
- [ ] New source files and their sha256 values; runner with guards like `gate_logreg_2026.py` (date, pins, no override).
- [ ] Coordinator decision on XGBoost.
