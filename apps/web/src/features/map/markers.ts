/**
 * Start / destination marker elements. Shape, letter and text label distinguish them, never colour
 * alone: start = circle "A", destination = square "B". A searched place is a hollow, dashed map pin
 * with the place name: it marks a place, not a confirmed walkable endpoint (the API snaps it to the
 * network within 75 m or refuses it with OFF_NETWORK).
 *
 * Markers are not interactive (no tab stop, no pointer events), so map clicks go through them.
 */
import type { PointKey } from '@/stores/planner';

export const MARKER_COLORS: Record<PointKey, string> = { origin: '#087F8C', destination: '#101B2C' };
export const MARKER_LETTER: Record<PointKey, string> = { origin: 'A', destination: 'B' };

export type MarkerSpec = {
  key: PointKey;
  /** Accessible name, already localised (e.g. "Start: searched place, Gare Centrale — approximate"). */
  ariaLabel: string;
  searched: boolean;
  /** Visible place name for a searched place (truncated by CSS). */
  placeLabel?: string | null;
};

/** Inline SVG for the legend and the marker (one source of truth for the shapes). */
export function markerSvg(key: PointKey, searched: boolean, size = 32): string {
  const c = MARKER_COLORS[key];
  const letter = MARKER_LETTER[key];
  const text = (fill: string, y: number) =>
    `<text x="16" y="${y}" text-anchor="middle" font-family="Inter Variable,system-ui,sans-serif" font-size="14" font-weight="700" fill="${fill}">${letter}</text>`;
  if (searched) {
    // Teardrop pin, white fill, dashed outline in the point's colour; tip at the bottom centre.
    const h = Math.round(size * 1.3);
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${h}" viewBox="0 0 32 42" aria-hidden="true" focusable="false"><path d="M16 40 C16 40 3 25 3 15 A13 13 0 0 1 29 15 C29 25 16 40 16 40 Z" fill="#ffffff" stroke="${c}" stroke-width="3" stroke-dasharray="4 2.5"/>${text(c, 20)}</svg>`;
  }
  const shape =
    key === 'origin'
      ? `<circle cx="16" cy="16" r="13" fill="${c}" stroke="#ffffff" stroke-width="3"/>`
      : `<rect x="3.5" y="3.5" width="25" height="25" rx="3" fill="${c}" stroke="#ffffff" stroke-width="3"/>`;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 32 32" aria-hidden="true" focusable="false">${shape}${text('#ffffff', 21)}</svg>`;
}

/** The marker element and where MapLibre should anchor it. */
export function markerElement(spec: MarkerSpec): { el: HTMLDivElement; anchor: 'center' | 'bottom' } {
  const el = document.createElement('div');
  el.setAttribute('role', 'img');
  el.setAttribute('aria-label', spec.ariaLabel);
  el.dataset.testid = `marker-${spec.key}`;
  el.dataset.markerKind = spec.searched ? 'searched-place' : 'point';
  el.style.cssText = 'pointer-events:none;display:flex;flex-direction:column;align-items:center;filter:drop-shadow(0 1px 2px rgba(0,0,0,.45))';
  el.innerHTML = markerSvg(spec.key, spec.searched);
  if (spec.searched && spec.placeLabel) {
    const tag = document.createElement('span');
    tag.textContent = spec.placeLabel;
    tag.setAttribute('aria-hidden', 'true');
    // Under the pin would cover the tip; the label sits above it instead (anchor stays the tip).
    tag.style.cssText =
      'order:-1;margin-bottom:2px;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:1px 6px;border-radius:6px;background:#ffffff;color:#101B2C;font:600 12px/1.4 Inter Variable,system-ui,sans-serif;border:1px dashed #64748B';
    el.appendChild(tag);
  }
  return { el, anchor: spec.searched ? 'bottom' : 'center' };
}
