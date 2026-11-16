"""Greater-Montréal region builds and the fixed-link report — offline.

Geometry is made-up squares in a fake place; no real data is implied. The only real values are
the Wave 1 island build's published checksums (hashes of inputs, not data), used to prove the
generalised builder computes the island's cache key and run checksum verbatim.
"""

import geopandas as gpd
import pytest
from shapely.geometry import LineString, box

from winterpath_ingestion.osm import island, links, region
from winterpath_ingestion.sources import sda

# Wave 1 island build (docs/agent-reports/data.md; data/processed/osm_island/manifest.json)
PBF_261108 = "76f100e41397bbc3428ed357b2c1f91d3f8d3f2663b335c34dfb3321e9614768"
BOUNDARIES = (
    "c2357160a8dce9039283cae02408cf48f02c20fd183fb75b93f80234555f70ef|"
    "687843fa0a55e555d8c94fc154c17d803feb36524ce603f58ac4b3ec70cd856d|v1"
)
ISLAND_CHECKSUM = "c5c9e2b3c0cdebce3c5af15e8178254b127a0a1e64b44e68925c6849f8231711"


def test_island_keys_are_the_wave1_strings():
    clip_name, checksum = region.run_keys(region.ISLAND, PBF_261108, BOUNDARIES, "")
    assert checksum == ISLAND_CHECKSUM
    assert clip_name.startswith("clip_island_") and len(clip_name) == len("clip_island_.json") + 16


def test_greater_keys_differ_from_island_and_between_stages():
    k1 = region.run_keys(region.STAGE1, PBF_261108, BOUNDARIES, "|sda:x|munis:65005,58227")
    k2 = region.run_keys(region.STAGE2, PBF_261108, BOUNDARIES, "|sda:x|munis:all")
    ki = region.run_keys(region.ISLAND, PBF_261108, BOUNDARIES, "")
    assert len({k1[1], k2[1], ki[1]}) == 3
    assert k1[0].startswith("clip_stage1_") and k2[0].startswith("clip_stage2_")


def test_region_specs():
    assert region.ISLAND.municipalities == () and region.ISLAND.out_name == "osm_island"
    assert set(region.STAGE1.municipalities) == {"65005", "58227"}  # Laval, Longueuil
    assert set(region.STAGE1.municipalities) < set(region.STAGE2.municipalities)
    assert region.STAGE1_LAVAL.municipalities == ("65005",)
    assert len({r.out_name for r in region.REGIONS.values()}) == len(region.REGIONS)
    assert set(region.STAGE2.municipalities) == set(sda.MUNICIPALITIES)


def _sda_layer(rename=None):
    rows = [
        ("65005", "Laval", "Laval", None, box(0, 1, 1, 2)),
        ("58227", "Longueuil", "Longueuil", "Agglomération de Longueuil", box(1, 0, 2, 1)),
        ("64008", "Terrebonne", "Les Moulins", None, box(0, 2, 1, 3)),
        ("60013", "Repentigny", "L'Assomption", None, box(1, 2, 2, 3)),
        ("58007", "Brossard", "Longueuil", "Agglomération de Longueuil", box(1, -1, 2, 0)),
        ("58033", "Boucherville", "Longueuil", "Agglomération de Longueuil", box(2, 0, 3, 1)),
        ("58012", "Saint-Lambert", "Longueuil", "Agglomération de Longueuil", box(2, -1, 3, 0)),
        ("87120", "Saint-Lambert", "Abitibi-Ouest", None, box(9, 9, 10, 10)),  # namesake
        ("66023", "Montréal", "Montréal", "Agglomération de Montréal", box(0, 0, 1, 1)),
        ("66142", "TNO aquatique de la MRC géographique de Montréal", "Montréal", None,
         box(0.9, 0.9, 1.1, 1.1)),
        ("66143", "TNO terrestre de la MRC géographique de Montréal", "Montréal", None,
         box(0.95, 0.95, 1.0, 1.0)),
    ]  # fmt: skip
    if rename:
        rows = [(c, rename.get(c, n), *rest) for c, n, *rest in rows]
    return gpd.GeoDataFrame(
        {
            "MUS_CO_GEO": [r[0] for r in rows],
            "MUS_NM_MUN": [r[1] for r in rows],
            "MUS_NM_MRC": [r[2] for r in rows],
            "MUS_NM_AGG": [r[3] for r in rows],
            "MUS_NM_REG": "x",
            "MUS_CO_VER": "V-test",
        },
        geometry=[r[4] for r in rows],
        crs="EPSG:4269",
    )


def test_sda_selects_by_code_not_name():
    out, water = sda.select(_sda_layer())
    assert dict(zip(out["code"], out["name"], strict=True)) == sda.MUNICIPALITIES
    assert "87120" not in set(out["code"])  # the other Saint-Lambert
    assert sorted(water["name"]) == sorted(sda.MRC_MONTREAL_WATER)


def test_sda_refuses_unexpected_names():
    with pytest.raises(ValueError, match="differ from expected"):
        sda.select(_sda_layer({"65005": "Somewhere else"}))


