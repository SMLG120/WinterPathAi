"""Committed registry/card numbers must equal the committed evaluation output exactly."""

import json

import pytest

from winterpath_ml import config, evaluate

REG = config.REGISTRY_PATH


@pytest.mark.skipif(not REG.exists(), reason="no registry yet")
def test_card_and_registry_match_evaluation():
    reg = json.loads(REG.read_text())
    ev = json.loads((config.MODELS_DIR / "evaluation" / f"{reg['run_id']}.json").read_text())
    rows = [{"split": s, "method": m, **v} for s in ("test_chrono", "test_spatial") for m, v in ev["results"][s].items()]
    table = evaluate.fmt_table(rows, ["split", "method", "pr_auc", "brier", "precision_at_k", "recall_at_k", "base_rate", "n"])
    card = (config.MODELS_DIR / "cards" / f"{evaluate.MODEL_ID}.md").read_text()
    assert table in card
    m = reg["layers"]["model"]
    assert m["enabled"] == ev["gate_pass"]
    assert reg["active_layer"] == ("model" if ev["gate_pass"] else "heuristic")
    assert m["evaluation"]["pr_auc"] == ev["results"]["test_chrono"]["hgb"]["pr_auc"]
    assert m["evaluation"]["n_test"] == ev["results"]["test_chrono"]["hgb"]["n"]
    assert reg["levels"]["thresholds"] == ev["level_thresholds"]
