# Recovery

Local backup/restore scripts: `infra/scripts/db-backup.sh`, `infra/scripts/db-restore.sh` (`infra/RUNBOOK.md` §3–5). This document covers the hosted demo.

## What can be rebuilt vs. what must be backed up
| Data | Rebuildable? | How |
|---|---|---|
| `wp.node`, `wp.edge`, `wp.sidewalk_polygon` | Yes | `wp-ingest osm/voirie` from cached raw files, then `wp-ingest load` |
| `wp.closure`, `wp.report_311_cell` | Yes | `wp-ingest entraves` / `wp-ingest 311`, then load |
| `wp.weather_obs`, `wp.weather_daily` | Yes (within ECCC's archive) | `wp-ingest eccc`, then load |
| `wp.risk_cell_score` | Yes | re-run `winterpath_ml.score` for the needed days |
| `wp.community_report`, `wp.pilot_request` | **No** | empty in the read-only demo; if writes are ever enabled, they need real backups |
| `wp.ingest_run` | History only | included in logical dumps |

Supabase Free includes **no automatic backups**. Take a logical dump before every migration and before any bulk reload, and keep it outside Git:
```bash
pg_dump "$MIGRATE_DATABASE_URL" --schema=wp --format=custom --no-owner --file=wp-$(date +%Y%m%d-%H%M).dump
```

## Supabase project paused (1 week of inactivity)
1. Supabase dashboard → the project → **Restore project**. Wait until it reports healthy.
2. Check `/api/v1/health` on the Render service; restart the Render service if its pool kept dead connections (pool_pre_ping should recover on its own).
3. Run the scheduled workflows once manually (`workflow_dispatch`) to refresh weather and scores.

## Render service broken after a deploy
1. Render dashboard → service → **Events** → redeploy the last good deploy (or `git revert` the bad merge on `main` and deploy).
2. Confirm `/api/v1/health` and one `/routes/compare` request.

## Cloudflare Pages bad deploy
Pages → Deployments → choose the last good deployment → **Rollback**. (Direct-upload deployments keep previous versions.)

## Database migration failed
1. Migrations run in a transaction per revision; a failed revision rolls back.
2. If data is wrong after a successful migration: `alembic downgrade <previous>` (all migrations have tested downgrades), or restore the pre-migration dump with `pg_restore --clean --if-exists --schema=wp`.

## Credential leak
1. Rotate immediately: Supabase role password (`ALTER ROLE … PASSWORD`), Render env var, GitHub secret, or provider API token.
2. Redeploy the API so it picks up the new value.
3. If the secret reached Git, removing it requires a history rewrite — needs explicit owner approval (never done automatically).

## Full rebuild from nothing
1. Create Supabase project → enable PostGIS in `extensions` → create roles (`infra/SUPABASE.md`).
2. `alembic upgrade head` as `wp_migrate`.
3. Load data from the operator's cached `data/processed/` (or re-run the pipeline).
4. Create the Render service from `infra/render.yaml`, set secrets, deploy.
5. Build `apps/web` with `npm run build:pages` and the production `VITE_*` values (it refuses unsafe settings such as mocks on, and scans `dist/` for mock code, source maps, secrets and missing headers), then upload `dist/` to Cloudflare Pages.
6. Set GitHub Actions secrets; run the scheduled workflows once.
