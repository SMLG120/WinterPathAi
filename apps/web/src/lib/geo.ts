import { MAX_BBOX_AREA_DEG2, PILOT_BBOX } from './env';
import type { LonLat } from '@/api/types';

export type Bbox = [minLon: number, minLat: number, maxLon: number, maxLat: number];

export function bboxArea([w, s, e, n]: Bbox): number {
  return Math.max(0, e - w) * Math.max(0, n - s);
}

/** Clip a viewport bbox to the pilot area; returns null when they don't intersect. */
export function clipToPilot([w, s, e, n]: Bbox): Bbox | null {
  const c: Bbox = [
    Math.max(w, PILOT_BBOX.west),
    Math.max(s, PILOT_BBOX.south),
    Math.min(e, PILOT_BBOX.east),
    Math.min(n, PILOT_BBOX.north),
  ];
  return c[0] < c[2] && c[1] < c[3] ? c : null;
}

/** Whether a bbox may be sent to /hazards or /map/segments without a 422 BBOX_TOO_LARGE. */
export function isQueryableBbox(b: Bbox): boolean {
  return bboxArea(b) > 0 && bboxArea(b) <= MAX_BBOX_AREA_DEG2;
}

/** Format for the `bbox` query parameter (minLon,minLat,maxLon,maxLat) with 5 dp. */
export function formatBbox(b: Bbox): string {
  return b.map((v) => v.toFixed(5)).join(',');
}

export function isInPilot(p: LonLat): boolean {
  return p.lon >= PILOT_BBOX.west && p.lon <= PILOT_BBOX.east && p.lat >= PILOT_BBOX.south && p.lat <= PILOT_BBOX.north;
}

export function isValidLonLat(p: { lon: number; lat: number }): boolean {
  return Number.isFinite(p.lon) && Number.isFinite(p.lat) && Math.abs(p.lon) <= 180 && Math.abs(p.lat) <= 90;
}

/** Display-only rounding; precise coordinates are never logged anywhere. */
export function formatLonLat(p: LonLat, dp = 5): string {
  return `${p.lat.toFixed(dp)}, ${p.lon.toFixed(dp)}`;
}
