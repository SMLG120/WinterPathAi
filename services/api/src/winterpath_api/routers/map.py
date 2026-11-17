"""/hazards and /map/segments (bbox-limited, paginated GeoJSON)."""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Hashable
from datetime import UTC, datetime
from typing import Any

import structlog
from anyio import from_thread
from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel
from winterpath_routing import Hazard, HazardKind, RiskEstimate

from ..cache import (
    caches_for,
    graph_version,
    hazard_version,
    key_digest,
    norm_bbox,
    risk_version,
)
from ..deps import GeoJSONResponse, get_state
from ..errors import ApiError
from ..params import bbox_intersects, paginate_by_id, parse_bbox
from ..schemas import HazardCollection, SegmentCollection
from ..state import AppState

router = APIRouter(tags=["map"])
log = structlog.get_logger("winterpath_api.map")

#: At most this many /map/segments responses are built at once; the rest wait their turn.
#: A segments page is hundreds of features, so each one in flight holds several MiB of
#: short-lived objects. On the 0.1-CPU / 512 MiB instance, six at once left ~160 MiB of freed
#: heap unreturned and starved /health; running them in parallel gains nothing there anyway.
SEGMENTS_MAX_CONCURRENT = 2
_segments_slots = threading.BoundedSemaphore(SEGMENTS_MAX_CONCURRENT)

#: status logged (never received) when the client left before its segments page was built
CLIENT_CLOSED = 499


class _ClientGone(Exception):
    """The client disconnected while its request waited for a build slot."""


def render(model: BaseModel, response_class: type[Response] = GeoJSONResponse) -> bytes:
    """The body FastAPI would send for ``model`` under ``response_model_exclude_unset=True``."""
    content = model.model_dump(mode="json", by_alias=True, exclude_unset=True)
    return response_class(content=content).body


def _body(body: bytes) -> Response:
    return Response(content=body, media_type=GeoJSONResponse.media_type)


CROSSING_TYPES = {"marked", "traffic_signals", "unmarked", "uncontrolled"}
KERBS = {"lowered", "flush", "raised"}
EDGE_KINDS = {
    "sidewalk",
    "footway",
    "path",
    "pedestrian_street",
    "crossing",
    "shared_street",
    "steps",
    "other",
}


def hazard_feature(h: Hazard) -> dict[str, Any]:
    props: dict[str, Any] = {
        "kind": h.kind.value,
        "evidence": h.evidence.to_dict(),
        "blocks_passage": h.blocks_passage,
        "valid_from": h.valid_from,
        "valid_to": h.valid_to,
    }
    if h.title_en:
        props["title_en"] = h.title_en
    if h.title_fr:
        props["title_fr"] = h.title_fr
    if h.kind is HazardKind.REPORT_311_AGGREGATE:
        props["report_count"] = h.report_count
    return {"type": "Feature", "id": h.hazard_id, "geometry": h.geometry, "properties": props}


