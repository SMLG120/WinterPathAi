import { useMemo, useState } from 'react';
import { clipToPilot, formatBbox, isQueryableBbox, type Bbox } from '@/lib/geo';
import { useDebounced } from '@/lib/useDebounced';

export type OverlayBboxState = { bbox: string | null; reason: 'ok' | 'outside' | 'too-large' | 'pending' };

/** Viewport → debounced, pilot-clipped bbox suitable for /hazards and /map/segments. */
export function useOverlayBbox(debounceMs = 400) {
  const [viewport, setViewport] = useState<Bbox | null>(null);
  const debounced = useDebounced(viewport, debounceMs);
  const state = useMemo<OverlayBboxState>(() => {
    if (!debounced) return { bbox: null, reason: 'pending' };
    const clipped = clipToPilot(debounced);
    if (!clipped) return { bbox: null, reason: 'outside' };
    if (!isQueryableBbox(clipped)) return { bbox: null, reason: 'too-large' };
    return { bbox: formatBbox(clipped), reason: 'ok' };
  }, [debounced]);
  return { ...state, setViewport };
}
