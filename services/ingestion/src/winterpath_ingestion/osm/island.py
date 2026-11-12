"""Island pedestrian graph (WinterPath 2.0, Wave 1 feasibility) — local only.

Input: the cached Geofabrik Quebec PBF (same file and MD5 check as the pilot) and the boundaries
product (`wp-ingest boundaries`). Rules are exactly the pilot's (`graph.build_graph`): same
inclusion policy, same splitting, same stable IDs, no invented connectivity, gaps reported.

Area rule (documented, deterministic):
1. Clip: keep every highway way whose line intersects agglomeration land (all archipel islands),
   complete ways (all their nodes, even off-land: e.g. the far end of a bridge).
2. Component rule: among ways the graph policy admits, union ways that share an OSM node. Keep a
   component only if at least one of its nodes lies on the MAIN island. Other islands are thus
   included only where mapped pedestrian links (ways sharing nodes, e.g. a bridge sidewalk or a
   walkable road) connect them; isolated networks on other islands are dropped and reported.
   Disconnected networks ON the main island are kept (reported as components, as in the pilot).
3. Labels: each node is `main_island`, `other_island` (with island_id) or
   `outside_agglomeration_land` (bridge decks over water, the Laval / Longueuil / South-Shore end
   of a bridge). Nothing outside the agglomeration is labelled island.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import Counter
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely

from ..config import Settings
from ..runs import RunResult, read_manifest, run_atomic
from ..sources import boundaries
from . import geofabrik
from .graph import build_graph, exclusion_reason
from .pipeline import GRAPH_POLICY, write_geojson

log = logging.getLogger(__name__)
ISLAND_VERSION = "1"
OUT_NAME = "osm_island"
BIG_COMPONENT_EDGES = 50  # report non-largest components with more directed edges than this


class _DSU:
    def __init__(self):
        self.p: dict[int, int] = {}

    def find(self, x: int) -> int:
        p = self.p
        p.setdefault(x, x)
        root = x
        while p[root] != root:
            root = p[root]
        while p[x] != root:
            p[x], x = root, p[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def filter_to_main_island(osm: dict, main_geom) -> tuple[dict, dict]:
    """Component rule (module docstring §2) on raw OSM elements, before build_graph."""
    elements = osm["elements"]
    nodes = {e["id"]: e for e in elements if e["type"] == "node"}
    ways = [e for e in elements if e["type"] == "way"]
    dsu = _DSU()
    cand = []
    for w in ways:
        if exclusion_reason(w.get("tags", {})):
            continue
        refs = [r for r in w["nodes"] if r in nodes]
        if len(refs) < 2:
            continue
        cand.append(w)
        for r in refs[1:]:
            dsu.union(refs[0], r)
    ids = np.fromiter(nodes.keys(), dtype=np.int64)
    lon = np.fromiter((nodes[i]["lon"] for i in ids), dtype=float)
    lat = np.fromiter((nodes[i]["lat"] for i in ids), dtype=float)
    shapely.prepare(main_geom)
    on_main = shapely.contains_xy(main_geom, lon, lat)
    main_roots = {dsu.find(int(i)) for i in ids[on_main] if int(i) in dsu.p}
    keep_ways, drop = [], Counter()
    for w in cand:
        r0 = next(r for r in w["nodes"] if r in nodes)
        if dsu.find(r0) in main_roots:
            keep_ways.append(w["id"])
        else:
            drop["ways"] += 1
    keep = set(keep_ways)
    excluded_ids = {w["id"] for w in ways} - {w["id"] for w in cand}
    out = [e for e in elements if e["type"] == "node" or e["id"] in keep or e["id"] in excluded_ids]
    dropped_roots = {dsu.find(next(r for r in w["nodes"] if r in nodes)) for w in cand} - main_roots
    stats = {
        "candidate_ways": len(cand),
        "ways_kept": len(keep),
        "ways_dropped_not_connected_to_main_island": drop["ways"],
        "networks_dropped_not_connected_to_main_island": len(dropped_roots),
    }
    return {**osm, "elements": out}, stats


def label_nodes(nodes: gpd.GeoDataFrame, islands: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """land ∈ main_island | other_island | outside_agglomeration_land, plus island_id."""
    j = gpd.sjoin(
        nodes[["node_id", "geometry"]],
        islands[["island_id", "is_main_island", "geometry"]],
        how="left",
        predicate="within",
    ).drop_duplicates("node_id")
    land = np.where(
        j["island_id"].isna(),
        "outside_agglomeration_land",
        np.where(j["is_main_island"].fillna(False).astype(bool), "main_island", "other_island"),
    )
    return nodes.assign(
        land=land, island_id=[i if isinstance(i, str) else None for i in j["island_id"]]
    )


def per_unit(
    edges: gpd.GeoDataFrame, nodes: gpd.GeoDataFrame, limits: gpd.GeoDataFrame
) -> list[dict]:
    """Nodes by location; edges and km by edge midpoint (unclipped admin limits, so a bridge deck
    counts to the unit whose water it crosses). km are undirected (each segment once)."""
    lim = limits[["NOM", "TYPE", "geometry"]]
    nj = gpd.sjoin(nodes[["node_id", "geometry"]], lim, how="left", predicate="within")
    nj = nj.drop_duplicates("node_id")
    mid = edges.geometry.interpolate(0.5, normalized=True)
    em = gpd.GeoDataFrame(
        {"length_m": edges["length_m"].values}, geometry=mid.values, crs=edges.crs
    )
    ej = gpd.sjoin(em, lim, how="left", predicate="within")
    ej = ej[~ej.index.duplicated(keep="first")]
    out = []
    names = sorted(limits["NOM"].unique()) + [None]
    types = dict(zip(limits["NOM"], limits["TYPE"], strict=True))
    for n in names:
        nm = nj["NOM"].isna() if n is None else nj["NOM"] == n
        emk = ej["NOM"].isna() if n is None else ej["NOM"] == n
        out.append(
            {
                "unit": n or "outside agglomeration limits",
                "type": types.get(n, "—"),
                "nodes": int(nm.sum()),
                "directed_edges": int(emk.sum()),
                "km": round(float(ej.loc[emk, "length_m"].sum()) / 2 / 1000, 1),
            }
        )
    return out


def component_report(edges: gpd.GeoDataFrame, nodes: gpd.GeoDataFrame, limits) -> dict:
    by = edges.groupby("component_id")
    n_edges = by.size()
    km = by["length_m"].sum() / 2 / 1000
    n_nodes = nodes.groupby("component_id").size()
    total_nodes = int(len(nodes))
    total_km = float(edges["length_m"].sum()) / 2 / 1000
    big = []
    for cid in n_edges.index:
        if cid == 0 or n_edges[cid] <= BIG_COMPONENT_EDGES:
            continue
        sub = nodes[nodes["component_id"] == cid]
        c = shapely.MultiPoint(list(sub.geometry.values)).centroid
        units = gpd.sjoin(sub[["geometry"]], limits[["NOM", "geometry"]], predicate="within")
        lands = Counter(sub["land"])
        big.append(
            {
                "component_id": int(cid),
                "directed_edges": int(n_edges[cid]),
                "nodes": int(n_nodes.get(cid, 0)),
                "km": round(float(km[cid]), 2),
                "units": sorted(units["NOM"].unique()),
                "land": dict(lands),
                "centroid": [round(c.x, 5), round(c.y, 5)],
            }
        )
    big.sort(key=lambda x: -x["directed_edges"])
    return {
        "components": int(n_edges.size),
        "largest_nodes": int(n_nodes.get(0, 0)),
        "largest_node_share": round(int(n_nodes.get(0, 0)) / max(total_nodes, 1), 4),
        "largest_km": round(float(km.get(0, 0.0)), 1),
        "largest_length_share": round(float(km.get(0, 0.0)) / total_km, 4) if total_km else 0.0,
        "size_histogram_directed_edges": {
            "1-2": int((n_edges <= 2).sum()),
            "3-10": int(((n_edges > 2) & (n_edges <= 10)).sum()),
            "11-50": int(((n_edges > 10) & (n_edges <= 50)).sum()),
            "51+ (not largest)": len(big),
        },
        "non_largest_over_50_edges": big,
    }


def pinned_pbf_url(settings: Settings) -> str | None:
    """Same Geofabrik extract as the pilot graph (osm_pilot manifest provenance), so island and
    pilot share one OSM snapshot and the cached PBF is reused. None → resolve latest."""
    m = read_manifest(settings.processed_dir / "osm_pilot")
    return ((m or {}).get("provenance") or {}).get("url")


def run(settings: Settings, *, refresh: bool = False, force: bool = False) -> RunResult:
    t0 = time.perf_counter()
    timings: dict[str, float] = {}

    def lap(name: str, since: float) -> float:
        now = time.perf_counter()
        timings[name] = round(now - since, 1)
        return now

    boundaries.run(settings, refresh=refresh)
    bm = read_manifest(settings.processed_dir / "boundaries")
    pbf = geofabrik.fetch(
        settings.raw_dir, settings.user_agent, refresh=refresh, url=pinned_pbf_url(settings)
    )
    t = lap("fetch_and_boundaries_s", t0)

    bdir = settings.processed_dir / "boundaries"
    islands = gpd.read_file(bdir / "islands.geojson")
    limits = gpd.read_file(bdir / "admin_limits.geojson")
    main_geom = islands.loc[islands["is_main_island"].astype(bool)].geometry.iloc[0]
    land = islands.geometry.union_all()

    key = hashlib.sha256(
        f"{pbf.sha256}|{bm['input_checksum']}|island-v{ISLAND_VERSION}|clip-v{geofabrik.CLIP_VERSION}".encode()
    ).hexdigest()[:16]
    clip_path = pbf.path.parent / f"clip_island_{key}.json"
    checksum = hashlib.sha256(
        f"{pbf.sha256}|{bm['input_checksum']}|{clip_path.name}|{GRAPH_POLICY}|island-v{ISLAND_VERSION}".encode()
    ).hexdigest()

    def build(staging: Path, run_id: str) -> dict:
        nonlocal t
        timings["clip_cached"] = clip_path.exists() and not refresh
        if timings["clip_cached"]:
            osm = json.loads(clip_path.read_text())
        else:
            log.info("clipping %s to agglomeration land (two streaming passes)", pbf.path.name)
            osm = geofabrik.clip_area(pbf.path, land, pbf.replication_timestamp)
            tmp = clip_path.with_name(clip_path.name + ".part")
            tmp.write_text(json.dumps(osm, separators=(",", ":")))
            tmp.replace(clip_path)
        t = lap("clip_s", t)
        osm_f, fstats = filter_to_main_island(osm, main_geom)
        t = lap("component_filter_s", t)
        res = build_graph(osm_f, snapshot=pbf.replication_timestamp, ingest_run_id=run_id)
        t = lap("build_graph_s", t)
        nodes = label_nodes(res.nodes, islands)
        comp_main = nodes.groupby("component_id")["land"].apply(
            lambda s: (s == "main_island").any()
        )
        edges = res.edges
        t = lap("label_s", t)
        units = per_unit(edges, nodes, limits)
        comps = component_report(edges, nodes, limits)
        t = lap("report_s", t)
        write_geojson(edges, staging / "edges.geojson")
        write_geojson(nodes, staging / "nodes.geojson")
        (staging / "gaps.json").write_text(json.dumps(res.gaps, indent=1))
        t = lap("write_s", t)
        timings["total_s"] = round(time.perf_counter() - t0, 1)
        lands = Counter(nodes["land"])
        other = Counter(nodes.loc[nodes["land"] == "other_island", "island_id"])
        stats = {
            **res.stats,
            "clip": osm["clip_stats"],
            "component_filter": fstats,
            "components_without_main_island_node_after_build": int((~comp_main).sum()),
            "network_km_undirected": round(res.stats["total_length_m_undirected"] / 1000, 1),
            "nodes_by_land": dict(lands),
            "nodes_by_other_island": dict(other.most_common()),
            "per_unit": units,
            "component_report": comps,
            "timings_s": timings,
        }
        (staging / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False))
        return {
            "source_id": "osm",
            "region": "montreal_island",
            "osm_snapshot": pbf.replication_timestamp,
            "raw_file": pbf.path.name,
            "raw_sha256": pbf.sha256,
            "boundaries_checksum": bm["input_checksum"],
            "graph_policy": GRAPH_POLICY,
            "provenance": {
                **pbf.provenance(),
                "area_rule": "osm.island module docstring (clip to agglomeration land; keep "
                "components with a main-island node)",
                "clip": osm["clip_stats"],
            },
            "stats": stats,
        }

    return run_atomic(OUT_NAME, settings.processed_dir, checksum, build, force=force)
