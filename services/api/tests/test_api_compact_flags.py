"""Wave 1 prototypes behind flags (default OFF): ROUTING_COMPACT_GRAPH and ROUTING_STEPS_V2.

With the compact graph ON every endpoint answers exactly as with it OFF (real pilot_mini OSM
fixture). Steps v2 changes only the steps list, and keeps the contract shape."""

from __future__ import annotations

from api_testlib import PILOT_MINI, pilot_bbox_param, pilot_route_points, validate_response
from winterpath_routing import RoutingEngine
from winterpath_routing.compact_engine import CompactRoutingEngine

from winterpath_api.settings import Settings


def test_flags_default_off() -> None:
    s = Settings.from_env({})
    assert (s.routing_compact_graph, s.routing_steps_v2) == (False, False)
    s = Settings.from_env({"ROUTING_COMPACT_GRAPH": "true", "ROUTING_STEPS_V2": "1"})
    assert (s.routing_compact_graph, s.routing_steps_v2) == (True, True)


def _body() -> dict:
    o, d = pilot_route_points()
    return {"origin": o, "destination": d, "departure_time": "2026-12-15T15:00:00Z"}


def _all(c) -> dict:
    out = {}
    for path in ("/health", "/coverage", f"/map/segments?bbox={pilot_bbox_param()}&limit=1000"):
        r = c.get(f"/api/v1{path}")
        assert r.status_code == 200, r.text
        j = r.json()
        j.pop("generated_at", None)
        j.get("checks", {}).pop("database", None)
        out[path] = j
    r = c.post("/api/v1/routes/compare", json=_body())
    assert r.status_code == 200, r.text
    validate_response(r, "/routes/compare", "post")
    out["compare"] = r.json()
    return out


_VOLATILE = ("generated_at", "computed_at", "time", "request_id")


def _strip_times(x):
    if isinstance(x, dict):
        return {k: _strip_times(v) for k, v in x.items() if k not in _VOLATILE}
    if isinstance(x, list):
        return [_strip_times(v) for v in x]
    return x


def test_compact_graph_answers_identically(make_client) -> None:
    off = make_client(fixture_dir=PILOT_MINI)
    on = make_client(fixture_dir=PILOT_MINI, routing_compact_graph=True)
    assert type(on.app.state.wp.engine) is CompactRoutingEngine
    assert type(off.app.state.wp.engine) is RoutingEngine
    assert _strip_times(_all(on)) == _strip_times(_all(off))


def test_steps_v2_same_routes_fewer_or_equal_steps(make_client) -> None:
    v1 = make_client(fixture_dir=PILOT_MINI).post("/api/v1/routes/compare", json=_body()).json()
    r = make_client(fixture_dir=PILOT_MINI, routing_steps_v2=True).post(
        "/api/v1/routes/compare", json=_body()
    )
    assert r.status_code == 200
    validate_response(r, "/routes/compare", "post")
    v2 = r.json()
    for a, b in zip(v1["routes"], v2["routes"], strict=True):
        assert a["edge_ids"] == b["edge_ids"] and a["distance_m"] == b["distance_m"]
        assert len(b["steps"]) <= len(a["steps"])
        # distance is redistributed between steps, never dropped
        assert abs(sum(s["distance_m"] for s in b["steps"]) - a["distance_m"]) < 0.5
