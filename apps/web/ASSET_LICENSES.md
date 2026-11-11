# Asset & licence manifest — apps/web

Verified 2026-11-10 from installed `package.json` / `LICENSE` files (not from memory). Not legal advice.

## Fonts (self-hosted, bundled into `dist/assets/*.woff2`)
| Asset | Package | Licence | Commercial | Notes |
|---|---|---|---|---|
| Inter (variable) | `@fontsource-variable/inter` 5.3.0 | SIL OFL 1.1 | Yes | © The Inter Project Authors. Served from our own origin; no Google Fonts requests. |
| Source Serif 4 (variable) | `@fontsource-variable/source-serif-4` 5.3.1 | SIL OFL 1.1 | Yes | Full OFL text ships in the package `LICENSE`. |

## Images / illustrations
| Asset | Origin | Licence |
|---|---|---|
| Logo + favicon (`src/components/layout/Logo.tsx`, `public/favicon.svg`) | Original, authored for this project | Project-owned |
| Hero poster SVG (`src/components/hero/HeroPoster.tsx`) | Original, authored for this project | Project-owned |
| UI icons | `lucide-react` 0.545.0 | ISC |

## 3D
| Asset | Origin | Licence |
|---|---|---|
| Low-poly winter streetscape (`src/components/hero/cityModel.ts`, `Scene3D.tsx`) | Procedurally generated from three.js primitives (boxes, icosahedra, cylinders, spheres, capsule, cone). No GLB, no textures, no third-party or stock models. Generic, not modelled on any real street. | Project-owned |

Budget measured by `cityModel.test.ts` (see agent report): triangles and draw calls vs. ux-spec limits (≤ 60k, ≤ 50).

## Map
| Item | Licence / terms | Attribution shown |
|---|---|---|
| OpenFreeMap vector tiles + `positron` style (runtime, not bundled) | Free incl. commercial use; OSM data ODbL; OpenMapTiles schema | Auto from style + custom AttributionControl, always expanded |
| OpenStreetMap data | ODbL 1.0 | "© OpenStreetMap contributors (ODbL)" on map + footer |
| MapLibre GL JS 6.17.0 | BSD-3-Clause | — |

Not used: tile.openstreetmap.org, public Nominatim, Google Fonts CDN.

## Demo-mode data (mock build only, `VITE_USE_MOCKS=true`)
| Data | Origin | Licence |
|---|---|---|
| Sidewalk segments | `data/fixtures/pilot_mini/edges.geojson` (Data agent), real OSM extract, imported read-only | ODbL 1.0 (+ Ville de Montréal CC BY 4.0 for `sidewalk_polygon_ids`) |
| Hazards, weather, route geometries | Hand-written fixtures in `src/mocks/`, every datum `evidence.state = "simulated"` | Project-owned; visibly marked SIMULATED |

The fixture is **not** included in the production (real-API) build (verified: no fixture edge IDs in `dist/`).

## Runtime JavaScript dependencies (production)
Licence counts across all non-dev packages in `package-lock.json`: MIT 85, ISC 9, BSD-3-Clause 5, BSD-2-Clause 2, Apache-2.0 2, (MIT OR Apache-2.0) 1, 0BSD 1, OFL-1.1 2 (fonts). No copyleft code licences.
