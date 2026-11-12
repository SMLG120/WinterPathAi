import { create } from 'zustand';
import type { LonLat } from './planner-types';

/**
 * Recent destinations — opt-in, this device only, clearable (v2 brief).
 *
 * Privacy limits (architecture §9: no location tracking):
 * - nothing is stored until the user ticks the opt-in; turning it off deletes everything;
 * - destinations only, never the start point (often home) or the user's geolocation;
 * - rounded to 4 decimals (≈ 11 m) — enough to route (the API snaps within 75 m);
 * - at most 5 entries, each dropped after 30 days;
 * - never sent anywhere: used only to fill the destination field when the user picks one.
 */
export type RecentDestination = { lon: number; lat: number; at: number };

export const RECENT_KEY = 'wp-recent-destinations';
export const OPT_IN_KEY = 'wp-recent-optin';
export const RECENT_MAX = 5;
export const RECENT_TTL_MS = 30 * 24 * 3600 * 1000;

const round4 = (x: number) => Math.round(x * 1e4) / 1e4;

function read<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v == null ? fallback : (JSON.parse(v) as T);
  } catch {
    return fallback;
  }
}
function write(key: string, v: unknown | null) {
  try {
    if (v == null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(v));
  } catch {
    /* storage blocked (private mode): the feature simply does not persist */
  }
}

function valid(list: unknown, now: number): RecentDestination[] {
  if (!Array.isArray(list)) return [];
  return list
    .filter(
      (x): x is RecentDestination =>
        !!x && typeof x === 'object' && Number.isFinite(x.lon) && Number.isFinite(x.lat) && Number.isFinite(x.at) && now - x.at < RECENT_TTL_MS,
    )
    .slice(0, RECENT_MAX);
}

type State = {
  enabled: boolean;
  items: RecentDestination[];
  setEnabled: (on: boolean) => void;
  add: (p: LonLat, now?: number) => void;
  clear: () => void;
};

export const useRecentDestinations = create<State>((set, get) => {
  const now = Date.now();
  const enabled = read<boolean>(OPT_IN_KEY, false) === true;
  const items = enabled ? valid(read(RECENT_KEY, []), now) : [];
  if (!enabled) write(RECENT_KEY, null);
  return {
    enabled,
    items,
    setEnabled: (on) => {
      write(OPT_IN_KEY, on ? true : null);
      write(RECENT_KEY, null);
      set({ enabled: on, items: [] });
    },
    add: (p, at = Date.now()) => {
      if (!get().enabled) return;
      const e = { lon: round4(p.lon), lat: round4(p.lat), at };
      const items = [e, ...valid(get().items, at).filter((x) => x.lon !== e.lon || x.lat !== e.lat)].slice(0, RECENT_MAX);
      write(RECENT_KEY, items);
      set({ items });
    },
    clear: () => {
      write(RECENT_KEY, null);
      set({ items: [] });
    },
  };
});
