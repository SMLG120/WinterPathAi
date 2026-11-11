# Agent report — ml

- **Status:** MERGED (fa8b4ea into `integration/winterpath`). Follow-up work since then: READY FOR REVIEW.
- **Branch / SHA:** agent/ml @ dd191742b842369e5ef23e74d5a9c3b731b65360 (pre-registration). Gate runner and Addendum 1 are in the following commit; this report update is committed on top of them.
- **Integration merges:** `integration/winterpath` merged three times with `git merge --no-edit`, all clean:
  - 56a9f96: contract v1.1.0 + platform.
  - 3aae499: contract v1.2.0 + data.
  - fa8b4ea: contract v1.3.0 + routing + the ML merge; fast-forward.
- **Date (UTC):** 2026-11-10

## Update after merge (contract v1.3.0) — 2026-11-10

### What was done
- Merged `integration/winterpath` at fa8b4ea (contract v1.3.0). The merge was a fast-forward with no conflicts.
- **Canonical source ids (v1.3):** ML already used `mtl-311` and `eccc-geomet` (`inference.SOURCE_IDS`), so no code change was needed.
- **Pre-registered a new gate:** `models/gate-logreg-2026.md`, for "logistic regression as model", committed in dd19174 at 2026-11-10 16:46:50 −05:00. That is before the first test day of winter 2026-27.
  - **Not evaluated:** no metric of the candidate on 2026-27 exists, and none can until the winter ends.
  - The earliest allowed run is 2027-05-08.
  - The 2025-26 result that motivated it is treated as hypothesis-generating only.
- **Frozen by the gate document:**
  - Labels: unchanged, ML's own aggregation, independent of CR-ML-1.
  - Coverage: the v2 file, by sha256.
  - Holdout: the same 5 res-6 blocks.
  - Splits: train winters 2021–2024, isotonic calibration on 2025, test on 2026 (chrono + spatial).
  - Candidate: `models.Logistic`, pinned via sha256 of 6 source files.
  - Gating comparators: (a) and (b); HGB is report-only.
- **Gate criteria:**
  - ΔPR-AUC ≥ 0.010.
  - Bootstrap CI lower bound > 0.
  - Brier below both comparators.
  - New: per-borough calibration ratio within [0.5, 2] for boroughs with ≥ 100 positives.
- The document also lists the conditions that void a run, and what happens to the registry on pass or fail.
- `models/registry.json` is **unchanged**: the active layer is still `heuristic`, and `model.enabled = false`.

### Checks run on the merged tree
```text
$ grep -rn "vmtl-\|eccc-climate" services/ml/src services/ml/tests models/registry.json || echo "no stale source ids"
no stale source ids
$ cd services/ml && uv run pytest -q
............................                                             [100%]
28 passed in 1.66s
$ uv run python -c "...FEATURES / coverage / holdout_blocks..."   # facts cited in the gate document
24
2930 5
```

### Gate runner (follow-up, same day)
- `services/ml/src/winterpath_ml/gate_logreg_2026.py` implements the pre-registered protocol. It **refuses** to run before 2027-05-08 or if any pinned file or the coverage list differs from its recorded sha256. There is no override flag.
  - It downloads a fresh 311 snapshot into a separate path and rejects snapshots dated before 2027-05-08.
  - It applies the void rules and the four gate criteria (`decide()`, a pure function), and writes `models/evaluation/logreg-2026-<sha8>.json`.
  - It does **not** edit the registry; a PASS is promoted through a separate reviewed commit.
- Frozen coverage list committed as `models/coverage-v2-8d19aa86-cells.txt` (2,930 ids, sha256 `3e80a04b…5e58`). `models/artifacts/` is git-ignored, so a clean 2027 checkout would otherwise lack it.
  - The root `.gitignore` ignores `coverage/` directories, so it is a flat file, not `models/coverage/…`.
