# winterpath_ml

Winter 311 **report-risk** research pipeline and the inference interface used by `services/api`.

Target (ADR-5): P(≥1 winter-related 311 report in an H3 res-9 cell during the next local day).
This is *reporting behaviour*, never sidewalk safety, ice or clearance.

## Commands (Python 3.12, uv)

```bash
cd services/ml
uv sync
uv run python -m winterpath_ml.evaluate      # downloads public data if missing, prints metrics + gate, writes artifacts/registry/card
uv run python -m winterpath_ml.audit         # writes models/label-audit.md
uv run python -m winterpath_ml.score --start 2026-11-10   # per-day score table for the active layer
uv run pytest
```

Raw downloads go to `services/ml/.cache/` (git-ignored). Only H3-aggregated counts are written to disk.
Artifacts go to `$MODEL_ARTIFACT_DIR` (default `models/artifacts/`, git-ignored); `models/registry.json`,
`models/evaluation/*.json` and `models/cards/*.md` are committed.

## API usage

```python
from datetime import datetime, timezone
from winterpath_ml.inference import load_provider

risk = (
    load_provider()
)  # active layer from models/registry.json; NullRiskProvider if artifacts missing
est = risk.edge_risk(
    [[-73.5772, 45.5048], [-73.5765, 45.5050]], datetime.now(timezone.utc)
)
est.to_dict()  # {"level": ..., "probability": None|float, "evidence": {...}}  == OpenAPI RiskEstimate
risk.status()  # == OpenAPI ModelStatus
```

`unknown` is returned for: cells outside coverage (incl. demerged municipalities such as Westmount),
months outside Nov–Apr, days without a score table, and edges touching any such cell.
The heuristic layer always returns `probability = null`. `ModelRiskProvider` refuses to load a model
the registry marks disabled.

**Do not use `data_311.read_report_cells_sql`.** It predates contract v1.5.0 (`nature` in the PK) and doesn't filter natures. It is left unchanged only because `data_311.py` is pinned by `models/gate-logreg-2026.md`. Use `winterpath_ml.report_cells_db.read_report_cells(conn)` instead (optional extra: `uv sync --extra db`). It sums `nature IN ('requete','plainte')` over the four label categories (`sidewalk_slippery`, `roadway_slippery`, `snow_clearing`, `snow_dumping`), excluding the v1.6 alley categories (CR-ML-2), and returns the same `(h3, day, category, n)` frame. Verified against Data f6eb3b2's v1.6 load: 0 cell-days differ from the CSV label of record (see the agent report).

```bash
uv run --extra db python -m winterpath_ml.report_cells_db --compare --database-url "$URL"
```

## Artifact location
All artifact reads go through `inference.artifact_path()`, which resolves registry entries under `MODEL_ARTIFACT_DIR` (default `models/artifacts`). When artifacts are missing, `load_provider()` logs `risk_registry_missing` / `risk_artifacts_missing` and returns `NullRiskProvider`; a missing scores directory logs `risk_scores_missing`.

## Wiring into services/api (edge-id protocol)

`winterpath_routing.RiskProvider` takes edge ids, not geometry. Use the adapter:

```bash
RISK_PROVIDER=winterpath_ml.inference:api_provider
WP_EDGES_GEOJSON=data/fixtures/pilot_mini/edges.geojson   # default; must match the graph the API routes on
```

`api_provider()` returns an `EdgeIdRiskProvider` exposing `risk_layer`, `edge_risk(edge_ids, at)` and `model_status()`.
Edge ids missing from the GeoJSON come back as `unknown`. The API package must list `winterpath-ml` as a dependency;
that is a Routing/API-owned change.
