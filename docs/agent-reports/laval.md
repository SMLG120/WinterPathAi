# Agent E (laval) — Laval chantiers routiers → closures

Branch `agent/laval-closures`. Run date 2026-11-17.

## Source
- CKAN `chantiers-routiers` (Données Québec), organization `ville-de-laval`, license_id `cc-by` (CC BY 4.0), metadata_modified 2026-11-05T16:52:14.
- Resources (same data): CSV / GeoJSON / KML / SHP "permis-obstruction". Used GeoJSON (carries geometry):
  https://www.donneesquebec.ca/recherche/dataset/d41f625c-1bd3-4202-a8c1-50b573b3ade4/resource/3272909c-7469-4d87-acd2-4831a33d50f4/download/permis-obstruction.geojson (resource last_modified 2026-11-05T16:51:50).
- sha256 of downloaded file: `3d85b0d5516aa5cdd8889f1327c3a8dc8984bea52958b6e11ea408d38a00f7f9` (41 822 296 bytes), cached in git-ignored `data/raw/laval-chantiers/`.
- Attribution: "Contient des données de la Ville de Laval, sous licence CC BY 4.0".
- The dataset is **obstruction permits** (roadway), not only "road works".

## Schema (35 784 features, CRS84)
Geometry: LineString 31 313, MultiLineString 4 471, none missing. **No identifier column.** Properties (all rows): TYPE (14 values: Entrave, Fermeture, Détour, Obstruction partielle, ...), STATUT (Abandonné 35 456, Existant 226, '' 89, Proposé 13), DATE_DEBUT / DATE_FIN (`MM/DD/YYYY HH:MM:SS`; 506 / 562 empty; DATE_FIN has a year-0205 typo), REMARQUE, NATURE_TRAVAUX (20 values), ALERTE511, CIRCULATION (10), PUBLIQUE, ENTRAVE (12: '', Partielle, Fermeture complète, Rue barrée, Stationnement, Trottoir (1 row), ...), RESPONSABLE (13), LOCALISATION (street names, free text).
There is no pedestrian-passage field. **Lead review correction (2026-11-17):** `ENTRAVE='Trottoir'` (obstruction on the sidewalk) occurs on **81** features (80 `Abandonné`, 1 `Existant`), not 1; it is now kept verbatim in `sidewalk_blockedtype`. It is not a statement that passage is blocked, so `blocks_passage` stays null. Other trottoir/piéton mentions are free text (REMARQUE, LOCALISATION, NATURE_TRAVAUX 'Réfection de trottoir-bordure') and are not parsed.

## Counts
- features_total 35 784; 519 byte-identical duplicate features collapsed; kept inside the SDA Laval (65005) polygon: **35 263** closures (coarse-bbox run gave 35 265).
- status: permit_issued 225 (Existant); unknown 35 038 (Abandonné 34 936, '' 89, Proposé 13).
- Active today (2026-11-17: permit_issued AND valid_from <= now AND (valid_to null OR now < valid_to)): **89**. 9 Existant rows lack valid_from and are not counted.
- Null valid_from 503, null valid_to 561; date_flags: end_before_start 111, DATE_FIN implausible/unparsed 3.
- blocks_passage: true 0 / false 0 / **null 35 263**.
- Geometry: LineString 30 916, MultiLineString 4 347.

## Mapping
| Field | Rule |
|---|---|
| closure_id | `laval:<sha1[:16]>` of canonical (properties+geometry) JSON; the publisher gives no id, so ids change if a record is edited |
| status | STATUT: Existant→permit_issued; all else (Abandonné, Proposé, '', unseen)→unknown, raw in attrs.currentstatus. "Abandonné" is NOT read as cancelled/completed (35k historic records; meaning unverified) |
| valid_from / valid_to | DATE_DEBUT / DATE_FIN as America/Montreal local → ISO with offset; empty/unparseable/year<2000 → null (raw kept in attrs, flag in attrs.date_flags). Whether DATE_FIN midnight is inclusive is not published |
| blocks_passage, backsidewalk_blocks_passage | always null: no pedestrian field; a roadway closure never implies a sidewalk closure |
| sidewalk_blockedtype | `ENTRAVE` verbatim when it is `Trottoir` (81 rows: 1 permit_issued, 80 unknown); otherwise null — never inferred from free text |
| attrs | all 12 raw properties verbatim, currentstatus, date_flags, weekly_schedule=null (not published → activity inside the window unknown) |
| evidence_state | confirmed (the permit record only) |
| geometry | published line as is (roadway, not sidewalk) |

Region: `wp-ingest laval-chantiers` keeps features intersecting the SDA Laval polygon if `data/processed/boundaries_sda` exists, else a coarse Laval bbox (which also catches northern Montréal-island edges). `--region` is not applicable.

## Tests (literal, services/ingestion)
```
All checks passed!                      (uv run ruff check .)
39 files already formatted              (uv run ruff format --check .)
108 passed, 10 skipped, 2 warnings in 3.33s   (uv run pytest -q)
```
New: tests/test_laval_chantiers.py (18 tests) + tests/fixtures/laval_chantiers_sample.geojson (4 real rows, coordinates rounded to 6 dp).

## Change request (coordinator; docs/contracts untouched)
CR-LAVAL-1: add canonical source id `laval-chantiers` to /data-sources (registry.py entry added: Ville de Laval, CC BY 4.0, attribution above, url https://www.donneesquebec.ca/recherche/dataset/chantiers-routiers). Also: (a) approve the `laval:` closure_id prefix (content hash); (b) no db_load loader written (needs the wp.source row and a decision on target DB), so `load --source laval-chantiers` is not wired; (c) note in data-model that Laval closures are lines and that `status='unknown'` covers the historic "Abandonné" rows.

## Open issues
- "Abandonné" semantics unverified; with status unknown, `wp.closure_active_at` will not treat those rows as active. Confirm with the publisher whether it means ended/archived.
- Hash ids: an upstream edit yields a new id.
- No weekly schedule; active-by-dates is only an upper bound.
- Routing must match these roadway lines to edges itself; nothing here claims sidewalk status.


## Lead review (2026-11-17)
- Re-ran in services/ingestion: `ruff check` → All checks passed!; `ruff format --check` → 39 files already formatted; `pytest -q` → 115 passed, 10 skipped (7 new parametrised cases for the sidewalk mapping).
- Real file through `build_closures` (bbox only): 35,265 closures; `sidewalk_blockedtype` Trottoir 81 / null 35,184; `blocks_passage` null for all.
