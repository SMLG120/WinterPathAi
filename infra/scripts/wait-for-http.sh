#!/usr/bin/env bash
# Wait until a URL returns HTTP 2xx. Usage: infra/scripts/wait-for-http.sh <url> [timeout_s]
set -euo pipefail
url="${1:?usage: $0 <url> [timeout_s]}"; timeout="${2:-60}"; start=$(date +%s)
until curl -fsS -o /dev/null "$url"; do
  (( $(date +%s) - start >= timeout )) && { echo "ERROR: $url not ready after ${timeout}s" >&2; exit 1; }
  sleep 1
done
echo "ready: $url"
