#!/usr/bin/env bash
# Create one branch + worktree per agent from an exact baseline SHA. Non-destructive:
# existing worktrees are validated and reused, never reset or forced.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
BASELINE_SHA="${1:-$(baseline_sha || true)}"
[[ -n "$BASELINE_SHA" ]] || die "usage: $0 <BASELINE_SHA> (or create tag $BASELINE_TAG)"
git -C "$REPO_ROOT" cat-file -e "${BASELINE_SHA}^{commit}" || die "baseline $BASELINE_SHA not found"
# One shared local-only dev password for the single PostGIS container (untracked file).
SHARED_ENV="$REPO_ROOT/.env.local"
if [[ ! -f "$SHARED_ENV" ]]; then
  umask 077; printf 'POSTGRES_USER=wp_dev\nPOSTGRES_PASSWORD=%s\nPOSTGRES_PORT=55432\n' "$(openssl rand -hex 16)" > "$SHARED_ENV"
  log "wrote $SHARED_ENV (local dev DB credentials, git-ignored)"
fi
pw="$(grep '^POSTGRES_PASSWORD=' "$SHARED_ENV" | cut -d= -f2)"
for a in "${AGENTS[@]}"; do
  p="$(wt_path "$a")"; b="agent/$a"
  if git -C "$REPO_ROOT" worktree list --porcelain | grep -qx "worktree $p"; then
    cur="$(git -C "$p" branch --show-current)"
    [[ "$cur" == "$b" ]] || die "$p exists but is on '$cur', expected '$b' — fix manually"
    log "reuse worktree $p ($b @ $(git -C "$p" rev-parse --short HEAD))"
  elif [[ -e "$p" ]]; then
    die "$p exists but is not a registered worktree — refusing to touch it"
  elif git -C "$REPO_ROOT" show-ref --verify --quiet "refs/heads/$b"; then
    log "RUN git worktree add $p $b (existing branch)"
    git -C "$REPO_ROOT" worktree add "$p" "$b"
  else
    log "RUN git worktree add -b $b $p $BASELINE_SHA"
    git -C "$REPO_ROOT" worktree add -b "$b" "$p" "$BASELINE_SHA"
  fi
  env_file="$p/.env.local"
  if [[ ! -f "$env_file" ]]; then
    read -r api web db <<<"$(ports "$a")"
    {
      echo "# Local dev only — generated $(date -u +%FT%TZ). Not a secret store."
      echo "AGENT_NAME=$a"
      echo "API_PORT=$api"
      [[ "$web" != "-" ]] && echo "WEB_PORT=$web"
      if [[ "$db" != "-" ]]; then
        echo "POSTGRES_PORT=55432"; echo "POSTGRES_DB=$db"; echo "POSTGRES_USER=wp_dev"
        echo "POSTGRES_PASSWORD=$pw"
        echo "DATABASE_URL=postgresql+psycopg://wp_dev:$pw@localhost:55432/$db"
      fi
      echo "API_CORS_ORIGINS=http://localhost:5173,http://localhost:5174,http://localhost:5175"
      echo "HTTP_USER_AGENT=WinterPathAI-dev/0.1 (local development)"
      [[ "$a" == frontend ]] && { echo "VITE_API_BASE_URL=http://localhost:8104/api/v1"; echo "VITE_USE_MOCKS=true"; echo "VITE_MAP_STYLE_URL=https://tiles.openfreemap.org/styles/positron"; }
      [[ "$a" == ml ]] && echo "MODEL_ARTIFACT_DIR=models/artifacts"
    } > "$env_file"
    log "wrote $env_file"
  fi
done
git -C "$REPO_ROOT" worktree list
