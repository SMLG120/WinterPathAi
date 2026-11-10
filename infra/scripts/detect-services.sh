#!/usr/bin/env bash
# Print the compose profiles whose source trees exist on this branch; explain skips on stderr.
# Usage: infra/scripts/detect-services.sh   ->  e.g. "--profile api --profile web"
source "$(dirname "$0")/_common.sh"
args=()
if [[ -f "$INFRA_ROOT/services/api/pyproject.toml" ]]; then args+=(--profile api)
else echo "SKIP api: services/api/pyproject.toml not present on this branch" >&2; fi
if [[ -f "$INFRA_ROOT/apps/web/package.json" ]]; then args+=(--profile web)
else echo "SKIP web: apps/web/package.json not present on this branch" >&2; fi
echo "${args[*]:-}"
