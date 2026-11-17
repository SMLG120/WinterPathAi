"""Inside the coverage bbox but outside the served outline -> OUTSIDE_COVERAGE, not OFF_NETWORK.

Seen on the island graph: Laval, Longueuil and Terrebonne fall inside the island's bbox, so they
were answered "more than 75 m from the network" and the UI told users to move closer to a
sidewalk.
"""

from __future__ import annotations

from api_testlib import grid, validate_response

from winterpath_api.params import outside_area

URL = "/api/v1/routes/compare"
# Same point as test_compare_routes_error_cases: inside the toy bbox, > 75 m from any edge.
FAR = {"lon": -73.570, "lat": 45.510}


def _square(w: float, s: float, e: float, n: float) -> dict:
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


def test_outside_area_needs_evidence() -> None:
    sq = _square(-1, -1, 1, 1)
    assert outside_area(5, 5, sq) is True
    assert outside_area(0, 0, sq) is False
    assert outside_area(1, 0, sq) is False  # on the boundary = covered
    assert outside_area(5, 5, None) is False  # no outline: never claim "outside"
    assert outside_area(5, 5, {"type": "Polygon", "coordinates": "bad"}) is False


def test_off_network_outside_outline_becomes_outside_coverage(client) -> None:
    # Outline that excludes FAR but sits inside the bbox.
    client.app.state.wp.coverage_area = _square(-73.60, 45.49, -73.575, 45.505)
    r = client.post(URL, json={"origin": grid(0, 0), "destination": FAR})
    assert r.status_code == 422, r.text
    validate_response(r, "/routes/compare", "post")
    body = r.json()
    assert body["code"] == "OUTSIDE_COVERAGE"
    assert body["details"]["which"] == "destination"
    assert "coverage_bbox" in body["details"]


def test_off_network_inside_outline_stays_off_network(client) -> None:
    client.app.state.wp.coverage_area = _square(-73.60, 45.49, -73.55, 45.52)
    r = client.post(URL, json={"origin": grid(0, 0), "destination": FAR})
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "OFF_NETWORK"
    assert r.json()["details"]["max_snap_distance_m"] == 75
