import { create } from 'zustand';

/** How many API requests are currently waiting for a sleeping backend to wake (cold start). */
export const useBackendStore = create<{ waking: number; adjust: (d: 1 | -1) => void }>((set) => ({
  waking: 0,
  adjust: (d) => set((s) => ({ waking: Math.max(0, s.waking + d) })),
}));
