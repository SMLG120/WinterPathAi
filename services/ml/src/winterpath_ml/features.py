"""Leakage-safe cell × day feature panel.

Convention: the row for (cell c, day D) predicts whether >=1 winter report is created in c on
local day D. Every feature for that row is computed from data dated strictly before D
(i.e. available at 00:00 local on D). This is enforced by computing all windows as
cumulative-sum differences ending at D-1 and is checked by `tests/test_leakage.py`.
"""

from __future__ import annotations

from datetime import date, timedelta

import h3
import numpy as np
import pandas as pd
from scipy import sparse

from . import config
from .weather import weather_features

COUNT_LAGS = (1, 3, 7, 28)
NEIGHBOUR_LAGS = (1, 7)

FEATURES = (
    [f"lag_{k}d" for k in COUNT_LAGS]
    + [f"nb_lag_{k}d" for k in NEIGHBOUR_LAGS]
    + [
        "hist_rate",
        "hist_mean_count",
        "all_req_365d",
        "city_lag_1d",
        "city_lag_3d",
        "w_tmax_1d",
        "w_tmin_1d",
        "w_precip_1d",
        "w_precip_3d",
        "w_snow_1d",
        "w_snow_3d",
        "w_snow_ground_1d",
        "w_freeze_thaw_1d",
        "w_freeze_thaw_3d",
        "dow",
        "is_weekend",
        "holiday",
        "season_day",
    ]
)


