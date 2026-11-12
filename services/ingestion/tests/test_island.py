"""Island area rules (WinterPath 2.0 Wave 1) — offline, synthetic geometry in a fake place.

Coordinates are made-up squares; no real data is implied.
"""

import geopandas as gpd
import pandas as pd
import pytest
import shapely
from shapely.geometry import LineString, Point, box

from winterpath_ingestion.osm import geofabrik, island
from winterpath_ingestion.sources import boundaries

MAIN = box(0.0, 0.0, 0.10, 0.10)  # "main island"
OTHER = box(0.12, 0.0, 0.14, 0.02)  # bridged island
LONE = box(0.20, 0.0, 0.21, 0.01)  # island with no mapped link


def _archipel():
    return gpd.GeoDataFrame(
        geometry=[shapely.MultiPolygon([MAIN, OTHER, LONE])], crs="EPSG:4326"
    ).to_crs("EPSG:2950")


def test_islands_largest_is_main():
    isl = boundaries.islands_from_archipel(_archipel())
    assert list(isl["island_id"]) == ["isl-0000", "isl-0001", "isl-0002"]
    assert list(isl["is_main_island"]) == [True, False, False]
    assert isl.area_km2.iloc[0] > isl.area_km2.iloc[1] > isl.area_km2.iloc[2]
    assert isl.geometry.iloc[0].buffer(1e-6).contains(MAIN.buffer(-1e-6))


def test_build_clips_units_to_land_and_flags_other_islands():
    limits = gpd.GeoDataFrame(
        {
            "NOM": ["West", "East", "Water"],
            "TYPE": ["Arrondissement", "Ville liée", "Ville liée"],
            "CODEMAMH": ["A", "B", "C"],
        },
        geometry=[box(-0.05, -0.05, 0.05, 0.15), box(0.05, -0.05, 0.16, 0.15), box(0.3, 0, 0.4, 1)],
        crs="EPSG:4326",
    )
    res = boundaries.build(limits, _archipel())
    u = res["units"]
    west = u[(u.unit_name == "West") & (u.land == "main_island")].geometry.iloc[0]
    assert west.bounds == pytest.approx((0.0, 0.0, 0.05, 0.10), abs=1e-6)  # water clipped off
    assert set(u[u.land == "other_islands"].unit_name) == {"East"}
    st = res["stats"]
    assert st["units_without_main_island_land"] == ["Water"]
    assert st["admin_units_by_type"] == {"Arrondissement": 1, "Ville liée": 2}


def test_area_predicate_segment_semantics():
    keep = geofabrik.area_predicate(MAIN)
    assert keep([(0.05, 0.05), (0.06, 0.06)])  # inside
    assert keep([(-0.01, 0.05), (0.11, 0.05)])  # crosses, no vertex inside
    assert not keep([(0.2, 0.2), (0.3, 0.3)])
    assert keep([(0.05, 0.05)])  # single node inside


def _osm():
    n = {
        1: (0.05, 0.05),
        2: (0.09, 0.01),  # main
        3: (0.13, 0.01),  # other island, reached by bridge 2-3
        4: (0.135, 0.015),
        5: (0.205, 0.005),  # lone island
        6: (0.206, 0.006),
        7: (0.125, 0.012),
        8: (0.13, 0.015),  # other island, separate net
    }
    nodes = [{"type": "node", "id": i, "lon": x, "lat": y} for i, (x, y) in n.items()]
    ways = [
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "footway"}},
        {"type": "way", "id": 11, "nodes": [2, 3], "tags": {"highway": "footway", "bridge": "yes"}},
        {"type": "way", "id": 12, "nodes": [3, 4], "tags": {"highway": "residential"}},
        {"type": "way", "id": 13, "nodes": [5, 6], "tags": {"highway": "footway"}},
        {"type": "way", "id": 14, "nodes": [7, 8], "tags": {"highway": "footway"}},
        {"type": "way", "id": 15, "nodes": [5, 6], "tags": {"highway": "footway", "foot": "no"}},
    ]
    return {"elements": [*nodes, *ways]}


def test_component_rule_keeps_bridged_island_drops_isolated():
    out, st = island.filter_to_main_island(_osm(), MAIN)
    way_ids = {e["id"] for e in out["elements"] if e["type"] == "way"}
    assert way_ids == {10, 11, 12, 15}  # 13, 14 dropped; 15 kept only to be counted as excluded
    assert st["ways_dropped_not_connected_to_main_island"] == 2
    assert st["networks_dropped_not_connected_to_main_island"] == 2


def test_label_nodes_never_labels_off_land_as_island():
    isl = boundaries.islands_from_archipel(_archipel())
    nodes = gpd.GeoDataFrame(
        {"node_id": ["a", "b", "c"]},
        geometry=[Point(0.05, 0.05), Point(0.13, 0.01), Point(0.11, 0.01)],  # c: over water
        crs="EPSG:4326",
    )
    lab = island.label_nodes(nodes, isl)
    assert list(lab["land"]) == ["main_island", "other_island", "outside_agglomeration_land"]
    assert lab["island_id"].iloc[1] == "isl-0001" and pd.isna(lab["island_id"].iloc[2])


def test_bbox_clip_unchanged_semantics():
    """The pilot bbox clip still uses the bbox predicate (edge IDs must not move)."""
    bbox = (0.0, 0.0, 0.1, 0.1)
    coords = [(-0.01, 0.05), (0.11, 0.05)]
    assert geofabrik.way_intersects_bbox(coords, bbox)
    assert LineString(coords).intersects(box(*bbox))


def test_entraves_keep_predicate_overrides_pilot_bbox():
    """region=island: closures kept by an area predicate (agglomeration land), not the bbox."""
    from winterpath_ingestion.sources import entraves

    main = [
        {"id": "1", "longitude": "0.05", "latitude": "0.05", "currentstatus": "Permis émis"},
        {
            "id": "2",
            "longitude": "0.11",
            "latitude": "0.01",
            "currentstatus": "Permis émis",
        },  # water
        {"id": "3", "longitude": "x", "latitude": "y"},
    ]
    base = {"duration_start_date": "", "duration_end_date": ""}
    main = [{**base, **m} for m in main]
    land = shapely.MultiPolygon([MAIN, OTHER])
    shapely.prepare(land)
    got, unmapped = entraves.build_closures(
        main, [], keep=lambda lon, lat: bool(shapely.contains_xy(land, lon, lat))
    )
    assert list(got["closure_id"]) == ["entrave:1"]
    assert unmapped["no_coordinates"] == 1
    none_in_pilot, _ = entraves.build_closures(main, [])  # synthetic coords are outside the pilot
    assert len(none_in_pilot) == 0


def test_region_validation():
    from winterpath_ingestion.config import Settings
    from winterpath_ingestion.sources import entraves, voirie

    s = Settings(data_dir=__import__("pathlib").Path("/nonexistent"), user_agent="t")
    for mod in (entraves, voirie):
        with pytest.raises(ValueError):
            mod.run(s, region="laval")
