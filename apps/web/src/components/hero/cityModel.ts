/**
 * Original, procedurally generated low-poly "Montréal-inspired" streetscape.
 * Generic triplexes with exterior staircases, snowbanks, streetlights, a pedestrian
 * and a highlighted path. No real street likeness, no third-party models.
 *
 * Pure data + geometry factories so the triangle / draw-call budget can be
 * verified in a unit test without WebGL (cityModel.test.ts).
 */
import * as THREE from 'three';

export type Instance = { p: [number, number, number]; s: [number, number, number]; r?: number; c?: string };
export type Part = {
  id: string;
  geometry: () => THREE.BufferGeometry;
  material: 'standard' | 'emissive' | 'snow';
  color: string;
  emissive?: string;
  instances: Instance[];
};

/** Deterministic PRNG so the scene (and poster) are stable across loads. */
function mulberry32(seed: number) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const BRICK = ['#8c4a3c', '#9b5b45', '#7a4436', '#a8705a', '#6f5b52', '#8a6a55'];
export const STREET_LENGTH = 44;
export const SNOW_COUNT = 700;

export function createCityModel(seed = 7): Part[] {
  const rnd = mulberry32(seed);
  const bodies: Instance[] = [];
  const cornices: Instance[] = [];
  const windows: Instance[] = [];
  const steps: Instance[] = [];
  const balconies: Instance[] = [];
  const doors: Instance[] = [];

  // Two rows of triplexes facing a street that runs along Z.
  for (const side of [-1, 1] as const) {
    let z = -STREET_LENGTH / 2 + 1;
    while (z < STREET_LENGTH / 2 - 3) {
      const w = 4.2 + rnd() * 1.2;
      const h = 6.6 + rnd() * 1.4;
      const d = 7;
      const x = side * (6.2 + d / 2);
      const cz = z + w / 2;
      const color = BRICK[Math.floor(rnd() * BRICK.length)]!;
      bodies.push({ p: [x, h / 2, cz], s: [d, h, w - 0.15], c: color });
      cornices.push({ p: [x - side * 0.1, h + 0.18, cz], s: [d + 0.3, 0.36, w + 0.05] });
      const face = side * 6.2;
      // 3 floors × 2 windows on the street facade.
      for (let f = 0; f < 3; f++) {
        for (const off of [-0.9, 0.9]) {
          windows.push({ p: [face - side * 0.02, 1.4 + f * 2.1, cz + off], s: [0.06, 1.0, 0.7] });
        }
      }
      // Ground-floor door + second-floor balcony.
      doors.push({ p: [face - side * 0.03, 1.0, cz - 1.6], s: [0.06, 1.9, 0.8] });
      balconies.push({ p: [face + side * 0.55, 2.95, cz], s: [1.1, 0.12, w - 0.6] });
      // Iconic exterior staircase: 8 steps climbing to the balcony.
      for (let i = 0; i < 8; i++) {
        steps.push({
          p: [face + side * (2.6 - i * 0.25), 0.2 + i * 0.35, cz + 1.25],
          s: [0.3, 0.08, 0.9],
        });
      }
      z += w;
    }
  }

  const snowbanks: Instance[] = [];
  for (const side of [-1, 1] as const) {
    for (let z = -STREET_LENGTH / 2; z < STREET_LENGTH / 2; z += 1.6 + rnd()) {
      snowbanks.push({
        p: [side * (3.3 + rnd() * 0.3), 0.15, z],
        s: [0.9 + rnd() * 0.4, 0.45 + rnd() * 0.35, 1.1 + rnd() * 0.6],
        r: rnd() * Math.PI,
      });
    }
  }

  const poles: Instance[] = [];
  const lamps: Instance[] = [];
  for (const side of [-1, 1] as const) {
    for (let z = -STREET_LENGTH / 2 + 4; z < STREET_LENGTH / 2; z += 9) {
      const zz = z + (side > 0 ? 4.5 : 0);
      poles.push({ p: [side * 4.1, 2.4, zz], s: [1, 1, 1] });
      lamps.push({ p: [side * 3.75, 4.85, zz], s: [1, 1, 1] });
    }
  }

  // Highlighted path: dashes along the right sidewalk, then crossing the street.
  const path: Instance[] = [];
  for (let z = 12; z > -16; z -= 1.4) path.push({ p: [4.9, 0.32, z], s: [0.35, 0.04, 0.9] });
  for (let x = 4.2; x > -4.2; x -= 1.2) path.push({ p: [x, 0.07, -16.8], s: [0.8, 0.04, 0.35] });

  const sidewalks: Instance[] = [
    { p: [-4.9, 0.12, 0], s: [2.6, 0.24, STREET_LENGTH] },
    { p: [4.9, 0.12, 0], s: [2.6, 0.24, STREET_LENGTH] },
  ];

  const box = () => new THREE.BoxGeometry(1, 1, 1);
  return [
    { id: 'ground', geometry: () => new THREE.PlaneGeometry(80, 80).rotateX(-Math.PI / 2), material: 'snow', color: '#e9f2f7', instances: [{ p: [0, -0.01, 0], s: [1, 1, 1] }] },
    { id: 'road', geometry: () => new THREE.PlaneGeometry(7.2, STREET_LENGTH).rotateX(-Math.PI / 2), material: 'standard', color: '#4a5566', instances: [{ p: [0, 0.01, 0], s: [1, 1, 1] }] },
    { id: 'sidewalks', geometry: box, material: 'snow', color: '#dfe9f0', instances: sidewalks },
    { id: 'bodies', geometry: box, material: 'standard', color: '#ffffff', instances: bodies },
    { id: 'cornices', geometry: box, material: 'snow', color: '#f4f8fb', instances: cornices },
    { id: 'windows', geometry: box, material: 'emissive', color: '#f6d8a0', emissive: '#e7a83e', instances: windows },
    { id: 'doors', geometry: box, material: 'standard', color: '#2c3a4f', instances: doors },
    { id: 'balconies', geometry: box, material: 'standard', color: '#2b2f36', instances: balconies },
    { id: 'steps', geometry: box, material: 'standard', color: '#2b2f36', instances: steps },
    { id: 'snowbanks', geometry: () => new THREE.IcosahedronGeometry(1, 1), material: 'snow', color: '#f7fafc', instances: snowbanks },
    { id: 'poles', geometry: () => new THREE.CylinderGeometry(0.07, 0.09, 4.8, 8), material: 'standard', color: '#1d2633', instances: poles },
    { id: 'lamps', geometry: () => new THREE.SphereGeometry(0.22, 10, 8), material: 'emissive', color: '#fff4d6', emissive: '#ffd27a', instances: lamps },
    { id: 'path', geometry: box, material: 'emissive', color: '#bde8f4', emissive: '#087f8c', instances: path },
  ];
}

