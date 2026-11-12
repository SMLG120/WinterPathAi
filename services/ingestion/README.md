# winterpath_ingestion

Idempotent ETL for WinterPath AI (owner: Data agent). Python 3.12, `uv`.

```bash
cd services/ingestion
uv sync
uv run wp-ingest osm        # Geofabrik Quebec PBF (cached, MD5-checked) → bbox clip → data/processed/osm_pilot
uv run wp-ingest voirie     # Voirie polygons + edge match → data/processed/voirie
uv run wp-ingest fixture    # → data/fixtures/pilot_mini (≤200 real edges near McGill)
uv run wp-ingest entraves   # → data/processed/entraves (closures + blocked-type mapping)
uv run wp-ingest 311        # → data/processed/report_311 (H3 r9 × day × category × nature counts)
uv run wp-ingest eccc       # → data/processed/weather_obs
uv run wp-ingest load       # processed → PostGIS wp.* (DATABASE_URL), one txn per source
uv run wp-ingest load --weather-since 2025-11-01   # same, wp.weather_obs bounded (hosted DB)
uv run wp-ingest load --source eccc-geomet        # one source only (repeatable; canonical source_id)
uv run wp-ingest boundaries # limadmin + archipel (CC BY 4.0) → data/processed/boundaries (main island, units, islands)
uv run wp-ingest osm-island # island graph (same PBF + rules as the pilot) → data/processed/osm_island (local only)
DATABASE_URL=…/wp_island uv run wp-ingest load --source osm --osm-graph island   # local wp_island DB
uv run alembic -c ../../db/alembic.ini upgrade head   # migrations (db/migrations)
uv run pytest               # unit + PostGIS tests (PostGIS tests skip if unreachable)
```

- Same input checksum ⇒ no-op (`--force` to rebuild). Outputs are built in a staging dir and
  swapped in with `os.replace`; DB loads stage → upsert → prune inside one transaction.
- Raw downloads live in git-ignored `data/raw/`; 311 raw rows never leave it.
- `HTTP_USER_AGENT` and `DATABASE_URL` come from the repo-root `.env.local`.
- OSM path policy (contract v1.5.0): service/cycleway only with explicit
  `foot=yes|designated|permissive`; corridor/indoor excluded.
- 311 consumers `SUM(n)` over the natures they need (labels: requete + plainte); k-anonymity
  (n<3) applies after summing.
- Topology: edges connect only through shared OSM nodes. Gaps are reported in
  `data/qa/osm_pilot_gaps.json`, never repaired.

## Per-source load (`--source`)

`wp-ingest load --source <source_id>` loads only the named sources. The flag is repeatable, and
the accepted values are `osm`, `mtl-voirie`, `mtl-entraves`, `mtl-311` and `eccc-geomet`. It uses
the same path as a full load: one transaction per source (staging → upsert → prune), a `failed`
ingest_run on error with current rows untouched, and a no-op when the same checksum has already
succeeded. It combines with `--force` and `--weather-since`. Other sources are not touched even
when their processed output exists. Without `--source`, all five load as before.

Scheduled weather job (`.github/workflows/scheduled.yml`): `wp-ingest eccc --refresh` fetches
hourly data from 2022 onward. To keep the hosted table bounded, pass a rolling cutoff, e.g.
`wp-ingest load --source eccc-geomet --weather-since "$(date -u -d '365 days ago' +%F)"` (GNU date).

## Bounding `wp.weather_obs` (`--weather-since`)

`wp-ingest load --weather-since YYYY-MM-DD` keeps only hourly observations with
`observed_at >= YYYY-MM-DD 00:00 America/Montreal`. Older rows in the CSV are not inserted, and
older rows already in `wp.weather_obs` are deleted in the same transaction. Other tables are not
affected, and `wp.weather_daily` (3,550 rows, about 1 MB) is not bounded.

The cutoff is mixed into the load checksum, so a bounded load and a full load never no-op each
other. Running `load` again without the flag restores the full history. `ingest_run.log.counts`
records `_weather_obs_skipped_before_since` and `_weather_obs_pruned_before_since`; these
diagnostics are not included in `record_count`.

Measured on 2026-11-11 against local PostGIS 16-3.4. Each case is a fresh database migrated to
`0006` and loaded from the current `data/processed`, followed by `VACUUM ANALYZE`:

| `--weather-since` | weather_obs rows | weather_obs size | all `wp.*` objects | whole database |
|---|---|---|---|---|
| (none, 2022-01-01 →) | 84,249 | 10 MB | 35 MB | 51 MB |
| 2025-11-01 (~1 year) | 17,160 | 2.2 MB | 27 MB | 43 MB |
| 2026-08-01 (~3 months) | 4,061 | 0.6 MB | 26 MB | 41 MB |

- About 16 MB of "whole database" is the baseline of an empty PostGIS database, including 7 MB
  for `spatial_ref_sys`. Supabase's own schemas add an overhead that was not measured here.
- The local `wp_data` is 79 MB only because of dead tuples from repeated rebuilds.
- Pruning an existing DB frees space for reuse but does not shrink files until `VACUUM FULL`.
  For the hosted DB, load with the bound from the start.

## Initial load into the hosted DB (Supabase)

This loads the hosted DB from the existing local `data/processed/`, with no re-download. It has
not been run against Supabase: the steps are written from the migrations and loader code, not
from a real Supabase run. Platform owns the hosted project and its login users (migration 0001
creates only `NOLOGIN` group roles).

