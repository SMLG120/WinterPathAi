// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { createExplainerModel, explainerBudget, LENSES, LENS_EVIDENCE } from './explainerModel';

describe('condition explainer scene', () => {
  it('stays far inside the 3D budget (≤ 60k triangles, ≤ 50 draw calls)', () => {
    const { triangles, drawCalls } = explainerBudget();
    console.warn(`[explainer-budget] triangles=${triangles} drawCalls=${drawCalls}`);
    expect(triangles).toBeLessThanOrEqual(60_000);
    expect(drawCalls).toBeLessThanOrEqual(50);
  });

  it('every lens has at least one element to highlight', () => {
    const lenses = new Set(createExplainerModel().map((p) => p.lens));
    for (const l of LENSES) expect(lenses.has(l)).toBe(true);
  });

  it('evidence per lens follows data-model.md; snow-loading never yields a sidewalk state', () => {
    expect(LENS_EVIDENCE).toEqual({
      steps: 'unknown',
      closure: 'confirmed',
      reports: 'unverified_report',
      snowLoading: null,
      weather: 'model_estimate',
    });
  });
});
