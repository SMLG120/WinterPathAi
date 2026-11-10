import pandas as pd

from winterpath_ml import config, splits


def test_holdout_is_whole_blocks_and_deterministic(SYNTHETIC_cells):
    import h3

    cells = sorted(set().union(*[h3.grid_disk(c, 30) for c in SYNTHETIC_cells[:1]]))
    a = splits.holdout_blocks(cells)
    assert a == splits.holdout_blocks(cells)
    blk = splits.spatial_blocks(cells)
    held = set(blk[blk.isin(a)].index)
    assert held and len(held) < len(cells)


def test_assign_has_no_cell_or_time_overlap():
    import h3

    centre = h3.latlng_to_cell(45.5, -73.6, 9)
    cells = sorted(h3.grid_disk(centre, 30))
    days = pd.to_datetime(
        ["2023-01-10", "2024-12-10", "2026-01-10"]
    )  # train, valid, test winters
    panel = pd.DataFrame([(c, d) for d in days for c in cells], columns=["h3", "day"])
    panel["winter"] = [config.winter_of(d.date()) for d in panel["day"]]
    s = splits.assign(panel, cells)
    tr = set(panel.loc[s == "train", "h3"])
    sp = set(panel.loc[s == "test_spatial", "h3"])
    va = set(panel.loc[s == "valid", "h3"])
    assert sp and tr and not (sp & tr) and not (sp & va)
    assert (
        panel.loc[s == "train", "day"].max()
        < panel.loc[s == "valid", "day"].min()
        < panel.loc[s == "test_chrono", "day"].min()
    )
