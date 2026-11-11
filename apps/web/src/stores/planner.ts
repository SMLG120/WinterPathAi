import { create } from 'zustand';
import type { LonLat, RouteProfile, RouteVariant } from './planner-types';

export type PointKey = 'origin' | 'destination';

type State = {
  origin: LonLat | null;
  destination: LonLat | null;
  picking: PointKey | null;
  profile: RouteProfile;
  avoidUnverifiedReports: boolean;
  selected: RouteVariant;
  setPoint: (k: PointKey, p: LonLat | null) => void;
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
};

/**
 * Planner state. Deliberately NOT persisted: coordinates live in memory only
 * (no location tracking, no route history — architecture §9).
 */
export const usePlannerStore = create<State>((set, get) => ({
  ...initial,
  setPoint: (k, p) => set({ [k]: p } as Pick<State, PointKey>),
  pickFromMap: (p) => {
    const { picking, origin, destination } = get();
    const target: PointKey = picking ?? (!origin ? 'origin' : !destination ? 'destination' : 'destination');
    set({ [target]: p, picking: null } as Partial<State>);
  },
  setPicking: (picking) => set({ picking }),
  swap: () => set((s) => ({ origin: s.destination, destination: s.origin })),
  setProfile: (profile) => set({ profile }),
  setAvoidUnverifiedReports: (avoidUnverifiedReports) => set({ avoidUnverifiedReports }),
  setSelected: (selected) => set({ selected }),
  reset: () => set(initial),
}));
