# WinterPath AI — local developer entry points (Platform agent).
# Credentials are read from the untracked .env.local when present (never committed).

SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help

ENV_FILE ?= .env.local
COMPOSE := docker compose $(if $(wildcard $(ENV_FILE)),--env-file $(ENV_FILE),)
IT_DIR := tests/integration
PY_PACKAGES := services/ingestion services/routing services/ml services/api

.PHONY: help up up-db down config test contract smoke lint lint-python lint-web lint-infra secrets audit check-docker

help: ## List targets
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-12s %s\n", $$1, $$2}'

check-docker:
	@docker info >/dev/null 2>&1 || { echo "BLOCKED: Docker daemon unreachable (Docker Desktop paused/stopped?)" >&2; exit 2; }

config: ## Validate docker-compose.yml (no output on success)
	$(COMPOSE) config --quiet && echo "compose config OK"

up-db: check-docker ## Start only PostGIS and wait until healthy
	$(COMPOSE) up -d --wait --wait-timeout 180 db

up: check-docker ## Start db + api/web when their source trees exist on this branch
	@profiles="$$(infra/scripts/detect-services.sh)"; \
	echo "+ $(COMPOSE) $$profiles up -d --build --wait"; \
	$(COMPOSE) $$profiles up -d --build --wait --wait-timeout 300

down: check-docker ## Stop containers (keeps the shared winterpath_pgdata volume)
	$(COMPOSE) --profile api --profile web down

test: ## Integration tests: smoke, privacy, CORS, contract (stub unless API_BASE_URL is set)
	cd $(IT_DIR) && uv sync --locked --quiet && uv run pytest -q
	@for p in $(PY_PACKAGES); do \
	  if [[ -f $$p/pyproject.toml ]]; then echo "== $$p"; (cd $$p && uv run pytest -q); \
	  else echo "SKIP $$p: no pyproject.toml on this branch"; fi; \
	done
	@if [[ -f apps/web/package.json ]]; then (cd apps/web && npm run --if-present test -- --run); \
	else echo "SKIP apps/web: no package.json on this branch"; fi

contract: ## Schemathesis contract tests only (API_BASE_URL to target a real API)
	cd $(IT_DIR) && uv sync --locked --quiet && uv run pytest -q -m contract

smoke: ## Smoke tests only
	cd $(IT_DIR) && uv sync --locked --quiet && uv run pytest -q -m smoke

lint: lint-python lint-web lint-infra ## All linters

lint-python:
	cd $(IT_DIR) && uv sync --locked --quiet && uv run ruff check . && uv run ruff format --check .
	@for p in $(PY_PACKAGES); do \
	  if [[ -f $$p/pyproject.toml ]]; then echo "== $$p"; (cd $$p && uv run --with ruff ruff check . && uv run --with ruff ruff format --check .); \
	  else echo "SKIP $$p: no pyproject.toml on this branch"; fi; \
	done

lint-web:
	@if [[ -f apps/web/package.json ]]; then (cd apps/web && npm run --if-present lint); \
	else echo "SKIP apps/web: no package.json on this branch"; fi

lint-infra: ## actionlint + shellcheck + compose config
	@command -v actionlint >/dev/null || { echo "actionlint not installed (brew install actionlint)" >&2; exit 2; }
	actionlint
	@command -v shellcheck >/dev/null || { echo "shellcheck not installed (brew install shellcheck)" >&2; exit 2; }
	shellcheck -x -S warning infra/scripts/*.sh infra/db/init/*.sh
	POSTGRES_USER=lint POSTGRES_PASSWORD=lint-placeholder docker compose config --quiet && echo "compose config OK"

secrets: ## gitleaks over full git history (redacted output)
	@command -v gitleaks >/dev/null || { echo "gitleaks not installed (brew install gitleaks)" >&2; exit 2; }
	gitleaks git --redact --verbose --exit-code 1 .

audit: ## pip-audit for Python packages present; npm audit (fail on high) for web
	cd $(IT_DIR) && uv run --with pip-audit pip-audit --progress-spinner off
	@for p in $(PY_PACKAGES); do \
	  if [[ -f $$p/pyproject.toml ]]; then (cd $$p && uv run --with pip-audit pip-audit --skip-editable --progress-spinner off); \
	  else echo "SKIP $$p: no pyproject.toml on this branch"; fi; \
	done
	@if [[ -f apps/web/package.json ]]; then (cd apps/web && npm audit --audit-level=high --omit=dev); \
	else echo "SKIP apps/web: no package.json on this branch"; fi
