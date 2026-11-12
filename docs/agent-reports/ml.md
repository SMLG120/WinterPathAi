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

### API interface mismatch found and fixed on the ML side
- **The mismatch:** `services/api` and `services/routing` define `RiskProvider` as `risk_layer` + `edge_risk(edge_ids, at) -> {edge_id: RiskEstimate}`. My providers take edge **geometry** and return one estimate. If wired directly, the API's `NormalisingRiskProvider` would have caught the error and silently returned `unknown` for everything.
- **The fix:** added `inference.EdgeIdRiskProvider` + factory `inference.api_provider`. It looks edge geometry up from a GeoJSON (`WP_EDGES_GEOJSON`, default `data/fixtures/pilot_mini/edges.geojson`), returns explicit `unknown` for ids it can't find, and exposes `model_status()`. No Routing/API files were edited.
- **Verified** against the real API adapter code, read-only, in a temporary env:
```text
$ cd services/api && uv run --with-editable ../ml python - <<'EOF' ... load_risk_provider("winterpath_ml.inference:api_provider") ...
NormalisingRiskProvider risk_layer= heuristic
2026-01-15 201 {'elevated': 60, 'moderate': 140, 'unknown': 1} prob non-null: 0
2026-07-01 201 {'unknown': 201} prob non-null: 0
evidence: model_estimate ('mtl-311', 'eccc-geomet') 2026-01-15 05:00:00+00:00
{'risk_layer': 'heuristic', 'enabled': False, 'model_id': 'winter311-hgb-v1'}
```
  - 201 ids = the 200 pilot edges + one deliberately bogus id, which comes back `unknown`.
