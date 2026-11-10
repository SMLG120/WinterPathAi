#!/usr/bin/env bash
# Logical backup of one database from the local container to backups/ (git-ignored path
# outside the repo by default). Usage: infra/scripts/db-backup.sh <db> [out_dir]
source "$(dirname "$0")/_common.sh"
db="${1:?usage: $0 <database> [out_dir]}"; out="${2:-$INFRA_ROOT/../winterpath-backups}"
[[ "$db" =~ ^wp_[a-z_]+$ ]] || die "refusing unexpected database name: $db"
require_docker
mkdir -p "$out"; umask 077
f="$out/${db}_$(date -u +%Y%m%dT%H%M%SZ).dump"
compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc --no-owner "$1"' _ "$db" > "$f"
[[ -s "$f" ]] || die "backup file is empty: $f"
shasum -a 256 "$f" | tee "$f.sha256"
echo "backup written: $f"
