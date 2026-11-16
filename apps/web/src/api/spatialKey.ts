/**
 * Spatially normalised overlay bboxes: the viewport is widened outward to a zoom-dependent
 * grid so that small pans produce the *same* bbox string — the same TanStack Query key on the
 * client and the same response-cache key on the API. A grid cell is a power-of-two fraction of
 * a degree (exact in binary floating point, so snapping is deterministic) about one eighth of
 * the viewport's larger side; the widened box is then at most ~1.6× the viewport's area.
 *
 * The widened box is only used when it is still a valid request (inside coverage after
 * clipping, not over the API's area limit); otherwise a finer grid is tried, and finally the
 * viewport itself is used unchanged. Snapping only ever widens: every feature in the viewport
 * is still inside the requested box.
 */
import type { Bbox } from '@/lib/geo';

/** Grid cells per viewport side (larger side). */
export const GRID_DIVISIONS = 8;
/** How many finer grids to try when the widened box is too large. */
const FINER_TRIES = 3;

export function gridStep(b: Bbox, divisions = GRID_DIVISIONS): number {
  const span = Math.max(b[2] - b[0], b[3] - b[1]);
  if (!(span > 0) || !Number.isFinite(span)) return 0;
  return 2 ** Math.floor(Math.log2(span / divisions));
}

export function snapOutward([w, s, e, n]: Bbox, step: number): Bbox {
  if (!(step > 0)) return [w, s, e, n];
  return [Math.floor(w / step) * step, Math.floor(s / step) * step, Math.ceil(e / step) * step, Math.ceil(n / step) * step];
}

/**
 * `clipped` is the viewport already clipped to coverage; `clip` re-clips a widened box;
 * `ok` says whether a box may be requested (area limit).
 */
export function normaliseOverlayBbox(clipped: Bbox, clip: (b: Bbox) => Bbox | null, ok: (b: Bbox) => boolean): Bbox {
  let step = gridStep(clipped);
  for (let i = 0; i < FINER_TRIES && step > 0; i++, step /= 2) {
    const snapped = clip(snapOutward(clipped, step));
    if (snapped && ok(snapped)) return snapped;
  }
  return clipped;
}
