"""Source-adapter unit tests. All rows below are SYNTHETIC, written to exercise the mapping
rules; they are not real records."""

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Polygon

from winterpath_ingestion.sources import eccc, entraves, r311, voirie


# ---------------------------------------------------------------- Entraves
def _main(i, lon=-73.575, lat=45.505):
    return {
        "id": i,
        "longitude": str(lon),
        "latitude": str(lat),
        "currentstatus": "Permis émis",
        "duration_start_date": "2026-11-01T00:00:00Z",
        "duration_end_date": "2026-12-01T00:00:00Z",
        "permit_permit_id": "SYN",
        "reason_category": "SYN",
    }


def _imp(i, side, back="Aucun impact / non applicable"):
    return {
        "id_request": i,
        "sidewalk_blockedtype": side,
        "backsidewalk_blockedtype": back,
        "streetid": "",
        "name": "",
        "fromname": "",
        "toname": "",
        "length": "",
    }


def test_blocks_passage_only_when_barred():
    main = [_main("a"), _main("b"), _main("c"), _main("d"), _main("e")]
    imps = [
        _imp("a", "Barré"),
        _imp("b", "Obstrué (un passage piéton de 1,5 m est conservé)"),
        _imp("c", "Aucun impact / non applicable"),
        _imp("d", "Valeur inconnue"),  # unknown value → null, never True
        # e: no impact rows → null
    ]
    gdf, unmapped = entraves.build_closures(main, imps)
    bp = dict(zip(gdf["closure_id"], gdf["blocks_passage"], strict=True))
    assert bp == {
        "entrave:a": True,
        "entrave:b": False,
        "entrave:c": False,
        "entrave:d": None,
        "entrave:e": None,
    }
    assert unmapped == {"sidewalk_blockedtype='Valeur inconnue'": 1}
    assert set(gdf["evidence_state"]) == {"confirmed"}


def test_closures_outside_bbox_dropped():
    gdf, _ = entraves.build_closures([_main("x", lon=-73.70, lat=45.60)], [])
    assert len(gdf) == 0


def test_aggregate_rule():
    assert entraves.aggregate([False, True]) is True
    assert entraves.aggregate([False, None]) is None
    assert entraves.aggregate([]) is None


# ---------------------------------------------------------------- 311
def _row(acti, lat="45.5", lon="-73.57", err="0", date="2025-01-15T10:00:00"):
    return {
        "ACTI_NOM": acti,
        "LOC_LAT": lat,
        "LOC_LONG": lon,
        "LOC_ERREUR_GDT": err,
        "DDS_DATE_CREATION": date,
    }


def test_311_filters_and_aggregates():
    rows = [
        _row("Trottoir glissant"),
        _row("Trottoir glissant"),
        _row("Trottoir glissant", err="1"),  # borough-office location → dropped
        _row("Trottoir glissant", lat="", lon=""),
        _row("Nid de poule"),  # not winter
        _row("Opération déneigement", date="2025-01-16T01:00:00"),
    ]
    counts, reasons = r311.aggregate_rows(rows)
    assert reasons == {
        "ok": 3,
        "located_at_borough_office": 1,
        "no_location": 1,
        "not_winter_category": 1,
    }
    assert sum(counts.values()) == 3
    keys = sorted(counts)
    assert all(len(k[0]) == 15 for k in keys)  # H3 res-9 cell string
    assert {(k[1], k[2]) for k in keys} == {
        ("2025-01-15", "sidewalk_slippery"),
        ("2025-01-16", "snow_clearing"),
    }


# ---------------------------------------------------------------- ECCC
def test_swob_sentinels_are_null_not_zero():
    r = eccc.swob_row(
        {
            "msc_id-value": "7025251",
            "date_tm-value": "2026-01-01T00:00:00.000Z",
            "air_temp": -12.0,
            "snw_dpth": -1,
            "pcpn_amt_pst1hr": None,
        }
    )
    assert r["snow_depth_cm"] is None and r["precip_mm"] is None
    assert r["temperature_c"] == -12.0 and r["observed_at"] == "2026-01-01T00:00:00Z"


def test_climate_hourly_row():
    r = eccc.climate_hourly_row(
        {
            "CLIMATE_IDENTIFIER": "7025251",
            "UTC_DATE": "2026-01-15T05:00:00",
            "TEMP": 2,
            "PRECIP_AMOUNT": None,
            "WIND_SPEED": 12,
        }
    )
    assert r["observed_at"] == "2026-01-15T05:00:00Z"
    assert r["precip_mm"] is None and r["snow_depth_cm"] is None and r["wind_kmh"] == 12.0


def test_climate_daily_row_keeps_nulls():
    r = eccc.climate_daily_row(
        {
            "CLIMATE_IDENTIFIER": "7025251",
            "LOCAL_DATE": "2025-01-01 00:00:00",
            "TOTAL_PRECIPITATION": 6.8,
            "TOTAL_SNOW": 5.6,
            "SNOW_ON_GROUND": None,
            "MIN_TEMPERATURE": 0.3,
            "MAX_TEMPERATURE": 1.6,
        }
    )
    assert r["day"] == "2025-01-01" and r["source_collection"] == "climate-daily"
    assert r["snow_on_ground_cm"] is None  # missing stays NULL, never 0
    assert r["total_precip_mm"] == 6.8 and r["total_snow_cm"] == 5.6


def test_dedupe_prefers_climate_hourly():
    a = {"station_id": "s", "observed_at": "t", "source_collection": "swob-realtime"}
    b = {"station_id": "s", "observed_at": "t", "source_collection": "climate-hourly"}
    assert eccc.dedupe([a, b]) == [b] and eccc.dedupe([b, a]) == [b]


# ---------------------------------------------------------------- Voirie
def test_voirie_match_is_enrichment_by_overlap():
    # synthetic: a 20 m sidewalk polygon in EPSG:32188 near McGill, three edges
    x0, y0 = 299000.0, 5040000.0
    poly = Polygon([(x0, y0), (x0 + 20, y0), (x0 + 20, y0 + 3), (x0, y0 + 3)])
    polys = gpd.GeoDataFrame(
        {"polygon_id": ["trottoir:1"]}, geometry=[poly], crs="EPSG:32188"
    ).to_crs("EPSG:4326")
    lines = [
        LineString([(x0 + 1, y0 + 1.5), (x0 + 19, y0 + 1.5)]),  # inside
        LineString([(x0 + 15, y0 + 1.5), (x0 + 45, y0 + 1.5)]),  # ~20% inside → no
        LineString([(x0, y0 + 50), (x0 + 20, y0 + 50)]),  # far
    ]
    edges = gpd.GeoDataFrame(
        {"edge_id": ["a", "b", "c"], "edge_kind": ["sidewalk"] * 3},
        geometry=lines,
        crs="EPSG:32188",
    ).to_crs("EPSG:4326")
    m = voirie.match_edges(edges, polys)
    assert m == {"a": ["trottoir:1"], "b": [], "c": []}
    assert voirie.match_rates(edges, m)["sidewalk"]["matched"] == 1


def test_voirie_refuses_missing_crs():
    raw = gpd.GeoDataFrame(
        {"ID_VOI_ILOT": [1], "TYPEILOT_REF": ["x"], "MATERIAUILOT_REF": ["y"]},
        geometry=[Polygon([(0, 0), (1, 0), (1, 1)])],
    )
    with pytest.raises(ValueError):
        voirie.normalise(raw, "ilot")
