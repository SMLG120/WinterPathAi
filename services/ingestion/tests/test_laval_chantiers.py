"""Laval chantiers adapter. Fixture = 4 real rows (CC BY 4.0, Ville de Laval, 2026-11-17 file);
other cases are synthetic."""

import json
from pathlib import Path

import pandas as pd
import pytest

from winterpath_ingestion.sources import laval_chantiers as lc
from winterpath_ingestion.sources.registry import SOURCES

FIX = Path(__file__).parent / "fixtures" / "laval_chantiers_sample.geojson"


def _feats():
    return json.loads(FIX.read_text(encoding="utf-8"))["features"]


def _syn(
    statut="Existant", entrave="Rue barrée", d0="11/01/2026 00:00:00", d1="12/01/2026 00:00:00"
):
    return {
        "type": "Feature",
        "properties": {"STATUT": statut, "ENTRAVE": entrave, "DATE_DEBUT": d0, "DATE_FIN": d1},
        "geometry": {"type": "LineString", "coordinates": [[-73.7, 45.55], [-73.71, 45.56]]},
    }


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("Existant", "permit_issued"),
        ("Abandonné", "unknown"),  # not read as cancelled/completed
        ("Proposé", "unknown"),
        ("", "unknown"),
        (None, "unknown"),
        ("Autre", "unknown"),
    ],
)
def test_status_mapping(raw, want):
    assert lc.map_status(raw) == want
    assert want in lc.CLOSURE_STATUS_VALUES


@pytest.mark.parametrize(
    "entrave", ["Rue barrée", "Fermeture complète", "Trottoir", "Partielle", "", None]
)
def test_blocks_passage_never_inferred(entrave):
    assert lc.map_blocks_passage({"ENTRAVE": entrave}) is None


def test_dates_are_montreal_local():
    assert lc.parse_date("11/01/2026 00:00:00") == "2026-11-01T00:00:00-04:00"  # EDT
    assert lc.parse_date("12/01/2026 07:00:00") == "2026-12-01T07:00:00-05:00"  # EST
    assert lc.parse_date("") is None
    assert lc.parse_date(None) is None
    assert lc.parse_date("garbage") is None
    assert lc.parse_date("07/26/0205 00:00:00") is None  # implausible year, not invented


def test_ids_prefix_stable_and_duplicates_collapsed():
    a, b = _syn(), _syn(statut="Proposé")
    assert lc.closure_id(a).startswith("laval:") and lc.closure_id(a) == lc.closure_id(_syn())
    assert lc.closure_id(a) != lc.closure_id(b)
    gdf, st = lc.build_closures([a, _syn(), b])
    assert len(gdf) == 2 and st["duplicate_features_collapsed"] == 1


def test_build_rules_on_fixture():
    gdf, st = lc.build_closures(_feats())
    assert len(gdf) == 4
    assert set(gdf["evidence_state"]) == {"confirmed"}
    assert all(c.startswith("laval:") for c in gdf["closure_id"])
    assert gdf["blocks_passage"].isna().all()  # no pedestrian field → unknown for every row
    assert set(gdf["status"]) <= set(lc.CLOSURE_STATUS_VALUES)
    assert (
        gdf["attrs"].map(lambda a: a["currentstatus"]) == gdf["attrs"].map(lambda a: a["STATUT"])
    ).all()
    assert "STATUT='Abandonné'" in st or "STATUT='Proposé'" in st


def test_missing_dates_are_null_and_flags():
    gdf, _ = lc.build_closures(
        [_syn(d0="", d1=""), _syn(d0="12/01/2026 00:00:00", d1="11/01/2026 00:00:00")]
    )
    rows = {r.closure_id: r for r in gdf.itertuples()}
    empty = next(r for r in rows.values() if pd.isna(r.valid_from))
    assert pd.isna(empty.valid_to)
    rev = next(r for r in rows.values() if pd.notna(r.valid_from))
    assert "end_before_start" in rev.attrs["date_flags"]


def test_outside_laval_and_no_geometry_dropped():
    far = _syn()
    far["geometry"]["coordinates"] = [[-73.2, 45.3], [-73.19, 45.31]]  # south shore
    nog = _syn()
    nog["geometry"] = None
    gdf, st = lc.build_closures([far, nog])
    assert len(gdf) == 0 and st["no_geometry"] == 1 and st["outside_region"] == 1


def test_registry_entry():
    s = next(x for x in SOURCES if x["source_id"] == "laval-chantiers")
    assert s["license"] == "CC BY 4.0" and "Ville de Laval" in s["attribution"]


@pytest.mark.parametrize(
    ("entrave", "expected"),
    [
        ("Trottoir", "Trottoir"),
        (" Trottoir ", "Trottoir"),
        ("Partielle", None),
        ("Rue barrée", None),
        ("Hors chaussée", None),
        ("", None),
        (None, None),
    ],
)
def test_sidewalk_blockedtype_only_from_explicit_entrave(entrave, expected):
    p = {"ENTRAVE": entrave}
    assert lc.map_sidewalk_blockedtype(p) == expected
    assert lc.map_blocks_passage(p) is None  # sidewalk obstructed != passage blocked


# --- code review PR #3 -------------------------------------------------------------------------


def test_registry_entry_disabled_until_loaded():
    """upsert_sources writes every registry row on each load: Laval must not show as active."""
    s = next(x for x in SOURCES if x["source_id"] == "laval-chantiers")
    assert s["status"] == "disabled"


def test_far_future_year_is_implausible():
    assert lc.parse_date("07/26/2205 00:00:00") is None
    assert lc.parse_date("07/26/2100 00:00:00") is not None


def test_midnight_end_is_end_of_that_day():
    # date only → next local midnight; across the 2026-11-01 DST change the offset follows
    assert lc.parse_end("11/01/2026 00:00:00") == ("2026-11-02T00:00:00-05:00", True)
    assert lc.parse_end("12/01/2026 17:00:00") == ("2026-12-01T17:00:00-05:00", False)
    assert lc.parse_end("") == (None, False)
    gdf, _ = lc.build_closures([_syn(d0="11/20/2026 00:00:00", d1="12/01/2026 00:00:00")])
    r = gdf.iloc[0]
    assert r["valid_to"] == "2026-12-02T00:00:00-05:00"
    assert "DATE_FIN_date_only_end_of_day" in r["attrs"]["date_flags"]


def test_same_day_permit_is_not_end_before_start():
    gdf, _ = lc.build_closures([_syn(d0="12/01/2026 00:00:00", d1="12/01/2026 00:00:00")])
    assert "end_before_start" not in gdf.iloc[0]["attrs"]["date_flags"]


def test_empty_output_has_the_normal_columns():
    full, _ = lc.build_closures([_syn()])
    far = _syn()
    far["geometry"]["coordinates"] = [[-73.2, 45.3], [-73.19, 45.31]]
    empty, _ = lc.build_closures([far])
    assert list(empty.columns) == list(full.columns) == list(lc.COLUMNS)


def test_run_checksum_includes_mapping_version(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from winterpath_ingestion.config import Settings

    seen = []
    monkeypatch.setattr(
        lc,
        "download",
        lambda *a, **k: SimpleNamespace(path=tmp_path / "x", sha256="ab", fetched_at="t"),
    )
    monkeypatch.setattr(
        lc, "run_atomic", lambda name, d, checksum, build, force: seen.append(checksum)
    )
    s = Settings(data_dir=tmp_path, user_agent="test")
    lc.run(s)
    monkeypatch.setattr(lc, "MAPPING_VERSION", "laval-chantiers-vX")
    lc.run(s)
    assert seen[0] != seen[1]
