# Monitoring: data integrity and staleness — proposal (Platform, v2 Wave 1)

**Status:** proposal. Nothing here is deployed, and no secret or third-party account has been created. The owner decides on the items marked **(owner)**.

## Constraints
- **Render Free sleeps after 15 min idle.** Nothing may ping the API to keep it awake. Monitoring reads freshness **from the data (Postgres)**, not by waking the API.
- **GitHub cron is best effort.** GitHub's docs say: "The `schedule` event can be delayed during periods of high loads", "High load times include the start of every hour", and "some queued jobs may be dropped". In a public repository (this one is public), "scheduled workflows are automatically disabled when no repository activity has occurred in 60 days". So the scheduler cannot be the only thing watching the scheduler.
- **Supabase Free pauses after 1 week idle.** The scheduled writes keep it active as a side effect of real work. If the cron stops, monitoring must notice within 24 h, long before 7 days.
- **Least privilege.** Monitoring uses a **read-only** login (`wp_reader`), never the ETL secret.

## A. Daily data-integrity job (`integrity.yml`, proposal)
- **Trigger:** `cron: "37 13 * * *"` (off the top of the hour, after the 12:07 scoring run) plus `workflow_dispatch`. It also runs as a final `if: always()` job of every `scheduled.yml` run, which gives a second independent trigger (section B).
- **Credentials:** a new secret `WP_MONITOR_DATABASE_URL`, a Supabase session-pooler URL for a login in `wp_reader` **(owner creates it)**. Every check is `SELECT` only, and the run uses `SET default_transaction_read_only = on`.
- **Output:**
  - A table of PASS / WARN / FAIL with measured values goes to `$GITHUB_STEP_SUMMARY`.
  - **The job fails if any check FAILs.** GitHub then emails "the user who last modified the cron syntax in the workflow file" (GitHub docs), so the owner must enable Actions failure notifications.
  - No third-party service is involved.
- **API:** at most **one** request per run, `GET /api/v1/health` with a 120 s timeout to allow for cold start. It cross-checks that the deployed API reports `database: ok` and the expected contract version. A single daily wake is negligible, and this is the job's only API contact.

| # | Check (read-only SQL) | WARN | FAIL |
|---|---|---|---|
| F1 | `max(observed_at)` in `wp.weather_obs` (per station) | > 4 h old | > 6 h (two missed 3-hourly runs) |
| F2 | `max(day)` in `wp.weather_daily` | < local today − 1 | < local today − 2 |
| F3 | `max(day)` in `wp.risk_cell_score` (in season, per registry `season_months`) | < local today after 18:30 UTC | < local today − 1 |
| F4 | `max(day)` in `wp.report_311_cell` | > 3 days old | > 7 days old *(would FAIL today: data ends 2026-11-07, audit problem 4)* |
| F5 | Latest succeeded `wp.ingest_run` per source vs its cadence; a source **with no schedule** is reported as WARN "not scheduled" with its age | per-source | per-source |
| F6 | `wp.ingest_run` with `status='failed'` in the last 24 h | — | ≥ 1 |
| F7 | `wp.ingest_run` with `status='running'` and `started_at` > 2 h ago (crashed runner) | — | ≥ 1 |
| F8 | Advisory locks with `classid = 1464878420` (infra/ETL-LOCKS.md) held > 2 h | — | ≥ 1 |
| C1 | `wp.node` / `wp.edge` row counts vs the latest successful `osm` run's `record_count` | ±10 % | ±20 % or 0 |
| C2 | `wp.risk_cell_score` rows for the latest day vs coverage cell count (one row per cell) | — | ≠ |
| C3 | `wp.weather_obs` rows in the last 24 h per station | < 18 | < 8 |
| O1 | `wp.edge` whose `from_node_id` / `to_node_id` is missing from `wp.node` | — | ≥ 1 |
| O2 | Derived rows (per table) whose `ingest_run_id` is missing from `wp.ingest_run` | — | ≥ 1 |
| O3 | `wp.closure` with `valid_to < valid_from` | ≥ 1 | — |
| P1 | **Privacy / retention:** `wp.community_report` with `terminal_at < now() − 30 days` still present (contract: hard delete after 30 days) | — | ≥ 1 |
| P2 | `wp.community_report` with `status='pending'` and `expires_at < now()` (should be expired) | ≥ 1 | — |
| P3 | `wp.report_311_cell` with `n < 1` | — | ≥ 1 |
| G1 | Geometry columns with `ST_SRID(geom) <> 4326` | — | ≥ 1 |
| G2 | `NOT ST_IsValid(geom)` in `wp.sidewalk_polygon` | ≥ 1 | — |
| S1 | `pg_database_size(current_database())` against Supabase Free's 500 MB | ≥ 400 MB | ≥ 475 MB |
| A1 | One `GET /api/v1/health`: `status` and `checks.database` | degraded | no 200 within 120 s |

All thresholds are drafts; the owners of each table (Data, ML) confirm them. For the v2 island graph, S1 is the gate: Wave 1 measurements decide whether the island fits at all.

## B. Staleness monitoring without keep-alive
Layered, cheapest first. Every signal comes from activity that happens anyway.

1. **In-band, user-facing (no extra traffic).** When it is awake, the API computes freshness from the DB on every request: route `data_freshness`, `/weather/*` returns 503 when older than `WEATHER_MAX_AGE_MINUTES`, and Wave 2 adds `/data-status`. The web shows `delayed` / `stale`. Users are never told data is current when it is not. While Render sleeps, nobody is being served stale data.
2. **Post-run assertion in `scheduled.yml` (no extra trigger).** After each load, one `SELECT max(observed_at)` over the ETL connection fails the job if the load "succeeded" but freshness did not advance past the F1 FAIL threshold. This catches a silently empty upstream (ECCC returning nothing new).
3. **Daily integrity job (A).** A second, independent trigger; F1–F8 catch a dead scheduler within 24 h.
4. **Activity-driven check (no schedule needed).** Run the F-checks on every `push` to `main` as part of CI, using the read-only secret. Secrets are not exposed to pull requests from forks. Whenever anyone works on the repo, staleness is visible in CI.
5. **Dead-man's switch for "the scheduler never fired" (owner).** A scheduler that does not fire cannot report itself, and checks 2–4 share GitHub as their trigger. The only robust signal is outside GitHub. Two options:
   - **(a) Outbound heartbeat**, e.g. the healthchecks.io free tier. Each scheduled job sends one outbound HTTPS success ping at its end; the service emails the owner when an expected ping is missing (3 h grace for weather). This contacts a third-party monitor, **not Render**, so it is not a keep-alive. It needs an account and the owner's approval.
   - **(b) Move the trigger off GitHub cron**, e.g. Cloudflare Workers Cron Triggers (Cloudflare already hosts the web). A Worker calls GitHub's `workflow_dispatch` API on schedule. It needs a fine-grained token stored in Cloudflare and the owner's approval. This replaces the unreliable scheduler rather than watching it.

   Recommendation: (a) first, because it is smallest and reversible. Choose (b) if dropped runs recur after the top-of-hour fix.

## Thresholds summary (draft)
| Data | Cadence | WARN | FAIL |
|---|---|---|---|
| Weather observations | every 3 h (`17 */3`) | 4 h | 6 h |
| Risk scores | 12:07 + 18:07 UTC | today missing after 18:30 UTC | yesterday missing |
| 311 aggregates | **not scheduled** (audit problem 4) | 3 d | 7 d |
| Closures (entraves) | **not scheduled** | 26 h | 72 h |