def _parse_kinds(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    kinds = {k.strip() for k in raw.split(",") if k.strip()}
    valid = {k.value for k in HazardKind}
    bad = kinds - valid
    if bad:
        raise ApiError(400, "VALIDATION_ERROR", f"Unknown hazard kind(s): {sorted(bad)}.")
    return kinds


class _HazardIndex:
    """STR-tree over one hazard list's geometries (built once per hazard-list version): a bbox
    query then tests only nearby hazards instead of parsing every geometry per request."""

    def __init__(self, hazards: list[Hazard]) -> None:
        from shapely import STRtree
        from shapely.geometry import shape

        self.hazards = hazards
        self.tree = STRtree([shape(h.geometry) for h in hazards])

    def select(self, box: tuple[float, float, float, float]) -> list[Hazard]:
        from shapely.geometry import box as mkbox

        idx = sorted(int(i) for i in self.tree.query(mkbox(*box), predicate="intersects"))
        return [self.hazards[i] for i in idx]


_HAZARD_INDEX_SLOTS = 2
_hazard_indexes: OrderedDict[Hashable, _HazardIndex] = OrderedDict()
_hazard_index_lock = threading.Lock()


def _hazards_in(
    hazards: list[Hazard], version: Hashable | None, box: tuple[float, float, float, float]
) -> list[Hazard]:
    if version is None:  # no identity for this list: plain scan, as before
        return [h for h in hazards if bbox_intersects(h.geometry, box)]
    with _hazard_index_lock:
        ix = _hazard_indexes.get(version)
        if ix is not None:
            _hazard_indexes.move_to_end(version)
    if ix is None:
        ix = _HazardIndex(hazards)
        with _hazard_index_lock:
            _hazard_indexes[version] = ix
            while len(_hazard_indexes) > _HAZARD_INDEX_SLOTS:
                _hazard_indexes.popitem(last=False)
    return ix.select(box)


@router.get(
    "/hazards",
    response_model=HazardCollection,
    response_model_exclude_unset=True,
    response_class=GeoJSONResponse,
)
def list_hazards(
    request: Request,
    bbox: str | None = Query(None),
    kind: str | None = Query(None),
    limit: int = Query(500, ge=1, le=1000),
    cursor: str | None = Query(None),
    state: AppState = Depends(get_state),
) -> Response:
    box = parse_bbox(bbox, state.coverage_bbox)
    kinds = _parse_kinds(kind)
    now = datetime.now(UTC)
    try:
        hazards, version = hazard_version(state.hazards, now)
    except Exception as exc:
        raise ApiError(503, "UPSTREAM_UNAVAILABLE", "Hazard store unavailable.") from exc

    def build() -> tuple[bytes, dict[str, Any]]:
        sel = [
            h for h in _hazards_in(hazards, version, box) if kinds is None or h.kind.value in kinds
        ]
        page, nxt = paginate_by_id(sel, lambda h: h.hazard_id, limit, cursor)
        model = HazardCollection.model_validate(
            {
                "type": "FeatureCollection",
                "features": [hazard_feature(h) for h in page],
                "next_cursor": nxt,
            }
        )
        return render(model), {}

    caches = caches_for(request.app.state, state)
    if not caches.enabled or version is None:
        return _body(build()[0])
    key = (
        "hazards",
        version,
        norm_bbox(box),
        tuple(sorted(kinds)) if kinds is not None else None,
        limit,
        cursor,
    )
    entry, hit = caches.hazards.get_or_build(key, build)
    if hit:
        log.debug("cache_hit", cache="hazards", key=key_digest(key))
    return _body(entry.body)


@router.get(
    "/map/segments",
    response_model=SegmentCollection,
    response_model_exclude_unset=True,
    response_class=GeoJSONResponse,
)
async def list_segments(
    request: Request,
    bbox: str | None = Query(None),
    limit: int = Query(500, ge=1, le=1000),
    cursor: str | None = Query(None),
    state: AppState = Depends(get_state),
) -> Response:
    box = parse_bbox(bbox, state.coverage_bbox)
    if state.engine is None:
        raise ApiError(503, "UPSTREAM_UNAVAILABLE", "No pedestrian graph is loaded.")
    caches = caches_for(request.app.state, state)

    def build() -> tuple[bytes, dict[str, Any]]:
        with _segments_slots:
            # The page waited for a slot: if its viewer has already panned away (the web client
            # aborts obsolete viewport requests), don't spend the 0.1 CPU building it.
            if from_thread.run(request.is_disconnected):
                raise _ClientGone
            return render(_segments(state, box, limit, cursor)), {}

    def lookup() -> tuple[bytes, bool]:
        key = None
        if caches.enabled:
            now = datetime.now(UTC)
            gv, rv = graph_version(state), risk_version(state.risk, now)
            if gv is not None and rv is not None:
                key = ("segments", gv, rv, norm_bbox(box), limit, cursor)
        if key is None:
            return build()[0], False
        entry, hit = caches.segments.get_or_build(key, build)
        if hit:
            log.debug("cache_hit", cache="segments", key=key_digest(key))
        return entry.body, hit

    try:
        body, _hit = await run_in_threadpool(lookup)
    except _ClientGone:
        return Response(status_code=CLIENT_CLOSED)
    return _body(body)


def _segments(
    state: AppState, box: tuple[float, float, float, float], limit: int, cursor: str | None
) -> SegmentCollection:
    g = state.engine.graph
    # Non-walkable edges (foot_access no/private) are never presented as pedestrian segments.
    if hasattr(g, "legal"):  # compact graph: filter on its array, no Edge object per candidate
        ids = g.edges_in_bbox(*box, foot_legal_only=True)
    else:
        ids = [eid for eid in g.edges_in_bbox(*box) if g.edges[eid].foot_legal]
    page, nxt = paginate_by_id(ids, lambda x: x, limit, cursor)
    risk = state.risk.edge_risk(page, datetime.now(UTC)) if page else {}
    feats = []
    for eid in page:
        e = g.edges[eid]
        est = risk.get(eid) or RiskEstimate.unknown()
        sources = list(e.source_ids)
        if g.metadata.simulated:
            # SIMULATED graph: the segment's source list says so explicitly.
            sources = sorted(set(sources) | {"synthetic"})
        props: dict[str, Any] = {
            "length_m": round(e.length_m, 2),
            "edge_kind": e.edge_kind if e.edge_kind in EDGE_KINDS else "other",
            "connectivity_confidence": e.connectivity_confidence
            if e.connectivity_confidence in ("high", "medium", "low")
            else "low",
            "accessibility": {
                "step_free": e.step_free,
                "incline_percent": e.incline_percent,
                "width_m": e.width_m,
                "surface": e.surface,
            },
            "risk": est.to_dict(),
            "sources": sources,
            "updated_at": e.updated_at,
        }
        if e.edge_kind == "crossing":
            props["crossing"] = {
                "type": e.crossing_type if e.crossing_type in CROSSING_TYPES else "unknown",
                "kerb": e.kerb if e.kerb in KERBS else "unknown",
            }
        feats.append(
            {
                "type": "Feature",
                "id": eid,
                "geometry": {"type": "LineString", "coordinates": [list(c) for c in e.coords]},
                "properties": props,
            }
        )
    return SegmentCollection.model_validate(
        {"type": "FeatureCollection", "features": feats, "next_cursor": nxt}
    )
