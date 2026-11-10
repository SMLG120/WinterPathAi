#!/usr/bin/env bash
# Merge gate: fail if agent/<name> changed files outside its owned paths since the baseline.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
a="${1:?usage: $0 <agent>}"; paths="$(owned_paths "$a")" || die "unknown agent $a"
bad=0
while IFS= read -r f; do
  [[ -z "$f" ]] && continue
  ok=0
  [[ "$f" == "docs/agent-reports/$a.md" ]] && ok=1
  for p in $paths; do [[ "$f" == "$p"* ]] && ok=1; done
  if [[ $ok -eq 0 ]]; then echo "OWNERSHIP VIOLATION ($a): $f"; bad=1; fi
done < <(git -C "$REPO_ROOT" diff --name-only "$(git -C "$REPO_ROOT" merge-base "$INTEGRATION_BRANCH" "agent/$a")" "agent/$a")
[[ $bad -eq 0 ]] && echo "ownership OK for agent/$a"
exit $bad