- Addendum 1 in `models/gate-logreg-2026.md` records the above. It is a clarification only; no criterion, split, data rule or pinned file changed.
- `test_pinned_files_unchanged` runs in CI, so an edit to a frozen file fails the build.

```text
$ uv run --with ruff ruff check . && uv run --with ruff ruff format --check .
All checks passed!
24 files already formatted
$ uv run pytest -q
...................................                                      [100%]
35 passed in 4.37s
$ uv run python -m winterpath_ml.gate_logreg_2026 --check
pins OK; coverage list OK
date guard: pre-registered earliest run date is 2027-05-08; today is 2026-11-10. Test winter not evaluable.
$ uv run python -m winterpath_ml.gate_logreg_2026; echo "exit=$?"
REFUSED: pre-registered earliest run date is 2027-05-08; today is 2026-11-10. Test winter not evaluable.
pins OK; coverage list OK
exit=2
```

### Open items
- CR-ML-1 is pending a user decision. No Data-owned files were touched.
- **2027-05-08 or later:** run `uv run python -m winterpath_ml.gate_logreg_2026` once. If the decision is PASS, open a reviewed commit that promotes `winter311-logreg-v1` in the registry, as the gate document describes.
- Daily `winterpath_ml.score` scheduling is still unassigned (Platform/coordinator).

## Summary (original delivery)
- **Gate decision: FAIL.** The model is disabled (`layers.model.enabled = false`). The active layer is `heuristic`: baseline (b), historical frequency × a fixed weather multiplier. It reports levels only, with `probability = null`.
- HistGradientBoosting did **not** beat the strongest baseline, logistic regression (c), on either holdout. The PR-AUC difference vs that baseline was −0.0033 (most recent winter) and −0.0011 (held-out areas), with 95% CIs spanning 0.
- The target is P(≥1 winter-related 311 report in an H3 res-9 cell during local day D). It measures **reporting behaviour, not sidewalk safety**.

## Files changed
```text
$ git diff --stat $(git merge-base integration/winterpath HEAD) HEAD
 models/artifacts/.gitkeep                     |    0
 models/cards/winter311-hgb-v1.md              |  189 ++++
 models/evaluation/v1-8d19aa86.SUPERSEDED.json | 1148 +++++++++++++++++++++++++
 models/evaluation/v2-8d19aa86.json            |  914 ++++++++++++++++++++
 models/gate.md                                |   28 +
 models/label-audit.md                         |  158 ++++
 models/registry.json                          |  113 +++
 services/ml/.python-version                   |    1 +
 services/ml/README.md                         |   45 +
 services/ml/pyproject.toml                    |   24 +
 services/ml/src/winterpath_ml/__init__.py     |    2 +
 services/ml/src/winterpath_ml/audit.py        |  259 ++++++
 services/ml/src/winterpath_ml/config.py       |  113 +++
 services/ml/src/winterpath_ml/data_311.py     |  117 +++
 services/ml/src/winterpath_ml/evaluate.py     |  432 ++++++++++
 services/ml/src/winterpath_ml/features.py     |  222 +++++
 services/ml/src/winterpath_ml/inference.py    |  349 ++++++++
 services/ml/src/winterpath_ml/metrics.py      |   79 ++
 services/ml/src/winterpath_ml/models.py       |  166 ++++
 services/ml/src/winterpath_ml/py.typed        |    0
 services/ml/src/winterpath_ml/score.py        |   96 +++
 services/ml/src/winterpath_ml/splits.py       |   48 ++
 services/ml/src/winterpath_ml/weather.py      |  128 +++
 services/ml/tests/conftest.py                 |   63 ++
 services/ml/tests/test_card_consistency.py    |   43 +
 services/ml/tests/test_data_311.py            |   45 +
 services/ml/tests/test_features.py            |   71 ++
 services/ml/tests/test_inference.py           |  156 ++++
 services/ml/tests/test_leakage.py             |   82 ++
 services/ml/tests/test_metrics_models.py      |   34 +
 services/ml/tests/test_pilot_fixture.py       |   73 ++
 services/ml/tests/test_splits.py              |   36 +
 services/ml/uv.lock                           |  274 ++++++
 33 files changed, 5508 insertions(+)
$ scripts/check-ownership.sh ml
ownership OK for agent/ml
```

