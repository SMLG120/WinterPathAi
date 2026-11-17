# Place search (addresses and named places)

Owner: Agent A (search). Status: built on `agent/search`, not merged, not deployed.

## What it does

The planner's search box finds Greater Montréal addresses and named places, in French or English,
and fills the start or the destination. It also accepts typed coordinates.

- **Area:** all 16 municipalities of the Montréal agglomeration, plus Laval, Longueuil,
  Brossard, Boucherville, Saint-Lambert, Terrebonne and Repentigny.
- **No third-party geocoder.** Public Nominatim is forbidden, and no paid service or API key is
  used. The browser downloads small JSON files from the site's own origin
  (`/search/...`), so the production CSP (`connect-src 'self' …`) is unchanged.
- **Nothing in the API or the database.** Supabase has no room for a trigram index, and the
  Render API is near its 512 MB limit.

A result is a **place, not a confirmed walking endpoint**. The UI says so, and the route API
(`OFF_NETWORK`, `OUTSIDE_COVERAGE`) decides whether the point can be routed.

## Sources and licences

| Source | Used for | Licence | Attribution shown |
|---|---|---|---|
| Référentiel québécois des adresses (RQA), MRNF, version `20261101` (`RQA_CSV.zip`) | Civic addresses and street names | CC BY 4.0 | Under the search box, in `manifest.json` |
| OpenStreetMap, Geofabrik Québec extract `quebec-261110.osm.pbf` | Named places | ODbL 1.0 | Under the search box, in `manifest.json` |

- The RQA user guide (`Guide_d_utilisation_RQA.pdf`, text read for this work) says:
  - any use, including modification or integration in other products, must respect CC BY 4.0;
  - "Code postal" is an official mark of Canada Post, and the RQA includes information licensed
    from Canada Post.
  - **Postal codes are therefore not copied into the index.**
- The Ville de Montréal "Adresse ponctuelle" dataset is not used. RQA covers the island with
  per-row position quality and monthly updates (see docs/agent-reports/data.md §5).
- **ODbL:** the shards are a derived database of OSM data. If they are distributed, they must
  stay under ODbL with attribution. They are not committed to Git. Change request CR-SEARCH-1
  asks the coordinator to add both sources to `docs/data-sources-and-licenses.md`.

## Honesty rules applied

