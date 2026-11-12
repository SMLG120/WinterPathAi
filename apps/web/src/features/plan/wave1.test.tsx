import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { mockCompare } from '@/mocks/routes';
import { PTS } from '@/test/pilotPoints';
import { PILOT_BBOX } from '@/lib/env';
import { OPT_IN_KEY, RECENT_KEY, RECENT_MAX, RECENT_TTL_MS, useRecentDestinations } from '@/stores/recentDestinations';
import { clampPadding, fitTarget } from './mapFit';
import { nextSnap, PEEK_PX, settleSnap, snapHeight } from './sheet';
import { oldestFreshness } from './routeInfo';
import { RouteCards } from './RouteCards';

const routes = () => {
  const r = mockCompare({ origin: PTS.A, destination: PTS.B, locale: 'en' }, new Date());
  if (r.status !== 200) throw new Error('expected 200');
  return r.body.routes;
};

describe('bottom sheet snaps', () => {
  it('peek / half / full heights', () => {
    expect(snapHeight('peek', 780)).toBe(PEEK_PX);
    expect(snapHeight('half', 780)).toBe(390);
    expect(snapHeight('full', 780)).toBe(732);
  });
  it('a slow drag settles on the nearest snap; a flick moves one step in its direction', () => {
    expect(settleSnap(420, 780)).toBe('half');
    expect(settleSnap(120, 780)).toBe('peek');
    expect(settleSnap(400, 780, -1)).toBe('full'); // flick up from half
    expect(settleSnap(380, 780, 1)).toBe('peek'); // flick down from half
  });
  it('tap cycles, arrows step and stop at the ends', () => {
    expect(nextSnap('peek', 'cycle')).toBe('half');
    expect(nextSnap('half', 'cycle')).toBe('full');
    expect(nextSnap('full', 'cycle')).toBe('peek');
    expect(nextSnap('full', 'up')).toBe('full');
    expect(nextSnap('peek', 'down')).toBe('peek');
  });
});

describe('map fit', () => {
  it('fits the SELECTED route, not both, nor the region', () => {
    const rs = routes();
    const sel = rs.find((r) => r.variant === 'shortest')!;
    const xs = sel.geometry.coordinates.map((c) => c[0]!);
    expect(fitTarget(rs, 'shortest')[0][0]).toBe(Math.min(...xs));
    expect(fitTarget(rs, 'shortest')[1][0]).toBe(Math.max(...xs));
  });
  it('no route → the pilot area (recenter)', () => {
    expect(fitTarget([], 'winter_aware')).toEqual([
      [PILOT_BBOX.west, PILOT_BBOX.south],
      [PILOT_BBOX.east, PILOT_BBOX.north],
    ]);
  });
  it('padding is shrunk so MapLibre can always fit (it silently skips a fit that cannot)', () => {
    // 85 % sheet over a 779 px map: the old layout's case.
    const p = clampPadding({ top: 56, bottom: 662 + 16, left: 24, right: 24 }, 390, 779);
    expect(779 - p.top - p.bottom).toBeGreaterThanOrEqual(80);
    expect(clampPadding({ top: 56, bottom: 406, left: 24, right: 24 }, 390, 779)).toEqual({ top: 56, bottom: 406, left: 24, right: 24 });
  });
});

describe('recent destinations (opt-in, local only)', () => {
  beforeEach(() => {
    localStorage.clear();
    useRecentDestinations.setState({ enabled: false, items: [] });
  });
  it('stores nothing until the user opts in', () => {
    useRecentDestinations.getState().add({ lon: -73.57712345, lat: 45.50481234 });
    expect(useRecentDestinations.getState().items).toEqual([]);
    expect(localStorage.getItem(RECENT_KEY)).toBeNull();
  });
  it('after opt-in: rounded to 4 decimals, newest first, deduplicated, capped', () => {
    const st = useRecentDestinations.getState();
    st.setEnabled(true);
    for (let i = 0; i < RECENT_MAX + 2; i++) useRecentDestinations.getState().add({ lon: -73.57 - i / 1000, lat: 45.5 }, 1000 + i);
    useRecentDestinations.getState().add({ lon: -73.57712345, lat: 45.50481234 }, 5000);
    useRecentDestinations.getState().add({ lon: -73.57711, lat: 45.50479 }, 6000); // same point once rounded
    const items = useRecentDestinations.getState().items;
    expect(items).toHaveLength(RECENT_MAX);
    expect(items[0]).toEqual({ lon: -73.5771, lat: 45.5048, at: 6000 });
    expect(JSON.parse(localStorage.getItem(RECENT_KEY)!)).toEqual(items);
  });
  it('entries older than 30 days are dropped', () => {
    useRecentDestinations.getState().setEnabled(true);
    useRecentDestinations.getState().add({ lon: -73.57, lat: 45.5 }, 0);
    useRecentDestinations.getState().add({ lon: -73.58, lat: 45.5 }, RECENT_TTL_MS + 1);
    expect(useRecentDestinations.getState().items.map((x) => x.lon)).toEqual([-73.58]);
  });
  it('opting out deletes everything; clear empties the list', () => {
    useRecentDestinations.getState().setEnabled(true);
    useRecentDestinations.getState().add({ lon: -73.57, lat: 45.5 });
    useRecentDestinations.getState().clear();
    expect(localStorage.getItem(RECENT_KEY)).toBeNull();
    useRecentDestinations.getState().add({ lon: -73.57, lat: 45.5 });
    useRecentDestinations.getState().setEnabled(false);
    expect(localStorage.getItem(RECENT_KEY)).toBeNull();
    expect(localStorage.getItem(OPT_IN_KEY)).toBeNull();
    expect(useRecentDestinations.getState().items).toEqual([]);
  });
});

describe('compact route cards', () => {
  it('oldest freshness; unknown (null) wins over any date', () => {
    const r = routes()[0]!;
    expect(oldestFreshness({ ...r, data_freshness: { a: '2026-11-10T00:00:00Z', b: '2026-11-01T00:00:00Z' } })).toBe('2026-11-01T00:00:00Z');
    expect(oldestFreshness({ ...r, data_freshness: { a: '2026-11-10T00:00:00Z', b: null } })).toBeNull();
  });
  it('time, distance, unknown share as text + icon; selecting a card reports its variant', async () => {
    const onSelect = vi.fn();
    render(<RouteCards routes={routes()} selected="winter_aware" onSelect={onSelect} />);
    const sel = screen.getByTestId('route-card-winter_aware');
    expect(sel).toHaveAttribute('aria-pressed', 'true');
    expect(within(sel).getByTestId('card-unknown')).toHaveTextContent(/No condition data for .* of the route/);
    expect(within(sel).getByText('Oldest data', { exact: false })).toBeInTheDocument();
    await userEvent.click(screen.getByTestId('route-card-shortest'));
    expect(onSelect).toHaveBeenCalledWith('shortest');
  });
});
