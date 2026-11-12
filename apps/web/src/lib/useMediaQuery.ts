import { useSyncExternalStore } from 'react';

/** Live `matchMedia` result (false where matchMedia is unavailable, e.g. jsdom without a stub). */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia?.(query);
      m?.addEventListener('change', cb);
      return () => m?.removeEventListener('change', cb);
    },
    () => window.matchMedia?.(query).matches ?? false,
    () => false,
  );
}
