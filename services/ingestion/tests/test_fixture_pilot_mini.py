"""Checks on the committed data/fixtures/pilot_mini export (real OSM)."""

import json

import networkx as nx
import pytest

from .conftest import REPO

D = REPO / "data" / "fixtures" / "pilot_mini"
pytestmark = pytest.mark.skipif(not D.exists(), reason="pilot_mini not exported yet")


def _fc(name):
    return json.loads((D / name).read_text())


def test_metadata_and_attribution():
    meta = _fc("metadata.json")
    assert meta["simulated"] is False
    assert meta["osm_snapshot"]
    assert len(meta["bbox"]) == 4
    att = (D / "ATTRIBUTION.md").read_text()
    assert "OpenStreetMap contributors" in att and "ODbL" in att


def test_edge_limits_and_ids():
    edges = _fc("edges.geojson")["features"]
    nodes = {f["id"] for f in _fc("nodes.geojson")["features"]}
    assert 0 < len(edges) <= 200
    ids = [f["id"] for f in edges]
    assert len(ids) == len(set(ids))
    g = nx.Graph()
    for f in edges:
        p = f["properties"]
        assert f["id"] == p["edge_id"]
        assert p["from_node_id"] in nodes and p["to_node_id"] in nodes
        assert p["length_m"] > 0
        assert p["foot_access"] not in ("no", "private")
        assert f["geometry"]["type"] == "LineString"
        lon, lat = f["geometry"]["coordinates"][0]
        assert -74 < lon < -73 and 45 < lat < 46  # [lon, lat] order
        g.add_edge(p["from_node_id"], p["to_node_id"])
    assert nx.is_connected(g)
