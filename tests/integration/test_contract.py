"""Schemathesis contract tests against API_BASE_URL (stub by default).

* test_positive: schema-valid requests → every response must be declared by the contract,
  match its schema/content-type/headers, and never be a 5xx.
* test_negative: schema-invalid requests must be rejected with a declared 4xx. Operations whose
  contract declares no 4xx for invalid input are KNOWN CONTRACT GAPS (change request CR-PLAT-1
  in docs/agent-reports/platform.md) and are xfailed with strict=True, so the xfail turns into a
  failure as soon as the contract is fixed and the marker must be removed.
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
# Operations that declare no 400/422 response, so invalid input has no conforming status.
KNOWN_NEGATIVE_GAPS = {
    "getWeatherForecast",  # invalid ?hours → no 4xx declared
    "deleteOwnReport",  # bad uuid / missing X-Deletion-Token → only 204/404 declared
    "listReportsForModeration",  # invalid ?status/?limit → only 200/401 declared
    "moderateReport",  # invalid body / uuid → only 200/401/404 declared
}


def _schema(mode: GenerationMode) -> schemathesis.schemas.BaseSchema:
    s = schemathesis.openapi.from_path(Path(CONTRACT_PATH))
    s.config.generation.update(modes=[mode], max_examples=MAX_EXAMPLES, deterministic=True)
    return s


positive_schema = _schema(GenerationMode.POSITIVE)
negative_schema = _schema(GenerationMode.NEGATIVE)


def _call(case, target, checks) -> None:
    raw = case.operation.definition.raw
    headers = {}
    if raw.get("security") and target.admin_token:  # exercise the 2xx path of admin routes
        headers["Authorization"] = f"Bearer {target.admin_token}"
    if any(str(s).startswith("5") for s in raw.get("responses", {})):
        # A declared 5xx (e.g. 503 UPSTREAM_UNAVAILABLE) is a contract-conforming answer;
        # status_code_conformance still fails any *undeclared* 5xx such as 500.
        checks = [c for c in checks if c is not not_a_server_error]
    case.call_and_validate(base_url=target.base_url, headers=headers, checks=checks)


@positive_schema.parametrize()
@settings(deadline=None, suppress_health_check=list(HealthCheck), derandomize=True)
def test_positive(case, target) -> None:
    _call(case, target, BASE_CHECKS)


@negative_schema.parametrize()
@settings(deadline=None, suppress_health_check=list(HealthCheck), derandomize=True)
def test_negative(case, target, request) -> None:
    if case.operation.definition.raw.get("operationId") in KNOWN_NEGATIVE_GAPS:
        request.applymarker(pytest.mark.xfail(reason="contract declares no 4xx (CR-PLAT-1)", strict=True))
    _call(case, target, [*BASE_CHECKS, negative_data_rejection])
