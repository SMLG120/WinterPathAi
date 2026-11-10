#!/usr/bin/env bash
# Shared helpers for infra/scripts. Source, don't execute.
set -euo pipefail
INFRA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$INFRA_ROOT/.env.local}"
compose() {
  if [[ -f "$ENV_FILE" ]]; then docker compose --project-directory "$INFRA_ROOT" --env-file "$ENV_FILE" "$@"
  else docker compose --project-directory "$INFRA_ROOT" "$@"; fi
}
die() { echo "ERROR: $*" >&2; exit 1; }
require_docker() { docker info >/dev/null 2>&1 || die "Docker daemon unreachable (Docker Desktop paused/stopped?)"; }
