"""SYNTHETIC fixtures only — small hand-made frames, never real 311/ECCC data."""

from __future__ import annotations

import h3
import numpy as np
import pandas as pd
import pytest

CENTER = h3.latlng_to_cell(
    45.5048, -73.5772, 9
)  # McGill area, used only to get valid H3 ids


@pytest.fixture
def SYNTHETIC_cells() -> list[str]:
    ring = sorted(h3.grid_disk(CENTER, 2))
    return ring  # 19 cells


@pytest.fixture
def SYNTHETIC_days() -> pd.DatetimeIndex:
    return pd.date_range("2023-10-01", "2024-03-31", freq="D")


@pytest.fixture
def SYNTHETIC_reports(SYNTHETIC_cells, SYNTHETIC_days) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    rows = []
    for d in SYNTHETIC_days:
        for c in SYNTHETIC_cells:
            n = rng.poisson(0.15)
            if n:
                rows.append((c, d, "slippery_sidewalk", int(n)))
    return pd.DataFrame(rows, columns=["h3", "day", "category", "n"])


@pytest.fixture
def SYNTHETIC_all_requests(SYNTHETIC_cells, SYNTHETIC_days) -> pd.DataFrame:
    rng = np.random.default_rng(2)
    rows = [
        (c, d, "SYNTHETIC-BOROUGH", int(rng.poisson(2)) + 1)
        for d in SYNTHETIC_days
        for c in SYNTHETIC_cells
    ]
    return pd.DataFrame(rows, columns=["h3", "day", "borough", "n"])


@pytest.fixture
def SYNTHETIC_weather(SYNTHETIC_days) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    n = len(SYNTHETIC_days)
    tmin = rng.normal(-8, 6, n)
    return pd.DataFrame(
        {
            "tmax": tmin + rng.uniform(2, 10, n),
            "tmin": tmin,
            "precip": rng.exponential(1.5, n),
            "snow": rng.exponential(1.0, n),
            "snow_ground": rng.uniform(0, 30, n),
        },
        index=pd.DatetimeIndex(SYNTHETIC_days, name="day"),
    )
