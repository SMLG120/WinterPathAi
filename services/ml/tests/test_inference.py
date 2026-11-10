"""Inference honesty: unknown outside support, no probability from heuristic, disabled model refused."""

from datetime import datetime, timezone

import h3
import pandas as pd
import pytest

from winterpath_ml import inference

C_IN = h3.latlng_to_cell(45.5048, -73.5772, 9)
C_OUT = h3.latlng_to_cell(45.60, -73.50, 9)
TH = {"moderate": 0.02, "elevated": 0.04, "high": 0.08}


def _SYNTHETIC_registry(model_enabled: bool) -> dict:
    return {
        "run_id": "SYNTHETIC",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "target": "SYNTHETIC target",
        "training_window": "SYNTHETIC",
        "active_layer": "model" if model_enabled else "heuristic",
        "season_months": [11, 12, 1, 2, 3, 4],
        "levels": {"thresholds": TH},
        "limitations": ["SYNTHETIC"],
        "layers": {
            "heuristic": {"id": "h", "enabled": True},
            "model": {"id": "m", "enabled": model_enabled, "evaluation": None},
        },
    }


def _SYNTHETIC_scores(cells, day="2026-01-15", p=0.05):
    return pd.DataFrame({"h3": cells, "day": pd.Timestamp(day), "p": p, "scored_at": "2026-01-15T06:00:00+00:00",
                         "data_through": "2026-01-15T05:00:00+00:00"})


NOON_LOCAL_JAN15 = datetime(2026, 1, 15, 17, 0, tzinfo=timezone.utc)


def _heur(cells=(C_IN,), cov=(C_IN,), p=0.05):
    return inference.HeuristicRiskProvider(_SYNTHETIC_registry(False), "heuristic", _SYNTHETIC_scores(list(cells), p=p), frozenset(cov))


def test_heuristic_never_returns_probability():
    e = _heur().cell_risk(C_IN, NOON_LOCAL_JAN15)
    assert e.level == "elevated" and e.probability is None
    assert e.evidence.state == "model_estimate" and "not a validated probability" in e.evidence.note
    assert e.evidence.observed_at == "2026-01-15T05:00:00+00:00" and e.evidence.retrieved_at == "2026-01-15T06:00:00+00:00"


@pytest.mark.parametrize(
    "cell,when,why",
    [
        (C_OUT, NOON_LOCAL_JAN15, "coverage"),
        (C_IN, datetime(2026, 7, 15, 17, tzinfo=timezone.utc), "season"),
        (C_IN, datetime(2026, 1, 16, 17, tzinfo=timezone.utc), "day"),
    ],
)
def test_unknown_outside_support(cell, when, why):
    e = _heur().cell_risk(cell, when)
    assert e.level == "unknown" and e.probability is None and e.evidence.state == "unknown"


def test_local_day_conversion():
    # 03:00 UTC on Jan 16 is still Jan 15 in Montréal
    assert _heur().cell_risk(C_IN, datetime(2026, 1, 16, 3, tzinfo=timezone.utc)).level == "elevated"
    with pytest.raises(ValueError):
        _heur().cell_risk(C_IN, datetime(2026, 1, 15, 12))


def test_disabled_model_refused():
    with pytest.raises(inference.ModelDisabledError):
        inference.ModelRiskProvider(_SYNTHETIC_registry(False), "model", _SYNTHETIC_scores([C_IN]), frozenset([C_IN]))


def test_enabled_model_returns_probability_only_inside_support():
    m = inference.ModelRiskProvider(_SYNTHETIC_registry(True), "model", _SYNTHETIC_scores([C_IN], p=0.01), frozenset([C_IN]))
    e = m.cell_risk(C_IN, NOON_LOCAL_JAN15)
    assert e.level == "low" and e.probability == 0.01
    assert m.cell_risk(C_OUT, NOON_LOCAL_JAN15).probability is None


def test_edge_partially_outside_coverage_is_unknown():
    lat, lon = h3.cell_to_latlng(C_IN)
    nb = next(iter(set(h3.grid_ring(C_IN, 1))))
    lat2, lon2 = h3.cell_to_latlng(nb)
    coords = [[lon, lat], [lon2, lat2]]
    assert _heur().edge_risk(coords, NOON_LOCAL_JAN15).level == "unknown"
    full = _heur(cells=(C_IN, nb), cov=(C_IN, nb))
    assert full.edge_risk(coords, NOON_LOCAL_JAN15).level == "elevated"


def test_levels_and_status():
    assert [inference.level_for(p, TH) for p in (0.0, 0.02, 0.05, 0.5)] == ["low", "moderate", "elevated", "high"]
    st = _heur().status()
    assert st["risk_layer"] == "heuristic" and st["enabled"] is False
    assert "did not pass" in st["limitations"][0]


def test_null_provider_and_missing_registry(tmp_path):
    p = inference.load_provider(tmp_path / "nope.json")
    assert isinstance(p, inference.NullRiskProvider)
    assert p.cell_risk(C_IN, NOON_LOCAL_JAN15).level == "unknown"


def test_edge_risk_rows_dst_day():
    rows = inference.edge_risk_rows([("e1", [[-73.5772, 45.5048], [-73.5771, 45.5048]])], inference.NullRiskProvider(),
                                    datetime(2026, 3, 8, 17, tzinfo=timezone.utc), None)
    r = rows[0]
    assert r["level"] == "unknown" and r["model_id"] is None
    assert (r["valid_to"] - r["valid_from"]).total_seconds() == 23 * 3600  # DST start in Montréal
