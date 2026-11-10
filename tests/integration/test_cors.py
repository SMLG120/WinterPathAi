"""CORS: allow-list only, no wildcard, no credentials."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.cors

ALLOWED = os.environ.get("CORS_ALLOWED_ORIGIN", "http://localhost:5175")
DISALLOWED = "https://evil.example"


def _preflight(client, origin: str):
    return client.options(
        "/routes/compare",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )


def test_preflight_allowed_origin(client) -> None:
    r = _preflight(client, ALLOWED)
    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-origin") == ALLOWED
    assert "POST" in r.headers.get("access-control-allow-methods", "")


def test_preflight_disallowed_origin(client) -> None:
    r = _preflight(client, DISALLOWED)
    assert r.headers.get("access-control-allow-origin") in (None, "")


def test_simple_request_headers(client) -> None:
    ok = client.get("/health", headers={"Origin": ALLOWED})
    bad = client.get("/health", headers={"Origin": DISALLOWED})
    assert ok.headers.get("access-control-allow-origin") == ALLOWED
    assert bad.headers.get("access-control-allow-origin") is None
    for r in (ok, bad):
        assert r.headers.get("access-control-allow-origin") != "*"
        assert r.headers.get("access-control-allow-credentials") != "true"
