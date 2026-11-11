# syntax=docker/dockerfile:1.7
# WinterPath API image — python:3.12-slim, non-root, no build tools in the final stage.
# Build context: repository root.   docker build -f infra/docker/api.Dockerfile .
#
# Installs the API and its local path dependencies (routing, ml) from services/api/uv.lock:
# pinned and hash-checked (--frozen), no dev deps, and NON-editable. The API's
# [tool.uv.sources] marks routing/ml as editable path deps; an editable install would point at
# /src, which does not exist in the runtime stage (found by the v1.7 deploy-readiness smoke test).
# The ASGI entry point is API_APP (winterpath_api.main:app, confirmed by the Routing agent's code).

FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/opt/venv
COPY --from=ghcr.io/astral-sh/uv:0.10.7 /uv /usr/local/bin/uv
WORKDIR /src
COPY services/ services/
RUN set -eu; \
    [ -f services/api/uv.lock ] || { echo "ERROR: services/api/uv.lock missing" >&2; exit 1; }; \
    cd services/api && uv sync --frozen --no-dev --no-editable --python /usr/local/bin/python3.12

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH \
    API_APP=winterpath_api.main:app API_ROOT_PATH=""
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
# Model registry + the coverage artifact the risk provider needs (scores themselves come from
# wp.risk_cell_score when RISK_SCORE_SOURCE=postgis). Root-owned, read-only: inference never writes.
# Integrity: ML verifies artifacts against the sha256 values in registry.json before use.
RUN mkdir -p /app/models/artifacts/v2-8d19aa86
COPY --chown=root:root --chmod=0444 models/registry.json /app/models/registry.json
COPY --chown=root:root --chmod=0444 models/artifacts/v2-8d19aa86/coverage_cells.parquet /app/models/artifacts/v2-8d19aa86/coverage_cells.parquet
ENV MODEL_REGISTRY_PATH=/app/models/registry.json \
    MODEL_ARTIFACT_DIR=/app/models/artifacts
# Small committed OSM fixture graph (ODbL; ATTRIBUTION.md travels with it) so the image can boot
# with ROUTING_GRAPH_SOURCE=fixture (CI smoke test, offline demo). The API's default fixture path is
# relative to the source tree, which does not exist inside an installed venv, so set it explicitly.
COPY --chown=root:root data/fixtures/pilot_mini/ /app/data/fixtures/pilot_mini/
ENV ROUTING_FIXTURE_DIR=/app/data/fixtures/pilot_mini
USER 10001:10001
EXPOSE 10000
# Contract v1.7: bind 0.0.0.0:$PORT. Render injects PORT (default 10000); the default matches it.
# --no-access-log: uvicorn's access log prints raw query strings; the API emits its own
# structured, coordinate-redacted request log (infra/OBSERVABILITY.md).
CMD ["sh", "-c", "exec uvicorn \"$API_APP\" --host 0.0.0.0 --port \"${PORT:-10000}\" --proxy-headers --no-access-log"]
