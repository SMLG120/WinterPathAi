# WinterPath AI

Montréal-first, bilingual (EN/FR) pedestrian winter-navigation web product. *Navigate Montreal's winter, one better step at a time.*

**Status:** contract v1 baseline — Milestone A (Foundation). No application code has landed on `integration/winterpath` yet.

- Spec: `WinterPath_AI_Revised_Claude_Master_Prompt.md`
- Architecture: `docs/architecture.md` · Contracts: `docs/contracts/` · Sources & licences: `docs/data-sources-and-licenses.md` · UX: `docs/ux-spec.md`
- Agent briefs: `docs/agents/` · Agent reports: `docs/agent-reports/`

## Orchestration
```bash
scripts/create-worktrees.sh            # branches agent/<name> + ../winterpath-<name> from tag baseline-v1
scripts/launch-winterpath-agents.sh    # tmux session "winterpath": integration + 5 agent windows
scripts/status-winterpath-agents.sh    # SHAs, dirty state, reports
scripts/check-ownership.sh <agent>     # merge gate
scripts/merge-agent.sh <agent>         # coordinator: gated --no-ff merge
tmux attach -t winterpath
```

Nothing is pushed or deployed by these scripts.

## Attribution
Map data © OpenStreetMap contributors (ODbL). Contains data from Ville de Montréal (CC BY 4.0). Data Source: Environment and Climate Change Canada.
