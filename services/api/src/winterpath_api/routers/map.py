"""/hazards and /map/segments (bbox-limited, paginated GeoJSON)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from winterpath_routing import Hazard, HazardKind, RiskEstimate

from ..deps import GeoJSONResponse, get_state
from ..errors import ApiError
from ..params import bbox_intersects, paginate_by_id, parse_bbox
from ..schemas import HazardCollection, SegmentCollection
from ..state import AppState

router = APIRouter(tags=["map"])

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


@router.get(
    "/hazards",
    response_model=HazardCollection,
    response_model_exclude_unset=True,
    response_class=GeoJSONResponse,
)
def list_hazards(
    bbox: str | None = Query(None),
    kind: str | None = Query(None),
    limit: int = Query(500, ge=1, le=1000),
    cursor: str | None = Query(None),
    state: AppState = Depends(get_state),
) -> HazardCollection:
    box = parse_bbox(bbox)
    kinds = _parse_kinds(kind)
    now = datetime.now(UTC)
    try:
        hazards = state.hazards.list(now)
    except Exception as exc:
        raise ApiError(503, "UPSTREAM_UNAVAILABLE", "Hazard store unavailable.") from exc
    sel = [
        h
        for h in hazards
        if (kinds is None or h.kind.value in kinds) and bbox_intersects(h.geometry, box)
    ]
    page, nxt = paginate_by_id(sel, lambda h: h.hazard_id, limit, cursor)
    return HazardCollection.model_validate(
        {
            "type": "FeatureCollection",
            "features": [hazard_feature(h) for h in page],
            "next_cursor": nxt,
        }
    )


@router.get(
    "/map/segments",
    response_model=SegmentCollection,
    response_model_exclude_unset=True,
    response_class=GeoJSONResponse,
)
def list_segments(
    bbox: str | None = Query(None),
    limit: int = Query(500, ge=1, le=1000),
    cursor: str | None = Query(None),
    state: AppState = Depends(get_state),
) -> SegmentCollection:
    box = parse_bbox(bbox)
    if state.engine is None:
        raise ApiError(503, "UPSTREAM_UNAVAILABLE", "No pedestrian graph is loaded.")
    g = state.engine.graph
    # Non-walkable edges (foot_access no/private) are never presented as pedestrian segments.
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
