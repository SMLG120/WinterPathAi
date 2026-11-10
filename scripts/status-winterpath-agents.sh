#!/usr/bin/env bash
# Show tmux windows, branch SHAs, dirty state, commit counts and report presence per agent.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
base="$(baseline_sha || echo '?')"
echo "baseline: $base   integration: $(git -C "$REPO_ROOT" rev-parse --short "$INTEGRATION_BRANCH" 2>/dev/null)"
tmux list-panes -a -F '  #{@agent} -> #{session_name}:#{window_index}.#{pane_index} (#{pane_id}) #{pane_current_command}' 2>/dev/null | grep -v '^  [[:space:]]*->' || echo "  no agent panes found in tmux"
printf '%-9s %-9s %-7s %-6s %-7s %s\n' AGENT SHA COMMITS DIRTY REPORT LAST_COMMIT
for a in "${AGENTS[@]}"; do
  p="$(wt_path "$a")"
  if [[ ! -d "$p" ]]; then printf '%-9s %s\n' "$a" "NO WORKTREE"; continue; fi
  sha="$(git -C "$p" rev-parse --short HEAD)"
  n="$(git -C "$p" rev-list --count "$base..HEAD" 2>/dev/null || echo '?')"
  dirty="$(git -C "$p" status --porcelain | wc -l | tr -d ' ')"
  rep=$([[ -f "$p/docs/agent-reports/$a.md" ]] && echo yes || echo no)
  last="$(git -C "$p" log -1 --format='%cr: %s' | cut -c1-60)"
  printf '%-9s %-9s %-7s %-6s %-7s %s\n' "$a" "$sha" "$n" "$dirty" "$rep" "$last"
done
