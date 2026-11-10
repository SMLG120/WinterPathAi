# infra/ — Platform-owned infrastructure

Nothing in this directory creates cloud resources by itself. All deployment files are
**drafts**; applying them requires explicit user approval (architecture §10).

| Path | Purpose |
|---|---|
| `db/init/20-winterpath.sh` | PostGIS bootstrap: 5 per-agent databases, `postgis` extension, group roles `wp_reader`/`wp_writer`/`wp_migrator`. Idempotent. |
| `docker/api.Dockerfile` | API image (python:3.12-slim, uid 10001, no access log). Entry point `API_APP` (default `winterpath_api.main:app` — confirm with Routing agent). |
| `docker/web.Dockerfile` + `docker/nginx-spa.conf` | Vite build → static files on `nginx-unprivileged` (:8080, non-root). |
| `render.yaml` | Render blueprint draft for the API (not applied; no cron jobs declared). |
| `vercel/vercel.json` | Vercel project config draft for `apps/web`. |
| `SUPABASE.md` | Supabase/PostGIS notes, roles, migrations. |
| `RUNBOOK.md` | Local ops, backup/restore, rollback. |
| `OBSERVABILITY.md` | Structured log format, `/health` expectations, privacy rules for logs. |
| `scripts/` | Helpers: `db-bootstrap.sh`, `db-backup.sh`, `db-restore.sh`, `wait-for-http.sh`, `detect-services.sh`. |

## Vercel (draft)
- Project root directory: `apps/web`. Copy `infra/vercel/vercel.json` to `apps/web/vercel.json`
  at integration time (that path is owned by the Frontend agent; coordinate via the coordinator).
- Environment: only public `VITE_API_BASE_URL`, `VITE_MAP_STYLE_URL`. No secrets — Vite inlines
  `VITE_*` into the bundle.
- The SPA rewrite excludes `/assets/` so missing hashed assets 404 instead of returning HTML.

## Local ports (integration-rules §4)
Platform: API 8105, web 5175, DB `wp_platform` on the shared container at `127.0.0.1:55432`.
