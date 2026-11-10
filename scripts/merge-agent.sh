#!/usr/bin/env bash
# Coordinator-only: gated, non-forced merge of one agent branch into the integration branch.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
a="${1:?usage: $0 <agent>}"
[[ "$(git -C "$REPO_ROOT" branch --show-current)" == "$INTEGRATION_BRANCH" ]] || die "main checkout must be on $INTEGRATION_BRANCH"
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || die "main checkout is dirty — commit or stash first"
p="$(wt_path "$a")"
[[ -z "$(git -C "$p" status --porcelain)" ]] || die "$p has uncommitted work — ask the agent to commit"
"$REPO_ROOT/scripts/check-ownership.sh" "$a"
[[ -f "$p/docs/agent-reports/$a.md" ]] || die "missing docs/agent-reports/$a.md"
log "RUN git merge --no-ff agent/$a"
git -C "$REPO_ROOT" merge --no-ff --no-edit "agent/$a" || { log "merge conflict — resolve manually; nothing was aborted or reset"; exit 1; }
log "merged agent/$a -> $(git -C "$REPO_ROOT" rev-parse --short HEAD). Re-run integration tests now."