## Commands run and literal results

### Evaluation (`cd services/ml && uv run python -m winterpath_ml.evaluate`), final run
```text
rows per split: {'train': 929764, 'valid': 372317, 'test_chrono': 372317, 'test_spatial': 158013}
fitting baseline_hist_freq
fitting baseline_freq_x_weather
fitting baseline_logistic
fitting hgb
| split | method | pr_auc | brier | precision_at_k | recall_at_k | base_rate | n |
|---|---|---|---|---|---|---|---|
| test_chrono | baseline_hist_freq | 0.0752 | 0.0289 | 0.1109 | 0.0884 | 0.0305 | 372317 |
| test_chrono | baseline_freq_x_weather | 0.0930 | 0.0288 | 0.1109 | 0.0884 | 0.0305 | 372317 |
| test_chrono | baseline_logistic | 0.1649 | 0.0274 | 0.1235 | 0.0985 | 0.0305 | 372317 |
| test_chrono | hgb | 0.1616 | 0.0275 | 0.1207 | 0.0962 | 0.0305 | 372317 |
| test_spatial | baseline_hist_freq | 0.0563 | 0.0219 | 0.0725 | 0.1819 | 0.0228 | 158013 |
| test_spatial | baseline_freq_x_weather | 0.0736 | 0.0217 | 0.0725 | 0.1819 | 0.0228 | 158013 |
| test_spatial | baseline_logistic | 0.1345 | 0.0210 | 0.0791 | 0.1985 | 0.0228 | 158013 |
| test_spatial | hgb | 0.1334 | 0.0210 | 0.0798 | 0.2002 | 0.0228 | 158013 |

gate test_chrono: best_baseline=baseline_logistic diff=-0.0033 ci95=[-0.0137, 0.0080] margin=False ci=False brier=False -> FAIL
gate test_spatial: best_baseline=baseline_logistic diff=-0.0011 ci95=[-0.0127, 0.0086] margin=False ci=False brier=True -> FAIL
GATE: FAIL -> heuristic layer, model disabled
```
Reproducibility: the v2 evaluation ran three times: initial, an unchanged re-run, and a re-run after the ruff refactor. Each re-run's `models/evaluation/v2-8d19aa86.json`, minus `generated_at`, was compared to the previous one; the script printed `IDENTICAL` both times. The joblib artifact checksums were also identical across runs.

`precision_at_k` and `recall_at_k` are identical for baselines (a) and (b) by construction. The weather multiplier is the same for every cell on a given day, so it doesn't change the within-day ranking.

