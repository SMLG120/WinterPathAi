"""Nature-summing reader for wp.report_311_cell (CR-ML-1). DB-free unless WP_ML_TEST_REPORT_DB_URL is set."""

import os
from datetime import date

import pandas as pd
import pytest

from winterpath_ml import report_cells_db as rdb


class _FakeCursor:
    def __init__(self, rows):
        self.rows, self.sql, self.params = rows, None, None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self.sql, self.params = sql, params

    def fetchall(self):
        return self.rows


class _FakeConn:
    def __init__(self, rows):
        self.cur = _FakeCursor(rows)

    def cursor(self):
        return self.cur


def test_reader_filters_label_natures_and_sums():
    conn = _FakeConn([("892baa441b3ffff", date(2024, 1, 10), "sidewalk_slippery", 3)])
    df = rdb.read_report_cells(conn)
    assert conn.cur.params == {"natures": ["requete", "plainte"]}
    assert (
        "SUM(n)" in conn.cur.sql
        and "nature = ANY" in conn.cur.sql
        and "GROUP BY h3, day, category" in conn.cur.sql
    )
    assert list(df.columns) == ["h3", "day", "category", "n"] and df["n"].iloc[0] == 3


def _SYNTHETIC_raw():
    acts = [
        "Trottoir glissant",
        "Dépôt neige-ruelle",
        "Trottoir glissant",
        "Trottoir glissant",
    ]
    return pd.DataFrame(
        {
            "NATURE": ["Requete", "Requete", "Information", "Requete"],
            "ACTI_NOM": acts,
            "TYPE_LIEU_INTERV": "Adresse",
            "ARRONDISSEMENT": "SYNTH",
            "ARRONDISSEMENT_GEO": "SYNTH",
            "LOC_ERREUR_GDT": "0",
            "PROVENANCE_ORIGINALE": "Téléphone",
            "lon": [-73.5772, -73.6000, -73.5772, -73.5772],
            "lat": [45.5048, 45.5300, 45.5048, 45.5048],
            "day": pd.to_datetime(
                ["2024-01-10", "2024-01-10", "2024-01-10", "2024-01-11"]
            ),
        }
    )


def test_compare_attributes_difference_to_alley_categories():
    raw = _SYNTHETIC_raw()
    from winterpath_ml import data_311

    label = data_311.aggregate_report_cells(data_311.winter_reports(raw))
    alley_cell = data_311.to_cells(pd.Series([-73.6000]), pd.Series([45.5300]))[0]
    db = pd.concat(
        [
            label,
            pd.DataFrame(
                {
                    "h3": [alley_cell],
                    "day": [pd.Timestamp("2024-01-10")],
                    "category": ["snow_dumping"],
                    "n": [1],
                }
            ),
        ]
    )
    r = rdb.compare(db, raw)
    assert r["db_vs_csv_label"] == {
        "cell_days_count_differs": 1,
        "abs_count_diff": 1,
        "label_differs_cell_days": 1,
    }
    assert r["db_vs_csv_label_plus_alley"]["cell_days_count_differs"] == 0


@pytest.mark.skipif(
    not os.environ.get("WP_ML_TEST_REPORT_DB_URL"), reason="live wp_data not configured"
)
def test_live_db_reader_shape():
    with rdb.connect(os.environ["WP_ML_TEST_REPORT_DB_URL"]) as conn:
        df = rdb.read_report_cells(conn)
    assert len(df) > 0 and set(df["category"]) <= {
        "sidewalk_slippery",
        "roadway_slippery",
        "snow_clearing",
        "snow_dumping",
    }
