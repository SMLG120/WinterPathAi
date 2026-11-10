"""Topology tests on a small REAL OSM extract (tests/fixtures/overpass_mcgill_small.json)."""

import copy
import random
import re

import networkx as nx
from pyproj import Transformer
from shapely.geometry import LineString

from winterpath_ingestion.osm.graph import INCLUDED_HIGHWAYS, build_graph

EDGE_ID = re.compile(r"^(osm:n\d+|syn:[0-9a-f]{16})>(osm:n\d+|syn:[0-9a-f]{16}):\d+$")


def test_edge_ids_stable_across_two_builds(overpass_small, built):
    again = build_graph(overpass_small, snapshot="x")
    assert list(again.edges["edge_id"]) == list(built.edges["edge_id"])
    assert list(again.nodes["node_id"]) == list(built.nodes["node_id"])


def test_edge_ids_independent_of_element_order(overpass_small, built):
    shuffled = copy.deepcopy(overpass_small)
    random.Random(42).shuffle(shuffled["elements"])
    again = build_graph(shuffled)
    assert sorted(again.edges["edge_id"]) == sorted(built.edges["edge_id"])
    a = again.edges.set_index("edge_id")["osm_way_id"].sort_index()
    b = built.edges.set_index("edge_id")["osm_way_id"].sort_index()
    assert (a == b).all()


def test_no_prohibited_foot_access(built):
    assert not built.edges["foot_access"].isin(["no", "private"]).any()


def test_extract_actually_contained_prohibited_ways(overpass_small, built):
    """Guard: the exclusion test above is meaningful only if such ways exist in the input."""
    ways = [e for e in overpass_small["elements"] if e["type"] == "way"]
    prohibited = {w["id"] for w in ways if w.get("tags", {}).get("foot") == "no"}
    assert prohibited
    assert not set(built.edges["osm_way_id"]) & prohibited


def test_only_included_highway_types(built):
    assert set(built.edges["highway"]) <= INCLUDED_HIGHWAYS


def test_lengths_positive_and_match_32188(built):
    tr = Transformer.from_crs("EPSG:4326", "EPSG:32188", always_xy=True)
    assert (built.edges["length_m"] > 0).all()
    for geom, length in zip(built.edges.geometry, built.edges["length_m"], strict=True):
        xs, ys = tr.transform(*zip(*geom.coords, strict=True))
        recomputed = LineString(list(zip(xs, ys, strict=True))).length
        assert abs(recomputed - length) <= 0.01 * recomputed


def test_no_duplicate_ids(built):
    assert built.edges["edge_id"].is_unique
    assert built.nodes["node_id"].is_unique


def test_edge_id_format_and_endpoints(built):
    nodes = set(built.nodes["node_id"])
    for r in built.edges.itertuples():
        assert EDGE_ID.match(r.edge_id)
        assert r.edge_id.startswith(f"{r.from_node_id}>{r.to_node_id}:")
        assert r.from_node_id in nodes and r.to_node_id in nodes


def test_geometry_endpoints_match_nodes(built):
    pos = dict(zip(built.nodes["node_id"], built.nodes.geometry, strict=True))
    for r in built.edges.itertuples():
        assert r.geometry.coords[0] == (pos[r.from_node_id].x, pos[r.from_node_id].y)
        assert r.geometry.coords[-1] == (pos[r.to_node_id].x, pos[r.to_node_id].y)


def test_every_edge_has_reverse_twin(built):
    fwd = {(r.from_node_id, r.to_node_id, r.osm_way_id) for r in built.edges.itertuples()}
    for u, v, w in fwd:
        assert (v, u, w) in fwd


def test_crossing_nodes_carry_metadata(overpass_small, built):
    tagged = {
        f"osm:n{e['id']}"
        for e in overpass_small["elements"]
        if e["type"] == "node" and e.get("tags", {}).get("highway") == "crossing"
    }
    in_graph = built.nodes[built.nodes["node_id"].isin(tagged)]
    assert len(in_graph) > 0
    assert (in_graph["kind"] == "crossing").all()
    assert in_graph["crossing_type"].notna().all()


def test_crossing_edges_have_crossing_info(built):
    cr = built.edges[built.edges["edge_kind"] == "crossing"]
    assert len(cr) > 0
    for c in cr["crossing"]:
        assert c["type"] in {"marked", "traffic_signals", "unmarked", "uncontrolled", "unknown"}
        assert c["kerb"] in {"lowered", "flush", "raised", "unknown"}
    assert built.edges.loc[built.edges["edge_kind"] != "crossing", "crossing"].isna().all()


def test_steps_never_step_free(built):
    assert (built.edges.loc[built.edges["highway"] == "steps", "step_free"] == False).all()  # noqa: E712


def test_components_consistent(built):
    g = nx.Graph()
    g.add_edges_from(zip(built.edges["from_node_id"], built.edges["to_node_id"], strict=True))
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    assert built.stats["components"] == len(comps)
    largest = built.edges[built.edges["component_id"] == 0]
    assert set(largest["from_node_id"]) == comps[0]


def test_connectivity_from_osm_topology_only(built):
    assert set(built.edges["connectivity_confidence"]) == {"high"}
    assert not built.nodes["node_id"].str.startswith("syn:").any()


def test_gaps_reported_not_repaired(built):
    for gap in built.gaps:
        if gap["type"] == "near_miss_dangling_endpoint":
            assert gap["distance_m"] <= 2.0
            assert gap["node_id"] not in gap["near_edge_id"].split(">")[0]
