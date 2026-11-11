# Production readiness (2026-11-11)

**Verdict: a free-tier public *demo*, not a production service.** Render's own docs say free instances should not be used for production applications. Supabase Free has no backups. No external monitoring exists.

States: **Deployed** (live and verified by request), **Configured** (set up and verified once), **Local only**, **Blocked**, **Not implemented**.

| Area | State | Evidence / note |
|---|---|---|
| PostGIS database (Supabase Free, us-east-1) | Deployed | Migrated to 0007; 49 MB; least-privilege roles verified (`wp_api` cannot insert) |
| API (Render Free, Virginia) | Deployed | `/health` returns `ok` for graph, database, risk and weather; compare returns 200; p95 806 ms over 60 live requests |
| Read-only mode | Deployed | `POST /reports` and `/pilot-requests` return 503 `WRITES_DISABLED` (live) |
| CORS allow-list | Configured | Exact origin `https://winterpath.pages.dev`; a foreign origin gets no allow-origin header. The real Pages origin can only be confirmed after the Pages deploy |
| Closures and 311 hazards in production routing | **Not yet**: production uses `API_STORE_BACKEND=memory` | Switching to `postgis` returned 503 (the `wp_reader` PII revoke on `community_report`). The fix is pending from routing. Until then, live routes do **not** avoid active closures |
| Weather (ECCC) | Deployed and scheduled | Latest observation is served live; the cron job succeeded (runs 43084925719 and 43086426247) |
| Daily risk scores | Deployed and scheduled | Run 43086426247 wrote 2,930 heuristic scores for 2026-11-11 from a GitHub runner |
| Risk model | Heuristic only | Labelled as a heuristic, not probabilities (API warning on every route). No trained model is deployed |
| 311 / closure refresh | Manual | `wp.report_311_cell` currently ends 2026-11-07 |
| Web app (Cloudflare Pages) | **Blocked** | The bundle is built and checked locally (no maps, no mocks, no secrets, CSP uses the Render origin). The API token is active but can see 0 accounts |
| Security headers on the live site | Blocked | Depends on the Pages deploy |
| Secrets hygiene | Configured | gitleaks clean on the repo history and on `dist/`; secrets only in Render env, a GitHub secret, and `.env.deploy` (mode 600) |
| Backups | Not implemented | Manual `pg_dump` procedure only (`RECOVERY.md`) |
| Monitoring and alerting | Not implemented | — |
| Geocoding | Not implemented by design | Map-pin selection; no public Nominatim |
| Community reports and pilot requests | Disabled by design | Need a privacy impact assessment (Law 25) before enabling |
| Legal review | Pending | ODbL derivative-database question; Canada.ca, Overpass and Cloudflare terms not yet read; 311 timezone unknown |

## Before calling this "production"
1. Paid or always-on hosting for the API, so it never sleeps. Requires owner approval and cost.
2. Database backups (Supabase Pro, or scheduled dumps to private storage).
3. External uptime monitoring and alerting.
4. A scheduled refresh for closures and 311 aggregates.
5. Legal and privacy review (above).
6. A validated risk model, if the product will claim more than a heuristic.
