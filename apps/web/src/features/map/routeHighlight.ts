import { create } from 'zustand';
import type { RouteVariant } from '@/stores/planner-types';

/**
 * Transient hover/focus highlight shared by the map lines, the compact route cards and the
 * comparison details. Selection itself stays in the planner store (`selected`); this is only the
 * "pointing at" state, so hovering never changes what is shown or fitted.
 */
type HighlightState = {
  hovered: RouteVariant | null;
  /** Where the highlight came from: the map line or a card/details panel. */
  from: 'map' | 'list' | null;
  setHovered: (v: RouteVariant | null, from: 'map' | 'list') => void;
};

export const useRouteHighlight = create<HighlightState>((set, get) => ({
  hovered: null,
  from: null,
  setHovered: (hovered, from) => {
    const s = get();
    if (s.hovered === hovered && (hovered === null || s.from === from)) return;
    set({ hovered, from: hovered ? from : null });
  },
}));

/** Props for any list element that should highlight its route on the map while pointed at / focused. */
export function highlightHandlers(variant: RouteVariant) {
  const set = useRouteHighlight.getState().setHovered;
  const clear = () => {
    if (useRouteHighlight.getState().hovered === variant) set(null, 'list');
  };
  return {
    onPointerEnter: () => set(variant, 'list'),
    onPointerLeave: clear,
    onFocus: () => set(variant, 'list'),
    onBlur: clear,
  };
}
