# Operations (hosted demo)

Deploy steps: `docs/DEPLOYMENT.md`. Incidents: `docs/RECOVERY.md`. Local runbook: `infra/RUNBOOK.md`.

## Routine
**Trigger:** the Cloudflare Worker `winterpath-scheduler` (`infra/cron-worker/`, Workers Cron Triggers, UTC) starts each job below through GitHub `workflow_dispatch`. GitHub's own `schedule:` crons in `scheduled.yml` stay as a best-effort backup: from 2026-11-11 to 11-13 they fired only some weather slots (6 of about 16, 1.5–3 h late) and never fired scoring, 311 or closures. Duplicate runs are safe (concurrency groups, ETL locks, idempotent loads). Worker runs: Cloudflare dashboard → Workers → winterpath-scheduler → Logs / Cron events.

| What | How | Frequency |
|---|---|---|
| Weather ingest (ECCC) | `scheduled.yml`, weather job | every 3 h at :17 UTC |
| Daily risk scoring | `scheduled.yml`, scoring job: downloads 311 (`--fetch-311`), writes `wp.risk_cell_score` (`--write-db`) | 12:07 and 18:07 UTC |
| 311 cell aggregates | `scheduled.yml`, `report-311-daily` (14-day window) and `report-311-weekly-full` | daily 11:27 UTC; full rebuild Sunday 10:47 UTC |
| Closures (Entraves, pilot bbox) | `scheduled.yml`, `closures-refresh`: `wp-ingest entraves --refresh`, then `load --source mtl-entraves` (lock WPET,3) | 09:37 and 15:37 UTC; manual: `gh workflow run scheduled.yml -f job=closures` |
| Graph refresh (OSM, voirie) | **Manual**: operator runs `wp-ingest` with `wp_etl`, then `load` | as needed (not scheduled) |
| Database size check | Supabase dashboard, or `select pg_size_pretty(pg_database_size(current_database()))` | weekly |
| Logical backup | `pg_dump` (see RECOVERY) | before each migration or bulk load |
| Render free hours | Render dashboard → Billing (750 h/month shared with the workspace's other free services) | monthly |
| Credential expiry | `GITHUB_DISPATCH_TOKEN` (Worker secret, fine-grained PAT, this repo only, Actions read/write): renew before its expiry date or every scheduled job stops. Cloudflare API token: check its TTL in the dashboard (the old token expired 2026-11-19); rotate the Supabase and Render tokens yearly | — |

## Health checks
- `GET https://winterpath-api.onrender.com/api/v1/health` reports four checks: `graph`, `database`, `risk` (layer and score source), and `weather` (latest observation time).
- `weather` is stale when the latest observation is older than `WEATHER_MAX_AGE_MINUTES` (180). In that case, check the last `scheduled.yml` run.
- Risk scores: `select day, count(*), max(scored_at) from wp.risk_cell_score group by 1 order by 1 desc`.

## Deploying an API change
1. Merge into `integration/winterpath`, and run tests and gitleaks.
2. Push to `main` (owner approval).
3. Render deploys are manual (autoDeploy off): `POST /v1/services/srv-dbqbv3ui0phs73c82qng/deploys` with the full commit SHA.
4. Check health, run one compare request, and confirm `POST /reports` returns 503.

## Logs
- Render: dashboard → Logs, or `GET /v1/logs?ownerId=…&resource=<service id>`. Logs are structured JSON with request_id, path, status and duration. No query strings, and no precise coordinates.
- The API logs the error envelope but **not the exception detail** for upstream 503s. On 2026-11-11 a permission error on `wp.community_report` was diagnosed only by re-running the repository locally as `wp_api`. Logging the exception class for upstream failures is a recommended follow-up.

## Monitoring
- **None external yet.** There is no uptime monitor or alerting. Any monitor added must respect Render's free-tier policy: no artificial keep-alive pings.

## Known operational limits
- GitHub Actions cron is best-effort and, for this repo, mostly did not fire (see Routine), hence the Worker trigger. If the Worker or its token fails, jobs stop: if `/health` shows weather `degraded` or routes show 100% unknown risk after 12:30 UTC, check the Worker's cron events and run `gh workflow run scheduled.yml -f job=weather` (or `job=scoring`).
- Render Free sleeps after 15 min idle, so the first request takes about a minute.
- Supabase Free pauses after 1 week of inactivity. The scheduled jobs are real database activity.
- Supabase Free has no backups.
- In-process rate limiting resets on every restart or deploy.