def _easter(year: int) -> date:
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = ((h + l_ - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def quebec_holidays_in_season(year: int) -> set[date]:
    """Statutory holidays (Québec) falling Nov–Apr, plus Dec 26. Known in advance, so not leakage."""
    e = _easter(year)
    return {
        date(year, 1, 1),
        e - timedelta(days=2),  # Good Friday
        e + timedelta(days=1),  # Easter Monday
        date(year, 12, 25),
        date(year, 12, 26),
    }


def is_season(days: pd.DatetimeIndex) -> np.ndarray:
    return np.isin(days.month, config.SEASON_MONTHS)


def modal_borough(all_cells: pd.DataFrame, before: pd.Timestamp) -> pd.Series:
    """h3 -> borough with the most geolocated requests before `before` (names normalised)."""
    a = all_cells[all_cells["day"] < before].assign(borough=lambda d: d["borough"].map(config.normalise_borough))
    g = a.groupby(["h3", "borough"])["n"].sum().reset_index().sort_values(["h3", "n", "borough"], ascending=[True, False, True])
    return g.drop_duplicates("h3").set_index("h3")["borough"]


def select_universe(all_cells: pd.DataFrame, before: pd.Timestamp) -> list[str]:
    """Covered cells = >=1 geolocated 311 request (any category) before `before` (training data only)
    AND modal borough is one of the City of Montréal's 19 boroughs served by this 311 dataset."""
    b = modal_borough(all_cells, before)
    return sorted(b[b.isin(config.CITY_BOROUGHS)].index.tolist())


def neighbour_matrix(cells: list[str]) -> sparse.csr_matrix:
    """Row i sums the k=1 ring of cell i (self excluded), restricted to covered cells."""
    idx = {c: i for i, c in enumerate(cells)}
    rows, cols = [], []
    for c, i in idx.items():
        for n in h3.grid_ring(c, 1):
            j = idx.get(n)
            if j is not None:
                rows.append(i)
                cols.append(j)
    return sparse.csr_matrix((np.ones(len(rows), dtype=np.float32), (rows, cols)), shape=(len(cells), len(cells)))


def _dense(df: pd.DataFrame, cells: list[str], days: pd.DatetimeIndex) -> np.ndarray:
    """(T, C) matrix of counts; rows outside `days`/`cells` dropped."""
    idx_c = pd.Index(cells)
    idx_d = pd.Index(days)
    g = df.groupby(["day", "h3"])["n"].sum().reset_index()
    ci = idx_c.get_indexer(g["h3"])
    di = idx_d.get_indexer(g["day"])
    ok = (ci >= 0) & (di >= 0)
    m = np.zeros((len(days), len(cells)), dtype=np.float32)
    np.add.at(m, (di[ok], ci[ok]), g["n"].to_numpy()[ok])
    return m


def _window_sum(cs: np.ndarray, t: np.ndarray, k: int) -> np.ndarray:
    """Sum over days [t-k, t-1] given cs = cumsum with a leading zero row (cs[t] = sum of rows < t)."""
    lo = np.clip(t - k, 0, None)
    return cs[t] - cs[lo]


def build_panel(
    report_cells: pd.DataFrame,
    all_cells: pd.DataFrame,
    weather_daily: pd.DataFrame,
    cells: list[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
    history_start: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Rows for every covered cell × in-season day in [start, end]."""
    history_start = history_start or min(report_cells["day"].min(), all_cells["day"].min())
    days = pd.date_range(history_start, end, freq="D")
    T, C = len(days), len(cells)

    Y = _dense(report_cells, cells, days)
    A = _dense(all_cells, cells, days)
    Nb = neighbour_matrix(cells)
    YN = np.asarray((Nb @ Y.T).T, dtype=np.float32)

    zero = np.zeros((1, C), dtype=np.float64)
    csY = np.vstack([zero, np.cumsum(Y, axis=0, dtype=np.float64)])
    csYN = np.vstack([zero, np.cumsum(YN, axis=0, dtype=np.float64)])
    csA = np.vstack([zero, np.cumsum(A, axis=0, dtype=np.float64)])
    season = is_season(days)
    pos_season = ((Y > 0) & season[:, None]).astype(np.float64)
    csPos = np.vstack([zero, np.cumsum(pos_season, axis=0)])
    cnt_season = (Y * season[:, None]).astype(np.float64)
    csCnt = np.vstack([zero, np.cumsum(cnt_season, axis=0)])
    n_season_before = np.concatenate([[0], np.cumsum(season)])
    city = Y.sum(axis=1).astype(np.float64)
    csCity = np.concatenate([[0.0], np.cumsum(city)])

    sel = np.where((days >= start) & (days <= end) & season)[0]
    sel = sel[sel >= max(COUNT_LAGS)]  # require full lag history
    tdays = days[sel]
    nT = len(sel)

    out: dict[str, np.ndarray] = {}
    out["h3"] = np.tile(np.array(cells, dtype=object), nT)
    out["day"] = np.repeat(tdays.values, C)
    out["label"] = (Y[sel] > 0).astype(np.int8).ravel()
    for k in COUNT_LAGS:
        out[f"lag_{k}d"] = _window_sum(csY, sel, k).ravel()
    for k in NEIGHBOUR_LAGS:
        out[f"nb_lag_{k}d"] = _window_sum(csYN, sel, k).ravel()
    ns = n_season_before[sel][:, None].astype(np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        out["hist_rate"] = np.where(ns > 0, csPos[sel] / ns, np.nan).ravel()
        out["hist_mean_count"] = np.where(ns > 0, csCnt[sel] / ns, np.nan).ravel()
    out["all_req_365d"] = _window_sum(csA, sel, 365).ravel()
    out["city_lag_1d"] = np.repeat(csCity[sel] - csCity[sel - 1], C)
    out["city_lag_3d"] = np.repeat(csCity[sel] - csCity[np.clip(sel - 3, 0, None)], C)

    wf = weather_features(weather_daily, tdays)
    for col in wf.columns:
        out[col] = np.repeat(wf[col].to_numpy(dtype=np.float64), C)

    hol = set()
    for y in range(tdays.min().year, tdays.max().year + 1):
        hol |= quebec_holidays_in_season(y)
    out["dow"] = np.repeat(tdays.day_of_week.to_numpy(), C)
    out["is_weekend"] = (out["dow"] >= 5).astype(np.int8)
    out["holiday"] = np.repeat(np.array([d.date() in hol for d in tdays], dtype=np.int8), C)
    sd = np.array([(d - pd.Timestamp(d.year if d.month >= 11 else d.year - 1, 11, 1)).days for d in tdays])
    out["season_day"] = np.repeat(sd, C)

    panel = pd.DataFrame(out)
    panel["winter"] = _winter_vec(panel["day"])
    for c in FEATURES:
        if panel[c].dtype == np.float64:
            panel[c] = panel[c].astype(np.float32)
    return panel


def _winter_vec(day: pd.Series) -> np.ndarray:
    d = pd.DatetimeIndex(day)
    return np.where(d.month >= 11, d.year, d.year - 1)
