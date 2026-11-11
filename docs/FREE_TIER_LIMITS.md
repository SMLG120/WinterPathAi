# Free-tier limits and degradation plan

Verified **2026-11-11** against the providers' official pages (URLs below). Limits change; re-check before relying on them. "Not found" means the page read did not state it — it is not an assumption either way.

Target hosting cost: **$0/month**, conditional on staying inside these limits and **not adding a payment method to Render**.

## Cloudflare Pages (frontend)
Source: https://developers.cloudflare.com/pages/platform/limits/ · https://developers.cloudflare.com/pages/configuration/serving-pages/ · https://developers.cloudflare.com/pages/configuration/build-image/

| Limit | Free plan |
|---|---|
| Builds | 500 / month, 1 at a time, 20 min timeout |
| Files per site | 20 000 |
| Max file size | 25 MiB |
| Projects per account | 100; max 5 Pages projects per repository |
| `_headers` / `_redirects` | 100 header rules; 2 000 static + 100 dynamic redirects |
| Bandwidth / requests (static) | not stated on the limits page; Workers migration guide: "requests for static assets on Workers are free" ("Like Pages") |
| Commercial use / auto-billing | not found on the pages read |

Behaviour used by WinterPath: with no top-level `404.html`, Pages "assumes that you are deploying a single-page application" and serves `/` for unknown paths (SPA fallback, no `_redirects` needed). Node is pinned with `.node-version`; `package.json` `engines` is **not** honoured by build image v3. WinterPath deploys by **direct upload** (no build minutes on Cloudflare's side).

## Render Free (API)
Source: https://render.com/docs/free · https://render.com/docs/compute-plans · https://render.com/docs/web-services · https://render.com/docs/regions

| Limit | Free plan |
|---|---|
| Compute | 0.1 CPU, 512 MB RAM, single instance |
| Sleep | spins down after **15 min** without inbound traffic; spin-up "takes about one minute" |
| Instance hours | 750 / workspace / month; exceeded ⇒ all Free services suspended until next month |
| Bandwidth / build minutes | included amounts not stated; overage **billed if a payment method exists**, otherwise Free services are suspended (bandwidth) or builds disabled (build minutes) |
| Filesystem | ephemeral ("Local files lost on redeploy"); no persistent disk |
| Ports | bind `0.0.0.0:$PORT` (default 10000); outbound 25/465/587 blocked |
| Regions | Oregon, Ohio, **Virginia** (chosen), Frankfurt, Singapore |
| Production use | "Do not use them for production applications." |
| Render Postgres Free | expires after 30 days — **not used** |

WinterPath does **not** use keep-alive pings to defeat sleeping (policy). The frontend shows a "server is waking up" state and retries with a bounded backoff instead.

## Supabase Free (database)
Source: https://supabase.com/pricing · https://supabase.com/docs/guides/platform/cost-control · https://supabase.com/docs/guides/database/connecting-to-postgres · https://supabase.com/docs/guides/database/extensions/postgis

| Limit | Free plan |
|---|---|
| Database | 500 MB (shared CPU, 500 MB RAM) |
| Egress | 5 GB (+5 GB cached) |
| Projects | 2 active (paused projects don't count) |
| Inactivity | **paused after 1 week of inactivity** |
| Backups | **not included** on Free |
| Billing | "you will not be charged while using the Free Plan" |
| Connectivity | direct connection is **IPv6-only**; shared pooler (session + transaction) is IPv4. Render ⇒ use the **session pooler** |
| PostGIS | enable in schema `extensions`, never `public` |
| Regions | Canada availability **not verified** from docs — confirm when creating the project |

WinterPath's whole local database is **79 MB** (2026-11-11: edges 16 MB, 311 cells 18 MB, hourly weather 21 MB), about 16 % of the quota.

## OpenFreeMap (basemap)
Source: https://openfreemap.org/ · https://openfreemap.org/tos/ (updated 2026-10-14)
Commercial use "Yes"; "no limits on the number of map views or requests"; no API key; attribution required (MapLibre adds it automatically); **no SLA**; "may discontinue it at any time without notice"; automated collection prohibited except bounded offline downloads (≤ 3 000 tiles / 50 MB, ≤ 4 parallel requests, unique User-Agent).

## GitHub Actions (CI + scheduled jobs)
Private repository: uses the account's monthly free minutes; jobs stop when the quota is exhausted unless a payment method and spending limit are configured. Scheduled jobs (approved 2026-11-11): weather ingest every 3 h, daily risk scoring. Measured minutes/month to be recorded in `docs/OPERATIONS.md` after the first week.

## Degradation plan

| Event | What users see | What to do |
|---|---|---|
| Render asleep | "Server is waking up (up to about a minute)…", bounded retries, then a retry button | Nothing; it is expected on Free |
| Render suspended (hours/bandwidth) | API unreachable → clear error, static pages still load | Wait for month reset, or approve a paid plan |
| Supabase paused (1 week idle) | API `/health` degraded; routes fail with a clear error | Restore the project in the Supabase dashboard (`docs/RECOVERY.md`); the scheduled jobs normally keep it active |
| Supabase storage near 500 MB | ingest jobs fail; existing data still served | Trim `weather_obs` window / old `risk_cell_score` rows; see `docs/OPERATIONS.md` |
| OpenFreeMap outage | map background missing; routes, list view and attribution still shown | Switch `VITE_MAP_STYLE_URL` to another provider and redeploy |
| Weather ingest failing | `/weather/current` 503 "unavailable", never invented values | Check scheduled workflow logs |
| Scoring job failing | risk shown as **Unknown** (never low) | Check scheduled workflow logs |
| GitHub Actions minutes exhausted | jobs stop; data goes stale and is labelled stale | Reduce schedule or wait for reset |
