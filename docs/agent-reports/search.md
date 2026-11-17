# Agent report — search (Agent A)

Status: **READY FOR REVIEW** · branch `agent/search` · base `e581535`
Feature commit `d07eee6`; finishing commit (this report, test fixes) follows it on the same branch.
Agent A stopped at a usage limit before writing this report; the lead finished it with the
commands below (2026-11-16). Not pushed, merged or deployed.

## What was built
- Self-hosted static place search: RQA addresses (CC BY 4.0, version 20261101, input sha256
  `f1e0725894bcfed5690a708c218af80e1a9564be0ce5263efc23ddd1d51450ea`) + OSM named places
  (ODbL, Geofabrik `quebec-261110`), prefix-sharded, served same-origin from Pages. No API key,
  no quota, no DB space, no API memory, no CSP change. Details: `docs/SEARCH.md`.
- `SearchBox` ARIA combobox (debounced, loading/empty/error/retry), fill origin or destination,
  coordinate parsing, EN/FR. Store: additive `labels: Record<PointKey, EndpointLabel | null>`;
  any non-search `setPoint`/map pick clears the label.
- Each result carries source and evidence state: RQA interpolated → `model_estimate`, RQA
  "Incertaine" → `unknown`, OSM places → `unverified_report`. A result is a place, not a
  confirmed routable endpoint.

## Index (local build `db33448b307ff577`)
| | |
|---|---|
| Municipalities | 23 (incl. island, Laval, Longueuil, Brossard, Saint-Lambert, Boucherville) |
| Addresses / streets / places | 984,119 / 13,917 / 6,413 (1,186 places outside the area dropped) |
| Addresses by quality | Géocodée 524,581 · Bâtiment 279,547 · Incertaine 178,951 · Centre lot 988 · Front lot 52 |
| Files / size | 945 files, 22 MB on disk; largest file 254,809 bytes (Pages limit 25 MiB, 20k files) |
| In Git | No — `apps/web/.gitignore` ignores `public/search/`; must be built before `build:pages` |

## Tests (literal summary lines, 2026-11-16)
```
$ npm run typecheck            # tsc -b --noEmit: no output
$ npm run lint                 # eslint --max-warnings 0: no output, exit 0
$ npx vitest run
 Test Files  26 passed (26)
      Tests  232 passed (232)
$ npx playwright test -c playwright.search.config.ts
  20 passed (57.4s)
$ npx playwright test          # main suite, before updating the obsolete test
  ✘   49 [desktop] › e2e/planner.spec.ts:94:1 › address search is disabled with an explanation (no public Nominatim) (1.1s)
  ✘  116 [mobile-390] › e2e/planner.spec.ts:94:1 › address search is disabled with an explanation (no public Nominatim) (1.1s)
  2 failed
  3 skipped
  129 passed (3.8m)
$ npx playwright test e2e/planner.spec.ts -g "place search is enabled"   # after replacing it
  2 passed (12.4s)
```
The 2 failures were the old test asserting the input is disabled; it now asserts an enabled combobox.

## Real-index queries (`realIndex.test.ts`, local index; `source|label|detail|position|evidence|lat,lon`)
```
Q: 1455 boul De Maisonneuve O  [ok, 1 results, 13 ms]
  address|rqa|1455 Boulevard De Maisonneuve Ouest|Montréal|interpolated|model_estimate|45.49730,-73.57900
Q: Université McGill  [ok, 2 results, 1 ms]
  place|osm|Université McGill|Montréal|university|unverified_report|45.50689,-73.57871
Q: Gare Centrale  [ok, 2 results, 1 ms]
  place|osm|Gare Centrale|Montréal|station|unverified_report|45.49993,-73.56669
Q: 1555 boul Chomedey, Laval  [ok, 1 results, 3 ms]
  address|rqa|1555 Boulevard Chomedey|Laval|interpolated|model_estimate|45.55360,-73.74779
Q: 151 rue St-Charles O, Longueuil  [ok, 1 results, 5 ms]
  address|rqa|151 Rue Saint-Charles Ouest|Longueuil|interpolated|model_estimate|45.53902,-73.50960
Q: 150 rue St-Charles O, Longueuil  [ok, 1 results, 2 ms]
  address|rqa|151 Rue Saint-Charles Ouest|Longueuil|interpolated|model_estimate|45.53902,-73.50960|nearest_civic
Q: 6000 boul de Rome, Brossard  [ok, 1 results, 3 ms]
  address|rqa|6000 Boulevard de Rome|Brossard|interpolated|model_estimate|45.44121,-73.44051
Q: 3480 rue University  [ok, 1 results, 1 ms]
  address|rqa|3480 Rue University|Montréal|uncertain|unknown|45.50667,-73.57734
Q: xqzzv wkkkp  [ok, 0 results, 0 ms]
Q: 45.5048, -73.5772  [ok, 1 results, 0 ms]
  coordinates|typed|45.504800, -73.577200|||-|45.50480,-73.57720
 Test Files  1 passed (1)
      Tests  7 passed (7)
```
- A non-existent civic number returns the nearest listed civic, flagged `nearest_civic` (shown to the user).
- Routability of a result is **not** verified here; the route API (OFF_NETWORK / outside coverage) decides.

## For integration (coordinator)
- D (`agent/mapux`) asked for `originMeta/destinationMeta` or an `endpoints` prop on `PlannerMap`.
  A's store exposes `labels`; Plan.tsx should pass `endpoints` derived from `labels` once both are merged.
- Deploy pipeline must run the index build (needs raw RQA zip + OSM pbf, a few GB RAM for the OSM pass)
  before `npm run build:pages`; otherwise the box shows "Search is unavailable".
- Not verified: Terrebonne / Repentigny queries; terms in the RQA user guide PDF beyond CC BY 4.0.
