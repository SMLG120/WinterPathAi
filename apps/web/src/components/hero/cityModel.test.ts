// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { createCityModel, sceneBudget } from './cityModel';

describe('3D hero scene budget (docs/ux-spec.md)', () => {
  it('stays within ≤ 60k triangles and ≤ 50 draw calls', () => {
    const { triangles, drawCalls } = sceneBudget();
    // Logged for the agent report.
    console.warn(`[3d-budget] triangles=${triangles} drawCalls=${drawCalls}`);
    expect(triangles).toBeLessThanOrEqual(60_000);
    expect(drawCalls).toBeLessThanOrEqual(50);
  });

  it('is deterministic (same seed → same layout)', () => {
    const a = createCityModel(7).map((p) => p.instances.length);
    const b = createCityModel(7).map((p) => p.instances.length);
    expect(a).toEqual(b);
  });

  it('contains the required elements: triplexes, staircases, snowbanks, streetlights, path', () => {
    const ids = new Map(createCityModel().map((p) => [p.id, p.instances.length]));
    for (const id of ['bodies', 'steps', 'snowbanks', 'poles', 'lamps', 'path']) expect(ids.get(id)).toBeGreaterThan(0);
  });
});
