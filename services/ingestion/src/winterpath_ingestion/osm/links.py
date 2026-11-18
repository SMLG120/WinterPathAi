"""Fixed links (bridges, tunnels) between the Montréal side and its neighbours, from OSM.

Read-only report: it never adds a way or an edge to any graph.

Method (deterministic, one streaming pass over the cached Geofabrik PBF):

1. "Montréal side" = the Agglomération de Montréal municipalities plus the two unorganised
   territories of the MRC de Montréal (river water and islets), all from the Québec SDA
   (:mod:`..sources.sda`). Each neighbouring municipality is an SDA ``munic_s`` polygon.
2. A *crossing way* is any ``highway=*`` or ``railway=*`` way whose line crosses the boundary of
   the Montréal side and touches a neighbouring municipality.
3. A crossing way tagged ``bridge``/``tunnel`` is grown into its *structure*: every bridge- or
   tunnel-tagged way reachable through shared OSM nodes (only through bridge/tunnel ways, so the
   streets at either end are not swallowed). The structure's name is ``bridge:name`` /
   ``tunnel:name`` / ``name`` as tagged; nothing is renamed. Growth stays within one mode
   (road/path ways vs railway ways), so a metro tunnel is not merged with station corridors.
4. Each way is classified with the graph's own inclusion rule (:func:`.graph.exclusion_reason`):
   foot-legal (an edge in the graph) or excluded with the reason. Since graph policy
   ``v1.6.0+seasonal-v1`` that rule excludes ``seasonal=*`` ways unless winter is listed, so such a
   way shows ``foot_legal`` false with the seasonal reason. Other time-conditional tags
   (``*:conditional``, ``opening_hours``, ``winter_service``) are copied verbatim and not evaluated.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import shapely
from shapely.geometry import LineString

from .graph import exclusion_reason

MONTREAL_AGG = "Agglomération de Montréal"
MRC_MONTREAL = "Montréal"  # MUS_NM_MRC of the agglomeration and of its two TNO
CONDITIONAL_KEYS = ("opening_hours", "seasonal", "winter_service", "opening_date")


def _is_struct(t: dict) -> bool:
    return t.get("bridge", "no") != "no" or t.get("tunnel", "no") != "no"


def _mode(t: dict) -> str:
    """Structures grow only within one mode: a metro tunnel never absorbs a station footway."""
    return "highway" if "highway" in t else "railway"


def conditional_tags(t: dict) -> dict:
    return {
        k: v
        for k, v in sorted(t.items())
        if k.endswith(":conditional") or k in CONDITIONAL_KEYS or k.startswith("seasonal")
    }


def classify(t: dict) -> dict:
    if "highway" not in t:
        return {"kind": f"railway={t.get('railway')}", "foot_legal": False, "reason": "not a road"}
    reason = exclusion_reason(t)
    return {"kind": f"highway={t['highway']}", "foot_legal": reason is None, "reason": reason}


def sides(munic: gpd.GeoDataFrame) -> tuple[object, gpd.GeoDataFrame]:
    m = munic.to_crs("EPSG:4326")
    m = m.assign(geometry=m.geometry.force_2d().make_valid())
    mtl = (m["MUS_NM_AGG"] == MONTREAL_AGG) | (m["MUS_NM_MRC"] == MRC_MONTREAL)
    return m[mtl].geometry.union_all(), m[~mtl]


def scan(pbf: Path, munic: gpd.GeoDataFrame, margin_deg: float = 0.03) -> dict:
    import osmium
    from osmium.filter import EntityFilter

    mtl, others = sides(munic)
    zone = mtl.buffer(margin_deg)
    near = others[others.intersects(zone)].reset_index(drop=True)
    boundary = mtl.boundary
    shapely.prepare(boundary)
    w0, s0, e0, n0 = zone.bounds
    ways: dict[int, dict] = {}
    crossing: list[int] = []
    fp = (
        osmium.FileProcessor(str(pbf))
        .with_locations("flex_mem")
        .with_filter(EntityFilter(osmium.osm.WAY))
    )
    for w in fp:
        t = dict(w.tags)
        if "highway" not in t and "railway" not in t:
            continue
        try:
            coords = [(nr.location.lon, nr.location.lat) for nr in w.nodes]
        except osmium.InvalidLocationError:
            continue
        if len(coords) < 2:
            continue
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        if max(xs) < w0 or min(xs) > e0 or max(ys) < s0 or min(ys) > n0:
            continue
        line = LineString(coords)
        is_x = boundary.intersects(line)
        if not (is_x or _is_struct(t)):
            continue
        ways[w.id] = {"tags": t, "nodes": [nr.ref for nr in w.nodes], "line": line}
        if is_x:
            crossing.append(w.id)
    return {"ways": ways, "crossing": sorted(crossing), "near": near, "mtl": mtl}


def structures(res: dict) -> list[dict]:
    """Group crossing ways into bridge/tunnel structures and attach neighbours."""
    ways, near = res["ways"], res["near"]
    by_node: dict[int, list[int]] = defaultdict(list)
    for wid, w in ways.items():
        if _is_struct(w["tags"]):
            for r in w["nodes"]:
                by_node[r].append(wid)
    seen: set[int] = set()
    out = []
    for wid in res["crossing"]:
        if wid in seen:
            continue
        t = ways[wid]["tags"]
        hits = sorted(near[near.intersects(ways[wid]["line"])]["MUS_NM_MUN"])
        if not hits:
            continue  # boundary between agglomeration and its own MRC water: internal
        group = {wid}
        if _is_struct(t):
            mode = _mode(t)
            stack = [wid]
            while stack:
                cur = stack.pop()
                for r in ways[cur]["nodes"]:
                    for nb in by_node.get(r, ()):
                        if nb not in group and _mode(ways[nb]["tags"]) == mode:
                            group.add(nb)
                            stack.append(nb)
        seen |= group
        members = []
        for m in sorted(group):
            mt = ways[m]["tags"]
            members.append(
                {
                    "osm_way_id": m,
                    "crosses_limit": m in res["crossing"],
                    **classify(mt),
                    "tags": {
                        k: mt[k]
                        for k in sorted(mt)
                        if k
                        in (
                            "highway",
                            "railway",
                            "name",
                            "bridge",
                            "bridge:name",
                            "tunnel",
                            "tunnel:name",
                            "ref",
                            "foot",
                            "access",
                            "bicycle",
                            "sidewalk",
                            "sidewalk:both",
                            "sidewalk:left",
                            "sidewalk:right",
                            "footway",
                            "segregated",
                        )
                    },
                    "conditional": conditional_tags(mt),
                }
            )
        names = sorted(
            {
                n
                for m in group
                for k in ("bridge:name", "tunnel:name", "name")
                if (n := ways[m]["tags"].get(k))
            }
        )
        out.append(
            {
                "neighbours": hits,
                "names": names,
                "foot_legal_ways": [x["osm_way_id"] for x in members if x["foot_legal"]],
                "members": members,
            }
        )
    out.sort(key=lambda s: (s["neighbours"], s["names"], s["members"][0]["osm_way_id"]))
    return out


def run(pbf: Path, sda_gpkg: Path, out: Path) -> list[dict]:
    munic = gpd.read_file(sda_gpkg, layer="munic_s")
    res = scan(pbf, munic)
    st = structures(res)
    out.write_text(json.dumps(st, indent=1, ensure_ascii=False))
    return st
