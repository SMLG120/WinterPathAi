# Operations (hosted demo)

Deploy steps: `docs/DEPLOYMENT.md`. Incidents: `docs/RECOVERY.md`. Local runbook: `infra/RUNBOOK.md`.

## Routine
| What | How | Frequency |
|---|---|---|
| Weather ingest (ECCC) | `scheduled.yml`, weather job (GitHub Actions cron) | every 3 h at :17 UTC |
| Daily risk scoring | `scheduled.yml`, scoring job: downloads 311 (`--fetch-311`), writes `wp.risk_cell_score` (`--write-db`) | 12:00 and 18:00 UTC |
| Closures / 311 cell aggregates / graph refresh | **Manual**: operator runs `wp-ingest` with `wp_etl`, then `load` | as needed (not scheduled yet) |
| Database size check | Supabase dashboard, or `select pg_size_pretty(pg_database_size(current_database()))` | weekly |
| Logical backup | `pg_dump` (see RECOVERY) | before each migration or bulk load |
| Render free hours | Render dashboard → Billing (750 h/month shared with the workspace's other free services) | monthly |
| Credential expiry | Cloudflare API token expires 2026-11-19; rotate the Supabase and Render tokens yearly | — |

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
- Render Free sleeps after 15 min idle, so the first request takes about a minute.
- Supabase Free pauses after 1 week of inactivity. The scheduled jobs are real database activity.
- Supabase Free has no backups.
- In-process rate limiting resets on every restart or deploy.
