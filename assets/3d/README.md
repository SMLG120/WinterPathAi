# assets/3d

The v1 hero scene ships **no binary 3D assets**. The low-poly Montréal-inspired streetscape
(triplexes with exterior staircases, snowbanks, streetlights, pedestrian, highlighted path, snowfall)
is generated procedurally from three.js primitives in
`apps/web/src/components/hero/cityModel.ts` and rendered with instanced meshes in `Scene3D.tsx`.

Why: zero licence risk, ~2.7 KB gz of scene code instead of a GLB download, and the triangle /
draw-call budget is unit-tested (`cityModel.test.ts`).

If a GLB is added later: author it ourselves, compress with gltf-transform (Draco or meshopt),
keep ≤ 1.5 MB including textures, record it in `apps/web/ASSET_LICENSES.md`, and store it here.
