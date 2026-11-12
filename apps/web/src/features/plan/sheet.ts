/** Mobile bottom-sheet snap points (v2 brief: peek / half / full). Heights in px of the planner area. */
export type Snap = 'peek' | 'half' | 'full';
export const SNAPS: Snap[] = ['peek', 'half', 'full'];

/** Peek = the handle row only (grabber + one-line summary): map stays almost fully visible. */
export const PEEK_PX = 76;
/** Full leaves a strip of map at the top so the user still sees where they are. */
export const FULL_GAP_PX = 48;

export function snapHeight(s: Snap, areaHeight: number): number {
  if (s === 'peek') return Math.min(PEEK_PX, areaHeight);
  if (s === 'full') return Math.max(PEEK_PX, areaHeight - FULL_GAP_PX);
  return Math.max(PEEK_PX, Math.round(areaHeight * 0.5));
}

/** Where a drag ends: a quick flick (|velocity| > 0.5 px/ms) moves one step, otherwise the nearest snap. */
export function settleSnap(height: number, areaHeight: number, velocity = 0): Snap {
  if (Math.abs(velocity) > 0.5) {
    const nearest = settleSnap(height, areaHeight);
    const i = SNAPS.indexOf(nearest);
    // velocity < 0: finger moving up → taller sheet.
    const j = Math.min(SNAPS.length - 1, Math.max(0, i + (velocity < 0 ? 1 : -1)));
    const step = SNAPS[j]!;
    // Don't jump past the snap the finger is already beyond.
    return (velocity < 0 ? snapHeight(step, areaHeight) >= height : snapHeight(step, areaHeight) <= height) ? step : nearest;
  }
  return SNAPS.reduce((best, s) => (Math.abs(snapHeight(s, areaHeight) - height) < Math.abs(snapHeight(best, areaHeight) - height) ? s : best));
}

/** Tap on the handle cycles peek → half → full → peek; Arrow keys move one step. */
export function nextSnap(s: Snap, dir: 'up' | 'down' | 'cycle'): Snap {
  const i = SNAPS.indexOf(s);
  if (dir === 'up') return SNAPS[Math.min(SNAPS.length - 1, i + 1)]!;
  if (dir === 'down') return SNAPS[Math.max(0, i - 1)]!;
  return SNAPS[(i + 1) % SNAPS.length]!;
}
