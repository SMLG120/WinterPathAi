"""Reader for the Data agent's `wp.report_311_cell` (contract v1.6.0; CR-ML-1, CR-ML-2).

The table is keyed (h3, day, category, nature). ML labels SUM `n` over
`nature IN ('requete','plainte')` AND `category IN` the four label categories
(`config.WINTER_CATEGORIES`: sidewalk_slippery, roadway_slippery, snow_clearing, snow_dumping).
Since v1.6 the alley activities have their own categories (`snow_clearing_alley`,
`snow_dumping_alley`) and are excluded here, matching the CSV label of record.
Returns the same (h3, day, category, n) frame as `data_311.aggregate_report_cells`.

    uv run --extra db python -m winterpath_ml.report_cells_db --compare --database-url "$URL"
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import pandas as pd

from . import config, data_311

LABEL_NATURES = ("requete", "plainte")
LABEL_CATEGORIES = tuple(dict.fromkeys(config.WINTER_CATEGORIES.values()))
# v1.6 alley categories: not part of the label; used only to diagnose differences.
EXTRA_ALLEY_ACTIVITIES = {
    "Déneigement ruelle": "snow_clearing_alley",
    "Dépôt neige-ruelle": "snow_dumping_alley",
}

SQL = """
SELECT h3, day, category, SUM(n)::int AS n
  FROM wp.report_311_cell
 WHERE nature = ANY(%(natures)s)
   AND category = ANY(%(categories)s)
 GROUP BY h3, day, category
"""


def connect(url: str | None = None):
    """psycopg connection from a SQLAlchemy-style or plain libpq URL (optional `db` extra)."""
    import psycopg

    url = url or os.environ["DATABASE_URL"]
    return psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://", 1))


def read_report_cells(
    conn,
    natures: tuple[str, ...] = LABEL_NATURES,
    categories: tuple[str, ...] = LABEL_CATEGORIES,
) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(SQL, {"natures": list(natures), "categories": list(categories)})
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["h3", "day", "category", "n"])
    df["day"] = pd.to_datetime(df["day"])
    df["n"] = df["n"].astype(int)
    return df


def _cell_day(df: pd.DataFrame) -> pd.Series:
    return df.groupby(["h3", "day"])["n"].sum()


def compare(
    db: pd.DataFrame, raw: pd.DataFrame, panel: pd.DataFrame | None = None
) -> dict:
    """Compare DB aggregates with the CSV label of record, on days both sources cover.

    `raw` is `data_311.read_raw_311()` output. Separates three causes of difference:
    the alley categories (expected, CR-ML-2), and anything left over (snapshot differences or bugs).
    """
    csv_label = data_311.aggregate_report_cells(data_311.winter_reports(raw))
    alley = raw[
        raw["ACTI_NOM"].isin(list(EXTRA_ALLEY_ACTIVITIES))
        & raw["NATURE"].isin(config.REPORT_NATURES)
    ].copy()
    alley["category"] = alley["ACTI_NOM"].map(EXTRA_ALLEY_ACTIVITIES)
    csv_alley = data_311.aggregate_report_cells(alley)

    last = min(db["day"].max(), csv_label["day"].max())
    window = lambda d: d[d["day"] <= last]
    a = _cell_day(window(csv_label))
    a_plus = _cell_day(pd.concat([window(csv_label), window(csv_alley)]))
    b = _cell_day(window(db))

    def diff(x: pd.Series, y: pd.Series) -> dict:
        j = pd.concat([x.rename("x"), y.rename("y")], axis=1).fillna(0)
        d = j[j["x"] != j["y"]]
        pos_x, pos_y = j["x"] > 0, j["y"] > 0
        return {
            "cell_days_count_differs": len(d),
            "abs_count_diff": int((d["x"] - d["y"]).abs().sum()),
            "label_differs_cell_days": int((pos_x != pos_y).sum()),
        }

    out = {
        "common_window_end": str(last.date()),
        "db_total_n": int(b.sum()),
        "csv_label_total_n": int(a.sum()),
        "csv_alley_rows": len(
            alley[data_311.valid_location(alley) & alley["day"].notna()]
        ),
        "db_vs_csv_label": diff(b, a),
        "db_vs_csv_label_plus_alley": diff(b, a_plus),
    }
    if panel is not None:
        p = panel[["h3", "day", "label"]].copy()
        p["day"] = pd.to_datetime(p["day"])
        p = p.set_index(["h3", "day"])
        lab_db = (b.reindex(p.index).fillna(0) > 0).astype(int)
        flips = p["label"] != lab_db
        out["v2_panel_rows"] = len(p)
        out["v2_panel_label_flips"] = int(flips.sum())
        out["v2_panel_flips_0_to_1"] = int(((p["label"] == 0) & (lab_db == 1)).sum())
        out["v2_panel_flips_1_to_0"] = int(((p["label"] == 1) & (lab_db == 0)).sum())
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    ap.add_argument(
        "--compare",
        action="store_true",
        help="compare with the CSV label of record and the v2 panel",
    )
    a = ap.parse_args(argv)
    if not a.database_url:
        print("no database url", file=sys.stderr)
        return 2
    with connect(a.database_url) as conn:
        db = read_report_cells(conn)
    print(
        f"db rows (h3, day, category) with nature in {LABEL_NATURES}, category in {LABEL_CATEGORIES}: "
        f"{len(db)}, sum n = {int(db['n'].sum())}"
    )
    if a.compare:
        raw = data_311.read_raw_311(config.RAW_311_CSV)
        feat = config.ARTIFACT_DIR / "v2-8d19aa86" / "features.parquet"
        panel = (
            pd.read_parquet(feat, columns=["h3", "day", "label"])
            if feat.exists()
            else None
        )
        print(json.dumps(compare(db, raw, panel), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
