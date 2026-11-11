"""Build the pilot pedestrian graph from an Overpass JSON response.

Topology rule (the only one): two edges are connected iff they share an OSM node. No snapping,
no inferred edges. Near-misses (dangling endpoints close to another edge) are *reported* as gaps.

Edges: every included OSM way is split at nodes that are shared with another included way, are
way endpoints, or carry pedestrian-relevant tags (crossing / kerb / barrier). Each resulting
segment belongs to exactly one way and is inserted in both directions (pedestrians may walk
either way on any of the included highway types).

IDs follow docs/contracts/data-model.md:
  node_id = "osm:n<id>"; edge_id = "<from>><to>:<k>", k = 0-based rank among parallel edges
  with the same (from, to) ordered by (osm_way_id, segment index).
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import networkx as nx
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, Point

from ..config import METRIC_CRS, WGS84

SOURCE_ID = "osm"

# Brief: footway, sidewalk(=footway), path, pedestrian, crossing(=footway), steps, living_street,
# residential/tertiary/secondary/primary only where walking is legal. Motorway/trunk never.
INCLUDED_HIGHWAYS = frozenset(
    {
        "footway",
        "path",
        "pedestrian",
        "steps",
        "living_street",
        "residential",
        "tertiary",
        "secondary",
        "primary",
    }
)
# Explicit "not legal for pedestrians" values.
FOOT_PROHIBITED = frozenset({"no", "private", "use_sidepath"})
ACCESS_PROHIBITED = frozenset({"no", "private"})

FOOT_ACCESS_ENUM = ("yes", "designated", "permissive", "no", "private", "unknown")

_TO_METRIC = Transformer.from_crs(WGS84, METRIC_CRS, always_xy=True)


# ---------------------------------------------------------------------------------- tag logic
def foot_access(tags: dict[str, str]) -> str:
    """Contract enum value. Explicit `foot` wins over `access`. Untagged → 'unknown' (we do not
    claim a legal status the data does not state)."""
    foot = tags.get("foot")
    if foot is not None:
        if foot == "use_sidepath":
            return "no"
        return foot if foot in FOOT_ACCESS_ENUM else "unknown"
    access = tags.get("access")
    if access in ("no", "private", "yes", "permissive", "designated"):
        return access
    return "unknown"


def exclusion_reason(tags: dict[str, str]) -> str | None:
    hw = tags.get("highway")
    if hw not in INCLUDED_HIGHWAYS:
        return f"highway={hw}"
    if tags.get("area") == "yes":
        return "area=yes (polygon, not a linear walkway)"
    if tags.get("foot") in FOOT_PROHIBITED:
        return f"foot={tags['foot']}"
    if "foot" not in tags and tags.get("access") in ACCESS_PROHIBITED:
        return f"access={tags['access']}"
    return None


def edge_kind(tags: dict[str, str]) -> str:
    hw = tags.get("highway")
    fw = tags.get("footway")
    if hw in ("footway", "path", "cycleway") and (
        fw == "crossing" or tags.get("path") == "crossing"
    ):
        return "crossing"
    if hw == "footway" and fw == "sidewalk":
        return "sidewalk"
    return {
        "footway": "footway",
        "path": "path",
        "pedestrian": "pedestrian_street",
        "steps": "steps",
        "living_street": "shared_street",
    }.get(hw or "", "other")  # roads: walking on the road edge itself


def crossing_type(tags: dict[str, str]) -> str | None:
    """CrossingInfo.type enum or None when the element is not a crossing."""
    is_crossing = (
        tags.get("highway") == "crossing"
        or tags.get("footway") == "crossing"
        or tags.get("path") == "crossing"
        or "crossing" in tags
        or "crossing:markings" in tags
    )
    if not is_crossing:
        return None
    c = tags.get("crossing")
    if c == "traffic_signals" or tags.get("crossing:signals") == "yes":
        return "traffic_signals"
    if c in ("marked", "zebra") or tags.get("crossing_ref") == "zebra":
        return "marked"
    m = tags.get("crossing:markings")
    if m and m != "no":
        return "marked"
    if c == "unmarked" or m == "no":
        return "unmarked"
    if c == "uncontrolled":
        return "uncontrolled"
    return "unknown"


def kerb_value(tags: dict[str, str]) -> str | None:
    k = tags.get("kerb")
    if k is None:
        return None
    return k if k in ("lowered", "flush", "raised") else "unknown"


def _parse_float(v: str | None) -> float | None:
    if v is None:
        return None
    s = v.strip().lower().replace(",", ".")
    for suffix in ("%", "m", " m"):
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
    try:
        return float(s)
    except ValueError:
        return None


def incline_percent(tags: dict[str, str]) -> float | None:
    v = tags.get("incline")
    if v is None or v in ("up", "down", "yes", "no"):
        return None
    return _parse_float(v)


def _bool(v: str | None) -> bool | None:
    if v in ("yes", "24/7", "automatic"):
        return True
    if v == "no":
        return False
    return None


def step_free(way_tags: dict[str, str], kerbs: list[str]) -> bool | None:
    """True only when a source tag verifies it (wheelchair=yes) and nothing contradicts it."""
    if way_tags.get("highway") == "steps":
        return False
    if way_tags.get("wheelchair") == "no":
        return False
    if "raised" in kerbs:
        return False
    if way_tags.get("wheelchair") == "yes":
        return True
    return None


# ------------------------------------------------------------------------------- data classes
@dataclass
class BuildResult:
    nodes: gpd.GeoDataFrame
    edges: gpd.GeoDataFrame
    stats: dict
    gaps: list[dict] = field(default_factory=list)


def node_id(osm_id: int) -> str:
    return f"osm:n{osm_id}"


def load_overpass(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------- build
def build_graph(
    osm: dict,
    *,
    snapshot: str | None = None,
    ingest_run_id: str | None = None,
    near_miss_m: float = 2.0,
) -> BuildResult:
    elements = osm["elements"]
    nodes_raw = {e["id"]: e for e in elements if e["type"] == "node"}
    ways_raw = sorted((e for e in elements if e["type"] == "way"), key=lambda e: e["id"])

    excluded: Counter[str] = Counter()
    ways: list[dict] = []
    for w in ways_raw:
        reason = exclusion_reason(w.get("tags", {}))
        if reason:
            excluded[reason] += 1
            continue
        refs = [r for i, r in enumerate(w["nodes"]) if i == 0 or r != w["nodes"][i - 1]]
        missing = [r for r in refs if r not in nodes_raw]
        if missing:
            excluded["missing node coordinates"] += 1
            continue
        if len(refs) < 2:
            excluded["degenerate way (<2 nodes)"] += 1
            continue
        ways.append({"id": w["id"], "tags": w.get("tags", {}), "refs": refs})

    usage: Counter[int] = Counter()
    for w in ways:
        for r in set(w["refs"]):
            usage[r] += 1
        # a closed way revisits its first node: that node is a split point
        if w["refs"][0] == w["refs"][-1]:
            usage[w["refs"][0]] += 1

    def is_split(r: int) -> bool:
        t = nodes_raw[r].get("tags", {})
        return usage[r] > 1 or crossing_type(t) is not None or "kerb" in t or "barrier" in t

    # ---- split ways into segments
    segments: list[dict] = []
    dropped_zero = 0
    for w in ways:
        refs = w["refs"]
        cut = [0] + [i for i in range(1, len(refs) - 1) if is_split(refs[i])] + [len(refs) - 1]
        for seg_idx, (a, b) in enumerate(zip(cut[:-1], cut[1:], strict=True)):
            seg_refs = refs[a : b + 1]
            coords = [(nodes_raw[r]["lon"], nodes_raw[r]["lat"]) for r in seg_refs]
            mx, my = _TO_METRIC.transform([c[0] for c in coords], [c[1] for c in coords])
            length = LineString(list(zip(mx, my, strict=True))).length
            if length <= 0:
                dropped_zero += 1
                continue
            segments.append(
                {"way": w, "seg": seg_idx, "refs": seg_refs, "coords": coords, "length": length}
            )

    # ---- nodes
    used_nodes = sorted({r for s in segments for r in (s["refs"][0], s["refs"][-1])})
    node_rows = []
    for r in used_nodes:
        t = nodes_raw[r].get("tags", {})
        ct = crossing_type(t)
        kind = "crossing" if ct else ("entrance" if "entrance" in t else "street_node")
        node_rows.append(
            {
                "node_id": node_id(r),
                "osm_id": r,
                "kind": kind,
                "crossing_type": ct,
                "kerb": kerb_value(t),
                "source_id": SOURCE_ID,
                "ingest_run_id": ingest_run_id,
                "geometry": Point(nodes_raw[r]["lon"], nodes_raw[r]["lat"]),
            }
        )
    nodes = gpd.GeoDataFrame(node_rows, geometry="geometry", crs=WGS84)

    # ---- directed edges
    directed = []
    for s in segments:
        w, t = s["way"], s["way"]["tags"]
        kerbs = [k for r in s["refs"] if (k := kerb_value(nodes_raw[r].get("tags", {})))]
        node_ct = [c for r in s["refs"] if (c := crossing_type(nodes_raw[r].get("tags", {})))]
        kind = edge_kind(t)
        cinfo = None
        if kind == "crossing":
            ctype = crossing_type(t) or next((c for c in node_ct if c != "unknown"), "unknown")
            ckerb = "unknown"
            if kerbs and "raised" in kerbs:
                ckerb = "raised"
            elif kerbs and all(k in ("lowered", "flush") for k in kerbs):
                ckerb = "flush" if all(k == "flush" for k in kerbs) else "lowered"
            cinfo = {"type": ctype, "kerb": ckerb}
        attrs = {
            "length_m": s["length"],
            "edge_kind": kind,
            "osm_way_id": w["id"],
            "highway": t.get("highway"),
            "name": t.get("name"),  # v1.3: street name for step directions
            "foot_access": foot_access(t),
            "step_free": step_free(t, kerbs),
            "incline_percent": incline_percent(t),
            "width_m": _parse_float(t.get("width")),
            "surface": t.get("surface"),
            "lit": _bool(t.get("lit")),
            "crossing": cinfo,
            "connectivity_confidence": "high",
            "sidewalk_polygon_ids": [],
            "source_id": SOURCE_ID,
            "ingest_run_id": ingest_run_id,
            "osm_snapshot": snapshot,
        }
        a, b = s["refs"][0], s["refs"][-1]
        line = LineString(s["coords"])
        directed.append(
            {**attrs, "_u": a, "_v": b, "_ord": (w["id"], s["seg"], 0), "geometry": line}
        )
        directed.append(
            {**attrs, "_u": b, "_v": a, "_ord": (w["id"], s["seg"], 1), "geometry": line.reverse()}
        )

    groups: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for e in directed:
        groups[(e["_u"], e["_v"])].append(e)
    for (u, v), grp in groups.items():
        grp.sort(key=lambda e: e["_ord"])
        for k, e in enumerate(grp):
            e["from_node_id"], e["to_node_id"] = node_id(u), node_id(v)
            e["edge_id"] = f"{node_id(u)}>{node_id(v)}:{k}"

    # ---- components (undirected; every edge exists both ways)
    g = nx.Graph()
    g.add_nodes_from(node_id(r) for r in used_nodes)
    g.add_edges_from((e["from_node_id"], e["to_node_id"]) for e in directed)
    comps = sorted(nx.connected_components(g), key=lambda c: (-len(c), min(c)))
    comp_of = {n: i for i, c in enumerate(comps) for n in c}
    for e in directed:
        e["component_id"] = comp_of[e["from_node_id"]]
    nodes["component_id"] = nodes["node_id"].map(comp_of)

    directed.sort(key=lambda e: e["edge_id"])
    for e in directed:
        del e["_u"], e["_v"], e["_ord"]
    edges = gpd.GeoDataFrame(directed, geometry="geometry", crs=WGS84)

    gaps = find_gaps(nodes, edges, g, comps, near_miss_m)

    total_len = sum(s["length"] for s in segments)
    comp_len = Counter()
    for s in segments:
        comp_len[comp_of[node_id(s["refs"][0])]] += s["length"]
    stats = {
        "osm_snapshot": snapshot,
        "ways_downloaded": len(ways_raw),
        "ways_included": len(ways),
        "ways_excluded_by_reason": dict(sorted(excluded.items())),
        "segments": len(segments),
        "zero_length_segments_dropped": dropped_zero,
        "nodes": len(nodes),
        "directed_edges": len(edges),
        "total_length_m_undirected": round(total_len, 1),
        "components": len(comps),
        "largest_component_nodes": len(comps[0]) if comps else 0,
        "largest_component_node_share": round(len(comps[0]) / max(len(used_nodes), 1), 4)
        if comps
        else 0.0,
        "largest_component_length_share": round(comp_len[0] / total_len, 4) if total_len else 0.0,
        "crossing_nodes": int((nodes["kind"] == "crossing").sum()),
        "edge_kind_counts": dict(sorted(Counter(edges["edge_kind"]).items())),
        "foot_access_counts": dict(sorted(Counter(edges["foot_access"]).items())),
        "step_free_counts": {
            str(k): v for k, v in sorted(Counter(map(str, edges["step_free"])).items())
        },
        "gap_count": len(gaps),
    }
    return BuildResult(nodes=nodes, edges=edges, stats=stats, gaps=gaps)


def find_gaps(nodes, edges, g: nx.Graph, comps, near_miss_m: float) -> list[dict]:
    """Report (never repair) dangling endpoints within ``near_miss_m`` of an edge they are not
    attached to. Each gap lists both components so reviewers can judge whether OSM is missing a
    connection."""
    if nodes.empty:
        return []
    nm = nodes.to_crs(METRIC_CRS)
    em = edges.to_crs(METRIC_CRS)
    em = em[em["from_node_id"] < em["to_node_id"]]  # one direction per segment
    deg = dict(g.degree())
    dangling = nm[nm["node_id"].map(lambda n: deg.get(n, 0) == 1)]
    if dangling.empty:
        return []
    tree = shapely.STRtree(em.geometry.values)
    gaps = []
    pts = dangling.geometry.values
    pairs = tree.query(pts, predicate="dwithin", distance=near_miss_m)
    seen = set()
    for pi, ei in zip(pairs[0], pairs[1], strict=True):
        node = dangling.iloc[pi]
        edge = em.iloc[ei]
        if node["node_id"] in (edge["from_node_id"], edge["to_node_id"]):
            continue
        if node["node_id"] in seen:
            continue
        seen.add(node["node_id"])
        d = float(node.geometry.distance(edge.geometry))
        lonlat = nodes.loc[nodes["node_id"] == node["node_id"]].geometry.iloc[0]
        gaps.append(
            {
                "type": "near_miss_dangling_endpoint",
                "node_id": node["node_id"],
                "near_edge_id": edge["edge_id"],
                "distance_m": round(d, 2),
                "node_component": int(node["component_id"]),
                "edge_component": int(edge["component_id"]),
                "lon": round(lonlat.x, 6),
                "lat": round(lonlat.y, 6),
            }
        )
    gaps.sort(key=lambda x: x["node_id"])
    for i, c in enumerate(comps[1:], start=1):
        gaps.append({"type": "disconnected_component", "component_id": i, "nodes": len(c)})
    return gaps
