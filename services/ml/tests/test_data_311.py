import pandas as pd

from winterpath_ml import data_311


def _SYNTHETIC_raw():
    return pd.DataFrame(
        {
            "NATURE": [
                "Requete",
                "Information",
                "Requete",
                "Plainte",
                "Requete",
                "Requete",
            ],
            "ACTI_NOM": [
                "Trottoir glissant",
                "Trottoir glissant",
                "Nid de poule",
                "Opération déneigement",
                "Trottoir glissant",
                "Trottoir glissant",
            ],
            "TYPE_LIEU_INTERV": ["Adresse"] * 6,
            "ARRONDISSEMENT": ["SYNTH"] * 6,
            "ARRONDISSEMENT_GEO": ["SYNTH"] * 6,
            "LOC_ERREUR_GDT": ["0", "0", "0", "0", "1", "0"],
            "PROVENANCE_ORIGINALE": ["Téléphone"] * 6,
            "lon": [-73.5772, -73.5772, -73.5772, -73.5773, -73.5772, None],
            "lat": [45.5048, 45.5048, 45.5048, 45.5049, 45.5048, None],
            "day": pd.to_datetime(["2024-01-10"] * 6),
        }
    )


def test_winter_filter_and_aggregate_schema():
    w = data_311.winter_reports(_SYNTHETIC_raw())
    assert set(w["NATURE"]) <= {"Requete", "Plainte"}
    agg = data_311.aggregate_report_cells(w)
    assert list(agg.columns) == ["h3", "day", "category", "n"]  # == wp.report_311_cell
    # geocode-error row and missing-coordinate row are dropped; Information row is not a report
    assert agg["n"].sum() == 2
    assert set(agg["category"]) == {"slippery_sidewalk", "snow_clearing"}
    assert "lon" not in agg.columns and "lat" not in agg.columns
