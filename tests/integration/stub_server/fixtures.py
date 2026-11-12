"""Canned STUB payloads. Every value here is schema-shaped test scaffolding, NOT real data.

Wherever the contract carries an `evidence` object the state is `simulated`, and every
human-readable string says STUB/SIMULATED. Nothing here describes real conditions in Montréal.
The only real values are contract constants (pilot bbox from docs/architecture.md §3).
"""

from __future__ import annotations

import math
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

STUB_VERSION = "stub-0.1.0"
STUB_LABEL = "STUB SERVER — SIMULATED payload for contract testing only"

# docs/architecture.md §3 (contract constant).
PILOT_BBOX = (-73.5880, 45.4960, -73.5620, 45.5130)
MAX_BBOX_AREA_DEG2 = 0.0025  # openapi.yaml components.parameters.Bbox


def now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso(dt: datetime | None = None) -> str:
    return (dt or now()).isoformat().replace("+00:00", "Z")


def simulated_evidence(note: str = STUB_LABEL) -> dict[str, Any]:
    return {
        "state": "simulated",
        "source_ids": ["stub"],
        "observed_at": None,
        "retrieved_at": iso(),
        "confidence": None,
        "note": note,
    }


def health() -> dict[str, Any]:
    return {
        "status": "degraded",
        "version": STUB_VERSION,
        "checks": {
            "stub": {"status": "ok", "detail": STUB_LABEL},
            "database": {"status": "disabled", "detail": "stub has no database"},
            "graph": {"status": "disabled", "detail": "stub has no routing graph"},
            "risk_layer": {"status": "disabled", "detail": "stub has no model"},
        },
    }


def coverage() -> dict[str, Any]:
    w, s, e, n = PILOT_BBOX
    return {
        "pilot_name": "McGill / Downtown pilot",
        "bbox": [w, s, e, n],
        "area": {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]},
        "graph": {"node_count": 0, "edge_count": 0, "built_at": None, "osm_snapshot": None},
        "known_gaps": [{"description": f"{STUB_LABEL}: no graph is loaded", "geometry": None}],
    }


def model_status() -> dict[str, Any]:
    return {
        "risk_layer": "none",
        "enabled": False,
        "model_id": None,
        "target": "P(>=1 winter-related 311 report in H3 res-9 cell within next 24h)",
        "trained_at": None,
        "training_window": None,
        "evaluation": None,
        "limitations": [STUB_LABEL],
    }


def _bbox_center(bbox: tuple[float, float, float, float]) -> list[float]:
    return [round((bbox[0] + bbox[2]) / 2, 6), round((bbox[1] + bbox[3]) / 2, 6)]


def hazards(bbox: tuple[float, float, float, float]) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "stub:hazard:0",
                "geometry": {"type": "Point", "coordinates": _bbox_center(bbox)},
                "properties": {
                    "kind": "community_report",
                    "evidence": simulated_evidence(),
                    "blocks_passage": None,
                    "title_en": "SIMULATED stub hazard",
                    "title_fr": "Danger SIMULÉ (serveur de test)",
                    "valid_from": None,
                    "valid_to": None,
                    "report_count": None,
                },
            }
        ],
        "next_cursor": None,
    }


def segments(bbox: tuple[float, float, float, float]) -> dict[str, Any]:
    w, s, e, n = bbox
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "stub:a>stub:b:0",
                "geometry": {"type": "LineString", "coordinates": [[w, s], [e, n]]},
                "properties": {
                    "length_m": 0,
                    "edge_kind": "other",
                    "crossing": None,
                    "connectivity_confidence": "low",
                    "accessibility": {
                        "step_free": None,
                        "incline_percent": None,
                        "width_m": None,
                        "surface": None,
                    },
                    "risk": {"level": "unknown", "probability": None, "evidence": simulated_evidence()},
                    "sources": ["stub"],
                    "updated_at": None,
                },
            }
        ],
        "next_cursor": None,
    }


def _haversine_m(a: dict[str, float], b: dict[str, float]) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def route_compare(origin: dict[str, float], destination: dict[str, float], request_id: str) -> dict[str, Any]:
    """A straight segment between the endpoints. NOT a route: no graph, no connectivity."""
    d = _haversine_m(origin, destination)
    return {
        "request_id": request_id,
        "routes": [
            {
                "variant": "shortest",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[origin["lon"], origin["lat"]], [destination["lon"], destination["lat"]]],
                },
                "distance_m": d,
                "duration_s": d / 1.3,
                "edge_ids": [],
                "unknown_share": 1.0,
                "explanation": [
                    {"code": "STUB_SIMULATED_RESPONSE", "text": STUB_LABEL, "evidence_state": "simulated"}
                ],
                "data_freshness": {"stub": None},
            }
        ],
        "risk_layer": "none",
        "computed_at": iso(),
        "weather_context": None,  # v1.8: stub has no forecast source
        "warnings": [STUB_LABEL, "SIMULATED straight line — not a walkable route"],
    }


def report_receipt(report_id: str) -> dict[str, Any]:
    return {
        "id": report_id,
        "status": "pending",
        "expires_at": iso(now() + timedelta(hours=72)),
        "deletion_token": secrets.token_urlsafe(32),
    }


def in_pilot(lon: float, lat: float) -> bool:
    w, s, e, n = PILOT_BBOX
    return w <= lon <= e and s <= lat <= n


# v1.8 /data-status. Mechanisms per docs/agents/v2-plan.md (routing item 3). The stub has no data
# source, so every product is `unavailable`; it never claims a last success or a cadence.
DATA_PRODUCT_MECHANISM: dict[str, str] = {
    "weather_observations": "scheduled_job",
    "weather_forecast": "api_on_demand",
    "weather_alerts": "api_on_demand",
    "closures": "manual",
    "reports_311": "manual",
    "risk_scores": "scheduled_job",
    "pedestrian_graph": "manual",
}


def data_status() -> dict[str, Any]:
    t = iso()
    return {
        "generated_at": t,
        "products": [
            {
                "id": pid,
                "freshness": {"state": "unavailable", "reason": f"{STUB_LABEL}: no data source connected", "evaluated_at": t},
                "last_success_at": None,
                "expected_cadence": None,
                "mechanism": mech,
                "notes": STUB_LABEL,
            }
            for pid, mech in DATA_PRODUCT_MECHANISM.items()
        ],
    }
