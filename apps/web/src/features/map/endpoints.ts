/**
 * Optional per-endpoint metadata (label + where the point came from).
 *
 * The planner store (owned by the search work) may grow fields describing a point; this file only
 * READS them and every field is optional, so the map works unchanged before and after they land.
 * Accepted shapes, first match wins:
 *   - `originMeta` / `destinationMeta`: { label?, source? }
 *   - `originLabel` / `destinationLabel` (string) and `originSource` / `destinationSource` (string)
 */
import type { PointKey } from '@/stores/planner';

/** `search` = a place found by text search: shown as a place, not as a confirmed walkable endpoint. */
export type EndpointSource = 'map' | 'coordinates' | 'geolocation' | 'recent' | 'search';
export type EndpointMeta = { label?: string | null; source?: EndpointSource | string | null };
export type EndpointMetas = Partial<Record<PointKey, EndpointMeta>>;

const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v.trim() : null);

/** Read whatever endpoint metadata a planner-store snapshot carries (unknown shapes → nothing). */
export function readEndpointMeta(state: unknown, key: PointKey): EndpointMeta | undefined {
  if (!state || typeof state !== 'object') return undefined;
  const s = state as Record<string, unknown>;
  const meta = s[`${key}Meta`];
  let label: string | null = null;
  let source: string | null = null;
  if (meta && typeof meta === 'object') {
    const m = meta as Record<string, unknown>;
    label = str(m.label) ?? str(m.name);
    source = str(m.source);
  }
  label ??= str(s[`${key}Label`]);
  source ??= str(s[`${key}Source`]);
  return label || source ? { label, source } : undefined;
}

/** True when the point is a searched place: the API snaps it to the walkable network (≤ 75 m) or refuses it. */
export const isSearchedPlace = (m: EndpointMeta | undefined) => m?.source === 'search';

/** Stable string for effect dependencies (avoids re-creating markers on every store change). */
export const metaKey = (m: EndpointMeta | undefined) => (m ? `${m.source ?? ''}|${m.label ?? ''}` : '');
