"""Contract validation helpers + SYNTHETIC test fixtures for API tests."""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

REPO = Path(__file__).resolve().parents[3]
CONTRACT = REPO / "docs" / "contracts" / "openapi.yaml"
TOY_DIR = REPO / "services" / "routing" / "tests" / "fixtures" / "synthetic" / "toy_grid"
ADMIN_TOKEN = "test-admin-token-not-a-secret-0123456789"

# toy grid geometry (see services/routing/tests/fixtures/synthetic/build_toy_grid.py)
LON0, LAT0, DLON, DLAT = -73.5780, 45.5030, 0.0010, 0.0007


def grid(r: int, c: int) -> dict[str, float]:
    return {"lon": LON0 + c * DLON, "lat": LAT0 + r * DLAT}


@cache
def spec() -> dict[str, Any]:
    return yaml.safe_load(CONTRACT.read_text())


def _validator(schema: dict[str, Any]) -> Draft202012Validator:
    root = {"components": spec()["components"], "allOf": [schema]}
    return Draft202012Validator(root, format_checker=FormatChecker())


def validate_schema(instance: Any, name: str) -> None:
    _validator({"$ref": f"#/components/schemas/{name}"}).validate(instance)


def response_schema(path: str, method: str, status: int) -> dict[str, Any] | None:
    resp = spec()["paths"][path][method]["responses"][str(status)]
    if "$ref" in resp:
        resp = spec()["components"]["responses"][resp["$ref"].rsplit("/", 1)[-1]]
    content = resp.get("content")
    if not content:
        return None
    media = content.get("application/json") or content.get("application/geo+json")
    return media["schema"]


def validate_response(resp, path: str, method: str) -> None:
    """Validate an httpx response against the contract for (path, method, status)."""
    schema = response_schema(path, method, resp.status_code)
    assert resp.status_code in {int(s) for s in spec()["paths"][path][method]["responses"]}, (
        f"status {resp.status_code} not declared for {method.upper()} {path}"
    )
    if schema is None:
        return
    _validator(schema).validate(resp.json())
