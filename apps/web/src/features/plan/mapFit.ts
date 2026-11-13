import type { Route } from '@/api/types';
import { getCoverage } from '@/lib/coverage';
import type { RouteVariant } from '@/stores/planner-types';

export type Padding = { top: number; right: number; bottom: number; left: number };
const MIN_VISIBLE = 80;

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

/** Bounds of the route to show (selected, else first), or the coverage area when there is none. */
export function fitTarget(routes: Route[], selected: RouteVariant): [[number, number], [number, number]] {
  const r = routes.find((x) => x.variant === selected) ?? routes[0];
  if (!r || r.geometry.coordinates.length === 0) {
    const { west: W, south: S, east: E, north: N } = getCoverage().box;
    return [[W, S], [E, N]];
  }
  const c = r.geometry.coordinates as [number, number][];
  let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const [x, y] of c) {
    x0 = Math.min(x0, x);
    y0 = Math.min(y0, y);
    x1 = Math.max(x1, x);
    y1 = Math.max(y1, y);
  }
  return [[x0, y0], [x1, y1]];
}
