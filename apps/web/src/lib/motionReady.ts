import { useSyncExternalStore } from 'react';

/**
 * Tracks whether Motion's async animation features have loaded. Components only start
 * from a hidden `initial` state once this is true, so content is never left invisible if
 * the features chunk is slow or fails to load (e.g. stale hashes after a deploy).
 */
let ready = false;
const listeners = new Set<() => void>();

export function loadMotionFeatures() {
  return import('./motionFeatures').then((m) => {
    ready = true;
    listeners.forEach((l) => l());
    return m.default;
  });
}

export function useMotionReady(): boolean {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => ready,
    () => false,
  );
}
