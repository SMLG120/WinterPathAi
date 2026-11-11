"""EdgeIdRiskProvider satisfies the routing/API protocol: risk_layer + edge_risk(edge_ids, at) -> {id: estimate}."""

from datetime import UTC, datetime

import h3
import pandas as pd

from winterpath_ml import inference

C = h3.latlng_to_cell(45.5048, -73.5772, 9)
LAT, LON = h3.cell_to_latlng(C)
WHEN = datetime(2026, 1, 15, 17, tzinfo=UTC)


def _SYNTHETIC_inner():
    reg = {
        "run_id": "SYNTHETIC",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "target": "t",
        "training_window": "w",
        "active_layer": "heuristic",
        "season_months": [11, 12, 1, 2, 3, 4],
        "levels": {"thresholds": {"moderate": 0.02, "elevated": 0.04, "high": 0.08}},
        "limitations": [],
        "layers": {
            "heuristic": {"id": "h", "enabled": True},
            "model": {"id": "m", "enabled": False, "evaluation": None},
        },
    }
    s = pd.DataFrame(
        {
            "h3": [C],
            "day": pd.Timestamp("2026-01-15"),
            "p": 0.05,
            "scored_at": "2026-01-15T06:00:00+00:00",
            "data_through": "2026-01-15T05:00:00+00:00",
        }
    )
    return inference.HeuristicRiskProvider(reg, "heuristic", s, frozenset([C]))


def test_edge_id_protocol_shape_and_unknown_ids():
    p = inference.EdgeIdRiskProvider(
        _SYNTHETIC_inner(), {"e1": [[LON, LAT], [LON + 0.00001, LAT]]}
    )
    assert p.risk_layer == "heuristic"
    out = p.edge_risk(["e1", "missing"], WHEN)
    assert set(out) == {"e1", "missing"}
    assert out["e1"]["level"] == "elevated" and out["e1"]["probability"] is None
    assert out["e1"]["evidence"]["state"] == "model_estimate"
    assert (
        out["missing"]["level"] == "unknown"
        and out["missing"]["evidence"]["state"] == "unknown"
    )
    assert p.model_status()["risk_layer"] == "heuristic"


def test_api_provider_factory_without_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(inference.config, "REGISTRY_PATH", tmp_path / "none.json")
    monkeypatch.setattr(
        inference, "load_provider", lambda **k: inference.NullRiskProvider()
    )
    monkeypatch.setenv("WP_EDGES_GEOJSON", str(tmp_path / "nope.geojson"))
    p = inference.api_provider()
    assert p.risk_layer == "none"
    assert p.edge_risk(["x"], WHEN)["x"]["level"] == "unknown"