- **Needed from Routing/API (not done by ML):**
  - add `winterpath-ml` (path dependency) to `services/api/pyproject.toml`;
  - set `RISK_PROVIDER=winterpath_ml.inference:api_provider` (and `WP_EDGES_GEOJSON` if the graph isn't pilot_mini);
  - artifacts must exist (`evaluate` + `score`), otherwise everything stays `unknown`.
- Tests after this change:
```text
$ cd services/ml && uv run pytest -q
.....................................                                    [100%]
37 passed in 11.68s
$ uv run --with ruff ruff check . && uv run --with ruff ruff format --check .
All checks passed!
25 files already formatted
```

### Contract v1.5.0 (CR-ML-1 accepted) — merged
- Merged `integration/winterpath` @ bbae7d3, clean.
- **Category names aligned** to the canonical `wp.report_311_cell` names (`sidewalk_slippery`, `roadway_slippery`, `snow_clearing`, `snow_dumping`) in `config.WINTER_CATEGORIES`.
  - `config.py` is not pinned by the logistic-regression gate; `data_311.py` is pinned and **unchanged**.
- **v2 results unchanged:** I rebuilt the aggregates and panel with the renamed categories and compared them to the evaluated artifact. I did not re-run or re-commit the evaluation; the registry, card and gate are untouched.
```text
categories: ['roadway_slippery', 'sidewalk_slippery', 'snow_clearing', 'snow_dumping']
interim identical after rename: True
panel identical to evaluated v2 features.parquet: True (2385020, 28) (2385020, 28)
$ uv run pytest -q
37 passed in 2.92s
$ uv run python -m winterpath_ml.gate_logreg_2026 --check
pins OK; coverage list OK
```
- **Nature-summing reader: not yet added.**
  - The coordinator's instruction is to add it once Data's migration is on integration. As of bbae7d3 there is no migration adding `nature` (the last is `0004_closure_status.py`).
  - `data_311.read_report_cells_sql` is now known-wrong: it doesn't filter or sum natures. It stays unchanged because `data_311.py` is gate-pinned; the README says not to use it. The new reader will live in a separate module.
- **Predicted difference** between the future DB reader (`SUM(n) WHERE nature IN ('requete','plainte')`) and the CSV labels. Measured now from the same 311 file:
```text
extra rows in Data's mapping (Requete/Plainte): 24 geolocated & valid: 24
Déneigement ruelle  Plainte     3
                    Requete     1
Dépôt neige-ruelle  Requete    20
in v2 panel: 24 of 24
would flip 0->1: 18 already positive: 6
  valid 10 · train 4 · test_chrono 4
```
  - Cause: Data maps `Déneigement ruelle` → `snow_clearing` and `Dépôt neige-ruelle` → `snow_dumping`. ML's frozen label set (v2 and `gate-logreg-2026.md`) excludes them. The table cannot separate them, so the DB reader **cannot reproduce the CSV labels exactly**: 18 of 2,385,020 cell-days would differ.

### CR-ML-2 (proposed) — keep alley categories separable in `wp.report_311_cell`
- **Request:** give the two alley activities their own canonical categories (e.g. `snow_clearing_alley`, `snow_dumping_alley`), or add the raw `acti_nom` to the key.
- **Effect:** consumers that want the current definitions can still `SUM` them together, and ML can exclude them, so the DB path reproduces the label of record exactly.
- **Alternative:** the coordinator accepts the 18-cell-day difference, and the CSV aggregation stays the label of record for v2 and the 2026-27 gate.
- ML continues other work and does not depend on the outcome.

### Merge of integration d04da54 (data 0005, routing ML/weather wiring, platform)
- Merged clean (e3f0df3).
- **Migration 0005 is the closure exclusive-end fix, not `report_311_cell.nature`.** `db/` and `services/ingestion` contain no `nature` change yet, so the nature-summing reader is **still pending** per the coordinator's instruction.
- **Routing wired ML differently from my adapter:** `RISK_PROVIDER=winterpath_ml.inference:load_provider`, adapted in the API, which calls my `cell_risk`/`edge_risk(coords)`/`status`. My `api_provider` is compatible but unused; either works.
- **Compatibility re-checked** against my current ML code, which is newer than the coordinator's verified 28-test ML run:
```text
$ cd services/api && uv run pytest -q          # uses services/ml from this branch (editable path dep)
71 passed, 8 skipped, 1 warning
  all 8 skips: "DATABASE_URL not set" (PostGIS tests); test_api_ml_risk.py ran and passed
$ cd services/routing && uv run pytest -q
210 passed, 1 skipped
$ cd services/ml && uv run pytest -q
37 passed
$ uv run python -m winterpath_ml.gate_logreg_2026 --check
pins OK; coverage list OK
```

### 2026-11-11 — artifact-dir bug fix; nature-summing reader verified against wp_data

**Frontend bug fixed (4a88459).**
- **Bug:** `inference._coverage()` and `score.py` built artifact paths from `REPO_ROOT` + the registry's repo-relative path, ignoring `MODEL_ARTIFACT_DIR`. When that variable pointed elsewhere, coverage wasn't found and the provider silently fell back to `NullRiskProvider`.
- **Fix:** a new `inference.artifact_path()` resolves every registry entry under `config.ARTIFACT_DIR/<run_id>/…`.
- **Warnings now logged:** `risk_registry_missing`, `risk_artifacts_missing` (names the expected path and `MODEL_ARTIFACT_DIR`), `risk_scores_missing`.
- No gate-pinned file was touched.
- **Regression tests:** `tests/test_artifact_dir.py` (4 tests).
- **End-to-end check** in a fresh process:
```text
$ MODEL_ARTIFACT_DIR=<copy outside repo> uv run python -c "...load_provider()..."
HeuristicRiskProvider
$ MODEL_ARTIFACT_DIR=<X>/missing uv run python -c "...load_provider()..."
WARNING:winterpath_ml.inference:risk_artifacts_missing: <X>/missing/v2-8d19aa86/coverage_cells.parquet not found (MODEL_ARTIFACT_DIR=<X>/missing); using NullRiskProvider (all unknown)
NullRiskProvider
```

**Data migration 0006 merged** from the exact commit `agent/data` ee5f1fc, as authorised (cc94e2b). The merge was clean.

**Reader:** `winterpath_ml.report_cells_db` (new module; `data_311.py` is untouched and still pinned).
- `read_report_cells(conn)` runs `SUM(n) … WHERE nature = ANY(['requete','plainte']) GROUP BY h3, day, category`.
- `psycopg` was added as the optional extra `db`.
- `wp_data` state, read-only: alembic `0006_report_311_nature`; natures loaded `requete` 61,067 rows / n 70,574, `plainte` 2,631 / 2,714, `commentaire` 6,729 / 7,326 (no `information`: those rows have no coordinates). Latest mtl-311 ingest run 4ed17177…, succeeded 2026-11-11 03:54 UTC.

**Verification** (`uv run --extra db python -m winterpath_ml.report_cells_db --compare --database-url <wp_data>`), literal output:
```text
db rows (h3, day, category) with nature in ('requete', 'plainte'): 63112, sum n = 73288
{
  "common_window_end": "2026-11-07",
  "db_total_n": 73288,
  "csv_label_total_n": 73264,
  "csv_alley_rows": 24,
  "db_vs_csv_label": {
    "cell_days_count_differs": 24,
    "abs_count_diff": 24,
    "label_differs_cell_days": 18
  },
  "db_vs_csv_label_plus_alley": {
    "cell_days_count_differs": 0,
    "abs_count_diff": 0,
    "label_differs_cell_days": 0
  },
  "v2_panel_rows": 2385020,
  "v2_panel_label_flips": 18,
  "v2_panel_flips_0_to_1": 18,
  "v2_panel_flips_1_to_0": 0
}
```
- **Result:** the prediction was confirmed exactly. The DB reader equals the CSV labels plus the two alley activities, with 0 differences. Against the label of record, the difference is the predicted 24 reports / 18 cell-days, all 0→1.
- No other difference, so there is no snapshot drift up to 2026-11-07, the DB load's last day. The CSV file runs to 2026-11-09.
- CR-ML-2 is not acted on: it awaits the user's decision. The CSV aggregation stays the label of record.

**Checks:**
```text
$ uv run --with ruff ruff check . && uv run --with ruff ruff format --check .
All checks passed!
28 files already formatted
$ uv run pytest -q
43 passed, 1 skipped          (skip = live-DB test, opt-in via WP_ML_TEST_REPORT_DB_URL)
$ WP_ML_TEST_REPORT_DB_URL=<wp_data> uv run --extra db pytest -q tests/test_report_cells_db.py
3 passed
$ uv run python -m winterpath_ml.gate_logreg_2026 --check
pins OK; coverage list OK
$ uv run --all-extras --with pip-audit pip-audit --skip-editable --progress-spinner off
No known vulnerabilities found
```
- The first pip-audit attempt failed with "Request failed after 3 retries" (network); the retry above succeeded.

### Merge of integration eb92007 (frontend, platform, v1.5.0 clarification) — 4c69b5b, clean
- No ML-relevant contract change: the clarification covers explanation-code evidence only.
- **Platform harness ran without artifacts** (risk layer `none`): the expected `NullRiskProvider` path. With 4a88459, artifacts mounted anywhere work through `MODEL_ARTIFACT_DIR`, and a missing directory now logs `risk_artifacts_missing` instead of failing silently.
- `agent/data` ee5f1fc is still **not** in integration, so the ownership-check note above still applies.
```text
$ cd services/ml && uv run pytest -q
43 passed, 1 skipped
$ uv run python -m winterpath_ml.gate_logreg_2026 --check
pins OK; coverage list OK
```

### Contract v1.6.0 (CR-ML-2 approved) — merged a292b63, clean
- **Reader updated:** `report_cells_db.read_report_cells` now filters on `nature = ANY(['requete','plainte']) AND category = ANY(LABEL_CATEGORIES)`.
  - `LABEL_CATEGORIES` is derived from `config.WINTER_CATEGORIES`: `sidewalk_slippery`, `roadway_slippery`, `snow_clearing`, `snow_dumping`.
  - So the v1.6 alley categories (`snow_clearing_alley`, `snow_dumping_alley`) are excluded.
  - The `--compare` diagnostics now map the alley activities to their v1.6 category names.
- **Expected after Data's v1.6 reload:** 0 cell-days differ from the CSV labels.
- **Not yet verified, by instruction.** The coordinator will send Data's new SHA. `wp_data` still holds the ee5f1fc load, where alley rows sit inside `snow_clearing`/`snow_dumping`; a comparison now would still show the old 18 and prove nothing.
- Migration 0006 will change in Data's next commit (v1.6 folds the alley categories into it). This branch has ee5f1fc's 0006 unmodified, so merging Data's new SHA will bring their version in cleanly.
```text
$ cd services/ml && uv run pytest -q
43 passed, 1 skipped
$ uv run python -m winterpath_ml.gate_logreg_2026 --check
pins OK; coverage list OK
```

### 2026-11-11 — v1.6 DB reader verified against Data f6eb3b2: 0 cell-days differ
- Merged the exact commit `agent/data` f6eb3b2 into this branch (71e7c7a). The merge was clean; that commit's migration 0006 includes the alley categories.
- **`wp_data` reload checked, read-only (no writes):**
```text
alembic_version: 0006_report_311_nature
report_311_cell_category_check: CHECK ((category = ANY (ARRAY['sidewalk_slippery', 'roadway_slippery', 'snow_clearing', 'snow_dumping', 'snow_clearing_alley', 'snow_dumping_alley'])))
snow_clearing_alley|commentaire|3|3
snow_clearing_alley|plainte|3|3
snow_clearing_alley|requete|1|1
snow_dumping_alley|requete|20|20
latest mtl-311 ingest_run: 18c1ca93-6448-4451-9605-a5ddbe9e8cfa | succeeded | 2026-11-11 13:38:57 UTC | record_count 70428
```
  The alley rows in `requete`+`plainte` total 1 + 3 + 20 = 24, the same 24 reports the CSV audit found.
- **Comparison** (`uv run --extra db python -m winterpath_ml.report_cells_db --compare --database-url <wp_data>`), literal output:
```text
db rows (h3, day, category) with nature in ('requete', 'plainte'), category in ('sidewalk_slippery', 'roadway_slippery', 'snow_clearing', 'snow_dumping'): 63091, sum n = 73264
{
  "common_window_end": "2026-11-07",
  "db_total_n": 73264,
  "csv_label_total_n": 73264,
  "csv_alley_rows": 24,
  "db_vs_csv_label": {
    "cell_days_count_differs": 0,
    "abs_count_diff": 0,
    "label_differs_cell_days": 0
  },
  "db_vs_csv_label_plus_alley": {
    "cell_days_count_differs": 24,
    "abs_count_diff": 24,
    "label_differs_cell_days": 18
  },
  "v2_panel_rows": 2385020,
  "v2_panel_label_flips": 0,
  "v2_panel_flips_0_to_1": 0,
  "v2_panel_flips_1_to_0": 0
}
```
- **Result: verified, 0 cell-days differ.** The DB reader reproduces the CSV label of record exactly over the common window (through 2026-11-07, the DB load's last day).
  - 0 label flips across all 2,385,020 v2 panel rows.
  - DB row count (63,091) equals ML's interim aggregate row count.
  - The reverse diagnostic (`plus_alley`) is now 24 / 18, so the alley categories are correctly separated.
- **Implication:** `report_cells_db.read_report_cells` can serve as the label source going forward. The v2 results, registry and logistic-regression gate are unchanged; the gate's label definition is identical by construction.
```text
$ WP_ML_TEST_REPORT_DB_URL=<wp_data> uv run --extra db pytest -q tests/test_report_cells_db.py
3 passed
$ uv run pytest -q
43 passed, 1 skipped
$ uv run python -m winterpath_ml.gate_logreg_2026 --check
pins OK; coverage list OK
```
- **Ownership check:** f6eb3b2 is not yet in integration, so `scripts/check-ownership.sh ml` still flags Data's files. Every non-ML file in this branch is byte-identical to f6eb3b2:
```text
$ git diff --name-only f6eb3b2 HEAD | grep -v -E '^(services/ml/|models/|docs/agent-reports/ml.md)'
(no output)
```
- **Resolved 2026-11-11:** integration/winterpath (6a712e9, all five agents) merged into agent/ml with `git merge --no-edit` (fast-forward 2e4d5fa → 6a712e9; no file under `services/ml/` or `models/` changed). Checks re-run:
```text
$ git merge-base --is-ancestor f6eb3b2 HEAD && echo "f6eb3b2 in HEAD"
f6eb3b2 in HEAD
$ scripts/check-ownership.sh ml
ownership OK for agent/ml
$ uv run pytest -q
43 passed, 1 skipped in 4.03s
$ uvx ruff check . && uvx ruff format --check .
All checks passed!
28 files already formatted
$ uv run python -m winterpath_ml.gate_logreg_2026 --check
pins OK; coverage list OK
date guard: pre-registered earliest run date is 2027-05-08; today is 2026-11-11. Test winter not evaluable.
```

### Open items
- None blocking. The logistic-regression gate runs on or after 2027-05-08. The daily `winterpath_ml.score` job is still unscheduled (Platform/coordinator).

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

## Headless daily scoring (`winterpath_ml.score`), 2026-11-11

**Inputs** (nothing else is read or downloaded):
| Input | Where it comes from | Size |
|---|---|---|
| `models/registry.json` | committed | — |
| `winter311-heuristic-v1.joblib` | `$MODEL_ARTIFACT_DIR/v2-8d19aa86/`. Git-ignored, so the runner must supply it. sha256 is checked against the registry **before** `joblib.load`. | 2,953 B |
| `coverage_cells.parquet` | same directory and sha check | 19,883 B |
| 311 « Requêtes 3-1-1 (2022 à ce jour) » CSV | downloaded with `--fetch-311` from `config.URL_311_2022_PRESENT` into `$WP_ML_CACHE_DIR/score/` (never overwrites the pinned evaluation snapshot), then aggregated by the unchanged `data_311.build_interim` | 850,499,252 B on 2026-11-11 |
| ECCC GeoMet `climate-daily`, stations 7025251 + 702S006, 2021-10-01..end | always fetched fresh into a temp dir. The old range-keyed cache could freeze an incomplete day: `eccc_…_2026-11-11.json`, fetched 2026-11-10 16:11, was byte-identical to the 11-10 file. | ~650 KB |

**Exit policy (revised per coordinator, supersedes the first version):**

| Exit | Meaning |
|---|---|
| 0 | Days written. Days whose inputs aren't published yet get a clear notice and are not written, which is not a failure. Out-of-season days are skipped with a notice. |
| 1 | A scored table failed validation (one row per coverage cell, finite `p` in [0, 1]). Nothing is written. |
| 2 | Artifact or registry error: missing, sha256 mismatch, or model disabled. |
| 3 | Download error (311 or ECCC), with the URL and the reason in the message. A failed 311 download leaves no `.part` file. |
| 4 | Stale: in season, and the newest `<day>.parquet` on disk is for a day that began (local midnight) more than 36 h ago. |

Under GitHub Actions, notices and errors are also emitted as `::notice::` / `::error::` annotations. Tables are written to `.<day>.parquet.tmp`, then `os.replace`d (the provider globs `*.parquet`). Pinned gate files are untouched (`pins OK`).

Real runs, 2026-11-11 13:02 EST, scratch artifacts, `GITHUB_ACTIONS=true`:
```text
== A: --start 2026-11-11 --end 2026-11-12
::notice title=winterpath_ml.score::2026-11-12 not scored yet: 311 data ends 2026-11-10 < 2026-11-11. Will be scored on a later run.
"rows_per_day": {"2026-11-11": 2930}, "newest_scored_day": "2026-11-11"
exit 0
== B: only 2026-11-09 on disk, --start 2026-11-12
::error title=winterpath_ml.score::score tables are stale: newest scored day 2026-11-09 began 61.0 h ago (> 36 h)
exit 4
== C: --fetch-311 through a proxy on a closed port
::error title=winterpath_ml.score::311 CSV download failed: GET https://donnees.montreal.ca/…/requetes311.csv -> URLError: <urlopen error [Errno 61] Connection refused>. Check that this runner can reach donnees.montreal.ca (HTTPS, port 443). Nothing was written.
exit 3
== D: ECCC through the same proxy
::error title=winterpath_ml.score::ECCC climate-daily download failed: https://api.weather.gc.ca -> URLError: <urlopen error [Errno 61] Connection refused>. Check that this runner can reach the ECCC GeoMet API. Nothing was written.
exit 3
```
Runner reachability of donnees.montreal.ca will be established on the first manual `workflow_dispatch` run (coordinator).

**Measured locally** (macOS arm64, `/usr/bin/time -l`, empty cache, scratch artifact dir):
```text
$ score --start 2026-11-11 --fetch-311            (via uv; includes 850 MB download)
exit 0; rows_per_day {"2026-11-11": 2930}; 311 sha256 7318fc5d…1ebf, last_day 2026-11-10
       55.26 real        12.02 user         3.57 sys
$ build_interim on the downloaded CSV               (venv python directly)
       10.62 real   1121468416  maximum resident set size   1591576592  peak memory footprint
$ score --start 2026-11-11                          (from aggregates, no 311 download)
        4.98 real    946569216  maximum resident set size    868124040  peak memory footprint
$ score --start 2026-11-11 --end 2026-11-12   (first version; now exit 0 + notice, see run A)
SCORE FAILED (inputs incomplete; nothing written): 2026-11-12: 311 data ends 2026-11-10 < 2026-11-11
exit 1
$ (one byte appended to the joblib)
SCORE FAILED (artifact/registry; nothing written): artifact sha256 mismatch … != registry 4c916346…6546
exit 2
$ MODEL_ARTIFACT_DIR=<empty>
SCORE FAILED (artifact/registry; nothing written): artifact missing: …
exit 2
```
Peak about 1.1 GB RSS (1.6 GB footprint) during aggregation, and about 55 s wall time, most of it the download.

**311 publication timing (observed once, not a guarantee):** at 12:44 on 2026-11-11 the file's max `DDS_DATE_CREATION` was 2026-11-10 21:57:12, with no rows for 11-11. So the job can score D once the file contains D-1. The readiness rule cannot prove D-1 is complete (an export before midnight would cut it short); this is unchanged from before and stated, not solved.

**API path never deserialises pickle/joblib:** `grep -rnE "joblib|pickle|dill|shelve|read_pickle|allow_pickle|torch\.load|np\.load"` over `services/api`, `services/routing` and `services/data` gave no matches (exit 1). In `services/ml` the only `joblib.load` is in `score.py` (batch job; it is now imported lazily after the sha check). `evaluate.py` only dumps. `inference.py` reads JSON and parquet only (pyarrow 26.0.1, past the CVE-2023-47248 fix in 14.0.1). New test `test_no_unpickle_api_path.py` runs `load_provider()` plus `cell_risk`, `edge_risk` and `status` in a fresh interpreter. It has a `pickle.find_class` audit hook and denies `pickle.load(s)`:
```text
{"provider": "HeuristicRiskProvider", "joblib": false, "sklearn": false, "events": []}
```
Negative control (same hook around `joblib.load` of the heuristic artifact): `caught pickle.find_class ('winterpath_ml.models', 'Calibrated')`.

**Checks (after the exit-policy revision):** `uv run pytest -q` → `58 passed, 1 skipped`. `uvx ruff check .` → `All checks passed!` `gate_logreg_2026 --check` → `pins OK; coverage list OK`. `scripts/check-ownership.sh ml` → `ownership OK for agent/ml`.

**Not done (Platform/coordinator):** the GitHub Actions workflow file itself (`.github/` is not ML-owned). That includes where the two git-ignored artifacts come from, where written score tables go so the API can read them, and the cron time. Network access from GitHub runners to donnees.montreal.ca has not been tested.

## Contract v1.7: `wp.risk_cell_score` writer + PostGIS provider, 2026-11-11

**Merges:** integration 5238c45 (cc9d330), then Data's migration 0007 at the exact commit 360fdd4 (4ba9c7d). Both were `git merge --no-edit` and clean. 360fdd4 is not in integration yet, so `scripts/check-ownership.sh ml` flags Data's 7 files. `git diff --name-only 360fdd4 HEAD`, restricted to non-ML paths, is empty: those files are byte-identical to Data's commit.

**Artifacts committed** (integration's `.gitignore` allows exactly these two). Their sha256 values match `models/registry.json`:
```text
4c9163461c21042c44a5ce80b57759e08c4bbc066fc3f35f223cb6b58de86546  models/artifacts/v2-8d19aa86/winter311-heuristic-v1.joblib
f7519df54d64d5d8734add8b4c3aa0631093007ffdd29de62432b729f8dc12cd  models/artifacts/v2-8d19aa86/coverage_cells.parquet
```

**Writer** (`score --write-db`, `score_db.write_scores`). One transaction does all of the following:
1. Inserts the `wp.ingest_run` row as `running`.
2. Per scored day, DELETEs the (`day`, `model_id`) partition and COPYs the new rows (`ingest_run_id` set, `data_through` = start of D local).
3. Deletes all rows with `day < today(America/Montreal) − 30 days`.
4. Marks the run `succeeded` with `record_count` and a provenance `log`.

On any error the transaction rolls back, so the previous partition stays intact. A `failed` ingest_run row is recorded separately, and the job exits **5**. Staleness (exit 4) is then checked against `max(day)` in the table for the model_id.
- `source_id` is `mtl-311` (FK to `wp.source`; scores derive from 311 history plus ECCC), overridable with `WP_ML_SCORE_SOURCE_ID`.
- `input_checksum` is namespaced `winterpath_ml.score:<sha256>`. Data's loader skips a source when (source_id, input_checksum) has already succeeded (`db_load._already_loaded`), and the namespace means an ML run can never make it skip a 311 load.
- `wp.source.last_success_at` is not touched.

**Provider** (`RISK_SCORE_SOURCE=postgis`): `inference.load_provider(engine=<SQLAlchemy engine>)` / `api_provider(engine=...)`.
- It reads `SELECT h3, p, data_through, scored_at FROM wp.risk_cell_score WHERE day=:day AND model_id=:model_id` for the requested **local** day, cached for 5 min per day.
- No row, a cell outside coverage, or a database error all mean `unknown` (never `low`).
- Heuristic probability stays `null`.
- No engine, or an unknown source value, gives `NullRiskProvider`.
- `file` (the default) is unchanged.

**API-side change needed (services/api, not ML-owned):** `adapters.load_risk_provider` calls `factory()` with no arguments. With `RISK_SCORE_SOURCE=postgis` it must call `factory(engine=db_engine)`, using the engine `state.py` already creates. Until then a deployed API gets `NullRiskProvider` (all unknown) and logs `risk_score_engine_missing`.

**Tested against a real DB at 0007.** `wp_ml` (ML's own DB) was migrated with Data's Alembic and seeded with Data's `db_load.upsert_sources`; `wp_data` was not touched:
```text
$ uv run alembic -c ../../db/alembic.ini -x url=<wp_ml> current
0007_risk_cell_score (head)
$ WP_ML_TEST_DB_URL=<wp_ml> uv run --extra db pytest -q tests/test_risk_cell_score_db.py
9 passed in 1.31s
```
The live tests use a unique SYNTHETIC model_id and clean up after themselves (`count(*)` afterwards is 0 in both tables). They check:
- partition replacement and ingest_run rows;
- 30-day retention;
- a run violating 0007's `p` CHECK (`CheckViolation`) that rolls back, leaves the old partition intact and records `failed`;
- the provider through a real SQLAlchemy engine: local-day boundary at 04:59/05:00 UTC, another model_id's row ignored, a day with no rows → unknown.

Real end-to-end, two identical runs (`score --start 2026-11-11 --end 2026-11-12 --write-db`):
```text
NOTICE: 2026-11-12 not scored yet: 311 data ends 2026-11-10 < 2026-11-11. Will be scored on a later run.
run 1: "rows_written": 2930, "rows_replaced": {"2026-11-11": 0},    5.60 real   854392832 max RSS
run 2: "rows_written": 2930, "rows_replaced": {"2026-11-11": 2930}, 5.99 real   780419072 max RSS
table: 2026-11-11|winter311-heuristic-v1|heuristic|2930|0.00120|0.06016|2026-11-11 05:00:00+00|1 run id
ingest_run: succeeded|2930|mtl-311|winterpath_ml.score:3e917eb742… (×2)
provider (RISK_SCORE_SOURCE=postgis): HeuristicRiskProvider Counter({'low': 2560, 'moderate': 369, 'elevated': 1})
  low None model_estimate 2026-11-11T05:00:00+00:00 2026-11-11T18:16:48+00:00
  2026-11-12 (no rows): Counter({'unknown': 2930}); outside coverage: unknown
```

**Checks:** without DB env `63 passed, 5 skipped`. With `WP_ML_TEST_DB_URL=<wp_ml>`: `67 passed, 1 skipped` (the skip is the `wp_data` reader test, which has its own env var). `uvx ruff check .` → `All checks passed!` `gate_logreg_2026 --check` → `pins OK; coverage list OK`. `sqlalchemy>=2.0` was added to the optional `db` extra (locks 2.1.8, same as services/api).

**Fix (coordinator):** under a plain `uv sync --locked` (no extras), two DB-free provider tests raised `ModuleNotFoundError: sqlalchemy`. Tests that need the optional `db` extra now skip with a reason:
```text
$ uv sync --locked && uv run --no-sync pytest -q -rs tests/test_risk_cell_score_db.py
SKIPPED [1] tests/test_risk_cell_score_db.py:239: sqlalchemy, psycopg not installed: optional 'db' extra (uv sync --extra db)
SKIPPED [1] tests/test_risk_cell_score_db.py:264: sqlalchemy, psycopg not installed: optional 'db' extra (uv sync --extra db)
3 passed, 6 skipped in 0.04s
$ uv run --no-sync pytest -q                                   (no extras)
61 passed, 7 skipped in 4.59s
$ uv sync --locked --all-extras && WP_ML_TEST_DB_URL=<wp_ml> uv run --no-sync pytest -q
67 passed, 1 skipped in 10.20s
```

## Deploy blocker fix: registry/artifact paths in a non-editable install, 2026-11-11
**Cause.** In a non-editable install (the API image), `config.py` lives at `/opt/venv/lib/python3.12/site-packages/winterpath_ml/`. `REPO_ROOT` then resolves to `/opt/venv`, and `REGISTRY_PATH` was hard-wired to `REPO_ROOT/models/registry.json` with no environment override. So the API logged `risk_registry_missing` and ran with no risk layer. A second bug: empty values such as `MODEL_ARTIFACT_DIR=` (as in `.env.example`) became `Path("")`, i.e. the repo root, instead of the default.

**Fix.**
- `config.REGISTRY_PATH` honours `MODEL_REGISTRY_PATH`, and `ARTIFACT_DIR` honours `MODEL_ARTIFACT_DIR` as before.
- Unset or empty means the dev default. Absolute paths are used as given; relative ones are taken from `REPO_ROOT` (same for `WP_ML_CACHE_DIR`).
- `load_registry` / `load_provider` resolve the registry path at call time, not at import time.
- The `risk_registry_missing` warning now prints `MODEL_REGISTRY_PATH`.
- `artifact_path()` already resolved entries as `ARTIFACT_DIR/<run_id>/<tail>`, never under `REPO_ROOT`. The test pins this for `/app/models/artifacts/v2-8d19aa86/coverage_cells.parquet`.

**Test** `tests/test_noneditable_layout.py`: the package is copied into `<tmp>/venv/lib/python3.12/site-packages`, imported from there in a fresh interpreter (cwd elsewhere), with the registry and the two committed artifacts under `<tmp>/app/models/`. It checks that:
- without env, it reproduces the image (`REPO_ROOT=<tmp>/venv`, NullRiskProvider, `risk_registry_missing`);
- with `MODEL_REGISTRY_PATH` + `MODEL_ARTIFACT_DIR`, it gives `HeuristicRiskProvider`, the coverage resolves under the artifact dir, and no missing-file warning appears;
- empty env values give the defaults.

Negative control (pre-fix `config.py` and `inference.py` from HEAD, same layout, env set):
```text
WARNING:winterpath_ml.inference:risk_registry_missing: <tmp>/venv/models/registry.json not found; using NullRiskProvider (all unknown)
OLD code: repo_root venv | registry <tmp>/venv/models/registry.json | provider NullRiskProvider
```
**Checks:** `uv sync --locked` (no extras) → `64 passed, 7 skipped`. `--all-extras` + `WP_ML_TEST_DB_URL=<wp_ml>` → `70 passed, 1 skipped`. `uvx ruff check .` → `All checks passed!` `gate_logreg_2026 --check` → `pins OK; coverage list OK` (config.py is not pinned).

**For the image (Platform):** set `MODEL_REGISTRY_PATH=/app/models/registry.json` and `MODEL_ARTIFACT_DIR=/app/models/artifacts` (absolute). `DEFAULT_EDGES_GEOJSON` (used only by `api_provider()` when `WP_EDGES_GEOJSON` is unset) is also REPO_ROOT-based; the configured `RISK_PROVIDER=winterpath_ml.inference:load_provider` does not use it.

## WinterPath 2.0, Wave 1 (ml): live weather library and Phase 5 plan (2026-11-11)

Merged integration eaac440 (clean). No training, no DB writes, no contract edits.

### Deviation: module name `winterpath_ml.weather_live`, not `winterpath_ml.weather`
`winterpath_ml.weather` already exists. It is the climate-daily feature loader, and its sha256 is pinned by the pre-registered logistic-regression gate (`models/gate-logreg-2026.md`). A package with that name would replace the module and void the 2027-05-08 run. The library is therefore `services/ml/src/winterpath_ml/weather_live/`. If the coordinator wants the plan's name, a re-export can be added after the gate run, or with a dated gate addendum.

### Library
| Module | Role |
|---|---|
| `model.py` (pure) | Dataclasses, `Provenance`, freshness rules, DST-safe helpers (`local_iso`, `local_day_bounds_utc`). All stored times are tz-aware UTC; local semantics use America/Toronto (America/Montreal links to it). |
| `eccc.py` | `http_get_json` (8 s timeout, User-Agent, 404 → `ProductUnavailable`, other failures → `FetchError`, non-JSON → `MalformedPayload`). `parse_citypage` / `parse_alerts` validate and normalise. |
| `provider.py` | `LiveWeatherProvider`: per-product TTL cache, single-flight lock, `retry_after` back-off (60 s) after a failure. Serves the last validated payload with degraded freshness. Injectable clock and fetcher. |
| `record.py` | Re-records the labelled fixtures. |

What `parse_citypage` / `parse_alerts` check and keep:
- The identifier must be `qc-147`.
- `lastUpdated` must carry an explicit offset (naive times are rejected).
- Hourly times must be strictly increasing.
- An alert page with `numberMatched > numberReturned` is rejected as truncated.
- Missing or blank values stay `None`, never 0.
- Alert text is kept verbatim. The licence requires "no alteration of the content or intent of the alert".
- ECCC icon URLs are not carried, because the GeoMet docs say commercial use of ECCC icons needs prior explicit consent.

Each `Snapshot` carries:
- provider (`eccc-geomet`), product, source URL;
- `issued_at`, `valid_from` / `valid_to`, `fetched_at`, `validated_at`;
- attribution and licence URL;
- freshness (`current|delayed|stale|unavailable`, with a reason);
- `fallback`.

**Freshness rules.** The state is the worst of issue age and our fetch age. It is `unavailable` when there is no payload or when `now ≥ valid_to` (last hourly + 1 h).

| Product | TTL | current → delayed | delayed → stale | Basis |
|---|---|---|---|---|
| citypage qc-147 | 10 min | issue > 90 min or fetch > 30 min | issue > 3 h or fetch > 3 h | ECCC: XML "updated hourly at a minimum" (Datamart readme). No cadence is published for the OGC item. |
| weather-alerts | 5 min | fetch > 15 min | fetch > 1 h | Alerts can come with "less than a half hours' notice". An empty list has no issue time, so only fetch age counts. |

If the city page is unavailable, or the product returns 404, the snapshot carries `fallback="observations_only"`: show SWOB observations, no forecast. An empty alert list means "ECCC reported no alerts for the queried area at `fetched_at`". It never means safe.

**Island matching for alerts is bbox-only for now.** The bbox is (−73.98, 45.40, −73.47, 45.71), each alert is labelled `area_match="bbox_intersects"`, and the bbox can match neighbouring areas such as Laval. Switch to Data's island polygon once it is published.

**Request volume.** One process makes at most 144 city-page and 288 alert fetches per day. ECCC's contact threshold is 86,400 requests/day (about 1 per second).

### Recorded fixtures (`services/ml/tests/fixtures/eccc/`, 128 KB, each with `.meta.json`: URL, `retrieved_at`, HTTP status, sha256, attribution)
```text
citypage_qc-147_20261111T234942Z.json  HTTP 200  30576 B  sha256 265c88ec62a2…  2026-11-11T23:49:42+00:00
alerts_island_bbox_20261111T234943Z.json  HTTP 200  853 B  sha256 1f02370e76c2…  2026-11-11T23:49:43+00:00
citypage_bc-98_with_warnings_20261111T234943Z.json  HTTP 200  36395 B  sha256 e11f9a814bdf…  2026-11-11T23:49:43+00:00
alerts_canada_sample_20261111T234943Z.json  HTTP 200  29774 B  sha256 2448a36a7cd8…  2026-11-11T23:49:43+00:00
citypage_missing_item_404_20261111T234944Z.json  HTTP 404  74 B  sha256 2d9bd297c82b…  2026-11-11T23:49:44+00:00
```
- Montréal had no warnings and no island alerts at recording time. The bc-98 page and the Canada-wide sample are labelled structure samples, not Montréal data.
- The Canada sample is a real partial page (limit 5 of 98). The parser rejects it as truncated, and the test checks that.
- Edge cases are SYNTHETIC copies of a recording, each with a named mutation inside the test.
- Tests verify each recording against its sha256 before use.

### Tests (`tests/test_weather_live.py`, 25 passed)
- **Outage:** no payload → `unavailable` + `observations_only`. A prior payload is kept and degrades current → delayed → stale. No upstream retries within `retry_after`.
- **Malformed:** six mutation cases, plus non-JSON and a truncated page. The last good payload is kept and the reason is shown.
- **Expired forecast:** `now = last hourly + 1 h` → `unavailable` + fallback.
- **Product disappearing:** 404 (the real 404 body) → `ProductUnavailable` → `observations_only`.
- **DST 2026-11-01:** 05:00Z → `01:00-04:00` and 06:00Z → `01:00-05:00`, both kept and distinct. The local day is 25 h, and ages are measured in UTC (80 min across the change).
- **DST 2027-03-14:** no 02:xx local hour, 07:00Z → `03:00-04:00`, the local day is 23 h.
- **TTL and single-flight:** 20 concurrent callers → 1 fetch; within the TTL there is no fetch.
- Missing fields stay None, warnings parse, alert text is verbatim (en and fr), and expired alerts are filtered at read time.

Live smoke (real ECCC, 2026-11-11 ~23:52 UTC; evidence only, not a test):
```text
citypage current | issued 49 min ago; fetched 0 min ago | fallback None
 issued 2026-11-11 23:02:50+00:00 valid 2026-11-12 00:00:00+00:00 -> 2026-11-13 00:00:00+00:00
 now 2026-11-11T18:00:00-05:00 4.7 C windchill -2.0 | Partly Cloudy
 hour+1 2026-11-11T19:00:00-05:00 4.0 C POP 0.0 %
 periods 12 Tonight | Increasing cloudiness early this evening. Low plus 1. | warnings 0
alerts current | 0 alerts, matched 0
second call (cached) ms 0.06 fetches {'citypage': 1, 'alerts': 1} | first calls s 0.7
```

### ECCC licence and usage summary
Pages read on 2026-11-11, all HTTP 200: licence, usage policy, GeoMet overview, OGC API page, City Page Weather (Datamart) readme, and the alerts readmes, at `eccc-msc.github.io/open-data/…`.
- **Licence (ECCC Data Server End-use Licence, page header "Version 2.1.1 - August 2026", while §9 says "version 2.1"):**
  - worldwide, royalty-free, perpetual, non-exclusive; commercial use included; copy, modify, publish, translate, adapt or distribute "for any lawful purpose";
  - attribution "Data Source: Environment and Climate Change Canada", with a link to the licence where possible;
  - no use of ECCC names, crests or logos, and no implied endorsement;
  - "as is", no warranty or liability;
  - alerts must be reproduced with "no alteration of the content or intent of the alert".
- **Usage policy:**
  - contact ECCC at or above 86,400 requests/day; ECCC may block users who saturate the service;
  - a meaningful User-Agent is recommended;
  - do not send `Cache-Control: no-cache` / `Pragma: no-cache` (our fetcher sends neither);
  - build local archives from the MSC Datamart, not GeoMet;
  - the policy "is subject to change".
- **Service level:** GeoMet is "operational 24/7", with user support "on a best effort basis during normal business hours". There is no SLA.
- **Icons:** commercial use requires prior explicit consent. We do not use them.
- **Not confirmed:**
  - No page read calls `citypageweather-realtime` experimental. None of the pages read documents that collection at all; the Datamart readme covers the XML files only. So "experimental" in the plan is unverified, but the fallback is built anyway.
  - **Correction (2026-11-11, coordinator; re-checked by ML at 23:58 UTC):** "experimental" **is** verified. The GeoMet `/collections` listing titles `citypageweather-realtime` as "City Page Weather [experimental]" (`weather-alerts` is titled "Weather Alerts"). I had fetched the collection document earlier but printed only its description, not its title. The observations-only fallback therefore covers a documented risk.
  - The alert time fields (publication / validity / expiration / event_end) are not defined on any page read. They are parsed as published.
  - No page read contains a "not for safety-critical use" statement.

### Phase 5 model-comparison plan (written only; nothing trained)
**Labels that exist.** Only one exists: winter-related Montréal 311 reports. Target: P(≥ 1 report in an H3 r9 cell on a local day), `NATURE ∈ {Requete, Plainte}`, four categories. It measures reporting behaviour, not sidewalk condition. There is no ground-truth label for ice or sidewalk state, and ECCC data are features, not labels.

Counts from the v2 snapshot 8d19aa86. Winter Y = Nov Y to Apr Y+1; "2021" is Jan–Apr 2022 only. A positive cell-day is a cell-day with at least one report.

| Winter | Reports | Positive cell-days | Cells | roadway_slippery | sidewalk_slippery | snow_clearing | snow_dumping |
|---|---|---|---|---|---|---|---|
| 2021 (Jan–Apr 2022) | 11,250 | 8,901 | 2,143 | 1,750 | 2,049 | 6,679 | 772 |
| 2022 | 15,125 | 12,568 | 2,236 | 1,219 | 1,357 | 10,983 | 1,566 |
| 2023 | 11,050 | 9,076 | 2,087 | 1,312 | 1,880 | 7,226 | 632 |
| 2024 | 17,595 | 13,992 | 2,280 | 1,650 | 1,661 | 12,920 | 1,364 |
| 2025 | 17,974 | 14,970 | 2,294 | 3,161 | 3,257 | 10,420 | 1,136 |
| 2026 (to 11-07) | 6 | 5 | 5 | 0 | 1 | 5 | 0 |

The newer snapshot 7318fc5d (2026-11-11) has the same 2026 counts. Its reports end 2026-11-07, while all requests run to 11-10. v2 panel positives within the 2,930 coverage cells: train 20,675 / valid 10,608 / test_chrono 11,356 / test_spatial 3,607 (of 929,764 / 372,317 / 372,317 / 158,013 rows).

**Constraints the comparison must respect:**
1. **Island coverage gap.** The 311 dataset covers only the 19 City of Montréal boroughs. The 15 linked municipalities (e.g. Westmount, Mont-Royal, Pointe-Claire) have no labels, so no model can be trained or validated there. Island cells outside labelled boroughs must stay `unknown`, not extrapolated. A geographic holdout can test transfer between boroughs, not to unlabelled municipalities.
2. **Frozen gate.** The logistic-regression gate pre-registered winter 2026-27 as its test winter (earliest run 2027-05-08). Computing any candidate metric on winter-2026 rows before then voids it. Until then, comparisons may use winters ≤ 2025 only, and since winter 2025 was already seen (the v2 test), those results are hypothesis-generating. The binding comparison is a new pre-registration written **before** its test winter. The next unseen winter is 2027-28, unless the new protocol is registered before 2026-27 data are touched and evaluated after 2027-05-08 alongside the existing gate.
3. **Coverage change.** The island needs coverage recomputed from Data's island polygon, which differs from the frozen v2 coverage. The new protocol must state it and must not alter the v2 files.
4. **Forecast features.** These cannot be trained yet: ECCC City Page Weather has no archive we have, so a forecast-aware model needs an archive of issued forecasts first. Recommendation (Platform/Data): store each City Page snapshot (e.g. from the Datamart, per the usage policy) from now on. Until then, models use observed weather only (the current D-1 features), and `departure_time` affects only the display of forecast weather, not the risk score.

**Candidates.** All take the same 24 v2 features (plus island coverage), fixed hyper-parameters chosen on the validation winter only, and isotonic calibration on a calibration winter:
- (a) historical frequency;
- (b) the current weather-rules heuristic;
- (c) logistic regression (the pinned gate candidate);
- (d) Poisson / negative-binomial count regression on the daily report count;
- (e) random forest;
- (f) gradient boosting, using `HistGradientBoosting`. XGBoost would be a new dependency (Apache-2.0) and is added only if the coordinator approves.

**Evaluation and decision:**
- **Holdouts:** chronological (the unseen winter) plus spatial (H3 res-6 blocks, seeded).
- **Metrics:** PR-AUC, Brier, precision/recall@50 cells/day, calibration curve, per-borough calibration ratio, and a day-block bootstrap 95 % CI for the PR-AUC difference against the best baseline.
- **Decision:** the same four criteria as the existing gates, all required on both holdouts. Otherwise the heuristic stays, with probability null.
- **Label noise and reporting bias** are stated in the card. Borough-level report rates differ, so per-borough calibration is gating.

### Checks
```text
$ uvx ruff check . && uvx ruff format --check .
All checks passed!
39 files already formatted
$ uv sync --locked && uv run --no-sync pytest -q                     (no extras)
89 passed, 7 skipped in 14.84s
$ uv sync --locked --all-extras && WP_ML_TEST_DB_URL=<wp_ml> uv run --no-sync pytest -q
95 passed, 1 skipped in 21.68s
$ uv run --no-sync python -m winterpath_ml.gate_logreg_2026 --check
pins OK; coverage list OK
$ scripts/check-ownership.sh ml
ownership OK for agent/ml
```

## Wave 1 follow-up: City Page forecast archive proposal and Phase 5 pre-registration draft (2026-11-11)
Merged integration 47615b4 (fast-forward; it contains contract v1.8.0 2e3d4b2 and the Wave 2a briefs). No ML files changed in the merge. No DB writes, no uploads, nothing provisioned.

### (1) Proposal: archive issued City Page forecasts from the MSC Datamart
**Why.** A forecast-aware risk model needs the forecasts as they were issued. GeoMet keeps only the latest, and the usage policy says local archives must be built "using MSC Datamart services, not MSC GeoMet services".

**Facts measured on 2026-11-11/12.** These came from ad-hoc requests (the policy reserves curl/wget for ad hoc retrieval): 24 hour-directory listings, 3 dated-directory listings and one file.
- **Path layout:** `https://dd.weather.gc.ca/today/citypage_weather/QC/{HH}/{YYYYMMDD}T{HHmmss.sss}Z_MSC_CitypageWeather_s0000635_{en|fr}.xml`. Site `s0000635` is "Montréal" (the `<name>` in the file) and has `hourlyForecast` × 24.
- **Volume:** on 2026-11-11, 62 Montréal files (31 en + 31 fr) appeared across all 24 UTC hours. That is one issue per hour plus extra issues; the readme says "updated hourly at a minimum, but can be updated earlier with issue of special weather warnings, watches and amendments".
- **Size:** about 34 KB (en) and 35 KB (fr) per file. One en file is 34,125 B, 2,707 B with `gzip -9` (12.6×), and 2,552 B with `xz -9`.
- **Retention:** dated copies exist at `https://dd.weather.gc.ca/{YYYYMMDD}/WXO-DD/citypage_weather/QC/{HH}/`. The root listed `20261013/ … 20261112/`, so about 30 days. `20261013/WXO-DD/citypage_weather/QC/12/` contained `20261013T120243.420Z_…_s0000635_en.xml`. **Issues older than about 30 days are lost**, so a backfill started now recovers 2026-10-13 onwards and loses one day per day of delay.

**Projected storage:**
| What | Per day | Per year |
|---|---|---|
| Raw XML, en only, gzip | 31 × 2.7 KB ≈ 84 KB | ≈ 31 MB |
| Raw XML, en + fr, gzip | ≈ 170 KB | ≈ 62 MB |
| Parsed hourly table (issue_time, valid_time, temp, POP, wind, gust, condition) | 31 × 24 = 744 rows ≈ 30–60 KB as Parquet (estimate, not measured) | ≈ 10–20 MB |

Recommendation: archive **en raw XML (gzip)** plus the parsed Parquet. The numbers are identical in fr, and the fr text is not needed for ML. Add fr only if the product needs historical French text.

**How to retrieve.** The usage policy prefers AMQP, and says not to request directory listings to check for new data.
- **Preferred:** an `sr3` (AMQP) subscription filtered to `citypage_weather/QC/.*s0000635_en\.xml`, downloading each file as it is announced. It needs a process that runs often enough for the broker queue to persist between connections. The queue-expiry setting has to be verified with ECCC's AMQP docs before relying on a periodic (rather than always-on) subscriber. GitHub cron is unreliable here (v2-plan problem 2), and Render Free sleeps.
- **Fallback, which needs a coordinator decision against the policy wording:** a once-daily job reads yesterday's dated directory (24 listings/day) and downloads the 31 en files. It is cheap (about 55 requests/day), but it uses listings.
- **One-time backfill now:** the same dated-directory read for 2026-10-13 → today, about 30 days × 55 requests ≈ 1,650 requests in one ad-hoc run. It must run soon, because each day of delay drops one day off the window.

**Where to store (owner/Platform decision; nothing provisioned):**
- Not git (CLAUDE.md: "Raw data … never go in Git").
- Not the Supabase database, given the 500 MB limit (`docs/FREE_TIER_LIMITS.md`) and that history is not needed by the API.
- Not GitHub Actions artifacts, which have limited retention.
- The right fit is **object storage**: Supabase Storage on the existing project, or Cloudflare R2 (Pages is already on Cloudflare). I have not verified either service's current free-tier limits or terms. Platform should confirm them before the owner chooses.
- Layout: `citypage/qc/s0000635/en/{YYYY}/{MM}/{DD}/{file}.xml.gz` plus a daily `parsed/{YYYY}-{MM}-{DD}.parquet` and a manifest (sha256, retrieval time, source URL).

**ML would add, once storage is decided (not now):**
- a Datamart XML parser in `weather_live`, sharing the normalised `HourlyForecast` records;
- the manifest writer;
- a test on a recorded file.

**Use limits:**
- The forecast archive starts in winter 2026-27, so no forecast-aware model can be trained before about two archived winters.
- `departure_time` stays display-only for risk (contract v1.8 `used_for: display_only`).

### (2) Phase 5 pre-registration draft: `models/gate-island-2027.DRAFT.md`
It is DRAFT only: not registered, with no force until renamed with all TBDs fixed before 2027-11-01. Its content:
- **Labels:** unchanged from v2.
- **Coverage:** island polygon ∩ the 19 boroughs ∩ prior 311 activity before 2026-11-01. The linked municipalities, which have no labels, stay `unknown`.
- **Splits:**
  - train winters 2021–2025;
  - selection on 2025-26 (already seen; used for choosing only);
  - calibration on 2026-27, **read only after 2027-05-08**;
  - **test 2027-28**, chronological plus spatial holdout with a new seed. Earliest run 2028-05-08.
- **Primary candidate:** one, chosen before registration among logistic / Poisson / RF / HGB (XGBoost pending the coordinator's decision).
- **Gate:** the same four criteria as v2, required on both holdouts.
- **Embargo:** it imposes, from now, an embargo on modelling reads of rows ≥ 2026-11-01 until the logistic-regression gate has run. The operational scoring job is the stated exception: it computes no metric.
- **Frozen files:** it touches none of the frozen v2 files and reads no winter-2026 rows. The label table it contains was computed in Wave 1 from snapshot 8d19aa86 (winters ≤ 2025 plus the 6 reports of November 2026, which were counted, not modelled).
- **Why 2027-28:** it is the earliest winter that is both unseen and not already pre-registered as a test winter by the logistic-regression gate.

## City Page forecast archive: one-time Datamart backfill + XGBoost pin (2026-11-12)
Coordinator decision: run the backfill now into the git-ignored `data/raw/eccc_citypage/`, then once a day by hand until the owner chooses storage. No AMQP subscriber, no cloud, nothing committed except code and this report.

**Script:** `services/ml/src/winterpath_ml/weather_live/datamart_archive.py`.
- **Requests:** sequential, ≥ 1.05 s between requests, User-Agent `WinterPathAI-dev/0.1 (local development)`. No Cache-Control/Pragma (urllib adds none; asserted in tests). Retries wait 5 / 15 / 45 s on timeouts, 429 and 5xx; 404 means "not there".
- **Scope:** only `*_s0000635_en.xml`. The French files are never requested.
- **Validation:** each XML is parsed and must carry `<location><name code="s0000635">` before it is stored.
- **Storage:** written via a `.part` file as `s0000635/en/YYYY/MM/DD/<file>.xml.gz`. `manifest.jsonl` records URL, `retrieved_at`, sha256 of the XML and of the gzip, and sizes. `days.json` records per-UTC-day status.
- **Idempotent:** known files are skipped, and complete past days are not listed again, so a daily run is about 48 listings plus about 35 downloads.
- **Tests:** `tests/test_datamart_archive.py` has 6 tests (spacing, retry, headers, gaps, wrong-site rejection, idempotence). They use SYNTHETIC XML and no network.

**Backfill run** (`--start 2026-10-13`, started 2026-11-12 00:03 UTC):
```text
{"requests": 1861, "wall_s": 1965}            # 0.95 requests/s average; 0 retries
records 1117 | unique files 1117 | unique XML sha256 1117
bytes xml 38481402 | bytes gz 3213221 | mean gz 2877
retrieved_at 2026-11-12T00:03:26+00:00 -> 2026-11-12T00:35:45+00:00
sha re-check on 50 random files: mismatches 0
$ du -sh data/raw/eccc_citypage  ->  5.0M   (git status: ignored)
```

**Per UTC day** (EN files; all 24 hour directories had files on every past day; 0 errors):
| Day | Files | Day | Files | Day | Files |
|---|---|---|---|---|---|
| 10-13 | 76 | 10-24 | 34 | 11-04 | 33 |
| 10-14 | 49 | 10-25 | 33 | 11-05 | 37 |
| 10-15 | 31 | 10-26 | 39 | 11-06 | 35 |
| 10-16 | 55 | 10-27 | 33 | 11-07 | 33 |
| 10-17 | 40 | 10-28 | 36 | 11-08 | 41 |
| 10-18 | 36 | 10-29 | 39 | 11-09 | 36 |
| 10-19 | 32 | 10-30 | 35 | 11-10 | 37 |
| 10-20 | 32 | 10-31 | 33 | 11-11 | 31 |
| 10-21 | 31 | 11-01 | 33 | 11-12 | 1 (partial: run at 00:03 UTC) |
| 10-22 | 33 | 11-02 | 32 | | |
| 10-23 | 32 | 11-03 | 39 | | |

**Gaps:**
- None in 2026-10-13 … 2026-11-11.
- 2026-11-12 is incomplete by design: only hour 00 existed, hour 23 was listed but empty, and hours 01–22 returned 404. Days before 2026-10-13 were already purged from the Datamart (about 30-day retention) and cannot be recovered.
- 2026-10-13 has 76 files, all distinct XML, but still only 4 forecast issues.

**What the files contain:**
- Distinct forecast issue times per day: `forecastGroup` usually 4 (5 on 10-28 and 11-06); `hourlyForecastGroup` usually 4 (5–6 on 10-27, 10-28, 11-01, 11-06).
- The archive holds **96 distinct hourly-forecast issues** in total. The extra files per day are hourly refreshes of current conditions and warnings.
- **For training:** the forecast-feature unit is about 4 issues/day, i.e. about 120 issues/month. Annual size is about 3.2 MB per 31 days gzip, so about 38 MB/year EN gzip, close to the 31 MB projected from one file.

**Daily run by hand** (from this machine, until the owner chooses storage):
```text
cd services/ml && uv run --no-sync python -m winterpath_ml.weather_live.datamart_archive
# default window: today-2 .. today (UTC); complete days are skipped
```
Missing a run is safe for up to about 30 days, which is the Datamart retention. After that, issues are lost.

**XGBoost (approved as a candidate):**
- `phase5` optional extra, exact pin 3.4.1, released 2026-08-15.
- **Licence:** Apache-2.0, verified from the installed wheel (`xgboost-3.4.1.dist-info/licenses/LICENSE` starts "Apache License / Version 2.0, January 2004"; `License-Expression: Apache-2.0`).
- **GPU dependency:** on Linux, `xgboost` pulls `nvidia-nccl-cu13` 2.32.6. That is a 206 MB wheel uploaded 2026-11-11, with no licence metadata on PyPI. So Linux (CI) uses `xgboost-cpu==3.4.1` (same release, Apache-2.0, 5.8 MB, no GPU deps), and other platforms use `xgboost==3.4.1` (the macOS wheel has no nccl dependency; `xgboost-cpu` has no macOS wheel). `uv.lock` contains no nccl.
- **Smoke test:** `import xgboost` gives 3.4.1, and `XGBClassifier` fits on toy data.
- **Audit:** `uvx pip-audit` on the locked `--all-extras` export reports "No known vulnerabilities found".
- **Not used yet:** no training.

**Checks:** no extras `95 passed, 7 skipped`. `--all-extras` + `WP_ML_TEST_DB_URL=<wp_ml>` `101 passed, 1 skipped`. `uvx ruff check/format`: clean. `gate_logreg_2026 --check`: `pins OK; coverage list OK`. `check-ownership.sh ml`: OK.

## Phase 5 EXPLORATORY model comparison (2026-11-12) — hypothesis-generating, NOT a validation claim
Winter 2025-26 was already seen (it was the v2 test). Nothing here validates any model, changes the registry or the gates, or reaches the API. The shipped layer remains the heuristic, with probability null.

**What ran.** `services/ml/src/winterpath_ml/phase5_explore.py` is a new module that imports `models`, `metrics` and `features` read-only.
- Data: the v2 panel `models/artifacts/v2-8d19aa86/features.parquet` (sha256 `ad63e3f0…` = registry) and the v2 interim 311 aggregates (snapshot `8d19aa86`). Every frame is filtered to `day < 2026-11-01` and asserted; `max_day_read = 2026-10-31`. **No rows from 2026-11-01 onwards were read.**
- Splits are exactly v2's: fit on train (2022-02-01..2024-04-30, 929,764 rows / 20,675 positives); isotonic on valid (2024-25, 372,317 / 10,608); report on test_chrono (2025-26, 372,317 / 11,356) and test_spatial (158,013 / 3,607).
- Candidates, with hyper-parameters fixed before the first run (no search):
  - hist freq and freq×weather (gating baselines);
  - Logistic (v2 pipeline);
  - Poisson count regression (same preprocessing, `PoissonRegressor(alpha=1e-4)`, target = daily report count; `count>0` reproduces the v2 label exactly, asserted);
  - RandomForest (300 trees, min_samples_leaf 100, sqrt features, max_samples 0.5);
  - XGBoost 3.4.1 (hist, 400 trees, depth 6, lr 0.05, subsample/colsample 0.8, min_child_weight 50);
  - v2 HGB (reference).
- Sanity check: Logistic and HGB reproduce `models/evaluation/v2-8d19aa86.json` to every printed digit (test_chrono 0.164858 / 0.161579; test_spatial 0.134491 / 0.133353).
- Command: `uv run --extra phase5 python -m winterpath_ml.phase5_explore` (wall 937 s, peak RSS 1.24 GB). Fit seconds: logistic 12.0, poisson 12.0, RF 120.9, XGB 55.6, HGB 391.6.

**Results (literal, from `results.json`).**
- PR-AUC is on uncalibrated scores. Brier is isotonic-calibrated on 2024-25.
- Δ is the difference against the best gating baseline (freq×weather on both splits), with a 95 % day-block bootstrap CI (200 resamples, seed 0).
- P/R@x% means the top ceil(x % × cells) flagged each day, pooled. @50 is `metrics.precision_recall_at_k` (k = 50/day ≈ 1.7 %).

test_chrono (2025-26):
```
method                      PR-AUC   dBest              CI95    Brier   P@1%   R@1%   P@5%   R@5%   P@50   R@50
baseline_hist_freq          0.0752 -0.0178 [-0.0346,-0.0048]  0.02888  0.134  0.045  0.099  0.162  0.111  0.088
baseline_freq_x_weather     0.0930 +0.0000                    0.02875  0.134  0.045  0.099  0.162  0.111  0.088
baseline_logistic           0.1649 +0.0718 [+0.0406,+0.1064]  0.02736  0.146  0.049  0.108  0.178  0.124  0.098
poisson_count               0.1626 +0.0696 [+0.0378,+0.1042]  0.02741  0.144  0.048  0.109  0.178  0.123  0.098
random_forest               0.1556 +0.0625 [+0.0354,+0.0989]  0.02758  0.139  0.046  0.110  0.180  0.122  0.097
xgboost                     0.1600 +0.0669 [+0.0383,+0.1032]  0.02753  0.141  0.047  0.106  0.174  0.125  0.099
hgb                         0.1616 +0.0686 [+0.0387,+0.1015]  0.02750  0.140  0.047  0.108  0.178  0.121  0.096
```
test_spatial (2025-26, holdout blocks):
```
method                      PR-AUC   dBest              CI95    Brier   P@1%   R@1%   P@5%   R@5%   P@50   R@50
baseline_hist_freq          0.0563 -0.0172 [-0.0330,-0.0051]  0.02192  0.101  0.045  0.074  0.163  0.072  0.182
baseline_freq_x_weather     0.0736 +0.0000                    0.02175  0.101  0.045  0.074  0.163  0.072  0.182
baseline_logistic           0.1345 +0.0609 [+0.0375,+0.0874]  0.02099  0.113  0.051  0.082  0.181  0.079  0.199
poisson_count               0.1313 +0.0578 [+0.0347,+0.0838]  0.02104  0.114  0.052  0.080  0.177  0.079  0.199
random_forest               0.1301 +0.0566 [+0.0352,+0.0857]  0.02103  0.115  0.052  0.081  0.179  0.080  0.200
xgboost                     0.1319 +0.0584 [+0.0377,+0.0849]  0.02100  0.112  0.050  0.082  0.182  0.080  0.201
hgb                         0.1334 +0.0598 [+0.0388,+0.0843]  0.02097  0.106  0.048  0.082  0.180  0.080  0.200
```
Per-borough calibration, test_chrono. Boroughs with ≥ 100 positives (15 of them); `mean_pred / obs_rate` min–max:
- hist 0.73–1.46;
- freq×weather 0.85–1.51;
- logistic 0.90–1.80;
- poisson 0.88–1.89;
- RF 0.86–1.40;
- XGB 0.91–1.47;
- HGB 0.91–1.43.

The worst is Saint-Laurent: obs 0.0104, logistic mean_pred 0.0188, ratio 1.80.

**Hypotheses, not conclusions.**
1. All five learned models beat both baselines by a similar, CI-separated margin, about +0.06 to +0.07 PR-AUC. Among them the spread is ≤ 0.009 PR-AUC, smaller than any CI width. The data does not separate logistic, Poisson, RF, XGB and HGB. More model complexity shows no visible gain, so the simplest candidate (logistic) remains the natural primary for the island pre-registration.
2. At a fixed alert rate the gain is small: P@1 % is 0.134 → 0.146 (chrono); R@5 % is 0.162 → 0.178. Most of the PR-AUC gain is in ordering *across* days, i.e. which days are bad. The within-day ranking comes mostly from history.
3. Hist freq and freq×weather give identical P/R at every alert rate. That is expected, because the weather multiplier is constant within a day, so it cannot change which cells are flagged on that day.
4. At a 5 % citywide alert rate, recall is concentrated in the central boroughs. In logistic, test_chrono: Plateau 0.60, Outremont 0.46, Ville-Marie 0.45. Pierrefonds-Roxboro and RDP-PAT are 0.00, Saint-Laurent 0.005. A citywide top-k under-serves outer boroughs. Per-borough or rate-normalised alerting is a question for the island protocol, not a result.
5. Calibrated per-borough ratios stay within [0.5, 2.0] for every method, but Saint-Laurent is over-predicted by 1.4–1.9×.

**Artifacts.** These are in `models/artifacts/phase5-explore-8d19aa86/` (git-ignored directory, committed with `git add -f` as instructed; no model pickles):

| file | bytes | sha256 |
|---|---|---|
| results.json | 14,108 | `96c86deb4beffa38ce0d4e2adc6e9f4bd51753bdbf1e32acfdd45bcbfd6632b0` |
| reliability.csv | 11,057 | `f46a289bd9a4bb7a51cd455847fdcdd3eac73fb1b4afcdfffca20c791b90328d` |
| borough.csv | 37,445 | `a25ac472fc280801355b242f9bda6e9b1b79f6d2211f8ed979c378129d8293b8` |
| manifest.json | 987 | lists the three above, input shas, the embargo check |

Tests: `tests/test_phase5_explore.py` (SYNTHETIC; alert-rate counting, embargo constant, method names) → `3 passed in 15.24s`.

## ETL advisory lock 100 for `wp.risk_cell_score` (2026-11-12)
This implements `infra/ETL-LOCKS.md` on integration `11ad5a2`, merged with `--no-edit`.
- **Constants.** `services/ml/src/winterpath_ml/locks.py` holds `WPET = 1464878420`, `SCHEMA_GATE = 0` and `RISK_CELL_SCORE = 100`. They are copied from Data's `winterpath_ingestion/locks.py`, not imported. `test_constants_match_data_copy` fails if Data's values ever drift.
- **`score_db.write_scores`.**
  - The first statement inside the existing single transaction is `pg_try_advisory_xact_lock_shared(WPET, 0)`, then `pg_try_advisory_xact_lock(WPET, 100)`.
  - If either lock is held elsewhere, `locks.Locked` is raised and the transaction rolls back. Nothing is written and **no** `ingest_run` row is recorded, because the other run is doing this work.
  - The best-effort `failed` ingest_run record also takes the shared schema gate first; if the gate is held, it skips recording.
  - Both locks are transaction-scoped and released on COMMIT, ROLLBACK or connection loss.
- **`score.main --write-db`.** On `Locked` it prints `NOTICE: lock (1464878420,<objid>) held by another run — skipping` (plus a `::notice` annotation under Actions) and **exits 0**. The staleness check is skipped on that run.
- **Fix found while wiring.** A local dict named `log` in `write_scores` shadowed the module logger. The failure-record fallback's `log.warning(...)` would therefore have raised AttributeError and masked the original error. The dict is renamed `prov`; behaviour is otherwise unchanged.
- **Tests** in `tests/test_locks.py`:
  - DB-free: constant match, acquisition order (gate shared → 100 exclusive), `Locked` on the gate or on 100, writer writes and records nothing when locked, CLI exits 0 with the notice;
  - live, two real connections on `wp_ml`: a holder of exclusive 100 → skip; a holder of the exclusive gate (as in a migration) → skip, with 0 score rows and 0 ingest_run rows; after the holder commits, the next write succeeds; a holder of the *shared* gate (another ETL load) does not block scoring.

```
$ WP_ML_TEST_DB_URL=$DATABASE_URL uv run --no-sync pytest -q tests/test_locks.py tests/test_risk_cell_score_db.py
18 passed in 4.34s
$ uv run --isolated --no-dev --with pytest pytest -q -p no:cacheprovider      # no extras
104 passed, 10 skipped in 86.29s (0:01:26)
$ WP_ML_TEST_DB_URL=$DATABASE_URL uv run --no-sync pytest -q                  # all extras + live DB
113 passed, 1 skipped in 24.43s
$ uv run --no-sync python -m winterpath_ml.gate_logreg_2026 --check
pins OK; coverage list OK
```
After the run, `wp_ml` holds 0 rows in `wp.risk_cell_score` and in `wp.ingest_run`, and 0 WPET advisory locks.

Answer to ETL-LOCKS open question 3: yes. `write_scores` replaces every (day, model_id) partition, applies retention and marks the ingest_run row in **one** transaction, so lock 100 lives inside it. No session-lock exception is needed.

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
