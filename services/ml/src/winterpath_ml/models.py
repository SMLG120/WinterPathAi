"""Baselines and candidate models.

Every method exposes `score(panel) -> ranking score`. Probabilities come from an isotonic
calibrator fitted on the validation winter only (`Calibrated`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

from .features import FEATURES

# Count-like features get log1p before the linear model.
_LOG_FEATURES = [f for f in FEATURES if f.startswith(("lag_", "nb_lag_", "all_req", "city_", "hist_mean"))]


class Scorer(Protocol):
    name: str

    def fit(self, df: pd.DataFrame) -> "Scorer": ...

    def score(self, df: pd.DataFrame) -> np.ndarray: ...


@dataclass
class HistoricalFrequency:
    """(a) Cell's share of prior in-season days with >=1 winter report (expanding, leakage-safe)."""

    name: str = "baseline_hist_freq"

    def fit(self, df: pd.DataFrame) -> "HistoricalFrequency":
        return self

    def score(self, df: pd.DataFrame) -> np.ndarray:
        return df["hist_rate"].fillna(0).to_numpy(dtype=float)


def weather_multiplier(df: pd.DataFrame) -> np.ndarray:
    """Fixed, hand-set weather multiplier (not fitted). Missing weather -> neutral 1.0.

    1 + snowfall_3d_cm / 5 + 0.5 * freeze_thaw_days_3d + 0.5 * [precip_1d > 0 and tmin_1d < 0]
    """
    snow = df["w_snow_3d"].fillna(0).to_numpy(dtype=float)
    ft = df["w_freeze_thaw_3d"].fillna(0).to_numpy(dtype=float)
    wet_cold = ((df["w_precip_1d"].fillna(0) > 0) & (df["w_tmin_1d"].fillna(1) < 0)).to_numpy(dtype=float)
    return 1.0 + snow / 5.0 + 0.5 * ft + 0.5 * wet_cold


@dataclass
class FrequencyWeatherHeuristic:
    """(b) Historical frequency × fixed weather multiplier. This is the shippable heuristic layer."""

    name: str = "baseline_freq_x_weather"

    def fit(self, df: pd.DataFrame) -> "FrequencyWeatherHeuristic":
        return self

    def score(self, df: pd.DataFrame) -> np.ndarray:
        return df["hist_rate"].fillna(0).to_numpy(dtype=float) * weather_multiplier(df)


def _log_counts(x: pd.DataFrame) -> pd.DataFrame:
    x = x.copy()
    for c in _LOG_FEATURES:
        x[c] = np.log1p(x[c].clip(lower=0))
    return x


@dataclass
class Logistic:
    """(c) L2 logistic regression on all features (log1p counts, imputed, standardised)."""

    name: str = "baseline_logistic"
    model: object = None

    def fit(self, df: pd.DataFrame) -> "Logistic":
        self.model = make_pipeline(
            FunctionTransformer(_log_counts),
            SimpleImputer(strategy="median", add_indicator=True),
            StandardScaler(),
            LogisticRegression(C=1.0, max_iter=2000),
        )
        self.model.fit(df[FEATURES], df["label"].to_numpy())
        return self

    def score(self, df: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(df[FEATURES])[:, 1]


@dataclass
class GradientBoosting:
    """Candidate: sklearn HistGradientBoosting with fixed hyper-parameters (no test-set tuning)."""

    name: str = "hgb"
    params: dict = field(
        default_factory=lambda: dict(
            learning_rate=0.05,
            max_iter=300,
            max_leaf_nodes=31,
            min_samples_leaf=200,
            l2_regularization=1.0,
            early_stopping=False,
            random_state=0,
        )
    )
    model: object = None

    def fit(self, df: pd.DataFrame) -> "GradientBoosting":
        self.model = HistGradientBoostingClassifier(**self.params)
        self.model.fit(df[FEATURES], df["label"].to_numpy())
        return self

    def score(self, df: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(df[FEATURES])[:, 1]


@dataclass
class Calibrated:
    """Wraps a fitted scorer with an isotonic map fitted on the validation winter only."""

    scorer: Scorer
    iso: IsotonicRegression | None = None

    @property
    def name(self) -> str:
        return self.scorer.name

    def calibrate(self, valid: pd.DataFrame) -> "Calibrated":
        self.iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        self.iso.fit(self.scorer.score(valid), valid["label"].to_numpy())
        return self

    def score(self, df: pd.DataFrame) -> np.ndarray:
        return self.scorer.score(df)

    def proba(self, df: pd.DataFrame) -> np.ndarray:
        return self.iso.predict(self.score(df))


def all_methods() -> list[Scorer]:
    return [HistoricalFrequency(), FrequencyWeatherHeuristic(), Logistic(), GradientBoosting()]


BASELINES = ("baseline_hist_freq", "baseline_freq_x_weather", "baseline_logistic")
CANDIDATE = "hgb"
