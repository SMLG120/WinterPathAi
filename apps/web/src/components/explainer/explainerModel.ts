/**
 * "Sidewalk condition explainer" — original, procedural low-poly vignette (ux-spec §3D, optional).
 * One short block: a triplex with an exterior staircase, a sidewalk, a snowbank, a roadwork
 * barrier, a 311 report marker and an ice patch. Each element belongs to one explainer lens;
 * the selected lens is highlighted. Illustrative only: no real street, no live conditions.
 *
 * Pure data so the budget is unit-tested without WebGL (explainerModel.test.ts).
 */
import * as THREE from 'three';
import type { EvidenceState } from '@/api/types';
import type { Part } from '@/components/hero/cityModel';

export const LENSES = ['steps', 'closure', 'reports', 'snowLoading', 'weather'] as const;
export type Lens = (typeof LENSES)[number];

/**
 * Evidence state WinterPath attaches to what each source yields (docs/contracts/data-model.md):
 * closures = official permit data → confirmed (activity unknown → unknown, said in the copy);
 * 311 and community-mapped OSM step-free tags → unverified_report (openapi ExplanationItem v1.5 mapping);
 * risk layer (validated model or labelled heuristic) → model_estimate.
 * Snow-loading plans are never turned into a sidewalk state.
 */
export const LENS_EVIDENCE: Record<Lens, EvidenceState | null> = {
  steps: 'unverified_report',
  closure: 'confirmed',
  reports: 'unverified_report',
  snowLoading: null,
  weather: 'model_estimate',
};

export type ExplainerPart = Part & { lens: Lens | null };

const box = () => new THREE.BoxGeometry(1, 1, 1);

export function createExplainerModel(): ExplainerPart[] {
  const steps = Array.from({ length: 7 }, (_, i) => ({
    p: [-2.6 + i * 0.32, 0.25 + i * 0.36, -0.2] as [number, number, number],
    s: [0.34, 0.1, 1.1] as [number, number, number],
  }));
  return [
    // Context (never highlighted)
    { id: 'building', lens: null, geometry: box, material: 'standard', color: '#8c4a3c', instances: [{ p: [-5.5, 3.2, 0], s: [4, 6.4, 7] }] },
    { id: 'cornice', lens: null, geometry: box, material: 'standard', color: '#3c4658', instances: [{ p: [-5.4, 6.55, 0], s: [4.3, 0.3, 7.2] }] },
    { id: 'balcony', lens: null, geometry: box, material: 'standard', color: '#3c4658', instances: [{ p: [-3.1, 2.75, 0], s: [0.9, 0.12, 6.4] }] },
    { id: 'road', lens: null, geometry: box, material: 'standard', color: '#4a5468', instances: [{ p: [4.6, -0.05, 0], s: [5, 0.1, 9] }] },
    { id: 'sidewalk', lens: null, geometry: box, material: 'snow', color: '#cfd8e3', instances: [{ p: [0.2, 0.05, 0], s: [3.2, 0.2, 9] }] },
    // Lens elements
    { id: 'steps', lens: 'steps', geometry: box, material: 'standard', color: '#8a96ad', instances: steps },
    {
      id: 'barrier',
      lens: 'closure',
      geometry: box,
      material: 'standard',
      color: '#f2a23a',
      instances: [
        { p: [0.2, 0.75, 2.6], s: [2.6, 0.18, 0.12] },
        { p: [0.2, 0.45, 2.6], s: [2.6, 0.18, 0.12] },
        { p: [-1, 0.5, 2.6], s: [0.12, 1, 0.12] },
        { p: [1.4, 0.5, 2.6], s: [0.12, 1, 0.12] },
      ],
    },
    {
      id: 'report',
      lens: 'reports',
      geometry: () => new THREE.ConeGeometry(0.35, 0.9, 6),
      material: 'standard',
      color: '#e2b44a',
      instances: [{ p: [0.6, 1.75, -2.8], s: [1, 1, 1] }],
    },
    {
      id: 'reportPole',
      lens: 'reports',
      geometry: () => new THREE.CylinderGeometry(0.05, 0.05, 1, 6),
      material: 'standard',
      color: '#e2b44a',
      instances: [{ p: [0.6, 0.9, -2.8], s: [1, 1, 1] }],
    },
    {
      id: 'snowbank',
      lens: 'snowLoading',
      geometry: () => new THREE.IcosahedronGeometry(1, 1),
      material: 'snow',
      color: '#f4f8fb',
      instances: [
        { p: [2.2, 0.35, -2.4], s: [0.9, 0.7, 1.6] },
        { p: [2.25, 0.4, 0], s: [0.8, 0.8, 1.4] },
        { p: [2.2, 0.3, 2.3], s: [0.9, 0.6, 1.5] },
      ],
    },
    {
      id: 'ice',
      lens: 'weather',
      geometry: () => new THREE.CylinderGeometry(1, 1, 0.04, 10),
      material: 'standard',
      color: '#bde8f4',
      instances: [{ p: [0.3, 0.17, -0.9], s: [0.9, 1, 0.6] }],
    },
  ];
}

export function explainerBudget(parts = createExplainerModel()) {
  let triangles = 0;
  for (const p of parts) {
    const g = p.geometry();
    const idx = g.getIndex();
    const tri = (idx ? idx.count : g.getAttribute('position').count) / 3;
    triangles += tri * p.instances.length;
    g.dispose();
  }
  return { triangles, drawCalls: parts.length };
}
