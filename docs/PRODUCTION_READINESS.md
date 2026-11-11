# Production readiness (2026-11-11)

**Verdict: a free-tier public *demo*, not a production service.** Render's own docs say free instances should not be used for production applications. Supabase Free has no backups. No external monitoring exists.

States: **Deployed** (live and verified by request), **Configured** (set up and verified once), **Local only**, **Blocked**, **Not implemented**.

| Area | State | Evidence / note |
|---|---|---|
| PostGIS database (Supabase Free, us-east-1) | Deployed | Migrated to 0007; 49 MB; least-privilege roles verified (`wp_api` cannot insert) |
| API (Render Free, Virginia) | Deployed | `/health` returns `ok` for graph, database, risk and weather; compare returns 200; p95 806 ms over 60 live requests |
| Read-only mode | Deployed | `POST /reports` and `/pilot-requests` return 503 `WRITES_DISABLED` (live) |
| CORS allow-list | Deployed | Exact origin `https://winterpath.pages.dev` (the real Pages origin); a foreign origin gets no allow-origin header and its preflight is rejected (400) |
| Closures and 311 hazards in production routing | Deployed | `API_STORE_BACKEND=postgis` with routing fix 8252f2e; `/hazards` serves 108 confirmed features; a live route reported "22 officially permitted closure(s) that block pedestrian passage were excluded". 311 cell hazards are currently absent because the aggregates end 2026-11-07 |
| Weather (ECCC) | Deployed and scheduled | Latest observation served live. GitHub skipped the 21:17 UTC cron on 2026-11-11 (health went `degraded` for weather until a manual run 43116467754); cron is best-effort |
| Daily risk scores | Deployed and scheduled | Run 43086426247 wrote 2,930 heuristic scores for 2026-11-11 from a GitHub runner |
| Risk model | Heuristic only | Labelled as a heuristic, not probabilities (API warning on every route). No trained model is deployed |
| 311 / closure refresh | Manual | `wp.report_311_cell` currently ends 2026-11-07 |
| Web app (Cloudflare Pages) | Deployed | `https://winterpath.pages.dev`; live bundle scanned (no source maps, no mock code, no localhost, none of the deploy secrets, gitleaks clean); browser test passed: basemap, layers, route comparison, FR, 390 px mobile; no console/CSP errors |
| Security headers on the live site | Deployed | CSP, HSTS, X-Frame-Options DENY, nosniff, Referrer-Policy, Permissions-Policy, COOP verified via `curl -D -` |
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
