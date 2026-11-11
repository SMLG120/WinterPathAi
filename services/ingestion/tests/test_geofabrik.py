"""Geofabrik PBF clip (contract v1.5.0) — offline. The PBF is written here from the committed real
OSM test extract (tests/fixtures/overpass_mcgill_small.json), so no network is needed."""

import osmium
import pytest

from winterpath_ingestion.osm import geofabrik
from winterpath_ingestion.osm.graph import build_graph

TS = "2026-11-08T21:21:00Z"


def _write_pbf(path, osm, extra_ways=()):
    h = osmium.io.Header()
    h.set("osmosis_replication_timestamp", TS)
    w = osmium.SimpleWriter(str(path), header=h)
    try:
        for e in sorted(osm["elements"], key=lambda e: e["id"]):
            if e["type"] == "node":
                w.add_node(
                    osmium.osm.mutable.Node(
                        id=e["id"], location=(e["lon"], e["lat"]), tags=e.get("tags", {})
                    )
                )
        for nodes in extra_ways:
            for nid, lon, lat in nodes[1]:
                w.add_node(osmium.osm.mutable.Node(id=nid, location=(lon, lat), tags={}))
        for e in sorted(osm["elements"], key=lambda e: e["id"]):
            if e["type"] == "way":
                w.add_way(osmium.osm.mutable.Way(id=e["id"], nodes=e["nodes"], tags=e["tags"]))
        for wid, nodes, tags in extra_ways:
            w.add_way(osmium.osm.mutable.Way(id=wid, nodes=[n[0] for n in nodes], tags=tags))
    finally:
        w.close()


def _bbox(osm, pad=0.01):
    pts = [(e["lon"], e["lat"]) for e in osm["elements"] if e["type"] == "node"]
    xs, ys = zip(*pts, strict=True)
    return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


def test_way_intersects_bbox_overpass_semantics():
    box = (0.0, 0.0, 1.0, 1.0)
    assert geofabrik.way_intersects_bbox([(0.5, 0.5), (2, 2)], box)  # one node inside
    assert geofabrik.way_intersects_bbox([(-1, 0.5), (2, 0.5)], box)  # crosses, no node inside
    assert not geofabrik.way_intersects_bbox([(2, 2), (3, 3)], box)
    assert not geofabrik.way_intersects_bbox([(-1, 2), (2, 3)], box)  # envelope overlaps only


def test_clip_reproduces_graph_and_edge_ids(tmp_path, overpass_small):
    """Same OSM data through PBF → clip → build gives byte-identical edge/node IDs."""
    pbf = tmp_path / "small.osm.pbf"
    # synthetic extra ways: one far outside the bbox, one crossing it with no node inside
    box = _bbox(overpass_small)
    w, s, e, n = box
    mid = (s + n) / 2
    extra = [
        (
            9_000_000_001,
            [(9_100_000_001, 10.0, 10.0), (9_100_000_002, 10.001, 10.0)],
            {"highway": "footway"},
        ),
        (
            9_000_000_002,
            [(9_100_000_003, w - 0.5, mid), (9_100_000_004, e + 0.5, mid)],
            {"highway": "footway"},
        ),
    ]
    _write_pbf(pbf, overpass_small, extra)
    assert geofabrik.pbf_header_timestamp(pbf) == TS

    clipped = geofabrik.clip(pbf, box, TS)
    way_ids = {x["id"] for x in clipped["elements"] if x["type"] == "way"}
    assert 9_000_000_001 not in way_ids  # outside
    assert 9_000_000_002 in way_ids  # crosses without a node inside (Overpass semantics)
    assert clipped["clip_stats"]["nodes_missing"] == 0

    clipped["elements"] = [
        x
        for x in clipped["elements"]
        if x["id"] not in (9_000_000_002, 9_100_000_003, 9_100_000_004)
    ]
    a = build_graph(clipped, snapshot=TS)
    b = build_graph(overpass_small, snapshot=TS)
    assert list(a.edges["edge_id"]) == list(b.edges["edge_id"])
    assert list(a.nodes["node_id"]) == list(b.nodes["node_id"])
    assert a.stats["ways_excluded_by_reason"] == b.stats["ways_excluded_by_reason"]


def test_md5_mismatch_is_fatal(tmp_path, monkeypatch):
    from winterpath_ingestion.http import DownloadError, RawFile

    f = tmp_path / "q.osm.pbf"
    f.write_bytes(b"not a pbf")
    md5 = tmp_path / "q.osm.pbf.md5"
    md5.write_text("0" * 32 + "  q.osm.pbf\n")

    def fake_download(url, dest, **kw):
        return RawFile(md5 if url.endswith(".md5") else f, "x", url, "t", True)

    monkeypatch.setattr(geofabrik, "download", fake_download)
    with pytest.raises(DownloadError, match="MD5 mismatch"):
        geofabrik.fetch(tmp_path, "ua", url="https://example.invalid/q.osm.pbf")
