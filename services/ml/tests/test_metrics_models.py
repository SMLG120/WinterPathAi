import numpy as np
import pandas as pd

from winterpath_ml import metrics, models


def test_precision_recall_at_k():
    day = np.array([1, 1, 1, 2, 2, 2])
    y = np.array([1, 0, 1, 0, 0, 1])
    s = np.array([0.9, 0.8, 0.1, 0.9, 0.5, 0.1])
    p, r = metrics.precision_recall_at_k(day, y, s, k=1)
    assert p == 0.5 and r == 1 / 3


def test_bootstrap_deterministic():
    rng = np.random.default_rng(0)
    day = np.repeat(np.arange(30), 20)
    y = rng.integers(0, 2, len(day))
    a, b = rng.random(len(day)), rng.random(len(day))
    assert metrics.bootstrap_pr_auc_diff(day, y, a, b, n_boot=20) == metrics.bootstrap_pr_auc_diff(day, y, a, b, n_boot=20)


def test_weather_multiplier_neutral_when_weather_missing():
    df = pd.DataFrame({"w_snow_3d": [np.nan], "w_freeze_thaw_3d": [np.nan], "w_precip_1d": [np.nan], "w_tmin_1d": [np.nan]})
    assert models.weather_multiplier(df)[0] == 1.0
