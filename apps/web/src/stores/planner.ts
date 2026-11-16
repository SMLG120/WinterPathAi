import { create } from 'zustand';
import type { EvidenceState } from '@/api/types';
import type { LonLat, RouteProfile, RouteVariant } from './planner-types';

export type PointKey = 'origin' | 'destination';

/**
 * Where an endpoint came from, when it was chosen in place search (features/search).
 * A label describes a PLACE, not a verified routable endpoint: routing decides that.
 * Cleared whenever the point is set any other way (map pick, coordinates, geolocation, swap keeps it with its point).
 */
export type EndpointLabel = {
  /** Display text, e.g. "1455 Boulevard De Maisonneuve Ouest" or "Université McGill". */
  text: string;
  /** Municipality / secondary text. */
  detail: string;
  kind: 'address' | 'place' | 'coordinates';
  /** rqa = Référentiel québécois des adresses; osm = OpenStreetMap; typed = coordinates typed by the user. */
  source: 'rqa' | 'osm' | 'typed';
  /** RQA position quality (address only). */
  quality?: 'building' | 'front_lot' | 'access' | 'lot_centre' | 'site' | 'interpolated' | 'uncertain' | 'other';
  /** Evidence state of the position (null for typed coordinates). */
  evidence: EvidenceState | null;
};

type State = {
  origin: LonLat | null;
  destination: LonLat | null;
  picking: PointKey | null;
  profile: RouteProfile;
  avoidUnverifiedReports: boolean;
  selected: RouteVariant;
  /** Search labels of the endpoints (additive, v2 search). null = set without search. */
  labels: Record<PointKey, EndpointLabel | null>;
  /** Set a point; `label` only when it comes from place search (any other source clears it). */
  setPoint: (k: PointKey, p: LonLat | null, label?: EndpointLabel | null) => void;
  /** Map click: fill the point being picked, else the first empty point, else replace destination. */
  pickFromMap: (p: LonLat) => void;
  setPicking: (k: PointKey | null) => void;
  swap: () => void;
  setProfile: (p: RouteProfile) => void;
  setAvoidUnverifiedReports: (v: boolean) => void;
  setSelected: (v: RouteVariant) => void;
  reset: () => void;
};

const initial = {
  origin: null,
  destination: null,
  picking: null,
  profile: 'standard' as RouteProfile,
  avoidUnverifiedReports: true,
  selected: 'winter_aware' as RouteVariant,
  labels: { origin: null, destination: null } as Record<PointKey, EndpointLabel | null>,
};

/**
 * Planner state. Deliberately NOT persisted: coordinates live in memory only
 * (no location tracking, no route history — architecture §9).
 */
export const usePlannerStore = create<State>((set, get) => ({
  ...initial,
  setPoint: (k, p, label = null) =>
    set((s) => ({ [k]: p, labels: { ...s.labels, [k]: p ? label : null } }) as Partial<State>),
  pickFromMap: (p) => {
    const { picking, origin, destination, labels } = get();
    const target: PointKey = picking ?? (!origin ? 'origin' : !destination ? 'destination' : 'destination');
    set({ [target]: p, picking: null, labels: { ...labels, [target]: null } } as Partial<State>);
  },
  setPicking: (picking) => set({ picking }),
  swap: () =>
    set((s) => ({ origin: s.destination, destination: s.origin, labels: { origin: s.labels.destination, destination: s.labels.origin } })),
  setProfile: (profile) => set({ profile }),
  setAvoidUnverifiedReports: (avoidUnverifiedReports) => set({ avoidUnverifiedReports }),
  setSelected: (selected) => set({ selected }),
  reset: () => set(initial),
}));