Steps 1–3 were rehearsed on a local scratch database (2026-11-11, at 0007):
- PostGIS was created `WITH SCHEMA extensions`, followed by the step-1 grants.
- The migration ran with `options=-c role=wp_migrator -c search_path=public,extensions`, and the
  load with `role=wp_writer`, all without superuser rights.
- Results: head was reached, `wp_migrator` owns all 13 tables and `alembic_version`, and
  `wp.edge.geom` is `extensions.geometry`. `load --source osm --source eccc-geomet` loaded exactly
  those two sources, and `wp_writer` can insert into and delete from `wp.risk_cell_score`.
- The local roles are NOLOGIN, so the search path went in `options` rather than in
  `ALTER ROLE … SET`.
- Not checked: Supabase-specific behaviour, namely its `options` passthrough and its default
  privileges.

**0. Prerequisite.** Check that the local processed outputs exist. `load` reads only
`data/processed/*/` and makes no network calls.

```bash
cd services/ingestion
ls ../../data/processed/{osm_pilot,voirie,entraves,report_311,weather_obs}/manifest.json
```

**1. One-time bootstrap, as the Supabase admin (`postgres`)**, in the SQL editor:

```sql
-- 0001 skips role creation when these already exist.
CREATE ROLE wp_reader NOLOGIN;
CREATE ROLE wp_writer NOLOGIN;
CREATE ROLE wp_migrator NOLOGIN;
-- Login users; passwords from your secret manager, never committed.
CREATE ROLE wp_migrate LOGIN PASSWORD '<secret>' IN ROLE wp_migrator;
CREATE ROLE wp_loader  LOGIN PASSWORD '<secret>' IN ROLE wp_writer;
-- The migrator creates schema wp and Alembic's public.alembic_version.
GRANT CREATE ON DATABASE postgres TO wp_migrator;
GRANT CREATE ON SCHEMA public TO wp_migrator;
-- Contract v1.7: PostGIS in schema `extensions`, enabled BEFORE the first migration
-- (0001's CREATE EXTENSION IF NOT EXISTS is then a no-op).
CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA extensions;
SELECT extnamespace::regnamespace FROM pg_extension WHERE extname = 'postgis';  -- → extensions
-- …and every login role used by Alembic, the API and jobs needs it on its search_path.
ALTER ROLE wp_migrate SET search_path = public, extensions;
ALTER ROLE wp_loader  SET search_path = public, extensions;
```

**2. Migrate as `wp_migrator`.** Use the direct connection (port 5432). The pooler may not pass
startup `options`. `options=-c role=wp_migrator` makes the session run as the group role, so
`wp_migrator` owns every object rather than the login user owning them. Read secrets without
echoing them or writing them to shell history:

```bash
read -rs "PGPW?wp_migrate password: "; echo   # zsh (bash: read -rsp '…' PGPW)
HOST=db.<project-ref>.supabase.co
MIG_URL="postgresql://wp_migrate:${PGPW}@${HOST}:5432/postgres?sslmode=require&options=-c%20role%3Dwp_migrator"
uv run alembic -c ../../db/alembic.ini -x url="$MIG_URL" upgrade head
uv run alembic -c ../../db/alembic.ini -x url="$MIG_URL" current      # → 0007_risk_cell_score (head)
unset PGPW MIG_URL
```

**3. Load as `wp_writer`** from local processed data, bounded weather:

```bash
read -rs "PGPW?wp_loader password: "; echo
DATABASE_URL="postgresql://wp_loader:${PGPW}@${HOST}:5432/postgres?sslmode=require" \
  uv run wp-ingest load --weather-since 2025-11-01
unset PGPW
```

An exported `DATABASE_URL` takes precedence over `.env.local`, which stays pointed at local
`wp_data`. A hosted URL kept in a file belongs in a git-ignored `.env.*` file, never in Git.

Expected output: one JSON line per source, with `"noop": false` and counts `node 7042`,
`edge 16846`, `sidewalk_polygon 1495`, `closure 167`, `report_311_cell 70428`,
`weather_obs 17160`, `weather_daily 3550` (current processed data, cutoff 2025-11-01). Each source
loads in its own transaction, and a failed source records a `failed` ingest_run without touching
current rows. Re-running is a no-op per source. Re-running with a different cutoff re-loads only
`eccc-geomet`.

**4. Verify:**

```sql
SELECT source_id, status, record_count, finished_at FROM wp.ingest_run ORDER BY finished_at;
SELECT pg_size_pretty(pg_database_size(current_database()));
```

## Island graph (WinterPath 2.0 Wave 1, local only)

`wp-ingest osm-island` builds the pedestrian graph for the Island of Montréal from the same
Geofabrik PBF as the pilot, pinned through `osm_pilot`'s manifest provenance URL, and with the
same `graph.build_graph` rules. The area rule is documented in `osm/island.py`:
- Clip to agglomeration land, i.e. every archipel island, keeping complete ways.
- Keep a connected network only if it has a node on the main island. Other islands are included
  only through mapped pedestrian links.
- Label every node `main_island`, `other_island` or `outside_agglomeration_land` (bridge decks,
  the Laval or Longueuil end of a bridge). Nothing outside the agglomeration is labelled island.

Load it into the separate local database `wp_island` with `load --source osm --osm-graph island`.
Never load it into `wp_data` or a hosted DB without a decision; see
`docs/agent-reports/data.md` → "Island feasibility" for sizes. The QA summary is
`data/qa/island_feasibility.json`.
