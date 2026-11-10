"""Edge-risk mapping on the Data agent's real pilot_mini OSM fixture (simulated=false).

Uses a SYNTHETIC score table so it needs no model artifacts; only the geometry is real.
"""

import json
from datetime import UTC, datetime

import h3
import pandas as pd
import pytest

from winterpath_ml import config, inference

EDGES = config.REPO_ROOT / "data" / "fixtures" / "pilot_mini" / "edges.geojson"
pytestmark = pytest.mark.skipif(
    not EDGES.exists(), reason="pilot_mini fixture not merged"
)
WHEN = datetime(2026, 1, 15, 17, tzinfo=UTC)


def _edges():
    return [
        (f["id"], f["geometry"]["coordinates"])
        for f in json.loads(EDGES.read_text())["features"]
    ]


def _SYNTHETIC_provider(cells):
    reg = {
        "run_id": "SYNTHETIC",
        "generated_at": "x",
        "target": "x",
        "training_window": "x",
        "active_layer": "heuristic",
        "season_months": [11, 12, 1, 2, 3, 4],
        "levels": {"thresholds": {"moderate": 0.02, "elevated": 0.04, "high": 0.08}},
        "layers": {
            "heuristic": {"id": "h", "enabled": True},
            "model": {"id": "m", "enabled": False},
        },
    }
    s = pd.DataFrame(
        {
            "h3": sorted(cells),
            "day": pd.Timestamp("2026-01-15"),
            "p": 0.03,
            "scored_at": "x",
            "data_through": "x",
        }
    )
    return inference.HeuristicRiskProvider(reg, "heuristic", s, frozenset(cells))


def test_fixture_edges_map_to_cells_near_mcgill():
    cells = {c for _, coords in _edges() for c in inference.cells_along(coords)}
    assert cells
    for c in cells:
        lat, lon = h3.cell_to_latlng(c)  # catches [lat, lon] swaps
        assert 45.49 < lat < 45.52 and -73.59 < lon < -73.56


def test_fixture_edges_unknown_unless_every_touched_cell_is_covered():
    edges = _edges()
    cells = sorted({c for _, coords in edges for c in inference.cells_along(coords)})
    full = inference.edge_risk_rows(edges, _SYNTHETIC_provider(cells), WHEN, "h")
    assert {r["level"] for r in full} == {"moderate"}
    assert all(r["probability"] is None for r in full)
    partial = inference.edge_risk_rows(edges, _SYNTHETIC_provider(cells[1:]), WHEN, "h")
    dropped = cells[0]
    for (_, coords), r in zip(edges, partial, strict=True):
        touches = dropped in inference.cells_along(coords)
        assert (r["level"] == "unknown") == touches
