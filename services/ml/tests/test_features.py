import numpy as np
import pandas as pd

from winterpath_ml import features


def test_neighbour_matrix_ring_only(SYNTHETIC_cells):
    m = features.neighbour_matrix(SYNTHETIC_cells)
    assert m.diagonal().sum() == 0
    assert m.sum(axis=1).max() <= 6


def test_out_of_season_days_excluded(SYNTHETIC_reports, SYNTHETIC_all_requests, SYNTHETIC_weather, SYNTHETIC_cells):
    p = features.build_panel(SYNTHETIC_reports, SYNTHETIC_all_requests, SYNTHETIC_weather, SYNTHETIC_cells,
                             pd.Timestamp("2023-10-01"), pd.Timestamp("2024-03-31"))
    months = pd.DatetimeIndex(p["day"]).month
    assert set(months) <= {11, 12, 1, 2, 3}
    assert p["day"].min() >= pd.Timestamp("2023-11-01")


def test_hist_rate_is_expanding_share_of_prior_season_days(SYNTHETIC_cells, SYNTHETIC_all_requests, SYNTHETIC_weather):
    c = SYNTHETIC_cells[3]
    rc = pd.DataFrame({"h3": [c], "day": pd.to_datetime(["2023-11-05"]), "category": "x", "n": [1]})
    p = features.build_panel(rc, SYNTHETIC_all_requests, SYNTHETIC_weather, SYNTHETIC_cells,
                             pd.Timestamp("2023-11-01"), pd.Timestamp("2023-11-30"))
    r = p[(p["h3"] == c)].set_index("day")
    # 2023-11-10: prior season days Nov 1..9 = 9, one positive
    assert np.isclose(r.loc["2023-11-10", "hist_rate"], 1 / 9)
    assert np.isclose(r.loc["2023-11-05", "hist_rate"], 0.0)


def test_holidays():
    h = features.quebec_holidays_in_season(2024)
    assert pd.Timestamp("2024-03-29").date() in h  # Good Friday 2024
    assert pd.Timestamp("2024-04-01").date() in h  # Easter Monday 2024


def test_universe_excludes_demerged_municipalities_and_future_activity(SYNTHETIC_cells):
    c1, c2, c3 = SYNTHETIC_cells[:3]
    ac = pd.DataFrame(
        {
            "h3": [c1, c2, c2, c3],
            "day": pd.to_datetime(["2023-01-01", "2023-01-01", "2023-01-02", "2025-01-01"]),
            "borough": ["Ville-Marie", "Westmount", "Ville-Marie", "Ville-Marie"],
            "n": [1, 5, 1, 1],
        }
    )
    u = features.select_universe(ac, pd.Timestamp("2024-11-01"))
    assert u == [c1]  # c2 modal borough Westmount (not in this 311 system), c3 only active after cutoff
