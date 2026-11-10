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

To swap the CSV aggregation for the Data agent's table: `data_311.read_report_cells_sql(conn)`
returns the same `(h3, day, category, n)` frame as `data_311.aggregate_report_cells`.
