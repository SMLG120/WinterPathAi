#!/usr/bin/env bash
# Launch exactly five interactive Claude Code sessions in tmux (one per worktree).
# Refuses to double-launch. Never uses --dangerously-skip-permissions or `claude -p`.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
for t in git tmux claude; do command -v "$t" >/dev/null || die "missing prerequisite: $t"; done
claude auth status >/dev/null 2>&1 || die "Claude Code not authenticated (run: claude auth login)"
for a in "${AGENTS[@]}"; do
  p="$(wt_path "$a")"
  [[ -d "$p" ]] || die "worktree $p missing — run scripts/create-worktrees.sh first"
  [[ "$(git -C "$p" branch --show-current)" == "agent/$a" ]] || die "$p not on agent/$a"
  [[ -f "$p/docs/agents/$a.md" ]] || die "$p/docs/agents/$a.md missing"
done
if ! tmux has-session -t "$SESSION" 2>/dev/null; then
  log "RUN tmux new-session -d -s $SESSION -n integration -c $REPO_ROOT"
  tmux new-session -d -s "$SESSION" -n integration -c "$REPO_ROOT"
fi
existing="$(tmux list-windows -t "$SESSION" -F '#{window_name}')"
for a in "${AGENTS[@]}"; do
  if grep -qx "$a" <<<"$existing" || [[ -n "$(agent_pane "$a")" ]]; then
    log "SKIP $a: agent pane already running ($(agent_pane "$a")) — no double launch"
    continue
  fi
  p="$(wt_path "$a")"
  prompt="Read docs/agents/$a.md and implement only your assigned work. Read docs/contracts and CLAUDE.md first."
  log "RUN tmux new-window -t $SESSION -n $a -c $p ; claude \"$prompt\""
  tmux new-window -d -t "$SESSION:" -n "$a" -c "$p"
  tmux set-option -p -t "$SESSION:$a" @agent "$a"
  tmux send-keys -t "$SESSION:$a" "claude $(printf '%q' "$prompt")" Enter
done
log "windows now: $(tmux list-windows -t "$SESSION" -F '#{window_name}' | tr '\n' ' ')"
echo "Attach: tmux attach -t $SESSION   |   Status: scripts/status-winterpath-agents.sh"
