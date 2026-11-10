# UX specification — v1

Brand: **WinterPath AI** — EN "Navigate Montreal's winter, one better step at a time." / FR « Traversez l'hiver montréalais, un meilleur pas à la fois. »

## Design system
- Tokens (CSS variables, Tailwind theme): `--navy #101B2C`, `--frost #BDE8F4`, `--teal #087F8C`, `--ice #F7FAFC`, `--slate #64748B`, `--amber #E7A83E`. Light + dark themes; system default, user toggle persisted.
- Contrast: all text ≥ 4.5:1 (large ≥ 3:1) — verify teal/amber on both themes; amber is never used for body text on ice.
- Type: open-licensed fonts self-hosted (e.g. Inter / Source Serif 4 — licence recorded in `apps/web/ASSET_LICENSES.md`).
- Components: shadcn/ui (Radix) primitives; focus ring 2 px frost on navy / teal on ice.
- Evidence badges (icon + text, never colour alone): Confirmed ✓ · Unverified report ⚑ · Model estimate ≈ · Unknown ? · SIMULATED (striped amber banner).
- Motion: Motion for React; all animation disabled under `prefers-reduced-motion`.

## Routes / pages
| Path | Page | Must contain |
|---|---|---|
| `/` | Landing | Hero + CTA "Plan your winter walk", 3D winter city (lazy), value prop, product preview, how-it-works (3 steps), privacy/data disclaimer, partner use cases, FAQ, footer with attributions |
| `/plan` | Route planner | Full-height MapLibre map; origin/destination via map click, "use my location" (consent), manual coordinates/address search (backend geocoder when configured; otherwise disabled with explanation); profile selector (standard / step-free / reduced mobility); compare card (shortest vs winter-aware: distance, duration, unknown share, explanation, freshness); hazard + closure overlays with legend; list-based step directions; mobile bottom sheet |
| `/winter` | Winter intelligence | ECCC current + forecast, unaltered alerts, freeze-thaw indicator, 311 winter-report history chart (aggregated), model status card (shows "disabled — not yet validated" when applicable), last-refresh timestamps, missing-data states |
| `/reports` | Community reports | Form (category, location with explicit consent checkbox, ≤280 chars), receipt with deletion token, status explanation, expiry notice, rate-limit message |
| `/how-it-works` | Transparency | Sources + licences (from `/data-sources`), map attribution, evidence states, model card, coverage map, privacy (Law 25), limitations |
| `/pilot` | Business / pilot | Segments (universities, campuses, municipalities, property managers), what a pilot includes, aggregate analytics description, form → `/pilot-requests`. No testimonials, logos or metrics that weren't measured |
| `/admin` | Moderation (token) | Not linked publicly |

Language: `/en/...` and `/fr/...` prefix; language switch preserves route; `<html lang>` updated. Every string through i18next; namespaces `common`, `landing`, `plan`, `winter`, `reports`, `how`, `pilot`, `errors`. CI fails on missing keys in either locale.

## Interaction states (every data view)
loading (skeleton) · success · empty · stale (freshness > threshold, amber badge) · error (retry) · offline · unknown/coverage-gap (hatched overlay, "Outside pilot area").
Geolocation denied → manual entry remains fully functional (Playwright test).

## 3D
- Original low-poly Montreal-inspired streetscape (generic triplexes with exterior staircases, snowbanks, streetlights, pedestrian, highlighted path, snowfall particles). No real-street likeness, no third-party proprietary models.
- Budget: ≤ 1.5 MB compressed GLB (Draco/meshopt) + textures, ≤ 60k triangles, ≤ 50 draw calls, DPR capped at 1.5 desktop / 1 mobile, 60 fps target on mid desktop, frameloop `demand` when idle.
- Lazy-loaded below LCP (static poster image first); `prefers-reduced-motion` → static poster; no WebGL → poster; scene has `aria-hidden` and a text description.
- Optional "sidewalk condition explainer" scene, labelled illustrative.

## Performance budgets
LCP < 2.5 s (4G mid phone), initial JS < 250 KB gz excluding map + 3D chunks, map chunk lazy on `/plan`. Measured with Lighthouse in CI; numbers reported, not assumed.

## Accessibility
Target WCAG 2.2 AA; axe in Playwright on every page; keyboard path through planner; route list alternative to map; target size ≥ 24 px. Do not claim compliance before an audit.
