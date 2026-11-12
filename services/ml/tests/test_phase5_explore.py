"""Phase 5 exploratory helpers. SYNTHETIC frames only; no data reads."""

import numpy as np
import pandas as pd
import pytest

from winterpath_ml import phase5_explore as p5


def test_alert_rate_flags_top_share_per_day():
    day = np.repeat(np.array(["2025-12-01", "2025-12-02"], dtype="datetime64[D]"), 100)
    s = np.tile(np.arange(100, 0, -1), 2).astype(float)  # first rows score highest
    y = np.zeros(200, dtype=int)
    y[[0, 1, 50, 100]] = 1
    r = p5.at_alert_rate(day, y, s, 0.05)
    assert r["flagged"] == 10  # 5 per day
    assert r["precision"] == pytest.approx(3 / 10)
    assert r["recall"] == pytest.approx(3 / 4)


def test_embargo_constant_and_label():
    assert p5.EMBARGO == pd.Timestamp("2026-11-01")
    assert "hypothesis-generating" in p5.LABEL and "Not a validation claim" in p5.LABEL


def test_method_names_unique_and_gating_present():
    names = [m.name for m in p5.methods()]
    assert len(names) == len(set(names))
    assert set(p5.GATING) <= set(names)
