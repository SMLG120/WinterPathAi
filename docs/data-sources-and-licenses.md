# Data sources & licences — verified inventory

Verification date: **2026-11-10**. Method: Données Québec CKAN API (`package_show`), CSV header reads, and fetches of the policy pages listed. "Unverified" means not yet confirmed — the Data agent must confirm before ingest. **Not legal advice**; ODbL share-alike obligations need counsel review before a commercial launch.

| # | Source | Publisher | Licence (as stated) | Commercial | Access | Cadence / freshness (2026-11-10) | Use in WinterPath |
|---|---|---|---|---|---|---|---|
| 1 | OpenStreetMap data — **Geofabrik `quebec-latest.osm.pbf`** (decided 2026-11-10; Overpass public no longer used by the pipeline) | OSMF / contributors | ODbL (legal code 1.0 linked from openstreetmap.org/copyright) | Yes, with attribution + share-alike on derivative DBs | Overpass public: <10k queries/day, <1 GB/day, identifying UA, no parallel scripts, back off 30 s on 429; **"Commercial use should use self-hosted or paid Overpass servers"**. Geofabrik: no stated quotas; any purpose with OSM acknowledgement (ODbL applies) | Continuous | Pedestrian graph backbone |
| 2 | Trottoir et îlot (Voirie) — Données Québec `vmtl-voirie-trottoir-ilot`, donnees.montreal.ca `voirie-trottoir-ilot` | Ville de Montréal | CC BY 4.0 | Yes, attribution | Open; ZIP GeoJSON/SHP/CSV | Monthly; resources modified 2026-11-02; temporal 2009– | Sidewalk polygons → edge enrichment only |
| 3 | Requêtes 311 — DQ `vmtl-requete-311`, MTL `requete-311` | Ville de Montréal | CC BY 4.0 | Yes, attribution | Open CSV (2022–present + archives 2014–2021) | Daily; modified 2026-11-10 | Aggregated winter-report features + ML labels |
| 4 | Entraves et travaux en cours — DQ `vmtl-info-travaux`, MTL `info-travaux` | Ville de Montréal | CC BY 4.0 | Yes, attribution | Open CSV/JSON | Daily; modified 2026-11-10 | Closures — **only** rows where `sidewalk_blockedtype` indicates pedestrian impact |
| 5 | Déneigement / Planif-Neige `vmtl-deneigement` | Ville de Montréal | CC BY 4.0 | Yes | **Token required** (email donneesouvertes@montreal.ca); SOAP/WSDL | Irregular | Opt-in adapter only; street snow-loading ≠ sidewalk clearance |
| 6 | ECCC MSC GeoMet OGC API (api.weather.gc.ca) | Environment and Climate Change Canada | ECCC Data Servers End-use Licence (page header v2.1.1 Aug 2026; §9 says v2.1 — mismatch noted) | Yes ("including for commercial purposes") | Open; no published rate limit found | Real-time / hourly / daily | Weather, alerts, historical climate |
| 7 | OpenFreeMap vector tiles | OpenFreeMap (MIT project; OSM data; OpenMapTiles schema) | Free, "Is commercial usage allowed? Yes." | Yes | No key; no SLA | — | Basemap (dev/pilot) |
| 8 | Protomaps basemap builds | Protomaps LLC | ODbL Produced Work; software BSD | Yes, OSM attribution | Self-host (don't hotlink downloads) | — | Production basemap fallback |

## Required attribution strings
- OSM: "© OpenStreetMap contributors" linking to https://www.openstreetmap.org/copyright, and state the data is available under the ODbL.
- OpenFreeMap: "OpenFreeMap © OpenMapTiles Data from OpenStreetMap" (MapLibre auto-adds from style).
- Ville de Montréal: "Contient des données de la Ville de Montréal, sous licence CC BY 4.0" + link to dataset page.
- ECCC: "Data Source: Environment and Climate Change Canada" + link to licence. Weather alerts reproduced **without alteration of content or intent**. No ECCC logos, no implied endorsement.

## Prohibited / restricted (verified policy text)
- **Public Nominatim**: autocomplete "strictly forbidden"; max 1 req/s; bulk scripts 4 req/min; must cache; custom UA. → Not used by WinterPath.
- **tile.openstreetmap.org**: no pre-seeding/bulk/offline; may be withdrawn for commercial services without notice; attribution must be visible. → Not used.
- **Planif-Neige**: do not bypass the token requirement.

## Schema notes (verified headers)
- 311 CSV columns: `ID_UNIQUE, NATURE, ACTI_NOM, TYPE_LIEU_INTERV, RUE, RUE_INTERSECTION1, RUE_INTERSECTION2, LOC_ERREUR_GDT, ARRONDISSEMENT, ARRONDISSEMENT_GEO, LIN_CODE_POSTAL, DDS_DATE_CREATION, PROVENANCE_*, UNITE_RESP_PARENT, LOC_LONG, LOC_LAT, LOC_X, LOC_Y, DERNIER_STATUT, DATE_DERNIER_STATUT`. The dataset warns it contains all requests whether or not the City intervened. **Location obfuscation — verified 2026-11-10 (Data agent, methodology "Production des données"):** address/installation locations are relocated to the middle of the nearest street segment longer than 45 m; LOC_* are labelled "Position obfusquée"; the location is the request site, not the requester; information requests are not geolocated; `LOC_ERREUR_GDT=1` means located at the borough office (BAM) — those rows are excluded. No further precision is published. `DDS_DATE_CREATION` has no timezone and the publisher doesn't state one (**unresolved**). Archive files overlap — dedupe on `ID_UNIQUE`. Regardless: aggregate to H3 res-9 cells; suppress cells with n<3 in public output; never display individual points.
- Entraves impacts CSV includes `sidewalk_blockedtype`, `backsidewalk_blockedtype`, `streetid`, `fromname`, `toname`, `length`. Main CSV includes `duration_start_date`, `duration_end_date`, `currentstatus`, `longitude`, `latitude`.
- Voirie: polygons differentiated by category/type; "not necessarily up to date across the whole territory" (publisher warning).

## Winter 311 categories (Data agent, from 996 distinct `ACTI_NOM`, 2022→2026-11-09)
`Trottoir glissant` → `sidewalk_slippery` (12 984) · `Chaussée glissante` → `roadway_slippery` (11 280) · `Opération déneigement` + `Déneigement ruelle` → `snow_clearing` (76 710) · `Dépôt Illégal - Neige` + `Dépôt neige-ruelle` → `snow_dumping` (7 375). Excluded: signage, towing, permits, cycle-path clearing, Info-Neige card, generic sidewalk repair.

## ECCC stations in use
7025251 MONTREAL INTL A (hourly since 2013; **hourly PRECIP_AMOUNT null throughout**; daily SNOW_ON_GROUND/TOTAL_PRECIPITATION populated) and 702S006 MONTREAL/PIERRE ELLIOTT TRUDEAU INTL (hourly precip present; hourly ends 2026-10-01 per metadata). ~13.6 km from McGill; no downtown hourly station found. SWOB `snw_dpth=-1` is a sentinel → NULL.

## Still unresolved
- 311 timestamp timezone unstated by publisher.
- Canada.ca terms of service linked from GeoMet; OpenFreeMap `/tos/`; FOSSGIS Overpass terms page — not yet read.
- Fonts and 3D asset licences (Frontend agent's asset manifest).
- ODbL derivative-database obligations — counsel review before commercial launch.
