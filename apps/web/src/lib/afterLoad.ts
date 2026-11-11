/**
 * Runs `cb` once the page has finished loading, the main thread is idle and an
 * extra grace period has passed — so heavy lazy chunks (3D, map) never compete
 * with the first meaningful paint (LCP). Returns a cancel function.
 */
export function afterLoadAndIdle(cb: () => void, graceMs = 0): () => void {
  let cancelled = false;
  let timer: number | undefined;
  let idleId: number | undefined;
  const w = window as Window & {
    requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number;
    cancelIdleCallback?: (id: number) => void;
  };
  const run = () => {
    if (cancelled) return;
    const fire = () => {
      if (!cancelled) timer = window.setTimeout(() => !cancelled && cb(), graceMs);
    };
    if (w.requestIdleCallback) idleId = w.requestIdleCallback(fire, { timeout: 1500 });
    else fire();
  };
  if (document.readyState === 'complete') run();
  else window.addEventListener('load', run, { once: true });
  return () => {
    cancelled = true;
    window.removeEventListener('load', run);
    if (timer !== undefined) window.clearTimeout(timer);
    if (idleId !== undefined) w.cancelIdleCallback?.(idleId);
  };
}

/** Two animation frames: the browser has painted what's already rendered. */
export function afterPaint(cb: () => void): () => void {
  let cancelled = false;
  const id = requestAnimationFrame(() => requestAnimationFrame(() => !cancelled && cb()));
  return () => {
    cancelled = true;
    cancelAnimationFrame(id);
  };
}
