import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { mockCompare } from '@/mocks/routes';
import { coverage as pilotCoverage } from '@/mocks/fixtures';
import { PTS } from '@/test/pilotPoints';
import { PILOT_BBOX } from '@/lib/env';
import { RouteCards } from '@/features/plan/RouteCards';
import { CompareCard } from '@/features/plan/CompareCard';
import { Legend } from '@/features/plan/Legend';
import { boundsSpanM, CONTROL_PADDING, fitDuration, fitPaddingFor, fitTarget } from '@/features/plan/mapFit';
import { boxPolygon, inServedArea, maskCollection, outlineCollection, parseArea, servedPolygons } from './coverageArea';
import { isSearchedPlace, readEndpointMeta } from './endpoints';
import { markerElement, markerSvg } from './markers';
import { combineStatus, overlayStatus, STALE_OVERLAY_MS, type QueryLike } from './dataStatus';
import { useRouteHighlight } from './routeHighlight';
import { ConditionCoverage } from './ConditionCoverage';
import { MapStatusChip } from './MapStatusChip';
import { ISLAND_AREA, islandCoverage, islandLongCompare, LONG_A, LONG_B } from './fixtures/islandLongRoute';

const compareData = () => {
  const r = mockCompare({ origin: PTS.A, destination: PTS.B, locale: 'en' }, new Date());
  if (r.status !== 200) throw new Error('expected 200');
  return r.body;
};

afterEach(() => useRouteHighlight.setState({ hovered: null, from: null }));

describe('coverage area (Polygon now, MultiPolygon-ready)', () => {
  const box = { west: -1, south: -1, east: 1, north: 1 };
  it('Polygon → one served polygon, ring closed', () => {
    const p = parseArea({ type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1]]] });
    expect(p).toHaveLength(1);
    expect(p[0]!.outer.at(-1)).toEqual([0, 0]);
  });
  it('MultiPolygon → every part, holes kept; mask punches each outer ring and refills holes', () => {
    const polys = parseArea(ISLAND_AREA);
    expect(polys).toHaveLength(2);
    expect(polys[0]!.holes).toHaveLength(1);
    const mask = maskCollection(polys);
    expect(mask.features[0]!.geometry.coordinates).toHaveLength(1 + 2); // world + 2 outer rings
    expect(mask.features.filter((f) => f.properties?.part === 'hole')).toHaveLength(1);
    expect(outlineCollection(polys).features[0]!.geometry.coordinates).toHaveLength(3);
  });
  it('broken or unknown geometry falls back to the bbox, never to "everything served"', () => {
    expect(parseArea({ type: 'Polygon', coordinates: [[[0, 0], [1, 0]]] })).toEqual([]);
    expect(parseArea({ type: 'GeometryCollection', coordinates: [] })).toEqual([]);
    expect(servedPolygons(null, box)).toEqual([boxPolygon(box)]);
  });
  it('point-in-area honours holes and separate parts', () => {
    const polys = parseArea(ISLAND_AREA);
    expect(inServedArea(LONG_A.lon, LONG_A.lat, polys)).toBe(true);
    expect(inServedArea(LONG_B.lon, LONG_B.lat, polys)).toBe(true);
    expect(inServedArea(-73.63, 45.475, polys)).toBe(false); // in the hole
    expect(inServedArea(-73.9, 45.505, polys)).toBe(true); // second part
    expect(inServedArea(-74.5, 45.5, polys)).toBe(false);
  });
});

describe('endpoint metadata (optional store fields)', () => {
  it('reads xMeta, or xLabel/xSource, or nothing', () => {
    expect(readEndpointMeta({ originMeta: { label: 'Gare Centrale', source: 'search' } }, 'origin')).toEqual({ label: 'Gare Centrale', source: 'search' });
    expect(readEndpointMeta({ destinationLabel: 'McGill', destinationSource: 'search' }, 'destination')).toEqual({ label: 'McGill', source: 'search' });
    expect(readEndpointMeta({ origin: { lon: 1, lat: 2 } }, 'origin')).toBeUndefined();
    expect(readEndpointMeta(null, 'origin')).toBeUndefined();
    expect(isSearchedPlace({ source: 'search' })).toBe(true);
    expect(isSearchedPlace({ source: 'map' })).toBe(false);
  });
});

describe('markers: shape + letter + text, not colour alone', () => {
  it('start is a circle, destination a square, searched place a dashed pin', () => {
    expect(markerSvg('origin', false)).toContain('<circle');
    expect(markerSvg('destination', false)).toContain('<rect');
    expect(markerSvg('destination', true)).toContain('stroke-dasharray');
  });
  it('searched place: bottom-anchored pin with a visible name and an "approximate" accessible name', () => {
    const { el, anchor } = markerElement({ key: 'destination', ariaLabel: 'Destination (B): searched place “McGill”. Approximate…', searched: true, placeLabel: 'McGill' });
    expect(anchor).toBe('bottom');
    expect(el.dataset.markerKind).toBe('searched-place');
    expect(el.getAttribute('role')).toBe('img');
    expect(el.textContent).toContain('McGill');
    expect(el.style.pointerEvents).toBe('none');
    const plain = markerElement({ key: 'origin', ariaLabel: 'Start (A)', searched: false });
    expect(plain.anchor).toBe('center');
    expect(plain.el.dataset.markerKind).toBe('point');
  });
});

