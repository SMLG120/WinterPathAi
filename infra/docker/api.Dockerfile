# syntax=docker/dockerfile:1.7
# WinterPath API image — python:3.12-slim, non-root, no build tools in the final stage.
# Build context: repository root.   docker build -f infra/docker/api.Dockerfile .
#
# Installs every Python package under services/ that has a pyproject.toml, in
# dependency order (routing, ml, api). Package layout is owned by the Routing/API
# and ML agents; the ASGI entry point is configurable via API_APP and defaults to
# the value the Routing agent is expected to provide (confirm at integration).

FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.10.7 /uv /usr/local/bin/uv
RUN python -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH
WORKDIR /src
COPY services/ services/
RUN set -eu; \
    found=0; \
    for pkg in routing ml api; do \
      if [ -f "services/$pkg/pyproject.toml" ]; then \
        echo "installing services/$pkg"; uv pip install --python /opt/venv/bin/python "./services/$pkg"; found=1; \
      else \
        echo "SKIP services/$pkg (no pyproject.toml on this branch)"; \
      fi; \
    done; \
    [ "$found" = 1 ] || { echo "ERROR: no Python service packages found under services/" >&2; exit 1; }; \
    uv pip install --python /opt/venv/bin/python "uvicorn[standard]>=0.30"

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH \
    API_APP=winterpath_api.main:app API_ROOT_PATH=""
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
# Read-only model artifacts may be bind-mounted here; inference never writes.
RUN mkdir -p /app/models/artifacts && chown -R app:app /app
USER 10001:10001
EXPOSE 8000
# --no-access-log: uvicorn's access log prints raw query strings; the API emits its own
# structured, coordinate-redacted request log (infra/OBSERVABILITY.md).
CMD ["sh", "-c", "exec uvicorn \"$API_APP\" --host 0.0.0.0 --port 8000 --proxy-headers --no-access-log"]