### Tests (`cd services/ml && uv run pytest -v`)
```text
collecting ... collected 28 items

tests/test_card_consistency.py::test_card_and_registry_match_evaluation PASSED [  3%]
tests/test_data_311.py::test_winter_filter_and_aggregate_schema PASSED   [  7%]
tests/test_features.py::test_neighbour_matrix_ring_only PASSED           [ 10%]
tests/test_features.py::test_out_of_season_days_excluded PASSED          [ 14%]
tests/test_features.py::test_hist_rate_is_expanding_share_of_prior_season_days PASSED [ 17%]
tests/test_features.py::test_holidays PASSED                             [ 21%]
tests/test_features.py::test_universe_excludes_demerged_municipalities_and_future_activity PASSED [ 25%]
tests/test_inference.py::test_heuristic_never_returns_probability PASSED [ 28%]
tests/test_inference.py::test_unknown_outside_support[892baa54aa3ffff-when0-coverage] PASSED [ 32%]
tests/test_inference.py::test_unknown_outside_support[892baa441b3ffff-when1-season] PASSED [ 35%]
tests/test_inference.py::test_unknown_outside_support[892baa441b3ffff-when2-day] PASSED [ 39%]
tests/test_inference.py::test_local_day_conversion PASSED                [ 42%]
tests/test_inference.py::test_disabled_model_refused PASSED              [ 46%]
tests/test_inference.py::test_enabled_model_returns_probability_only_inside_support PASSED [ 50%]
tests/test_inference.py::test_edge_partially_outside_coverage_is_unknown PASSED [ 53%]
tests/test_inference.py::test_levels_and_status PASSED                   [ 57%]
tests/test_inference.py::test_null_provider_and_missing_registry PASSED  [ 60%]
tests/test_inference.py::test_edge_risk_rows_dst_day PASSED              [ 64%]
tests/test_leakage.py::test_future_311_and_weather_do_not_change_features PASSED [ 67%]
tests/test_leakage.py::test_label_is_same_day_and_lags_exclude_it PASSED [ 71%]
tests/test_leakage.py::test_weather_features_use_previous_days PASSED    [ 75%]
tests/test_metrics_models.py::test_precision_recall_at_k PASSED          [ 78%]
tests/test_metrics_models.py::test_bootstrap_deterministic PASSED        [ 82%]
tests/test_metrics_models.py::test_weather_multiplier_neutral_when_weather_missing PASSED [ 85%]
tests/test_pilot_fixture.py::test_fixture_edges_map_to_cells_near_mcgill PASSED [ 89%]
tests/test_pilot_fixture.py::test_fixture_edges_unknown_unless_every_touched_cell_is_covered PASSED [ 92%]
tests/test_splits.py::test_holdout_is_whole_blocks_and_deterministic PASSED [ 96%]
tests/test_splits.py::test_assign_has_no_cell_or_time_overlap PASSED     [100%]

============================== 28 passed in 5.36s ==============================
```

### CI-equivalent checks (same commands as `.github/workflows/ci.yml`)
```text
$ uv run --with ruff ruff check .
All checks passed!
$ uv run --with ruff ruff format --check .
22 files already formatted
$ uv run --with pip-audit pip-audit --skip-editable --progress-spinner off
No known vulnerabilities found
Name          Skip Reason
------------- -------------------------------
winterpath-ml distribution marked as editable
```

### Scoring (`uv run python -m winterpath_ml.score ...`)
```text
2026-01-14: 2930 cells -> .../models/artifacts/v2-8d19aa86/scores/winter311-heuristic-v1/2026-01-14.parquet
2026-01-15: 2930 cells -> .../models/artifacts/v2-8d19aa86/scores/winter311-heuristic-v1/2026-01-15.parquet
2026-11-09: 2930 cells -> .../models/artifacts/v2-8d19aa86/scores/winter311-heuristic-v1/2026-11-09.parquet
2026-11-10: 2930 cells -> .../models/artifacts/v2-8d19aa86/scores/winter311-heuristic-v1/2026-11-10.parquet
2026-11-11: skipped (311 data ends 2026-11-09 < 2026-11-10)
```

### Real pilot_mini edges (200 OSM edges, Data agent fixture) with the active heuristic provider
```text
HeuristicRiskProvider
2026-01-15 {'elevated': 60, 'moderate': 140} probabilities non-null: 0
2026-11-10 {'moderate': 12, 'low': 188} probabilities non-null: 0
2026-07-01 {'unknown': 200} probabilities non-null: 0
distinct cells touched: 3
```
Across the full pilot bbox (36 H3 res-9 cells), 1 cell is `unknown` because its modal borough is Westmount (see the coverage finding below).