def test_component_anchor_union_keeps_unlinked_municipality_as_own_component():
    """Greater rule: a municipality network with no link to the island is kept (reported as a
    separate component), never joined by an invented edge."""
    main, muni = box(0, 0, 0.1, 0.1), box(0.2, 0, 0.3, 0.1)
    n = {1: (0.05, 0.05), 2: (0.06, 0.05), 3: (0.25, 0.05), 4: (0.26, 0.05), 5: (0.5, 0.5),
         6: (0.51, 0.5)}  # fmt: skip
    osm = {
        "elements": [
            *({"type": "node", "id": i, "lon": x, "lat": y} for i, (x, y) in n.items()),
            {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "footway"}},
            {"type": "way", "id": 11, "nodes": [3, 4], "tags": {"highway": "footway"}},
            {"type": "way", "id": 12, "nodes": [5, 6], "tags": {"highway": "footway"}},
        ]
    }
    out, st = island.filter_to_main_island(osm, main.union(muni))
    ways = {e["id"] for e in out["elements"] if e["type"] == "way"}
    assert ways == {10, 11}
    assert st["networks_dropped_not_connected_to_main_island"] == 1


def test_per_unit_largest_component_share():
    edges = gpd.GeoDataFrame(
        {"length_m": [100.0, 100.0, 50.0, 50.0], "component_id": [0, 0, 1, 1]},
        geometry=[
            LineString([(0.1, 0.1), (0.2, 0.2)]),
            LineString([(0.2, 0.2), (0.1, 0.1)]),
            LineString([(1.1, 0.1), (1.2, 0.2)]),
            LineString([(1.2, 0.2), (1.1, 0.1)]),
        ],
        crs="EPSG:4326",
    )
    nodes = gpd.GeoDataFrame(
        {"node_id": ["a", "b", "c", "d"], "component_id": [0, 0, 1, 1]},
        geometry=gpd.points_from_xy([0.1, 0.2, 1.1, 1.2], [0.1, 0.2, 0.1, 0.2]),
        crs="EPSG:4326",
    )
    limits = gpd.GeoDataFrame(
        {"NOM": ["A", "B"], "TYPE": ["t", "t"]}, geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)]
    ).set_crs("EPSG:4326")
    plain = island.per_unit(edges, nodes, limits)
    assert "largest_component_node_share" not in plain[0]  # island stats unchanged
    rows = {r["unit"]: r for r in island.per_unit(edges, nodes, limits, with_largest=True)}
    assert rows["A"]["largest_component_node_share"] == 1.0
    assert rows["B"]["largest_component_node_share"] == 0.0
    assert rows["B"]["km_in_largest_component"] == 0.0
    assert rows["outside agglomeration limits"]["largest_component_node_share"] is None


# ------------------------------------------------------------------------------ fixed links
def test_classify_uses_graph_policy():
    assert links.classify({"highway": "motorway"})["foot_legal"] is False
    assert links.classify({"highway": "cycleway", "foot": "designated"})["foot_legal"] is True
    assert links.classify({"highway": "cycleway"})["foot_legal"] is False  # no explicit foot
    assert links.classify({"highway": "primary", "foot": "use_sidepath"})["reason"] == (
        "foot=use_sidepath"
    )
    assert links.classify({"railway": "rail"}) == {
        "kind": "railway=rail",
        "foot_legal": False,
        "reason": "not a road",
    }


def test_conditional_tags_are_copied_verbatim():
    t = {
        "highway": "cycleway",
        "access:conditional": "no @ (Nov 15-Apr 15)",
        "winter_service": "no",
        "opening_hours": "06:00-22:00",
        "name": "x",
    }
    assert links.conditional_tags(t) == {
        "access:conditional": "no @ (Nov 15-Apr 15)",
        "opening_hours": "06:00-22:00",
        "winter_service": "no",
    }


def test_structures_groups_bridge_ways_and_skips_internal_boundary():
    mtl_side, others = links.sides(_sda_layer())
    near = others[others["MUS_NM_MUN"].isin(["Laval"])].reset_index(drop=True)
    ways = {
        # bridge deck in two ways, Montréal (y<1) to Laval (y>1)
        1: {"tags": {"highway": "footway", "bridge": "yes"}, "nodes": [10, 11]},
        2: {"tags": {"highway": "footway", "bridge": "yes", "name": "B"}, "nodes": [11, 12]},
        # motorway bridge with no foot access
        3: {"tags": {"highway": "motorway", "bridge": "yes"}, "nodes": [20, 21]},
        # street at the Laval end: not a structure, must not be swallowed
        4: {"tags": {"highway": "residential"}, "nodes": [12, 13]},
        # metro tunnel crossing, touching a station footway in a tunnel: different mode
        5: {"tags": {"railway": "subway", "tunnel": "yes"}, "nodes": [30, 31]},
        6: {"tags": {"highway": "footway", "tunnel": "yes"}, "nodes": [31, 32]},
    }
    lines = {
        1: [(0.5, 0.8), (0.5, 0.99)],
        2: [(0.5, 0.99), (0.5, 1.2)],
        3: [(0.7, 0.8), (0.7, 1.2)],
        4: [(0.5, 1.2), (0.5, 1.5)],
        5: [(0.3, 0.8), (0.3, 1.2)],
        6: [(0.3, 1.2), (0.35, 1.3)],
    }
    for k, w in ways.items():
        w["line"] = LineString(lines[k])
    res = {"ways": ways, "crossing": [2, 3, 5], "near": near, "mtl": mtl_side}
    st = links.structures(res)
    assert len(st) == 3
    metro = next(s for s in st if s["members"][0]["kind"] == "railway=subway")
    assert [m["osm_way_id"] for m in metro["members"]] == [5] and not metro["foot_legal_ways"]
    foot = next(s for s in st if s["foot_legal_ways"])
    assert foot["neighbours"] == ["Laval"] and sorted(foot["foot_legal_ways"]) == [1, 2]
    assert {m["osm_way_id"] for m in foot["members"]} == {1, 2}
    motor = next(s for s in st if s["members"][0]["kind"] == "highway=motorway")
    assert motor["members"][0]["reason"] == "highway=motorway"
