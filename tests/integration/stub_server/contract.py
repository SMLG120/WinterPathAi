"""Load docs/contracts/openapi.yaml and validate requests/responses against it.

Used by the schema-only stub and by tests. The contract is OpenAPI 3.1, whose schemas are
JSON Schema 2020-12; `#/components/...` refs are resolved by validating against a wrapper
document that carries the spec's `components` at its root.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = Path(os.environ.get("CONTRACT_PATH", REPO_ROOT / "docs" / "contracts" / "openapi.yaml"))
HTTP_METHODS = ("get", "put", "post", "delete", "patch", "head", "options")
_INT_RE = re.compile(r"^-?[0-9]+$")


@cache
def load_spec(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _validator(schema: dict[str, Any]) -> Draft202012Validator:
    wrapper = {"components": load_spec()["components"], **schema}
    return Draft202012Validator(wrapper, format_checker=FormatChecker())


def schema_errors(schema: dict[str, Any], instance: Any) -> list[str]:
    return [
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
        for e in _validator(schema).iter_errors(instance)
    ]


def component_schema(name: str) -> dict[str, Any]:
    return {"$ref": f"#/components/schemas/{name}"}


def _deref(obj: dict[str, Any]) -> dict[str, Any]:
    spec = load_spec()
    while "$ref" in obj:
        node: Any = spec
        for part in obj["$ref"].removeprefix("#/").split("/"):
            node = node[part]
        obj = node
    return obj


@dataclass(frozen=True)
class Operation:
    path: str
    method: str
    operation_id: str
    parameters: tuple[dict[str, Any], ...]
    request_body: dict[str, Any] | None
    responses: dict[str, Any]
    secured: bool
    declared_statuses: frozenset[str] = field(default_factory=frozenset)

    def response_schema(self, status: int) -> tuple[str, dict[str, Any]] | None:
        resp = self.responses.get(str(status))
        if resp is None:
            return None
        resp = _deref(resp)
        content = resp.get("content") or {}
        for media_type, body in content.items():
            return media_type, body.get("schema", {})
        return None


@cache
def operations() -> dict[str, Operation]:
    spec = load_spec()
    ops: dict[str, Operation] = {}
    for path, item in spec["paths"].items():
        shared = item.get("parameters", [])
        for method in HTTP_METHODS:
            if method not in item:
                continue
            op = item[method]
            params = tuple(_deref(p) for p in [*shared, *op.get("parameters", [])])
            ops[op["operationId"]] = Operation(
                path=path,
                method=method.upper(),
                operation_id=op["operationId"],
                parameters=params,
                request_body=_deref(op["requestBody"]) if "requestBody" in op else None,
                responses=op["responses"],
                secured=bool(op.get("security")),
                declared_statuses=frozenset(op["responses"].keys()),
            )
    return ops


class RequestInvalid(Exception):
    """Request violates the contract. kind = 'malformed' (HTTP 400) or 'invalid' (HTTP 422)."""

    def __init__(self, kind: str, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.kind = kind
        self.details = details or []


def _coerce(raw: list[str], schema: dict[str, Any], name: str) -> Any:
    schema = _deref(schema)
    typ = schema.get("type")
    if typ == "array":
        joined = ",".join(raw)
        items = joined.split(",") if joined else []
        return [_coerce([i], schema.get("items", {}), name) for i in items]
    if len(raw) != 1:
        raise RequestInvalid("invalid", f"parameter {name!r} given {len(raw)} times")
    value = raw[0]
    if typ == "integer":
        if not _INT_RE.match(value):
            raise RequestInvalid("invalid", f"parameter {name!r} is not an integer")
        return int(value)
    if typ == "number":
        try:
            return float(value)
        except ValueError as exc:
            raise RequestInvalid("invalid", f"parameter {name!r} is not a number") from exc
    if typ == "boolean":
        if value not in ("true", "false"):
            raise RequestInvalid("invalid", f"parameter {name!r} is not a boolean")
        return value == "true"
    return value


def validate_request(
    op: Operation,
    *,
    query: dict[str, list[str]],
    path_params: dict[str, str],
    headers: dict[str, str],
    content_type: str | None,
    body: bytes,
) -> dict[str, Any]:
    """Return {'params': {...}, 'body': ...} or raise RequestInvalid."""
    import json

    values: dict[str, Any] = {}
    for p in op.parameters:
        name, loc, schema = p["name"], p["in"], p.get("schema", {})
        if loc == "query":
            raw = query.get(name)
        elif loc == "path":
            raw = [path_params[name]] if name in path_params else None
        elif loc == "header":
            raw = [headers[name.lower()]] if name.lower() in headers else None
        else:  # cookie — unused by the contract
            continue
        if raw is None:
            if p.get("required"):
                raise RequestInvalid("invalid", f"missing required {loc} parameter {name!r}")
            continue
        value = _coerce(raw, schema, name)
        errs = schema_errors(schema, value)
        if errs:
            raise RequestInvalid("invalid", f"{loc} parameter {name!r} invalid", errs)
        values[name] = value

    payload: Any = None
    if op.request_body is not None:
        if not body:
            if op.request_body.get("required"):
                raise RequestInvalid("malformed", "request body is required")
        else:
            media = (content_type or "").split(";")[0].strip().lower()
            if media != "application/json":
                raise RequestInvalid("malformed", "Content-Type must be application/json")
            try:
                payload = json.loads(body)
            except ValueError as exc:
                raise RequestInvalid("malformed", "request body is not valid JSON") from exc
            schema = op.request_body["content"]["application/json"]["schema"]
            errs = schema_errors(schema, payload)
            if errs:
                raise RequestInvalid("invalid", "request body violates contract", errs)
    return {"params": values, "body": payload}
