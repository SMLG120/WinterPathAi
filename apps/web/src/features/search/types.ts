import type { EvidenceState, LonLat } from '@/api/types';

/** RQA `qualite_positionnement_geometrique`, as stable ids (see qualityFromRqa). */
export type PositionQuality = 'building' | 'front_lot' | 'access' | 'lot_centre' | 'site' | 'interpolated' | 'uncertain' | 'other';

export type ResultSource = 'rqa' | 'osm' | 'typed';

export type SearchResult = {
  id: string;
  /** address & place & coordinates set a point; street only completes the text (no point). */
  kind: 'address' | 'place' | 'street' | 'coordinates';
  label: string;
  /** Municipality, or the original-language name for an alias. */
  detail: string;
  point: LonLat | null;
  source: ResultSource;
  /** Position quality of an RQA address. */
  quality?: PositionQuality;
  /** OSM place kind (station, university, park…). */
  placeKind?: string;
  /** Evidence state of the POSITION (never of safety or routability). null for typed coordinates. */
  evidence: EvidenceState | null;
  /** Text put in the input for a street completion. */
  completion?: string;
  /** nearest_civic: the typed number is not listed; this is the closest listed number. */
  note?: 'nearest_civic' | 'lat_lon' | 'lon_lat' | 'outside_area';
  ref?: string;
};

export type SearchStatus = 'ok' | 'too_short' | 'coords_out_of_range';

export type SearchOutcome = { status: SearchStatus; results: SearchResult[] };

export type SourceInfo = {
  id: string;
  title: string;
  licence: string;
  licence_url: string;
  url: string;
  version: string;
  attribution: { fr: string; en: string };
};

/**
 * A place-search backend. The static same-origin index is the only implementation today; a
 * server-side geocoder can replace it later by implementing this interface (no UI change).
 */
export interface SearchProvider {
  readonly id: string;
  /** `near`: optional bias point (e.g. the coverage centre) used only to break ties. */
  search(query: string, opts?: { signal?: AbortSignal; limit?: number; near?: LonLat }): Promise<SearchOutcome>;
  sources(): Promise<SourceInfo[]>;
}

/** The index could not be loaded (missing deploy step, network, integrity). Retryable. */
export class SearchUnavailableError extends Error {
  constructor(
    message: string,
    readonly reason: 'missing' | 'network' | 'integrity' | 'format',
  ) {
    super(message);
    this.name = 'SearchUnavailableError';
  }
}

/** Position evidence: published building/lot position = confirmed; interpolated = estimate; uncertain = unknown. */
export function evidenceForQuality(q: PositionQuality): EvidenceState {
  if (q === 'interpolated') return 'model_estimate';
  if (q === 'uncertain' || q === 'other') return 'unknown';
  return 'confirmed';
}

const RQA_QUALITY: Record<string, PositionQuality> = {
  Bâtiment: 'building',
  'Front lot': 'front_lot',
  'Accès propriété': 'access',
  'Centre lot': 'lot_centre',
  Site: 'site',
  Géocodée: 'interpolated',
  Incertaine: 'uncertain',
};

export function qualityFromRqa(label: string | undefined): PositionQuality {
  return (label && RQA_QUALITY[label]) || 'other';
}
