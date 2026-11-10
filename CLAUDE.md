# WinterPath AI — shared project rules

Authoritative spec: `WinterPath_AI_Revised_Claude_Master_Prompt.md` (repo root). Contracts in `docs/contracts/` are **frozen at v1**; changes go through the coordinator (see `docs/contracts/integration-rules.md`).

## Read before editing
1. `docs/architecture.md`
2. `docs/contracts/openapi.yaml`, `docs/contracts/data-model.md`, `docs/contracts/integration-rules.md`
3. `docs/data-sources-and-licenses.md`
4. Your brief in `docs/agents/<name>.md`

## Honesty rules (non-negotiable)
- Never fabricate data, labels, metrics, API responses, testimonials, customers or safety claims.
- Every datum shown to users carries exactly one **evidence state**: `confirmed` · `unverified_report` · `model_estimate` · `unknown` · `simulated`. Unknown is never treated as zero risk. Simulated data is always visibly marked SIMULATED.
- Never describe a sidewalk as safe, cleared, ice-free or wheelchair accessible unless that status is verified by a cited source.
- 311 requests are *reports*, not confirmed obstacles. Snow-loading plans do not certify sidewalk clearance. Roadwork does not imply sidewalk closure unless `sidewalk_blockedtype` says so.
- Do not claim tests pass, commands ran, or anything deployed without literal command output.

## Geo rules
- API/GeoJSON: EPSG:4326, `[lon, lat]` order. Distances/areas: EPSG:32188 (NAD83 / MTM zone 8).
- Never infer connectivity between lines without an explicit topology rule. Report gaps; don't invent edges.
- Prohibited edges (no foot access, closed crossings, hard accessibility constraints) are **excluded**, not penalised.

## Legal / privacy
- No public Nominatim for autocomplete or bulk geocoding. No bulk download from tile.openstreetmap.org.
- Keep visible map attribution (OSM/ODbL, OpenFreeMap/OpenMapTiles, Ville de Montréal CC BY 4.0, ECCC).
- Never log raw precise user coordinates. No persistent location tracking. Raw data and secrets never go in Git.

## Process
- Stay in your owned paths (`docs/contracts/integration-rules.md` §1). Commit to your own `agent/<name>` branch only.
- Never push, force-push, merge, deploy, provision paid services, or use `--dangerously-skip-permissions`.
- Write tests, run them, paste literal results into `docs/agent-reports/<name>.md`.
- Python: 3.12, managed with `uv`. Node: 24 with npm. Use your assigned ports/DB (integration-rules §4).