/** The pedestrian is animated separately (3 meshes). */
export const pedestrianParts = () => [
  { id: 'ped-body', geometry: new THREE.CapsuleGeometry(0.22, 0.7, 4, 8), color: '#087f8c', y: 0.85 },
  { id: 'ped-head', geometry: new THREE.SphereGeometry(0.17, 10, 8), color: '#f0c9a8', y: 1.55 },
  { id: 'ped-hat', geometry: new THREE.ConeGeometry(0.19, 0.26, 8), color: '#e7a83e', y: 1.75 },
];

export function triangleCount(g: THREE.BufferGeometry): number {
  return g.index ? g.index.count / 3 : g.getAttribute('position').count / 3;
}

/** Budget accounting (ux-spec: ≤ 60k triangles, ≤ 50 draw calls). Snow points add 1 draw call, 0 triangles. */
export function sceneBudget(parts = createCityModel()) {
  let triangles = 0;
  let drawCalls = 1; // snowfall points
  for (const part of parts) {
    const g = part.geometry();
    triangles += triangleCount(g) * part.instances.length;
    drawCalls += 1; // one InstancedMesh per part
    g.dispose();
  }
  for (const p of pedestrianParts()) {
    triangles += triangleCount(p.geometry);
    drawCalls += 1;
    p.geometry.dispose();
  }
  return { triangles, drawCalls };
}