- Every address result shows its source and its RQA position quality, using the guide's
  definitions:

  | RQA value | Shown as | Evidence state of the position |
  |---|---|---|
  | Bâtiment | on the building, not necessarily the entrance | `confirmed` |
  | Front lot, Accès propriété, Centre lot, Site | front of lot, main access, centre of lot, site | `confirmed` |
  | Géocodée (interpolated along the road segment's address range) | approximate, interpolated along the street | `model_estimate` |
  | Incertaine | uncertain position | `unknown` |

- An RQA "Incertaine" or "Géocodée" point is never presented as an exact entrance.
- OSM places are `unverified_report`, like every OSM attribute in this app, and are labelled as
  "Label point of a community-mapped place, not an entrance".
- Typed coordinates are labelled "Coordinates you typed". They carry no evidence badge, because
  they are the user's own input, not data from a source.
- **Civic number not listed:** the closest listed number on that street is offered with an
  explicit note ("1450 is not listed on this street; this is the closest listed number"). It
  is never silently substituted.
- The evidence state describes the position only. It never says anything about safety,
  clearance or accessibility.

## Index format (`winterpath-search/1`)

```
apps/web/public/search/            (git-ignored; copied into dist/ by vite build)
  manifest.json                    format, build_id, sources (version, licence, attribution, input sha256),
                                   municipalities, RQA quality vocabulary, counts, sha256 of every shard
  v/<build_id>/s/<key>.json        token shards: streets and places having a name token starting with <key>
  v/<build_id>/a/<n>.json          address buckets: civic numbers of street ids ≡ n (mod 512)
```

- **Token shards.** Each shard holds the streets and places that have a name token starting with
  `<key>` (the first two characters of a canonical token).
  - Street row: `["s", sid, display, muni, tokens, generic, direction, count, lonE5, latE5]`.
  - Place row: `["p", pid, name, muni, tokens, kind, lonE5, latE5, osm_ref, primary_name]`.
    There is one row per distinct name (`name`, `name:fr`, `name:en`, `official_name`,
    `alt_name`, `short_name`).
- **Address rows.** Each row is `[civic, dLon, dLat, quality]`. Coordinates are 1e-5 degree
  integers, delta-encoded and sorted by civic number.
- **Deterministic.** The same inputs give byte-identical shards and the same `build_id`. That
  id is a hash of all shard hashes, and no wall-clock time is written to any shipped file.
- **Integrity.** The client checks each shard's SHA-256 against the manifest when
  `crypto.subtle` is available.
- **Caching.**
  - `/search/v/*` is `immutable` in `public/_headers`, because the version is in the path.
  - `manifest.json` keeps the Pages default (revalidated).
- **Missing files.** On Cloudflare Pages a missing file returns `index.html` with status 200.
  The client accepts only JSON content types, so a missing index gives an "unavailable" state,
  never a crash.

### Normalisation (identical in Python and TypeScript)

The rules are the same in Python and TypeScript, and the shared vectors
`apps/web/src/features/search/normalize.vectors.json` run in both test suites.

- Accents and case are folded, and every non-alphanumeric character becomes a separator.
- `saint/sainte/ste/st` → `st`.
- Ordinals: `1re/1er/1ère/première/1st` → `1`, and so on.
- Articles (`de du des la le les l d au aux of the`) are dropped.

The query parser (`query.ts`) handles the following:

- **Civic number.** A leading number is the civic number. A trailing one also works
  (`rue Peel 1455`). Suffixes and ranges are accepted (`1455A`, `1455-1457`). `2e` is an
  ordinal, not civic 2E.
- **Street type.** These words are optional, and give a bonus when they match: `rue/street`,
  `boul/boulevard/blvd/bd`, `av/ave/avenue`, `ch/chemin/road`, `pl/place`, `côte`, `montée`
  and others.
- **`St` read as "Street".** A trailing `St` after a name (`Peel St`, `Ste-Catherine St W`) is
  read as "Street".
- **Direction.** `O/Ouest/W/West`, `E/Est/East`, `N/Nord/North` and `S/Sud/South` are soft:
  they add a bonus or a penalty, and never filter.
- **Municipality.** The text after the last comma, or trailing words naming an indexed
  municipality, filters by municipality.

### Coordinates

These forms are accepted:

- `45.50, -73.57`
- `45.50 -73.57`
- `45,50; -73,57`
- `45.5N 73.57W`
- `-73.57, 45.50`

The order is decided explicitly:

1. Hemisphere letters decide.
2. Otherwise, a value beyond ±90 can only be a longitude.
3. Otherwise, if exactly one order falls in Greater Montréal, that order is used.
4. Otherwise both readings are offered, each labelled.

A decimal part (or a hemisphere letter) is required, so `1455 12` stays an address query.

## UI

`apps/web/src/features/search/SearchBox.tsx` is an ARIA 1.2 combobox with a listbox popup.

- **Keyboard.**
  - `aria-activedescendant` tracks the active option.
  - Up and Down wrap around the list.
  - Enter chooses the active option.
  - Escape closes the list; a second Escape clears the text.
- **Timing.** Typing is debounced by 300 ms, and a superseded request is aborted.
- **States:**
  - loading ("Searching…");
  - too short;
  - empty, which names the query;
  - invalid coordinates;
  - unavailable or network error, with a **Retry** button.
- **Fill target.** A radio group chooses Start or Destination. After a start is chosen, the
  target moves to Destination.
- **Street completion.** A street with no civic number fills the text ("Rue X, Municipality")
  and puts the caret at the start, so the user can type the number. It sets no point.
- **Store.** `setPoint(which, point, label)` stores `labels[which]` in
  `apps/web/src/stores/planner.ts`. This is additive. The label is cleared when the point is set
  any other way (map pick, coordinates, geolocation), and travels with its point on swap.
- **`PointInput`** shows the label, its source and quality, the evidence badge, and the note
  that the place is not a confirmed walking endpoint. Coordinate entry, map picking and
  geolocation are unchanged.
- **Map markers.** `PlannerMap.tsx` was not edited. Its existing markers follow
  `origin`/`destination`. For Agent D, `labels.origin` and `labels.destination` (text, detail,
  kind, source, quality, evidence) are available, for example for marker titles or to fit the
  map to a searched point outside the current view.
- **Provider.** The UI depends only on `SearchProvider` (`types.ts`), which has `search` and
  `sources`. A future backend geocoder can be injected through `SearchProviderContext` without
  UI changes.
- **Privacy.**
  - Queries never leave the browser. The server only sees which 2-character shard and which
    address bucket were requested.
  - Nothing is logged or stored.
  - The planner store is not persisted.

## Building the index

```bash
cd services/ingestion
uv sync
uv run python -m winterpath_ingestion.search_index \
  --rqa  <data>/raw/addresses/RQA_CSV.zip \
  --osm  <data>/raw/osm/geofabrik/quebec-261110.osm.pbf \
  --out  ../../apps/web/public/search \
  --report /tmp/search-index-report.json
```

- `--out` must be a directory named `search`. Old `v/<build_id>` directories are removed and the
  manifest is replaced atomically.
- The OSM pass needs a few GB of RAM (`flex_mem` location index over all of Québec).
- Measured numbers are in `docs/agent-reports/search.md`.

## Deployment

- Build step: `scripts/build-search-index.sh <RQA_CSV.zip> <quebec.osm.pbf>` (docs/DEPLOYMENT.md §3), then
  `npm run build:pages`, which refuses a bundle whose index is missing, altered, stale or unattributed
  (`build/pagesCheck.ts`). CI builds without the index (`PAGES_ALLOW_NO_SEARCH_INDEX=1`).
- The shards are **not committed**: they are derived from raw data (about 20 MB, about 945
  files), and `apps/web/.gitignore` ignores `public/search/`.
- Deployments are direct uploads (`wrangler pages deploy dist`), so the index must be built
  into `apps/web/public/search` **before** `npm run build:pages`. Vite copies it into `dist/`.
- **Cloudflare Pages limits:** at most 20,000 files and 25 MiB per file. The index is about
  945 files, and its largest file is under 300 KB.
- **Without the index**, the search box shows "Search is unavailable" and the rest of the
  planner works.
- **Refresh:** RQA is published monthly. Rebuild with the new zip and redeploy the web app. The
  build id changes, so caches cannot serve mixed versions.

## Tests

- **Python:** `services/ingestion/tests/test_search_index_build.py` and
  `test_search_index_normalize.py`.
- **Web unit and component:** `apps/web/src/features/search/*.test.ts(x)`. The synthetic
  fixture is `testIndex.ts`.
- **Real-index goldens:** `apps/web/src/features/search/realIndex.test.ts`, which is skipped
  when `public/search` is absent.
- **E2E:** `npx playwright test -c playwright.search.config.ts`, which builds a mock-API bundle
  on port 5176 and skips when the index is absent.
