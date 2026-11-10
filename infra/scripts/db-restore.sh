#!/usr/bin/env bash
# Restore a pg_dump custom-format file into a NEW database (never overwrites in place).
# Usage: infra/scripts/db-restore.sh <dump_file> <target_db>
# Rollback = point the service at the restored DB (or rename DBs) after verification.
source "$(dirname "$0")/_common.sh"
f="${1:?usage: $0 <dump_file> <target_db>}"; target="${2:?usage: $0 <dump_file> <target_db>}"
[[ -s "$f" ]] || die "dump not found or empty: $f"
[[ "$target" =~ ^wp_[a-z0-9_]+$ ]] || die "refusing unexpected database name: $target"
if [[ -f "$f.sha256" ]]; then shasum -a 256 -c "$f.sha256" || die "checksum mismatch for $f"; fi
require_docker
# $target is regex-validated above, so inlining it into SQL is safe.
exists="$(compose exec -T db sh -c "psql -U \"\$POSTGRES_USER\" -d postgres -tAc \"SELECT 1 FROM pg_database WHERE datname = '$target'\"")"
[[ -z "$exists" ]] || die "database $target already exists — choose a new name (no in-place overwrite)"
compose exec -T db sh -c 'createdb -U "$POSTGRES_USER" "$1" && psql -U "$POSTGRES_USER" -d "$1" -c "CREATE EXTENSION IF NOT EXISTS postgis"' _ "$target"
compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" --no-owner --exit-on-error -d "$1"' _ "$target" < "$f"
echo "restored $f into $target"
