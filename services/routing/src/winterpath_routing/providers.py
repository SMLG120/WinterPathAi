"""GraphProvider interface + implementations (integration-rules §2).

* :class:`FixtureGraphProvider` reads the ``data/fixtures/pilot_mini`` layout
  (``edges.geojson``, ``nodes.geojson``, ``metadata.json``) — or any directory with the same layout,
  e.g. the synthetic test fixture.
* :class:`PostgisGraphProvider` reads ``wp.edge`` / ``wp.node`` (data-model.md). Requires the
  ``postgis`` extra.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .geo import metric_length_m
from .models import Edge, GraphData, GraphMetadata, Node


@runtime_checkable
class GraphProvider(Protocol):
    def load(self) -> GraphData: ...


class GraphUnavailableError(RuntimeError):
    """No graph could be loaded (missing fixture / DB down). Never replaced by invented data."""


def _parse_dt(v: Any) -> datetime | None:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def _opt_bool(v: Any) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("true", "yes", "1"):
        return True
    if s in ("false", "no", "0"):
        return False
    return None


def _opt_float(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def edge_from_properties(edge_id: str, coords: list, props: dict[str, Any]) -> Edge:
    coords_t = tuple((float(c[0]), float(c[1])) for c in coords)
    length = _opt_float(props.get("length_m"))
    if length is None:
        length = metric_length_m(coords_t)
    # Crossing metadata: nested {"crossing": {"type", "kerb"}} (pilot_mini fixture) or flat
    # columns crossing_type / crossing_kerb (wp.edge, data-model v1.2) / kerb.
    crossing = props.get("crossing") if isinstance(props.get("crossing"), dict) else {}
    crossing_type = props.get("crossing_type") or crossing.get("type")
    kerb = props.get("crossing_kerb") or props.get("kerb") or crossing.get("kerb")
    src = props.get("source_ids") or props.get("sources")
    if src is None:
        src = [props["source_id"]] if props.get("source_id") else ["osm"]
    return Edge(
        edge_id=edge_id,
        from_node_id=str(props["from_node_id"]),
        to_node_id=str(props["to_node_id"]),
        coords=coords_t,
        length_m=float(length),
        edge_kind=str(props.get("edge_kind") or "other"),
        foot_access=str(props.get("foot_access") or "unknown"),
        step_free=_opt_bool(props.get("step_free")),
        incline_percent=_opt_float(props.get("incline_percent")),
        width_m=_opt_float(props.get("width_m")),
        surface=props.get("surface"),
        lit=_opt_bool(props.get("lit")),
        name=props.get("name"),
        connectivity_confidence=str(props.get("connectivity_confidence") or "low"),
        component_id=props.get("component_id"),
        source_ids=tuple(str(s) for s in src),
        updated_at=_parse_dt(props.get("updated_at")),
        crossing_type=crossing_type,
        kerb=kerb,
    )


class FixtureGraphProvider:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def load(self) -> GraphData:
        d = self.directory
        try:
            edges_fc = json.loads((d / "edges.geojson").read_text())
            nodes_fc = json.loads((d / "nodes.geojson").read_text())
            meta = json.loads((d / "metadata.json").read_text())
        except FileNotFoundError as exc:
            raise GraphUnavailableError(f"graph fixture incomplete in {d}: {exc.filename}") from exc

        if "simulated" not in meta:
            raise GraphUnavailableError("fixture metadata.json must state 'simulated' explicitly")

        nodes: dict[str, Node] = {}
        for f in nodes_fc["features"]:
            p = f.get("properties") or {}
            nid = str(f.get("id") or p["node_id"])
            lon, lat = f["geometry"]["coordinates"][:2]
            nodes[nid] = Node(
                node_id=nid,
                lon=float(lon),
                lat=float(lat),
                kind=str(p.get("kind") or "street_node"),
                crossing_type=p.get("crossing_type"),
                kerb=p.get("kerb"),
            )

        edges = []
        for f in edges_fc["features"]:
            p = f.get("properties") or {}
            eid = str(f.get("id") or p["edge_id"])
            edges.append(
                _with_node_crossing(
                    edge_from_properties(eid, f["geometry"]["coordinates"], p), nodes
                )
            )

        manifest: dict[str, Any] = {}
        if (d / "manifest.json").exists():
            manifest = json.loads((d / "manifest.json").read_text())
        freshness = {k: _parse_dt(v) for k, v in (meta.get("source_freshness") or {}).items()}
        snapshot = meta.get("osm_snapshot") or meta.get("snapshot")
        if "osm" not in freshness and snapshot:
            freshness["osm"] = _parse_dt(snapshot) if _looks_like_dt(snapshot) else None
        return GraphData(
            nodes=nodes,
            edges=edges,
            metadata=GraphMetadata(
                simulated=bool(meta["simulated"]),
                osm_snapshot=str(snapshot) if snapshot else None,
                built_at=_parse_dt(meta.get("built_at") or manifest.get("finished_at")),
                source_freshness=freshness,
                description=str(meta.get("description") or ""),
            ),
        )


def _looks_like_dt(v: Any) -> bool:
    try:
        _parse_dt(v)
        return True
    except ValueError:
        return False


def _with_node_crossing(edge: Edge, nodes: dict[str, Node]) -> Edge:
    """Crossing edges inherit crossing type/kerb from their crossing nodes if unset on the edge."""
    if edge.edge_kind != "crossing" or (edge.crossing_type and edge.kerb):
        return edge
    ct, kerb = edge.crossing_type, edge.kerb
    for nid in (edge.from_node_id, edge.to_node_id):
        n = nodes.get(nid)
        if n is None:
            continue
        ct = ct or n.crossing_type
        kerb = kerb or n.kerb
    if (ct, kerb) == (edge.crossing_type, edge.kerb):
        return edge
    from dataclasses import replace

    return replace(edge, crossing_type=ct, kerb=kerb)


class PostgisGraphProvider:
    """Loads the pilot graph from PostGIS (schema ``wp``, data-model.md v1)."""

    EDGE_SQL = """
        SELECT e.edge_id, e.from_node_id, e.to_node_id, ST_AsGeoJSON(e.geom) AS geom,
               e.length_m, e.edge_kind, e.foot_access, e.step_free, e.incline_percent,
               e.width_m, e.surface, e.lit, e.connectivity_confidence, e.component_id,
               e.source_id, e.updated_at{optional}
        FROM wp.edge e
        WHERE e.geom && ST_MakeEnvelope(:west, :south, :east, :north, 4326)
    """
    NODE_SQL = """
        SELECT n.node_id, ST_X(n.geom) AS lon, ST_Y(n.geom) AS lat, n.kind, n.crossing_type, n.kerb
        FROM wp.node n
        WHERE n.geom && ST_MakeEnvelope(:west, :south, :east, :north, 4326)
    """
    SOURCE_SQL = "SELECT source_id, last_success_at FROM wp.source"
    #: data-model v1.2 columns; selected only if the applied migrations created them
    OPTIONAL_EDGE_COLS = ("crossing_type", "crossing_kerb", "name")  # v1.2 / v1.3, when migrated
    COLUMNS_SQL = (
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'wp' AND table_name = 'edge'"
    )

    def __init__(self, database_url: str, bbox: tuple[float, float, float, float]) -> None:
        self.database_url = database_url
        self.bbox = bbox

    def load(self) -> GraphData:
        try:
            from sqlalchemy import create_engine, text
        except ImportError as exc:  # pragma: no cover - depends on extras
            raise GraphUnavailableError("install winterpath-routing[postgis]") from exc
        w, s, e, n = self.bbox
        params = {"west": w, "south": s, "east": e, "north": n}
        try:
            engine = create_engine(self.database_url, pool_pre_ping=True)
            with engine.connect() as conn:
                present = {r[0] for r in conn.execute(text(self.COLUMNS_SQL))}
                optional = "".join(f", e.{c}" for c in self.OPTIONAL_EDGE_COLS if c in present)
                node_rows = conn.execute(text(self.NODE_SQL), params).mappings().all()
                edge_sql = self.EDGE_SQL.format(optional=optional)
                edge_rows = conn.execute(text(edge_sql), params).mappings().all()
                src_rows = conn.execute(text(self.SOURCE_SQL)).mappings().all()
        except Exception as exc:
            raise GraphUnavailableError(f"PostGIS graph unavailable: {type(exc).__name__}") from exc

        nodes = {
            r["node_id"]: Node(
                node_id=r["node_id"],
                lon=float(r["lon"]),
                lat=float(r["lat"]),
                kind=r["kind"] or "street_node",
                crossing_type=r["crossing_type"],
                kerb=r["kerb"],
            )
            for r in node_rows
        }
        edges = []
        for r in edge_rows:
            # Edges crossing the bbox boundary may reference nodes outside it: skip, don't invent.
            if r["from_node_id"] not in nodes or r["to_node_id"] not in nodes:
                continue
            props = dict(r)
            coords = json.loads(props.pop("geom"))["coordinates"]
            edges.append(
                _with_node_crossing(edge_from_properties(r["edge_id"], coords, props), nodes)
            )
        freshness = {r["source_id"]: r["last_success_at"] for r in src_rows}
        built = max((e.updated_at for e in edges if e.updated_at), default=None)
        return GraphData(
            nodes=nodes,
            edges=edges,
            metadata=GraphMetadata(
                simulated=False,
                osm_snapshot=freshness["osm"].isoformat() if freshness.get("osm") else None,
                built_at=built,
                source_freshness=freshness,
                description="PostGIS wp.edge/wp.node",
            ),
        )
