"""Build the prebuilt graph artifact the API loads with ``ROUTING_GRAPH_SOURCE=artifact``.

    python -m winterpath_api.graph_artifact --out island.npz --from-postgis \\
        --bbox=-73.98,45.40,-73.47,45.71 --coverage-name "Island of Montréal" \\
        --coverage-area data/processed/boundaries/main_island.geojson

Run on a build machine, never by the API. Sources: ``--from-postgis`` (DATABASE_URL),
``--from-fixture DIR`` (edges.geojson / nodes.geojson / metadata.json), ``--from-processed DIR``
(an ingestion output such as ``data/processed/osm_greater_stage1``: edges.geojson, nodes.geojson
and the run's manifest.json, no database needed) or ``--from-artifact`` (re-pack an existing
artifact, e.g. to refresh the risk-cell index). Nothing is invented: the
graph is exactly what the provider returns, and the coverage area is the file given.

The output also carries, for the API:
* ``info["coverage"]``: name, bbox (node extent, rounded outward) and the area polygon;
* the edge → risk-cell index for the ML layer's sampler (``--risk-sampler``), with the sampler
  parameters recorded so a later ML change is detected instead of silently mismatched.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib
import inspect
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

from winterpath_routing import compact_io
from winterpath_routing.compact import CompactGraph

from .risk_cells import RiskCellIndex, _jsonable


def graph_from_processed(directory: str | Path) -> CompactGraph:
    """CompactGraph from an ingestion output directory (``wp-ingest osm-island|osm-region``).

    Same per-feature conversion as the fixture provider (``edge_from_properties``, crossing data
    inherited from crossing nodes), streamed into the compact builder so no list of ``Edge``
    objects is held. Metadata comes from the run manifest: real OSM data (``simulated`` false),
    snapshot = the PBF replication timestamp, freshness = that snapshot only.
    """
    from winterpath_routing.compact import CompactGraphBuilder
    from winterpath_routing.models import GraphMetadata, Node
    from winterpath_routing.providers import (
        _looks_like_dt,
        _parse_dt,
        _with_node_crossing,
        edge_from_properties,
    )

    d = Path(directory)
    manifest = json.loads((d / "manifest.json").read_text())
    if manifest.get("source_id") != "osm":
        raise SystemExit(f"{d}: not an OSM graph output (manifest source_id)")
    snapshot = manifest.get("osm_snapshot")
    b = CompactGraphBuilder()
    nodes: dict[str, Node] = {}
    for f in json.loads((d / "nodes.geojson").read_text())["features"]:
        p = f["properties"]
        nid = str(f.get("id") or p["node_id"])
        lon, lat = f["geometry"]["coordinates"][:2]
        n = Node(
            node_id=nid,
            lon=float(lon),
            lat=float(lat),
            kind=str(p.get("kind") or "street_node"),
            crossing_type=p.get("crossing_type"),
            kerb=p.get("kerb"),
        )
        nodes[nid] = n
        b.add_node(n)
    feats = json.loads((d / "edges.geojson").read_text())["features"]
    feats.reverse()
    while feats:  # pop as we go: the parsed GeoJSON is the largest object in this process
        f = feats.pop()
        p = f["properties"]
        eid = str(f.get("id") or p["edge_id"])
        b.add_edge(
            _with_node_crossing(edge_from_properties(eid, f["geometry"]["coordinates"], p), nodes)
        )
    title = manifest.get("title") or manifest.get("region") or d.name
    return b.build(
        GraphMetadata(
            simulated=False,
            osm_snapshot=str(snapshot) if snapshot is not None else None,
            # Same guard as the fixture provider: an unparseable snapshot is unknown freshness.
            built_at=_parse_dt(fin) if _looks_like_dt(fin := manifest.get("finished_at")) else None,
            source_freshness={"osm": _parse_dt(snapshot) if _looks_like_dt(snapshot) else None}
            if snapshot
            else {},
            description=f"OSM pedestrian graph, {title} (processed GeoJSON)",
        )
    )


def _graph(args: argparse.Namespace) -> CompactGraph:
    if args.from_artifact:
        return compact_io.load(args.from_artifact)[0]
    if args.from_processed:
        return graph_from_processed(args.from_processed)
    if args.from_fixture:
        from winterpath_routing.providers import FixtureGraphProvider

        return CompactGraph.from_graph_data(FixtureGraphProvider(args.from_fixture).load())
    from winterpath_routing.providers import PostgisGraphProvider

    url = os.environ.get("DATABASE_URL")
    if not url or not args.bbox:
        raise SystemExit("--from-postgis needs DATABASE_URL and --bbox")
    bbox = tuple(float(x) for x in args.bbox.split(","))
    return CompactGraph.from_graph_data(PostgisGraphProvider(url, bbox).load())


def _area(path: str | None, tolerance_m: float, merge_m: float) -> dict[str, Any] | None:
    """Union of the file's polygons, simplified in EPSG:32188, as WGS84 GeoJSON (6 decimals)."""
    if not path:
        return None
    import numpy as np
    import shapely
    from pyproj import Transformer
    from shapely.geometry import Polygon, mapping, shape
    from shapely.ops import unary_union

    doc = json.loads(Path(path).read_text())
    feats = doc["features"] if doc.get("type") == "FeatureCollection" else [doc]
    geom = unary_union([shape(f.get("geometry") or f) for f in feats])
    to_m = Transformer.from_crs(4326, 32188, always_xy=True).transform
    to_deg = Transformer.from_crs(32188, 4326, always_xy=True).transform

    def fwd(xy):
        return np.column_stack(to_m(xy[:, 0], xy[:, 1]))

    def back(xy):
        return np.column_stack(to_deg(xy[:, 0], xy[:, 1]))

    metric = shapely.transform(geom, fwd)
    if metric.geom_type != "Polygon":
        # The contract's Coverage.area is ONE Polygon. Islands separated by narrow channels are
        # joined by a morphological closing (merge_m out, merge_m back in) and the largest part
        # is kept, outline only: a service-area outline, not a land/water map.
        closed = metric.buffer(merge_m).buffer(-merge_m)
        parts = list(getattr(closed, "geoms", [closed]))
        metric = Polygon(max(parts, key=lambda g: g.area).exterior)
    simple = shapely.transform(metric.simplify(tolerance_m, preserve_topology=True), back)
    return mapping(shapely.set_precision(simple, 1e-6))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-postgis", action="store_true")
    src.add_argument("--from-fixture")
    src.add_argument("--from-artifact")
    src.add_argument("--from-processed")
    ap.add_argument("--bbox", help="w,s,e,n for --from-postgis")
    ap.add_argument("--coverage-name", required=True)
    ap.add_argument("--coverage-area", help="GeoJSON polygon(s) of the served area")
    ap.add_argument("--simplify-m", type=float, default=25.0)
    ap.add_argument("--merge-m", type=float, default=400.0, help="join islands closer than 2x this")
    ap.add_argument("--risk-sampler", default="winterpath_ml.inference:cells_along")
    ap.add_argument("--no-risk-index", action="store_true")
    args = ap.parse_args(argv)

    t0 = time.perf_counter()
    g = _graph(args)
    print(f"graph: {len(g.nodes)} nodes, {len(g.edges)} directed edges", file=sys.stderr)

    info: dict[str, Any] = {
        "coverage": {
            "name": args.coverage_name,
            "bbox": [
                math.floor(float(g.node_lon.min()) * 1000) / 1000,
                math.floor(float(g.node_lat.min()) * 1000) / 1000,
                math.ceil(float(g.node_lon.max()) * 1000) / 1000,
                math.ceil(float(g.node_lat.max()) * 1000) / 1000,
            ],
            "area": _area(args.coverage_area, args.simplify_m, args.merge_m),
        }
    }
    extras = {}
    if not args.no_risk_index:
        mod, _, fn = args.risk_sampler.partition(":")
        cells_along = getattr(importlib.import_module(mod), fn)
        params = {
            k: p.default
            for k, p in inspect.signature(cells_along).parameters.items()
            if p.default is not inspect.Parameter.empty
        }
        index = RiskCellIndex.build(g, cells_along)
        extras = index.to_extras()
        info["risk_cells"] = {"params": _jsonable(params), "sampler": args.risk_sampler}
        print(f"risk-cell index: {len(index.cells)} cells, {len(index.idx)} refs", file=sys.stderr)

    # A source that never loaded is not an input of this graph (same rule as
    # providers.route_source_freshness); a null would be shown to users as "updated: never".
    g.metadata = dataclasses.replace(
        g.metadata,
        source_freshness={k: v for k, v in g.metadata.source_freshness.items() if v is not None},
    )
    compact_io.save(g, args.out, extras=extras, info=info)
    out = {
        "path": args.out,
        "bytes": os.path.getsize(args.out),
        "sha256": compact_io.sha256_file(args.out),
        "nodes": len(g.nodes),
        "directed_edges": len(g.edges),
        "largest_component_share": round(g.largest_component_share, 4),
        "coverage_bbox": info["coverage"]["bbox"],
        "seconds": round(time.perf_counter() - t0, 1),
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
