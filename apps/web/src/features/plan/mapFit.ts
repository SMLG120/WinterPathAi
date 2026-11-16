import type { LonLat, Route } from '@/api/types';
import { getCoverage } from '@/lib/coverage';
import type { RouteVariant } from '@/stores/planner-types';

export type Padding = { top: number; right: number; bottom: number; left: number };
export type Bounds = [[number, number], [number, number]];
const MIN_VISIBLE = 80;

/** Room kept clear of the map's own controls (zoom buttons top-right, attribution) on top of the caller's padding. */
export const CONTROL_PADDING: Padding = { top: 60, right: 64, bottom: 48, left: 32 };

/**
 * MapLibre silently skips fitBounds when the padding leaves no room ("cannot fit within canvas"),
 * which left the whole-region view in place. Shrink the padding so at least MIN_VISIBLE px remain.
 */
export function clampPadding(p: Padding, width: number, height: number): Padding {
  const fit = (a: number, b: number, size: number): [number, number] => {
    const room = Math.max(0, size - MIN_VISIBLE);
    if (a + b <= room) return [a, b];
    const k = room / (a + b || 1);
    return [Math.floor(a * k), Math.floor(b * k)];
  };
  const [top, bottom] = fit(p.top, p.bottom, height);
  const [left, right] = fit(p.left, p.right, width);
  return { top, right, bottom, left };
}

/**
 * Per side, the larger of the caller's padding (bottom sheet, panel) and the room the map controls
 * need; then clamped so MapLibre can always fit.
 */
export function fitPaddingFor(caller: Partial<Padding> | undefined, width: number, height: number): Padding {
  const c = caller ?? {};
  const side = (k: keyof Padding) => Math.max(CONTROL_PADDING[k], c[k] ?? 0);
  return clampPadding({ top: side('top'), right: side('right'), bottom: side('bottom'), left: side('left') }, width, height);
}

function extend(b: [number, number, number, number], x: number | undefined, y: number | undefined) {
  if (!Number.isFinite(x) || !Number.isFinite(y)) return;
  b[0] = Math.min(b[0], x!);
  b[1] = Math.min(b[1], y!);
  b[2] = Math.max(b[2], x!);
  b[3] = Math.max(b[3], y!);
}

/**
 * Bounds to show: the selected route (else the first) plus the start/destination markers, which
 * can sit up to 75 m off the snapped route line; the coverage area when there is no route.
 */
export function fitTarget(routes: Route[], selected: RouteVariant, points: (LonLat | null | undefined)[] = []): Bounds {
  const r = routes.find((x) => x.variant === selected) ?? routes[0];
  if (!r || r.geometry.coordinates.length === 0) {
    const { west: W, south: S, east: E, north: N } = getCoverage().box;
    return [[W, S], [E, N]];
  }
  const b: [number, number, number, number] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const c of r.geometry.coordinates) extend(b, c[0], c[1]);
  for (const p of points) if (p) extend(b, p.lon, p.lat);
  return [[b[0], b[1]], [b[2], b[3]]];
}

/** Straight-line span of the bounds in metres (equirectangular; good enough to pick a fit style). */
export function boundsSpanM([[w, s], [e, n]]: Bounds): number {
  const R = 6_371_000;
  const lat = (((s + n) / 2) * Math.PI) / 180;
  const dx = (((e - w) * Math.PI) / 180) * R * Math.cos(lat);
  const dy = (((n - s) * Math.PI) / 180) * R;
  return Math.hypot(dx, dy);
}

/** Long cross-region routes fly a little longer so the user can follow the move; short ones snap. */
export function fitDuration(spanM: number, reducedMotion: boolean): number {
  if (reducedMotion) return 0;
  return spanM > 10_000 ? 900 : 600;
}
