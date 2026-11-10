"""Schemathesis contract tests against API_BASE_URL (stub by default).

* test_positive: schema-valid requests → every response must be declared by the contract,
  match its schema/content-type/headers, and never be a 5xx.
* test_negative: schema-invalid requests must be rejected with a declared 4xx. Since contract
  v1.1.0 (CR-PLAT-1) every operation that accepts input declares 400/422, so there are no
  expected failures.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis import GenerationMode
from schemathesis.checks import (
    content_type_conformance,
    negative_data_rejection,
    not_a_server_error,
    response_headers_conformance,
    response_schema_conformance,
    status_code_conformance,
)

from stub_server.contract import CONTRACT_PATH

pytestmark = pytest.mark.contract

MAX_EXAMPLES = int(os.environ.get("CONTRACT_MAX_EXAMPLES", "40"))
BASE_CHECKS = [
    not_a_server_error,
    status_code_conformance,
    content_type_conformance,
    response_schema_conformance,
    response_headers_conformance,
]


def _schema(mode: GenerationMode) -> schemathesis.schemas.BaseSchema:
    s = schemathesis.openapi.from_path(Path(CONTRACT_PATH))
    s.config.generation.update(modes=[mode], max_examples=MAX_EXAMPLES, deterministic=True)
    return s


positive_schema = _schema(GenerationMode.POSITIVE)
negative_schema = _schema(GenerationMode.NEGATIVE)


def _call(case, target, checks, *, inject_auth: bool) -> None:
    raw = case.operation.definition.raw
    headers = {}
    # Positive cases only: exercise the 2xx path of admin routes. Negative cases keep the
    # generated headers untouched — re-adding the token would undo a "missing Authorization"
    # mutation (authorized-but-invalid admin input is covered in test_smoke.py).
    if inject_auth and raw.get("security") and target.admin_token:
        headers["Authorization"] = f"Bearer {target.admin_token}"
    if any(str(s).startswith("5") for s in raw.get("responses", {})):
        # A declared 5xx (e.g. 503 UPSTREAM_UNAVAILABLE) is a contract-conforming answer;
        # status_code_conformance still fails any *undeclared* 5xx such as 500.
        checks = [c for c in checks if c is not not_a_server_error]
    case.call_and_validate(base_url=target.base_url, headers=headers, checks=checks)


@positive_schema.parametrize()
@settings(deadline=None, suppress_health_check=list(HealthCheck), derandomize=True)
def test_positive(case, target) -> None:
    _call(case, target, BASE_CHECKS, inject_auth=True)


@negative_schema.parametrize()
@settings(deadline=None, suppress_health_check=list(HealthCheck), derandomize=True)
def test_negative(case, target) -> None:
    _call(case, target, [*BASE_CHECKS, negative_data_rejection], inject_auth=False)
