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
