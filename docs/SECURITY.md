# Security

Scope: the public read-only demo (Cloudflare Pages → Render FastAPI → Supabase PostGIS). Architecture rules: `docs/architecture.md` §9. Logging rules: `infra/OBSERVABILITY.md`.

## Secrets
- Secrets live only in: Render environment (API), GitHub Actions secrets (scheduled jobs), the operator's git-ignored `.env.local` / `.env.deploy` (mode 600).
- Never in Git (`.gitignore` covers `.env`, `.env.*` except `.env.example`), never in `VITE_*` variables, never in logs.
- `gitleaks` runs in CI over the full history and locally before every push (`make secrets`).
- Admin endpoints use a bearer token; only its SHA-256 (`API_ADMIN_TOKEN_HASH`) is stored server-side. In the read-only demo, admin endpoints remain but have nothing to moderate.

## Database
- Least-privilege login roles (`infra/SUPABASE.md`): `wp_api` (read; the demo needs no writes), `wp_etl` (member of `wp_writer`, scheduled jobs), `wp_migrate` (member of `wp_migrator`, manual migrations only). The Supabase `postgres` owner credentials are never given to the API or CI.
- API connects through the Supabase session pooler with TLS (`sslmode=require`).
- Schema `wp` is not exposed through the Supabase Data API; PostGIS lives in `extensions`, so `spatial_ref_sys` is not exposed via `public`.
- All SQL is parameterised (SQLAlchemy `text()` with bound parameters); table names in SQL strings are code constants only.

## API
- CORS: exact origin allow-list from `API_CORS_ORIGINS`; never `*`; no credentials.
- Input validation: Pydantic v2 with `extra=forbid`; explicit `null` rejected for non-nullable fields (API-NULL-1, fixed 2026-11-11, covered by the platform harness).
- Public writes disabled in the demo (`API_PUBLIC_WRITES=false` ⇒ 503 `WRITES_DISABLED`).
- Rate limiting: in-process token bucket per client (`API_RATE_LIMIT_PER_MINUTE`, default 60), verified to return 429 under load.
- Error envelopes never include stack traces; request IDs for correlation.
- Coordinates: logs contain only rounded or H3-cell locations; uvicorn access log disabled (it would print raw query strings).
- No file uploads; no pickle/joblib deserialisation in the API path (risk scores are read from Parquet locally or from PostGIS in deployment).
- Container runs as a non-root user (uid 10001) from `python:3.12-slim`, no build tools in the final stage.

## Web
- Static assets only; no secrets in the bundle (gitleaks over the repo; the production build is made with `VITE_USE_MOCKS` unset — **not yet enforced by a CI check**, and the deployed bundle must be scanned for secrets and mock markers after upload).
- Security headers via Cloudflare `_headers`: Content-Security-Policy (self, API origin, OpenFreeMap), `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy` (geolocation only for self), `frame-ancestors 'none'`.
- No public source maps in production.
- Geolocation only after an explicit user action.

## Supply chain
- Lockfiles committed (`uv.lock` per Python package, `package-lock.json`); CI runs `pip-audit` and `npm audit`.
- GitHub Actions pinned to commit SHAs; the Playwright container image is pinned by digest.
- Dependabot / renovate: not configured (future).

## Reporting
Private repository; report issues to the repository owner. No bug-bounty programme.

## Known gaps (2026-11-11)
- No WAF or bot protection beyond Cloudflare's defaults for static assets and the API's in-process rate limiter (resets on restart; single instance).
- No external uptime monitoring or alerting yet (`docs/OPERATIONS.md`).
- Security headers and CSP verified on the live deployment (2026-11-11, `curl -D -` and a browser session with no CSP violations); re-check after any `_headers` change.
