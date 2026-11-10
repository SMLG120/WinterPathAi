#!/usr/bin/env bash
# Shared definitions for WinterPath orchestration scripts.
set -euo pipefail
AGENTS=(data routing ml frontend platform)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Worktrees live next to the main checkout.
PARENT_DIR="$(cd "$REPO_ROOT/.." && pwd)"
INTEGRATION_BRANCH="integration/winterpath"
SESSION="winterpath"
LOG_DIR="$REPO_ROOT/logs"
BASELINE_TAG="baseline-v1"
baseline_sha() { git -C "$REPO_ROOT" rev-parse --verify --quiet "${BASELINE_TAG}^{commit}"; }
wt_path() { printf '%s/winterpath-%s' "$PARENT_DIR" "$1"; }
log() { mkdir -p "$LOG_DIR"; printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOG_DIR/orchestration.log"; }
die() { log "ERROR: $*"; exit 1; }
owned_paths() {
  case "$1" in
    data) echo "data/ db/ services/ingestion/" ;;
    routing) echo "services/api/ services/routing/" ;;
    ml) echo "services/ml/ models/" ;;
    frontend) echo "apps/web/ assets/3d/" ;;
    platform) echo "infra/ .github/ tests/integration/ docker-compose.yml Makefile" ;;
    *) return 1 ;;
  esac
}
ports() { # api web db
  case "$1" in
    data) echo "8101 - wp_data" ;; routing) echo "8102 - wp_routing" ;; ml) echo "8103 - wp_ml" ;;
    frontend) echo "8104 5174 -" ;; platform) echo "8105 5175 wp_platform" ;; *) return 1 ;;
  esac
}
