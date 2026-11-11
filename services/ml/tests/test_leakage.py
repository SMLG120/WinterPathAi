"""Features for day t must depend only on data dated < t."""

import numpy as np
import pandas as pd

from winterpath_ml import features

START, END = pd.Timestamp("2023-11-15"), pd.Timestamp("2024-03-31")
T = pd.Timestamp("2024-01-20")


def _panel(rc, ac, w, cells):
    return (
        features.build_panel(rc, ac, w, cells, START, END)
        .set_index(["day", "h3"])
        .sort_index()
    )


def test_future_311_and_weather_do_not_change_features(
    SYNTHETIC_reports, SYNTHETIC_all_requests, SYNTHETIC_weather, SYNTHETIC_cells
):
    base = _panel(
        SYNTHETIC_reports, SYNTHETIC_all_requests, SYNTHETIC_weather, SYNTHETIC_cells
    )

    rc = SYNTHETIC_reports.copy()
    rc.loc[rc["day"] >= T, "n"] *= 50  # wildly perturb day t and everything after
    extra = pd.DataFrame(
        {"h3": SYNTHETIC_cells, "day": T, "category": "sidewalk_slippery", "n": 99}
    )
    rc = pd.concat([rc, extra], ignore_index=True)
    ac = SYNTHETIC_all_requests.copy()
    ac.loc[ac["day"] >= T, "n"] += 1000
    w = SYNTHETIC_weather.copy()
    w.loc[w.index >= T] = [30.0, 25.0, 99.0, 99.0, 0.0]
    pert = _panel(rc, ac, w, SYNTHETIC_cells)

    upto = base.index.get_level_values("day") <= T
    cols = features.FEATURES
    pd.testing.assert_frame_equal(base.loc[upto, cols], pert.loc[upto, cols])
    # sanity: the perturbation is visible in the label at t and in features after t
    assert (pert.loc[T, "label"] == 1).all()
    after = base.index.get_level_values("day") > T
    assert not np.allclose(
        base.loc[after, "lag_1d"].to_numpy(), pert.loc[after, "lag_1d"].to_numpy()
    )


def test_label_is_same_day_and_lags_exclude_it(
    SYNTHETIC_cells, SYNTHETIC_all_requests, SYNTHETIC_weather
):
    c = SYNTHETIC_cells[0]
    rc = pd.DataFrame(
        {
            "h3": [c, c],
            "day": pd.to_datetime(["2024-01-10", "2024-01-12"]),
            "category": "x",
            "n": [2, 1],
        }
    )
    p = features.build_panel(
        rc, SYNTHETIC_all_requests, SYNTHETIC_weather, SYNTHETIC_cells, START, END
    )
    p = p[p["h3"] == c].set_index("day")
    assert p.loc["2024-01-10", "label"] == 1 and p.loc["2024-01-10", "lag_1d"] == 0
    assert p.loc["2024-01-11", "lag_1d"] == 2 and p.loc["2024-01-11", "label"] == 0
    assert p.loc["2024-01-12", "lag_3d"] == 2
    assert p.loc["2024-01-13", "lag_3d"] == 3
    assert p.loc["2024-01-14", "lag_3d"] == 1  # window Jan 11..13
    assert p.loc["2024-01-13", "city_lag_1d"] == 1


def test_weather_features_use_previous_days(SYNTHETIC_weather):
    days = pd.DatetimeIndex(["2024-01-20"])
    wf = features.weather_features(SYNTHETIC_weather, days)
    prev = SYNTHETIC_weather.loc["2024-01-19"]
    assert wf.loc["2024-01-20", "w_tmin_1d"] == prev["tmin"]
    assert np.isclose(
        wf.loc["2024-01-20", "w_snow_3d"],
        SYNTHETIC_weather.loc["2024-01-17":"2024-01-19", "snow"].sum(),
    )