describe('overlay data status (from query state; swappable)', () => {
  const now = 1_000_000_000;
  const q = (o: Partial<QueryLike>): QueryLike => ({ status: 'success', fetchStatus: 'idle', dataUpdatedAt: now, hasData: true, ...o });
  it('maps query state to loading / updating / fresh / cached / stale / unavailable / error', () => {
    expect(overlayStatus(undefined).status).toBe('off');
    expect(overlayStatus(q({ status: 'pending', fetchStatus: 'fetching', hasData: false, dataUpdatedAt: 0 }), now).status).toBe('loading');
    expect(overlayStatus(q({ fetchStatus: 'fetching' }), now).status).toBe('updating');
    expect(overlayStatus(q({ status: 'pending', isPlaceholderData: true, hasData: true }), now).status).toBe('updating');
    expect(overlayStatus(q({}), now + 10_000).status).toBe('fresh');
    expect(overlayStatus(q({}), now + 120_000).status).toBe('cached');
    expect(overlayStatus(q({}), now + STALE_OVERLAY_MS + 1).status).toBe('stale');
    expect(overlayStatus(q({ status: 'error', error: { status: 503, code: 'UPSTREAM_UNAVAILABLE' } }), now).status).toBe('unavailable');
    expect(overlayStatus(q({ status: 'error', error: { status: 0, code: 'NETWORK' } }), now).status).toBe('unavailable');
    expect(overlayStatus(q({ status: 'error', error: { status: 500, code: 'INTERNAL' }, hasData: false }), now)).toMatchObject({ status: 'error', hasData: false });
  });
  it('combined: the worst state wins, the oldest timestamp is shown', () => {
    const c = combineStatus([
      { status: 'fresh', updatedAt: 5, hasData: true },
      { status: 'stale', updatedAt: 2, hasData: true },
      { status: 'off', updatedAt: null, hasData: false },
    ]);
    expect(c).toEqual({ status: 'stale', updatedAt: 2, hasData: true });
    expect(combineStatus([{ status: 'off', updatedAt: null, hasData: false }]).status).toBe('off');
  });
});

