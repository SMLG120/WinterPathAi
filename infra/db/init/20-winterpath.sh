#!/usr/bin/env bash
# WinterPath PostGIS bootstrap. Runs once on an empty volume via
# /docker-entrypoint-initdb.d (after the image's own 10_postgis.sh). Idempotent, so it
# can also be re-run against an existing cluster with infra/scripts/db-bootstrap.sh.
#
# Creates:
#   * databases listed in $WP_DATABASES, each with the postgis extension
#   * NOLOGIN group roles wp_reader / wp_writer / wp_migrator (least privilege)
#     - wp_migrator: may CREATE schemas in each DB (Alembic, Data agent)
#     - wp_reader:   SELECT on tables created by wp_migrator (default privileges)
#     - wp_writer:   wp_reader + INSERT/UPDATE/DELETE, sequence usage
# Login users are NOT created here: they are environment-specific (see infra/SUPABASE.md)
# and are granted membership of one group role, e.g.  GRANT wp_writer TO <login_user>;
set -euo pipefail

DBS="${WP_DATABASES:-wp_data wp_routing wp_ml wp_platform wp_integration}"
PSQL=(psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --no-password)

"${PSQL[@]}" --dbname postgres <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wp_reader')   THEN CREATE ROLE wp_reader   NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wp_writer')   THEN CREATE ROLE wp_writer   NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wp_migrator') THEN CREATE ROLE wp_migrator NOLOGIN; END IF;
END
$$;
GRANT wp_reader TO wp_writer;
SQL

for db in $DBS; do
  [[ "$db" =~ ^[a-z_][a-z0-9_]*$ ]] || { echo "invalid database name: $db" >&2; exit 1; }
  "${PSQL[@]}" --dbname postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '${db}'" | grep -q 1 \
    || "${PSQL[@]}" --dbname postgres -c "CREATE DATABASE ${db}"

  "${PSQL[@]}" --dbname "$db" <<SQL
CREATE EXTENSION IF NOT EXISTS postgis;
REVOKE ALL ON DATABASE ${db} FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE ${db} TO wp_reader, wp_writer, wp_migrator;
GRANT CREATE ON DATABASE ${db} TO wp_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO wp_reader, wp_writer;
GRANT USAGE, CREATE ON SCHEMA public TO wp_migrator;
ALTER DEFAULT PRIVILEGES FOR ROLE wp_migrator GRANT SELECT ON TABLES TO wp_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE wp_migrator GRANT INSERT, UPDATE, DELETE ON TABLES TO wp_writer;
ALTER DEFAULT PRIVILEGES FOR ROLE wp_migrator GRANT USAGE, SELECT ON SEQUENCES TO wp_writer;
ALTER DEFAULT PRIVILEGES FOR ROLE wp_migrator GRANT USAGE ON SCHEMAS TO wp_reader, wp_writer;
SQL
  echo "winterpath-init: database ${db} ready (postgis + role grants)"
done
