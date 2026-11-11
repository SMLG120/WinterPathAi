"""Regression (frontend report): artifacts must resolve under MODEL_ARTIFACT_DIR, and fallbacks must warn."""

import json
import logging
from datetime import UTC, datetime

import h3
import pandas as pd

from winterpath_ml import inference

C = h3.latlng_to_cell(45.5048, -73.5772, 9)
WHEN = datetime(2026, 1, 15, 17, tzinfo=UTC)


def _SYNTHETIC_registry(tmp_path):
    reg = {
        "run_id": "SYNTHETIC-run",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "target": "t",
        "training_window": "w",
        "active_layer": "heuristic",
        "season_months": [11, 12, 1, 2, 3, 4],
        "levels": {"thresholds": {"moderate": 0.02, "elevated": 0.04, "high": 0.08}},
        "limitations": [],
        # recorded repo-relative, exactly like the real registry
        "coverage": {"path": "models/artifacts/SYNTHETIC-run/coverage_cells.parquet"},
        "layers": {
            "heuristic": {"id": "h", "enabled": True},
            "model": {"id": "m", "enabled": False, "evaluation": None},
        },
    }
    p = tmp_path / "registry.json"
    p.write_text(json.dumps(reg))
    return reg, p


def test_artifacts_resolve_under_relocated_artifact_dir(tmp_path, monkeypatch):
    reg, reg_path = _SYNTHETIC_registry(tmp_path)
    art = tmp_path / "elsewhere"  # NOT under the repo
    run = art / "SYNTHETIC-run"
    (run / "scores" / "h").mkdir(parents=True)
    pd.DataFrame({"h3": [C]}).to_parquet(run / "coverage_cells.parquet")
    pd.DataFrame(
        {
            "h3": [C],
            "day": pd.Timestamp("2026-01-15"),
            "p": 0.05,
            "scored_at": "x",
            "data_through": "x",
        }
    ).to_parquet(run / "scores" / "h" / "2026-01-15.parquet")
    monkeypatch.setattr(inference.config, "ARTIFACT_DIR", art)
    assert (
        inference.artifact_path(reg, reg["coverage"]) == run / "coverage_cells.parquet"
    )
    p = inference.load_provider(reg_path)
    assert isinstance(p, inference.HeuristicRiskProvider)
    assert p.cell_risk(C, WHEN).level == "elevated"


def test_missing_artifacts_warn_and_fall_back(tmp_path, monkeypatch, caplog):
    _, reg_path = _SYNTHETIC_registry(tmp_path)
    monkeypatch.setattr(inference.config, "ARTIFACT_DIR", tmp_path / "empty")
    with caplog.at_level(logging.WARNING, logger="winterpath_ml.inference"):
        p = inference.load_provider(reg_path)
    assert isinstance(p, inference.NullRiskProvider)
    assert (
        "risk_artifacts_missing" in caplog.text
        and str(tmp_path / "empty") in caplog.text
    )


def test_missing_registry_warns(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="winterpath_ml.inference"):
        p = inference.load_provider(tmp_path / "nope.json")
    assert (
        isinstance(p, inference.NullRiskProvider)
        and "risk_registry_missing" in caplog.text
    )


def test_missing_scores_warn(tmp_path, monkeypatch, caplog):
    _, reg_path = _SYNTHETIC_registry(tmp_path)
    run = tmp_path / "art" / "SYNTHETIC-run"
    run.mkdir(parents=True)
    pd.DataFrame({"h3": [C]}).to_parquet(run / "coverage_cells.parquet")
    monkeypatch.setattr(inference.config, "ARTIFACT_DIR", tmp_path / "art")
    with caplog.at_level(logging.WARNING, logger="winterpath_ml.inference"):
        p = inference.load_provider(reg_path)
    assert isinstance(p, inference.HeuristicRiskProvider)
    assert "risk_scores_missing" in caplog.text
    assert p.cell_risk(C, WHEN).level == "unknown"
