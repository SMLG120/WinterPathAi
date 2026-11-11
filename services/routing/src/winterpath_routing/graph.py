"""In-memory pedestrian graph: NetworkX MultiDiGraph + projected geometries + spatial index.

Connectivity comes only from the provider's node ids (OSM topology or a documented snap rule
applied upstream). This module never invents edges between lines.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import networkx as nx
from shapely import STRtree
from shapely.geometry import LineString, Point, box
from shapely.geometry.base import BaseGeometry

from .geo import line_to_metric, point_to_metric, to_wgs84_lonlat
from .models import Edge, GraphData, GraphMetadata, Node


@dataclass(frozen=True, slots=True)
class Gap:
    """A disconnected part of the network (reported, never bridged)."""

    description: str
    lon: float
    lat: float
    edge_count: int


class GraphIntegrityError(ValueError):
    pass


class PedestrianGraph:
    def __init__(self, data: GraphData) -> None:
        self.metadata: GraphMetadata = data.metadata
        self.nodes: dict[str, Node] = dict(data.nodes)
        self.edges: dict[str, Edge] = {}
        self.g = nx.MultiDiGraph()

        for node in self.nodes.values():
            self.g.add_node(node.node_id)
        for e in data.edges:
            if e.edge_id in self.edges:
                raise GraphIntegrityError(f"duplicate edge_id {e.edge_id}")
            if e.from_node_id not in self.nodes or e.to_node_id not in self.nodes:
                raise GraphIntegrityError(f"edge {e.edge_id} references unknown node")
            if e.length_m <= 0 or len(e.coords) < 2:
                raise GraphIntegrityError(f"edge {e.edge_id} has non-positive length/geometry")
            self.edges[e.edge_id] = e
            self.g.add_edge(e.from_node_id, e.to_node_id, key=e.edge_id)

        self._edge_order: list[str] = list(self.edges)
        self.metric_lines: dict[str, LineString] = {
            eid: line_to_metric(self.edges[eid].coords) for eid in self._edge_order
        }
        self._tree = STRtree([self.metric_lines[eid] for eid in self._edge_order])
        self._wgs_tree = STRtree([LineString(self.edges[eid].coords) for eid in self._edge_order])

        self._node_xy: dict[str, tuple[float, float]] = {
            nid: tuple(point_to_metric(n.lon, n.lat).coords[0]) for nid, n in self.nodes.items()
        }
        self._compute_components()

    # ------------------------------------------------------------------ components
    def _compute_components(self) -> None:
        legal = nx.MultiDiGraph()
        legal.add_nodes_from(self.g.nodes)
        for e in self.edges.values():
            if e.foot_legal:
                legal.add_edge(e.from_node_id, e.to_node_id, key=e.edge_id)
        comps = sorted(
            (
                c
                for c in nx.weakly_connected_components(legal)
                if legal.subgraph(c).number_of_edges()
            ),
            key=lambda c: (-legal.subgraph(c).number_of_edges(), min(c)),
        )
        self.components: list[set[str]] = [set(c) for c in comps]
        main_nodes = self.components[0] if self.components else set()
        self.main_component_edge_ids: frozenset[str] = frozenset(
            e.edge_id
            for e in self.edges.values()
            if e.foot_legal and e.from_node_id in main_nodes and e.to_node_id in main_nodes
        )
        legal_edges = sum(1 for e in self.edges.values() if e.foot_legal)
        self.largest_component_share: float = (
            len(self.main_component_edge_ids) / legal_edges if legal_edges else 0.0
        )

    def gaps(self) -> list[Gap]:
        out: list[Gap] = []
        for comp in self.components[1:]:
            pts = [self.nodes[n] for n in comp]
            lon = sum(p.lon for p in pts) / len(pts)
            lat = sum(p.lat for p in pts) / len(pts)
            n_edges = sum(1 for e in self.edges.values() if e.foot_legal and e.from_node_id in comp)
            out.append(
                Gap(
                    description=(
                        f"Disconnected pedestrian sub-network ({n_edges} directed edges) not "
                        "reachable from the main network; not used for routing."
                    ),
                    lon=lon,
                    lat=lat,
                    edge_count=n_edges,
                )
            )
        return out

    # ------------------------------------------------------------------ spatial queries
    def edges_near_metric(self, geom: BaseGeometry, tolerance_m: float) -> list[str]:
        idx = self._tree.query(geom, predicate="dwithin", distance=tolerance_m)
        return [self._edge_order[i] for i in sorted(idx)]

    def edges_in_bbox(self, west: float, south: float, east: float, north: float) -> list[str]:
        idx = self._wgs_tree.query(box(west, south, east, north), predicate="intersects")
        return sorted(self._edge_order[i] for i in idx)

    def nearest_edges(
        self, lon: float, lat: float, max_m: float, allowed: Iterable[str] | None = None
    ) -> tuple[list[str], float, Point]:
        """Edges at the minimum distance (≤ ``max_m``) from the point, among ``allowed``.

        Returns all edges within 1 cm of the minimum so both directions of a two-way footway are
        candidates. ``([], inf, p)`` when none qualifies.
        """
        p = point_to_metric(lon, lat)
        if allowed is None or isinstance(allowed, (set, frozenset)):
            allowed_set = allowed  # no per-request copy of a 16k-edge set
        else:
            allowed_set = set(allowed)
        idx = self._tree.query(p, predicate="dwithin", distance=max_m)
        best: list[tuple[float, str]] = []
        for i in idx:
            eid = self._edge_order[i]
            if allowed_set is not None and eid not in allowed_set:
                continue
            best.append((self.metric_lines[eid].distance(p), eid))
        if not best:
            return [], float("inf"), p
        dmin = min(d for d, _ in best)
        return sorted(eid for d, eid in best if d <= dmin + 0.01), dmin, p

    def node_xy(self, node_id: str) -> tuple[float, float]:
        return self._node_xy[node_id]

    @staticmethod
    def metric_to_lonlat(x: float, y: float) -> tuple[float, float]:
        return to_wgs84_lonlat(x, y)
