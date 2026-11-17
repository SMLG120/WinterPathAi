"""Island pedestrian graph (WinterPath 2.0, Wave 1 feasibility) — local only. The build itself
is the generic :func:`.region.run_region` with :data:`.region.ISLAND`; the helpers here are shared
with the Greater Montréal regions.

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

import logging
from collections import Counter

import geopandas as gpd
import numpy as np
import shapely

from ..config import Settings
from ..runs import RunResult
from .graph import exclusion_reason

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
    edges: gpd.GeoDataFrame,
    nodes: gpd.GeoDataFrame,
    limits: gpd.GeoDataFrame,
    *,
    with_largest: bool = False,
) -> list[dict]:
    """Nodes by location; edges and km by edge midpoint (unclipped admin limits, so a bridge deck
    counts to the unit whose water it crosses). km are undirected (each segment once).
    ``with_largest`` adds each unit's share in the largest component (component_id 0), the only
    one routed; off for the island so its stats keep the Wave 1 columns."""
    lim = limits[["NOM", "TYPE", "geometry"]]
    nj = gpd.sjoin(nodes[["node_id", "geometry"]], lim, how="left", predicate="within")
    nj = nj.drop_duplicates("node_id")
    mid = edges.geometry.interpolate(0.5, normalized=True)
    em = gpd.GeoDataFrame(
        {"length_m": edges["length_m"].values}, geometry=mid.values, crs=edges.crs
    )
    ej = gpd.sjoin(em, lim, how="left", predicate="within")
    ej = ej[~ej.index.duplicated(keep="first")]
    if with_largest:
        comp_n = nj["node_id"].map(dict(zip(nodes["node_id"], nodes["component_id"], strict=True)))
        comp_e = edges["component_id"].reindex(ej.index)
    out = []
    names = sorted(limits["NOM"].unique()) + [None]
    types = dict(zip(limits["NOM"], limits["TYPE"], strict=True))
    for n in names:
        nm = nj["NOM"].isna() if n is None else nj["NOM"] == n
        emk = ej["NOM"].isna() if n is None else ej["NOM"] == n
        row = {
            "unit": n or "outside agglomeration limits",
            "type": types.get(n, "—"),
            "nodes": int(nm.sum()),
            "directed_edges": int(emk.sum()),
            "km": round(float(ej.loc[emk, "length_m"].sum()) / 2 / 1000, 1),
        }
        if with_largest:
            n_main = int((nm & (comp_n == 0)).sum())
            km_main = float(ej.loc[emk & (comp_e == 0), "length_m"].sum()) / 2 / 1000
            row["nodes_in_largest_component"] = n_main
            row["km_in_largest_component"] = round(km_main, 1)
            row["largest_component_node_share"] = (
                round(n_main / row["nodes"], 4) if row["nodes"] else None
            )
        out.append(row)
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


def run(settings: Settings, *, refresh: bool = False, force: bool = False) -> RunResult:
    """The island build through :mod:`.region` (current policy, including the seasonal rule)."""
    from .region import ISLAND, run_region

    return run_region(settings, ISLAND, refresh=refresh, force=force)