## Acceptance criteria
| Criterion (docs/agents/ml.md) | Met? | Evidence |
|---|---|---|
| Reproducible `uv run python -m winterpath_ml.evaluate` from raw public data | Yes | Downloads the 311 CSV and ECCC data if missing; three runs gave identical JSON (above) |
| Model card numbers match evaluation output exactly | Yes | The card and registry are generated from the evaluation JSON; `test_card_and_registry_match_evaluation` passes |
| Inference never returns a probability outside support | Yes | `test_unknown_outside_support[*]`, `test_edge_partially_outside_coverage_is_unknown`, `test_heuristic_never_returns_probability`, `test_disabled_model_refused` |
| `pytest services/ml` green, incl. leakage test | Yes | 28 passed; `test_leakage.py` perturbs 311 data and weather on/after t and asserts features ≤ t are unchanged |
| Label audit with measured numbers | Yes | `models/label-audit.md` (generated by `winterpath_ml.audit`) |
| Chronological + spatial block splits, no random row splits | Yes | `splits.py`; `test_assign_has_no_cell_or_time_overlap` |
| Baselines first (a, b, c), then HGB | Yes | Table above |
| Gate margin fixed before test results | Yes | `models/gate.md` committed in 641a1e4 at 2026-11-10 20:49:54 UTC. The first test-set metrics were computed at 20:56:02 UTC (`generated_at` in `v1-8d19aa86.SUPERSEDED.json`) |
| RiskProvider protocol + Heuristic/Model providers; thresholds in registry | Yes | `inference.py`; `models/registry.json` → `levels.thresholds` |
| Artifacts: versioned Parquet features, joblib model, registry, card | Yes | Listed below |

## Artifacts (git-ignored under `models/artifacts/v2-8d19aa86/`; checksums also recorded in `models/registry.json`)
| path | bytes | sha256 |
|---|---|---|
| coverage_cells.parquet | 19883 | f7519df54d64d5d8734add8b4c3aa0631093007ffdd29de62432b729f8dc12cd |
| features.parquet | 14150376 | ad63e3f0e36897c6255a85b57d7f51aab169ff3aa6a5df111d39ddefdea1fcc5 |
| metrics.json | 24557 | f9e643de85c39b282e3e8264aa05b0aba0827d25c85d19442425583b7a92f04b |
| winter311-heuristic-v1.joblib | 2953 | 4c9163461c21042c44a5ce80b57759e08c4bbc066fc3f35f223cb6b58de86546 |
| winter311-hgb-v1.joblib | 1110930 | 24cb290d8f0c2f3abd05e2e586c53b99bc623d3de3984cc807c2b0f28d9d9baf |
| scores/winter311-heuristic-v1/{2026-01-14,2026-01-15,2026-11-09,2026-11-10}.parquet | ~24–25 kB each | — |

Committed: `models/registry.json`, `models/gate.md`, `models/label-audit.md`, `models/cards/winter311-hgb-v1.md`, `models/evaluation/v2-8d19aa86.json` (active), `models/evaluation/v1-8d19aa86.SUPERSEDED.json` (kept for the record). No file is larger than 5 MB, and no raw data is committed.
Input raw file: `requetes311.csv` sha256 `8d19aa86ebc17270697883bcc3d0f746b381899501a5dc8967477bd6d49de8bb` (850,013,464 bytes, in `services/ml/.cache/raw/`, git-ignored).

## Disclosure: two evaluation versions
The **v1** run (first test-set evaluation) defined coverage as any cell with 311 activity. The label audit then showed that this dataset covers only the City of Montréal's **19 boroughs**. Demerged municipalities (Westmount, Mont-Royal, Côte-Saint-Luc, …) have almost no rows, so their cells would have been shown as `low` instead of `unknown`. That is a correctness and honesty bug, and it matters for the pilot because Westmount borders the McGill bbox. **v2** restricts coverage to the 19 boroughs (2,930 cells instead of 3,220).

The gate procedure, features and hyper-parameters are unchanged. The change came from the audit, not from test metrics. The gate failed in both versions:
- v1: ΔPR-AUC −0.0013 (most recent winter), +0.0015 (held-out areas), both CIs spanning 0.
- v2: numbers above.

Because the spatial holdout blocks are drawn from the coverage, they differ between v1 and v2 (v2 has 5 res-6 blocks and 158,013 test rows).

