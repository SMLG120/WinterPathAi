"""Chronological + spatial-block splits. No random row splits anywhere."""

from __future__ import annotations

import h3
import numpy as np
import pandas as pd

from . import config


def spatial_blocks(cells: list[str], res: int = config.SPATIAL_BLOCK_RES) -> pd.Series:
    return pd.Series(
        [h3.cell_to_parent(c, res) for c in cells], index=cells, name="block"
    )


def holdout_blocks(
    cells: list[str],
    fraction: float = config.SPATIAL_HOLDOUT_FRACTION,
    seed: int = config.SEED,
) -> set[str]:
    """Seeded random choice of whole H3 res-6 parent blocks (sorted first, so deterministic)."""
    blocks = sorted(set(spatial_blocks(cells)))
    rng = np.random.default_rng(seed)
    n = max(1, round(fraction * len(blocks)))
    return set(rng.choice(blocks, size=n, replace=False).tolist())


def assign(panel: pd.DataFrame, cells: list[str]) -> pd.Series:
    """Label each panel row: train | valid | test_chrono | test_spatial | unused.

    - train:        TRAIN_WINTERS, non-holdout blocks
    - valid:        VALID_WINTER, non-holdout blocks (calibration only)
    - test_chrono:  TEST_WINTER, non-holdout blocks
    - test_spatial: TEST_WINTER, holdout blocks (never seen in training or calibration)
    Holdout-block rows in train/valid winters are unused.
    """
    hold = holdout_blocks(cells)
    blk = spatial_blocks(cells)
    in_hold = panel["h3"].map(blk).isin(hold).to_numpy()
    w = panel["winter"].to_numpy()
    out = np.full(len(panel), "unused", dtype=object)
    out[np.isin(w, config.TRAIN_WINTERS) & ~in_hold] = "train"
    out[(w == config.VALID_WINTER) & ~in_hold] = "valid"
    out[(w == config.TEST_WINTER) & ~in_hold] = "test_chrono"
    out[(w == config.TEST_WINTER) & in_hold] = "test_spatial"
    return pd.Series(out, index=panel.index, name="split")
