# Supabase notes (draft — no project has been created)

Creating a Supabase project is a cloud-resource action and requires explicit user approval.
Plan limits and pricing must be checked at that time; nothing here asserts current terms.

## Compatibility rules for migrations (Data agent owns `db/migrations/`)
- Use only `postgis` (and optionally `h3`/`h3_postgis` if available on the target plan —
  **unverified**; keep an H3-in-Python fallback). No custom C extensions.
- Create objects in schema `wp`; do not modify Supabase-managed schemas (`auth`, `storage`,
  `realtime`, `extensions`, `graphql*`). On Supabase, `postgis` is installed into the
  `extensions` schema — reference types unqualified and keep `extensions` on `search_path`.
- Row Level Security: the API connects server-side with a dedicated login user; tables in `wp`
  are not exposed via PostgREST. If the Supabase Data API is enabled, exclude schema `wp` from
  exposed schemas or enable RLS with deny-all policies.

## Roles (mirror of local `infra/db/init/20-winterpath.sh`)
Run once as the project owner (SQL editor), adapting passwords from a password manager:
```sql
CREATE ROLE wp_reader NOLOGIN; CREATE ROLE wp_writer NOLOGIN; CREATE ROLE wp_migrator NOLOGIN;
GRANT wp_reader TO wp_writer;
CREATE ROLE wp_api LOGIN PASSWORD '<from password manager>' IN ROLE wp_reader;     -- API (read; + wp_writer if reports/pilot form enabled)
CREATE ROLE wp_etl LOGIN PASSWORD '<from password manager>' IN ROLE wp_writer;     -- ingestion jobs
CREATE ROLE wp_migrate LOGIN PASSWORD '<from password manager>' IN ROLE wp_migrator; -- Alembic, CI/manual only
ALTER DEFAULT PRIVILEGES FOR ROLE wp_migrator GRANT SELECT ON TABLES TO wp_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE wp_migrator GRANT INSERT, UPDATE, DELETE ON TABLES TO wp_writer;
ALTER DEFAULT PRIVILEGES FOR ROLE wp_migrator GRANT USAGE, SELECT ON SEQUENCES TO wp_writer;
```
Alembic must run with `SET ROLE wp_migrator` so that default privileges apply to new tables.

## Connection strings
- API on Render: transaction pooler URL (port 6543) — disable server-side prepared statements
  in the driver (psycopg: `prepare_threshold=None`).
- Migrations: direct/session connection (port 5432).
- Store in Render/CI secret stores only. Never in Git, never in `VITE_*`.

## Backups
Supabase plan-dependent (verify). Independently, take a logical dump before every migration
(`infra/RUNBOOK.md` §3) and keep it outside Git.