## Blockers
| Blocker | Impact | Next step / who |
|---|---|---|
| None blocking delivery | — | — |
| Population normalisation for the reporting-bias analysis | The audit uses area and overall 311 volume as proxies only | Coordinator/Data: decide whether to add a census population source (licence check needed) |
| 311 timestamp timezone not stated by publisher | Reports near midnight may land on the wrong day (pipeline assumes America/Montréal) | Data agent's open item; no action for ML unless resolved otherwise |

## Dependencies on other agents
- **Routing/API:** use `winterpath_ml.inference.load_provider()`. It returns `HeuristicRiskProvider` when artifacts exist, otherwise `NullRiskProvider`.
  - `edge_risk(coords_lonlat, valid_from_tz_aware)` returns OpenAPI `RiskEstimate` via `.to_dict()`.
  - `status()` returns OpenAPI `ModelStatus`.
  - `evidence.state` is `model_estimate` for the labelled heuristic, per the `EvidenceState` description in OpenAPI. Its `note` says it is not a validated probability.
  - `unknown` must get the routing `unknown_penalty`, never 0.
- **Score freshness:** a day is scored only when 311 data reaches D-1 and the D-3…D-1 weather observations exist. In production `winterpath_ml.score` must run daily after ingestion. Scheduling it is Platform's or the coordinator's call; nothing has been scheduled.
- **Artifacts** are git-ignored, so other worktrees and CI get `NullRiskProvider` until someone runs `evaluate` + `score` (about 5 min + 1 min locally, with network access to donnees.montreal.ca and api.weather.gc.ca).
- **`wp.edge_risk` writes:** `inference.edge_risk_rows(...)` produces rows in the table's shape. No DB write was implemented, because Docker/PostGIS wasn't used by this agent.

## Licensing / data notes
- Ville de Montréal 311 (CC BY 4.0): only H3 res-9 × day aggregates are written to disk. Raw rows stay in memory and individual points are never stored.
- ECCC climate-daily (ECCC Data Servers End-use Licence): observed values only; missing values stay NaN and are never zero-filled.
- Evidence `source_ids` = `["mtl-311", "eccc-geomet"]`, aligned with the Data agent's `wp.source` ids.

## Change requests (contracts)
**CR-ML-1 — `wp.report_311_cell` label definition (data-model; Data agent + coordinator).**
- The Data agent's aggregation counts every `NATURE` (`Requete`, `Plainte`, `Information`, `Commentaire`). For example, its `sidewalk_slippery` total of 12,984 equals all four natures summed. It also adds `Déneigement ruelle` and `Dépôt neige-ruelle`.
- ML labels use only `NATURE ∈ {Requete, Plainte}`, because `Information` (enquiries) and `Commentaire` are not condition reports. For `Opération déneigement`, that difference is 27,075 of 76,702 rows.
- Swapping ML onto `wp.report_311_cell` today would silently change the labels.
- Proposed additive change: add `nature text` to the primary key, or a `report_natures_only` variant/view. Until then, ML keeps its own CSV aggregation (`data_311.py`). `read_report_cells_sql()` exists, but it is **not** a drop-in for the label until this is resolved.
- Category names differ (`sidewalk_slippery` vs ML `slippery_sidewalk`). This doesn't affect the model, which sums categories; the names can be aligned in the same change.

## Recommendations (not acted on)
- Logistic regression (c) was the best method on both holdouts. Enabling it now would be a post-hoc choice made after seeing test results. The honest path is to pre-register a new gate for "logistic as model" and evaluate it on winter 2026-27 once it completes.
- Same-day weather forecasts would likely add skill, but training on them needs archived forecasts to avoid leakage.

## Review readiness
Ready for review:
- Code at bb74a70.
- Ownership check passes.
- 28 tests pass; ruff and pip-audit are clean.
- The gate decision (FAIL → heuristic layer, model disabled) is recorded in `models/registry.json` and `models/cards/winter311-hgb-v1.md`.
