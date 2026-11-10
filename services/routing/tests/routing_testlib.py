"""Test helpers (importable by unique name). All data here is SYNTHETIC."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from winterpath_routing import (
    Edge,
    Evidence,
    EvidenceState,
    GraphData,
    GraphMetadata,
    Node,
    PedestrianGraph,
    RiskEstimate,
    RiskLevel,
)
from winterpath_routing.geo import metric_length_m

TOY_DIR = Path(__file__).parent / "fixtures" / "synthetic" / "toy_grid"
AT = datetime(2026, 12, 15, 8, 0, tzinfo=UTC)
LON0, LAT0, DLON, DLAT = -73.5780, 45.5030, 0.0010, 0.0007


def grid_node(r: int, c: int) -> tuple[float, float]:
    return (LON0 + c * DLON, LAT0 + r * DLAT)


def gid(r: int, c: int) -> str:
    return f"syn:r{r}c{c}"


def eid(a: str, b: str) -> str:
    return f"{a}>{b}:0"


class StaticRiskProvider:
    """Test provider returning fixed levels; unspecified edges are omitted (→ unknown)."""

    def __init__(
        self,
        levels: Mapping[str, RiskLevel],
        state: EvidenceState = EvidenceState.MODEL_ESTIMATE,
        layer: str = "heuristic",
    ) -> None:
        self.levels = dict(levels)
        self.state = state
        self.risk_layer = layer

    def edge_risk(self, edge_ids: Sequence[str], at: datetime) -> Mapping[str, RiskEstimate]:
        return {
            eid: RiskEstimate(self.levels[eid], Evidence(self.state, ("test",)))
            for eid in edge_ids
            if eid in self.levels
        }


def build_graph(
    nodes: Mapping[str, tuple[float, float]],
    edges: Sequence[tuple[str, str, dict]],
) -> PedestrianGraph:
    ns = {k: Node(k, lon, lat, kind="synthetic") for k, (lon, lat) in nodes.items()}
    es: list[Edge] = []
    for u, v, props in edges:
        props = dict(props)
        oneway = props.pop("oneway", False)
        pairs = [(u, v)] if oneway else [(u, v), (v, u)]
        for a, b in pairs:
            coords = (nodes[a], nodes[b])
            es.append(
                Edge(
                    edge_id=f"{a}>{b}:0",
                    from_node_id=a,
                    to_node_id=b,
                    coords=coords,
                    length_m=metric_length_m(coords),
                    edge_kind=props.get("edge_kind", "footway"),
                    foot_access=props.get("foot_access", "yes"),
                    step_free=props.get("step_free"),
                    lit=props.get("lit"),
                    name=props.get("name"),
                    source_ids=("synthetic",),
                )
            )
    return PedestrianGraph(GraphData(ns, es, GraphMetadata(simulated=True)))


PILOT_MINI = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "pilot_mini"

OSM_SOURCE_ROW = {
    "source_id": "osm",
    "name": "OpenStreetMap data",
    "publisher": "OpenStreetMap Foundation / contributors",
    "license": "ODbL 1.0",
    "license_url": "https://opendatacommons.org/licenses/odbl/1-0/",
    "commercial_use": "allowed_with_conditions",
    "attribution": "© OpenStreetMap contributors (ODbL)",
    "url": "https://www.openstreetmap.org/copyright",
    "status": "active",
}


def load_pilot_mini_into_postgis(conn, fixture_dir: Path = PILOT_MINI) -> None:
    """Insert the REAL pilot_mini fixture into wp.node / wp.edge (own test DB only)."""
    import json as _json

    from sqlalchemy import text

    conn.execute(
        text(
            "INSERT INTO wp.source (source_id, name, publisher, license, license_url,"
            " commercial_use, attribution, url, status) VALUES (:source_id, :name, :publisher,"
            " :license, :license_url, :commercial_use, :attribution, :url, :status)"
            " ON CONFLICT (source_id) DO NOTHING"
        ),
        OSM_SOURCE_ROW,
    )
    nodes = _json.loads((fixture_dir / "nodes.geojson").read_text())["features"]
    edges = _json.loads((fixture_dir / "edges.geojson").read_text())["features"]
    conn.execute(
        text(
            "INSERT INTO wp.node (node_id, geom, kind, crossing_type, kerb, source_id) VALUES"
            " (:id, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :kind, :ct, :kerb, 'osm')"
        ),
        [
            {
                "id": f["properties"]["node_id"],
                "lon": f["geometry"]["coordinates"][0],
                "lat": f["geometry"]["coordinates"][1],
                "kind": f["properties"].get("kind") or "street_node",
                "ct": f["properties"].get("crossing_type"),
                "kerb": f["properties"].get("kerb"),
            }
            for f in nodes
        ],
    )
    conn.execute(
        text(
            "INSERT INTO wp.edge (edge_id, from_node_id, to_node_id, geom, length_m, edge_kind,"
            " foot_access, step_free, lit, surface, connectivity_confidence, component_id,"
            " source_id) VALUES (:id, :u, :v, ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326), :len,"
            " :kind, :foot, :sf, :lit, :surface, :conf, :comp, 'osm')"
        ),
        [
            {
                "id": f["properties"]["edge_id"],
                "u": f["properties"]["from_node_id"],
                "v": f["properties"]["to_node_id"],
                "g": _json.dumps(f["geometry"]),
                "len": f["properties"]["length_m"],
                "kind": f["properties"]["edge_kind"],
                "foot": f["properties"]["foot_access"],
                "sf": f["properties"].get("step_free"),
                "lit": f["properties"].get("lit"),
                "surface": f["properties"].get("surface"),
                "conf": f["properties"]["connectivity_confidence"],
                "comp": f["properties"].get("component_id"),
            }
            for f in edges
        ],
    )


def delete_pilot_mini_from_postgis(conn, fixture_dir: Path = PILOT_MINI) -> None:
    import json as _json

    from sqlalchemy import text

    eids = [
        f["properties"]["edge_id"]
        for f in _json.loads((fixture_dir / "edges.geojson").read_text())["features"]
    ]
    nids = [
        f["properties"]["node_id"]
        for f in _json.loads((fixture_dir / "nodes.geojson").read_text())["features"]
    ]
    conn.execute(text("DELETE FROM wp.edge WHERE edge_id = ANY(:ids)"), {"ids": eids})
    conn.execute(text("DELETE FROM wp.node WHERE node_id = ANY(:ids)"), {"ids": nids})
