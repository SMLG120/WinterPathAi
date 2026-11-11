import { create } from 'zustand';

export type ThemePref = 'light' | 'dark' | 'system';
const KEY = 'wp-theme';

function read(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'light' || v === 'dark' ? v : 'system';
  } catch {
    return 'system';
  }
}

export function resolveTheme(pref: ThemePref, systemDark: boolean): 'light' | 'dark' {
  return pref === 'system' ? (systemDark ? 'dark' : 'light') : pref;
}

type State = { pref: ThemePref; setPref: (p: ThemePref) => void };

/** Theme preference persisted locally (a UI convenience only — no personal data). */
export const useThemeStore = create<State>((set) => ({
  pref: read(),
  setPref: (pref) => {
    try {
      if (pref === 'system') localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, pref);
    } catch {
      /* storage unavailable: keep in memory */
    }
    set({ pref });
  },
}));
