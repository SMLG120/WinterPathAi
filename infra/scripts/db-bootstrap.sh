#!/usr/bin/env bash
# Re-apply the idempotent DB bootstrap (databases, postgis, roles) to a running db container.
# Useful when the volume pre-dates a change to infra/db/init/20-winterpath.sh.
source "$(dirname "$0")/_common.sh"
require_docker
compose exec -T db bash /docker-entrypoint-initdb.d/20-winterpath.sh
