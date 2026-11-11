"""Export `data/fixtures/pilot_mini/`: ≤200 real directed edges around McGill's Roddick Gates.

Selection is deterministic: starting at the graph node nearest ANCHOR (largest component),
undirected segments are added in order of network distance from the anchor (Dijkstra on
length_m; ties by edge_id) until adding the next segment's two directed edges would exceed
MAX_EDGES. The result is therefore connected. Nothing is synthesised.
"""

from __future__ import annotations

import heapq
import json
from pathlib import Path

import geopandas as gpd
import networkx as nx

from .config import Settings
from .osm.pipeline import read_geojson, write_geojson
from .runs import RunResult, read_manifest, run_atomic

ANCHOR = (-73.5765, 45.5045)  # Sherbrooke St W at McGill College Ave (Roddick Gates)
MAX_EDGES = 200

ATTRIBUTION = """# Attribution — pilot_mini fixture

Real data, not simulated (`"simulated": false` in metadata.json).

- **OpenStreetMap**: © OpenStreetMap contributors — https://www.openstreetmap.org/copyright.
  Data available under the Open Database Licence (ODbL 1.0). This fixture is a derived
  database extract and is itself distributed under the ODbL.
- Source extract: Geofabrik `quebec-latest.osm.pbf` (download.geofabrik.de), clipped to the
  pilot bbox; exact dated file, MD5 and OSM timestamp in metadata.json (`osm_source`).

Caveats: OSM tags describe mapped infrastructure, not current winter conditions. Nothing in this
fixture states that a sidewalk is cleared, ice-free, safe or wheelchair accessible.
`step_free=true` only reflects an OSM `wheelchair=yes` tag without a contradicting raised kerb;
`null` means unknown and must not be read as accessible.
"""

VOIRIE_ATTRIBUTION = """
- **Ville de Montréal — Voirie (trottoirs et îlots)**: Contient des données de la Ville de
  Montréal, sous licence CC BY 4.0 — https://donnees.montreal.ca/dataset/voirie-trottoir-ilot.
  Used only for `sidewalk_polygon_ids` (polygon ids matched to edges by spatial overlap).
  Publisher warning: not necessarily up to date across the whole territory.
"""


def select_edges(
    edges: gpd.GeoDataFrame, nodes: gpd.GeoDataFrame, anchor=ANCHOR, max_edges: int = MAX_EDGES
) -> gpd.GeoDataFrame:
    main = edges[edges["component_id"] == 0]
    main_nodes = nodes[nodes["node_id"].isin(set(main["from_node_id"]))]
    from shapely.geometry import Point

    ap = gpd.GeoSeries([Point(anchor)], crs="EPSG:4326").to_crs("EPSG:32188").iloc[0]
    d = main_nodes.to_crs("EPSG:32188").distance(ap)
    start = main_nodes.loc[d.idxmin(), "node_id"]

    g = nx.MultiGraph()
    for r in main.itertuples():
        if r.from_node_id <= r.to_node_id:
            g.add_edge(r.from_node_id, r.to_node_id, key=r.edge_id, w=r.length_m)
    dist = nx.single_source_dijkstra_path_length(
        g, start, weight=lambda u, v, d: min(x["w"] for x in d.values())
    )

    # rank each undirected segment by the network distance of its nearer endpoint
    heap = []
    for u, v, k, data in g.edges(keys=True, data=True):
        heapq.heappush(heap, (min(dist[u], dist[v]) + data["w"], k, u, v))
    chosen_nodes = {start}
    pending = []
    selected_fwd: list[str] = []
    while heap and 2 * (len(selected_fwd) + 1) <= max_edges:
        item = heapq.heappop(heap)
        _, k, u, v = item
        if u in chosen_nodes or v in chosen_nodes:
            selected_fwd.append(k)
            chosen_nodes.update((u, v))
            for p in pending:
                heapq.heappush(heap, p)
            pending = []
        else:
            pending.append(item)

    # include the reverse directed edge of every selected segment
    fwd = main.set_index("edge_id").loc[selected_fwd]
    pairs = set(zip(fwd["from_node_id"], fwd["to_node_id"], fwd["osm_way_id"], strict=True))
    mask = main.apply(
        lambda r: (
            (r.from_node_id, r.to_node_id, r.osm_way_id) in pairs
            or (r.to_node_id, r.from_node_id, r.osm_way_id) in pairs
        ),
        axis=1,
    )
    out = main[mask]
    # parallel segments of the same way between the same nodes could add >2 per segment; trim
    return out.sort_values("edge_id").head(max_edges)


def run(settings: Settings, *, refresh: bool = False, force: bool = False) -> RunResult:
    src = settings.processed_dir / "osm_pilot"
    m = read_manifest(src)
    if m is None:
        raise RuntimeError("run `wp-ingest osm` first")
    edges = read_geojson(src / "edges.geojson")
    nodes = read_geojson(src / "nodes.geojson")
    checksum = m["input_checksum"]
    vm = read_manifest(settings.processed_dir / "voirie")
    voirie_used = bool(vm and vm.get("osm_input_checksum") == m["input_checksum"])
    if voirie_used:
        mapping = json.loads(
            (settings.processed_dir / "voirie" / "edge_sidewalk_polygons.json").read_text()
        )
        edges["sidewalk_polygon_ids"] = edges["edge_id"].map(lambda e: mapping.get(e, []))
        checksum = f"{checksum}+{vm['input_checksum']}"

    def build(staging: Path, run_id: str) -> dict:
        sel = select_edges(edges, nodes)
        node_ids = set(sel["from_node_id"]) | set(sel["to_node_id"])
        sel_nodes = nodes[nodes["node_id"].isin(node_ids)].sort_values("node_id")
        write_geojson(sel, staging / "edges.geojson")
        write_geojson(sel_nodes, staging / "nodes.geojson")
        (staging / "ATTRIBUTION.md").write_text(
            ATTRIBUTION + (VOIRIE_ATTRIBUTION if voirie_used else "")
        )
        b = sel.total_bounds
        meta = {
            "simulated": False,
            "description": "Real OSM pedestrian edges around McGill Roddick Gates (WinterPath "
            "pilot_mini fixture).",
            "source_ids": ["osm", "mtl-voirie"] if voirie_used else ["osm"],
            "sidewalk_polygon_ids": "Voirie polygons matched by spatial overlap (enrichment "
            "only; never connectivity)"
            if voirie_used
            else "not enriched (empty lists mean not computed)",
            "osm_snapshot": m["osm_snapshot"],
            "osm_raw_sha256": m.get("raw_sha256"),
            "osm_pipeline_checksum": m["input_checksum"],
            "osm_source": {
                k: (m.get("provenance") or {}).get(k)
                for k in ("provider", "url", "last_modified", "osm_replication_timestamp", "md5")
            },
            "parent_bbox": m["bbox"],
            "bbox": [round(float(x), 6) for x in b],
            "anchor": list(ANCHOR),
            "edge_count": int(len(sel)),
            "node_count": int(len(sel_nodes)),
            "crs": "EPSG:4326",
            "length_crs": "EPSG:32188",
            "id_scheme": "docs/contracts/data-model.md#stable-ids",
            "license": "ODbL-1.0",
        }
        (staging / "metadata.json").write_text(json.dumps(meta, indent=2) + "\n")
        return {
            "stats": {
                "edge_count": meta["edge_count"],
                "node_count": meta["node_count"],
                "bbox": meta["bbox"],
            }
        }

    return run_atomic("pilot_mini", settings.fixtures_dir, checksum, build, force=force)