describe('map status chip', () => {
  it('error keeps older data visible, says so, and offers a 44 px retry', () => {
    const retry = vi.fn();
    render(<MapStatusChip state={{ kind: 'data', status: 'unavailable', updatedAt: Date.now(), hasData: true }} onRetry={retry} />);
    const chip = screen.getByTestId('map-status');
    expect(chip).toHaveAttribute('data-status', 'unavailable');
    expect(chip).toHaveTextContent('Map layers unavailable right now — showing the last view that loaded');
    fireEvent.click(screen.getByTestId('map-status-retry'));
    expect(retry).toHaveBeenCalled();
    expect(screen.getByTestId('map-status-retry').className).toContain('min-h-11');
  });
  it('stale shows the load time; zoomed-out view asks to zoom in', () => {
    const { rerender } = render(<MapStatusChip state={{ kind: 'data', status: 'stale', updatedAt: Date.parse('2026-11-16T15:00:00Z'), hasData: true }} />);
    expect(screen.getByTestId('map-status')).toHaveTextContent(/may be out of date \(loaded 10:00/);
    rerender(<MapStatusChip state={{ kind: 'view', reason: 'too-large' }} />);
    expect(screen.getByTestId('map-status')).toHaveTextContent('Zoom in to load sidewalk and closure layers');
  });
});

describe('winter-condition data coverage on cards', () => {
  it('bar + text; unknown is named; ≥ 50 % unknown says "mostly unknown"; no safety wording', () => {
    const { rerender } = render(<ConditionCoverage unknownShare={0.43} riskLayer="heuristic" />);
    const el = screen.getByTestId('condition-coverage');
    expect(within(el).getByRole('img')).toHaveAccessibleName('Condition data coverage: 57% known, 43% unknown');
    expect(el).toHaveTextContent('Source: labelled heuristic (estimate)');
    expect(screen.queryByTestId('mostly-unknown')).toBeNull();
    rerender(<ConditionCoverage unknownShare={0.7} riskLayer="model" />);
    expect(screen.getByTestId('mostly-unknown')).toBeInTheDocument();
    expect(screen.getByTestId('condition-coverage')).not.toHaveTextContent(/safe|cleared|ice-free|accessible/i);
  });
  it('no risk layer active → the bar shows the whole route as unknown, and says why', () => {
    render(<ConditionCoverage unknownShare={0.25} riskLayer="none" compact />);
    const el = screen.getByTestId('condition-coverage');
    expect(el).toHaveAttribute('data-unknown-share', '1.000');
    expect(el).toHaveTextContent('No risk layer active: conditions are not assessed');
  });
  it('non-finite share is treated as fully unknown, never as known', () => {
    render(<ConditionCoverage unknownShare={Number.NaN} />);
    expect(screen.getByTestId('condition-coverage')).toHaveAttribute('data-unknown-share', '1.000');
  });
});

describe('hover sync: cards ↔ map highlight store', () => {
  it('pointing at a card highlights its route; a highlight from the map marks the card and the details', () => {
    const data = compareData();
    render(<CompareCard data={data} selected="winter_aware" onSelect={vi.fn()} />);
    fireEvent.pointerEnter(screen.getByTestId('route-card-shortest'));
    expect(useRouteHighlight.getState()).toMatchObject({ hovered: 'shortest', from: 'list' });
    fireEvent.pointerLeave(screen.getByTestId('route-card-shortest'));
    expect(useRouteHighlight.getState().hovered).toBeNull();
    act(() => useRouteHighlight.getState().setHovered('shortest', 'map'));
    expect(screen.getByTestId('route-card-shortest')).toHaveAttribute('data-hovered', 'true');
    expect(screen.getByTestId('route-shortest')).toHaveAttribute('data-hovered', 'true');
    expect(screen.getByTestId('route-card-winter_aware')).not.toHaveAttribute('data-hovered');
  });
  it('keyboard focus highlights too', () => {
    render(<RouteCards routes={compareData().routes} selected="winter_aware" onSelect={vi.fn()} />);
    fireEvent.focus(screen.getByTestId('route-card-shortest'));
    expect(useRouteHighlight.getState().hovered).toBe('shortest');
    fireEvent.blur(screen.getByTestId('route-card-shortest'));
    expect(useRouteHighlight.getState().hovered).toBeNull();
  });
});

describe('fit (sheet / panel / controls, long routes)', () => {
  it('per side: the larger of caller padding and control room, then clamped', () => {
    expect(fitPaddingFor(undefined, 1000, 800)).toEqual(CONTROL_PADDING);
    const mobile = fitPaddingFor({ top: 56, right: 24, left: 24, bottom: 438 }, 390, 780);
    expect(mobile).toEqual({ top: 60, right: 64, bottom: 438, left: 32 });
    const tiny = fitPaddingFor({ bottom: 700 }, 390, 700);
    expect(700 - tiny.top - tiny.bottom).toBeGreaterThanOrEqual(80);
  });
  it('fit target includes markers that sit off the snapped line', () => {
    const rs = compareData().routes;
    const off = { lon: PILOT_BBOX.west + 0.0001, lat: PILOT_BBOX.south + 0.0001 };
    const [[w, s]] = fitTarget(rs, 'winter_aware', [off]);
    expect(w).toBe(off.lon);
    expect(s).toBe(off.lat);
  });
  it('long cross-region fixture: whole route in the target, slower fly', () => {
    const rs = islandLongCompare().routes;
    const t = fitTarget(rs, 'winter_aware', [LONG_A, LONG_B]);
    expect(t[0][0]).toBeLessThanOrEqual(LONG_B.lon);
    expect(t[1][0]).toBeGreaterThanOrEqual(LONG_A.lon);
    expect(boundsSpanM(t)).toBeGreaterThan(15_000);
    expect(fitDuration(boundsSpanM(t), false)).toBe(900);
    expect(fitDuration(boundsSpanM(t), true)).toBe(0);
  });
});

describe('legend', () => {
  const renderWith = (coverage: unknown) => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    qc.setQueryData(['coverage'], coverage);
    return render(
      <QueryClientProvider client={qc}>
        <Legend />
      </QueryClientProvider>,
    );
  };
  it('names shapes, the boundary and the outside area, and lists coverage gaps', () => {
    renderWith(pilotCoverage());
    const l = screen.getByTestId('legend');
    expect(l).toHaveTextContent('Start: circle A');
    expect(l).toHaveTextContent('Destination: square B');
    expect(l).toHaveTextContent('Searched place: dashed pin');
    expect(l).toHaveTextContent('Boundary of the routable area');
    expect(l).toHaveTextContent('Outside (hatched): no routes, no layers');
    expect(l).toHaveTextContent('Unknown is not low risk');
    expect(screen.getByTestId('legend-coverage-info')).toHaveTextContent('1 known gap in coverage');
  });
  it('fixture coverage name is shown as given (labelled TEST FIXTURE)', () => {
    renderWith(islandCoverage());
    expect(screen.getByTestId('legend-coverage-info')).toHaveTextContent('TEST FIXTURE');
  });
});
