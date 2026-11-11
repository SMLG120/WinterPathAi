# Data compliance matrix

Verification dates are per row. Source of record for source details: `docs/data-sources-and-licenses.md`; asset licences: `apps/web/ASSET_LICENSES.md`. **Not legal advice** — ODbL share-alike, Québec Law 25 and provider terms need counsel review before any commercial launch.

| Dataset / service | Provider | URL | Licence | Commercial reuse | Attribution | Quotas / access | Credentials | Update cadence | WinterPath use | Verified |
|---|---|---|---|---|---|---|---|---|---|---|
| OSM extract `quebec-latest.osm.pbf` | Geofabrik / OSM contributors | https://download.geofabrik.de/north-america/canada/quebec.html | ODbL 1.0 | Yes, with attribution + share-alike on derived databases | "© OpenStreetMap contributors", ODbL link | No stated quota; one download per refresh, cached, MD5-verified | None | Daily extracts; WinterPath refreshes manually | Pedestrian graph (pilot bbox clip only) | 2026-11-10 |
| Overpass API (public) | FOSSGIS | https://overpass-api.de | ODbL data | Policy directs commercial use to self-hosted/paid servers | — | <10k queries/day | None | — | **Not used by the pipeline** (ad-hoc developer checks only) | 2026-11-10 |
| Trottoir et îlot (Voirie) | Ville de Montréal | https://donnees.montreal.ca/dataset/voirie-trottoir-ilot | CC BY 4.0 | Yes | "Contient des données de la Ville de Montréal, sous licence CC BY 4.0" | Open download | None | Monthly | Sidewalk enrichment (never connectivity) | 2026-11-10 |
| Requêtes 311 | Ville de Montréal | https://donnees.montreal.ca/dataset/requete-311 | CC BY 4.0 | Yes | As above | Open CSV | None | Daily | H3 res-9 daily aggregates; n<3 suppressed publicly; no raw rows stored | 2026-11-10 |
| Entraves et travaux | Ville de Montréal | https://donnees.montreal.ca/dataset/info-travaux | CC BY 4.0 | Yes | As above | Open CSV/JSON | None | Daily | Closures only where `sidewalk_blockedtype` indicates pedestrian impact | 2026-11-10 |
| Déneigement / Planif-Neige | Ville de Montréal | https://donnees.montreal.ca/dataset/deneigement | CC BY 4.0 | Yes | As above | SOAP API | **Token required** — not requested; never bypassed | Irregular | **Not used** in the deployment | 2026-11-10 |
| ECCC MSC GeoMet OGC API | Environment and Climate Change Canada | https://api.weather.gc.ca | ECCC Data Servers End-use Licence | Yes ("including for commercial purposes") | "Data Source: Environment and Climate Change Canada"; alerts reproduced without alteration | No published rate limit found; identifying User-Agent | None | Hourly / daily | Weather observations (stations 7025251, 702S006) | 2026-11-10 |
| OpenFreeMap tiles + style | OpenFreeMap | https://openfreemap.org/tos/ | Free service; OSM data ODbL; OpenMapTiles schema | Yes ("Is commercial usage allowed? Yes.") | "© OpenMapTiles", "Data from OpenStreetMap" (MapLibre adds automatically) | "no limits on the number of map views or requests"; no automated collection; no SLA; may be discontinued without notice | None | — | Basemap at runtime (not bundled) | 2026-11-11 |
| tile.openstreetmap.org | OSMF | — | — | Restricted | — | No bulk/pre-seeding | — | — | **Not used** | 2026-11-10 |
| Geocoding | — | — | — | — | — | Public Nominatim autocomplete "strictly forbidden" | — | — | **No geocoder in v1**; map-pin selection; replaceable backend interface (`GEOCODER_PROVIDER`) | 2026-11-10 |
| Fonts (Inter, Source Serif 4) | Fontsource | npm packages | SIL OFL 1.1 | Yes | Licence text shipped in package | Self-hosted | None | — | UI typography | 2026-11-10 |
| Icons (lucide-react) | Lucide | npm | ISC | Yes | — | — | None | — | UI icons | 2026-11-10 |
| 3D scenes | Project-owned (procedural three.js primitives) | — | Project-owned | Yes | — | — | — | — | Hero + condition explainer (illustrative only) | 2026-11-10 |

## Still unresolved
- 311 `DDS_DATE_CREATION` timezone not published.
- Canada.ca terms linked from GeoMet; FOSSGIS Overpass terms page — not yet read.
- ODbL derivative-database obligations for the hosted PostGIS graph (likely a "Derivative Database" offered publicly via the API) — counsel review.
- Cloudflare free-plan commercial-use terms not found on the pages read.

## Privacy (Québec Law 25 oriented — needs counsel review)
- **Public deployment is read-only** (`API_PUBLIC_WRITES=false`): no community reports, pilot requests, accounts or route history are collected.
- Geolocation is requested only after an explicit user action; manual map selection is always available.
- Route coordinates are processed in memory; logs contain only rounded (3 dp) values or H3 res-7 cells, tested by the platform harness (`log_scan.precise_coordinates`, 0 hits on 2026-11-11).
- No cookies or analytics are added by WinterPath. OpenFreeMap states it does not use cookies and does not keep IP addresses in access logs.
- Hosting locations: API on Render (Virginia, USA); database on Supabase (Canada if available on Free, else USA). Because no personal information is collected in the read-only demo, no cross-border transfer of personal information is expected; **enabling public writes requires a privacy impact assessment first** (Law 25 s. 17).
- On-screen limitation notice: routes and risk layers are decision support; winter conditions change quickly; nothing guarantees a sidewalk is safe, cleared or accessible.
