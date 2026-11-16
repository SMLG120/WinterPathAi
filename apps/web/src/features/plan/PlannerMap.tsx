import { memo, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { useIsMutating } from '@tanstack/react-query';
import {
  AttributionControl,
  Map as MlMap,
  Marker,
  NavigationControl,
  setWorkerUrl,
  type GeoJSONSource,
  type IControl,
  type LngLatBoundsLike,
  type MapLayerMouseEvent,
} from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import '@/features/map/map.css';
// MapLibre v6 loads its worker from a sibling URL that bundlers rewrite; point it at the emitted asset.
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import type { Geometry, LineString } from 'geojson';
import type { HazardFeature, LonLat, Route, SegmentFeature } from '@/api/types';
import { useCoverage } from '@/api/queries';
import { getCoverage, subscribeCoverage } from '@/lib/coverage';
import { MAP_STYLE_URL, USE_MOCKS } from '@/lib/env';
import { clipToPilot, isQueryableBbox, type Bbox } from '@/lib/geo';
import { usePlannerStore, type PointKey } from '@/stores/planner';
import type { RouteVariant } from '@/stores/planner-types';
import { maskCollection, outlineCollection, servedPolygons } from '@/features/map/coverageArea';
import { isSearchedPlace, metaKey, readEndpointMeta, type EndpointMeta, type EndpointMetas } from '@/features/map/endpoints';
import { markerElement } from '@/features/map/markers';
import { useRouteHighlight } from '@/features/map/routeHighlight';
import { useOverlayQueryStatus } from '@/features/map/dataStatus';
import { MapStatusChip, type ChipState } from '@/features/map/MapStatusChip';
import { COVERAGE_STYLE, HAZARD_STYLE, RISK_COLORS, ROUTE_STYLE, ROUTE_WIDTH } from './mapStyle';
import { boundsSpanM, fitDuration, fitPaddingFor, fitTarget, type Padding } from './mapFit';

export type PlannerMapProps = {
  origin: LonLat | null;
  destination: LonLat | null;
  routes: Route[];
  selected: RouteVariant;
  segments: SegmentFeature[];
  hazards: HazardFeature[];
  showSegments: boolean;
  showHazards: boolean;
  picking: PointKey | null;
  onPick: (p: LonLat) => void;
  onViewport: (b: Bbox) => void;
  onStatus?: (s: 'ok' | 'no-webgl' | 'style-error') => void;
  /** Map area hidden by UI on top of it (mobile bottom sheet), in px; the fit keeps the route out of it. */
  fitPadding?: Partial<Padding>;
  /** Bump to re-fit (recenter button, sheet snap, panel toggle). New routes / selection re-fit by themselves. */
  fitRequest?: number;
  /** Clicking a route line selects it. Default: the planner store's `setSelected`. */
  onSelectRoute?: (v: RouteVariant) => void;
  /** Label / source of each point (e.g. a searched place). Default: read from the planner store if it has such fields. */
  endpoints?: EndpointMetas;
};

const VARIANTS: RouteVariant[] = ['shortest', 'winter_aware'];

setWorkerUrl(maplibreWorkerUrl);

const EMPTY = { type: 'FeatureCollection' as const, features: [] };
let initCount = 0;

function hatchImage(size = 12) {
  const data = new Uint8Array(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const on = (x + y) % size < 2;
      const i = (y * size + x) * 4;
      data[i] = 100;
      data[i + 1] = 116;
      data[i + 2] = 139;
      data[i + 3] = on ? 150 : 0;
    }
  }
  return { width: size, height: size, data };
}

/** A MapLibre control slot we render React into (so it stacks with the attribution in its corner). */
class PortalControl implements IControl {
  readonly el = document.createElement('div');
  onAdd() {
    this.el.className = 'maplibregl-ctrl wp-map-status';
    return this.el;
  }
  onRemove() {
    this.el.remove();
  }
}

const isVariant = (v: unknown): v is RouteVariant => v === 'shortest' || v === 'winter_aware';
const fsBool = (k: string) => ['boolean', ['feature-state', k], false];

function viewReason(b: Bbox): 'ok' | 'outside' | 'too-large' {
  const c = clipToPilot(b);
  if (!c) return 'outside';
  return isQueryableBbox(c) ? 'ok' : 'too-large';
}

function PlannerMap(props: PlannerMapProps) {
  const { t } = useTranslation(['plan', 'map', 'common']);
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const markers = useRef<Partial<Record<PointKey, { marker: Marker; key: string }>>>({});
  const [ready, setReady] = useState(false);
  const [chipHost, setChipHost] = useState<HTMLElement | null>(null);
  const [reason, setReason] = useState<'ok' | 'outside' | 'too-large'>('ok');
  const [mobile] = useState(() => !!window.matchMedia?.('(max-width: 1023px)').matches);
  const { origin, destination } = props;
  const cb = useRef(props);
  cb.current = props;

  // Init once. Everything after this updates sources, feature state or markers; the map is never rebuilt.
  useEffect(() => {
    if (!container.current) return;
    let map: MlMap;
    const coarse = !!window.matchMedia?.('(pointer: coarse)').matches;
    try {
      map = new MlMap({
        container: container.current,
        style: MAP_STYLE_URL,
        bounds: ((b) => [b.west, b.south, b.east, b.north])(getCoverage().box) as LngLatBoundsLike,
        fitBoundsOptions: { padding: 20 },
        maxZoom: 19,
        attributionControl: false,
        dragRotate: false,
        pitchWithRotate: false,
      });
      map.addControl(
        new AttributionControl({
          compact: false,
          customAttribution: [
            '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap contributors</a> (ODbL)',
            'Ville de Montréal (CC BY 4.0)',
            'ECCC',
          ],
        }),
        mobile ? 'top-left' : 'bottom-right',
      );
      map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
      // Status chip: under the attribution on mobile (the sheet covers the bottom), bottom-left on desktop.
      const chip = new PortalControl();
      map.addControl(chip, mobile ? 'top-left' : 'bottom-left');
      setChipHost(chip.el);
      map.getCanvas().setAttribute('aria-label', t('map.label'));
    } catch {
      cb.current.onStatus?.('no-webgl');
      return;
    }
    mapRef.current = map;
    container.current.dataset.mapInits = String(++initCount);
    // e2e hook (mock builds only; compiled out of real builds): lets tests project lon/lat to pixels.
    if (USE_MOCKS) (window as unknown as { __wpPlannerMap?: MlMap }).__wpPlannerMap = map;

    const emitViewport = () => {
      const b = map.getBounds();
      const box: Bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
      setReason(viewReason(box));
      cb.current.onViewport(box);
    };

    map.on('error', (e) => {
      // Style/tile failures must not break the planner; panel remains fully usable.
      if (!map.isStyleLoaded()) cb.current.onStatus?.('style-error');
      console.warn('map error', e.error?.message ?? 'unknown');
    });

    map.on('load', () => {
      map.addImage('hatch', hatchImage());
      // Outside the routable area: dimmed + hatched, with a cased outline on the boundary.
      map.addSource('outside', { type: 'geojson', data: EMPTY });
      map.addLayer({ id: 'outside-dim', type: 'fill', source: 'outside', paint: { 'fill-color': COVERAGE_STYLE.dim } });
      map.addLayer({ id: 'outside-fill', type: 'fill', source: 'outside', paint: { 'fill-pattern': 'hatch' } });
      map.addSource('coverage-outline', { type: 'geojson', data: EMPTY });
      map.addLayer({
        id: 'coverage-outline-casing',
        type: 'line',
        source: 'coverage-outline',
        layout: { 'line-join': 'round' },
        paint: { 'line-color': COVERAGE_STYLE.casing, 'line-width': COVERAGE_STYLE.width + 3, 'line-opacity': 0.9 },
      });
      map.addLayer({
        id: 'coverage-outline',
        type: 'line',
        source: 'coverage-outline',
        layout: { 'line-join': 'round' },
        paint: { 'line-color': COVERAGE_STYLE.line, 'line-width': COVERAGE_STYLE.width },
      });

      map.addSource('segments', { type: 'geojson', data: EMPTY });
      const riskColor = [
        'match',
        ['get', 'level'],
        'low', RISK_COLORS.low,
        'moderate', RISK_COLORS.moderate,
        'elevated', RISK_COLORS.elevated,
        'high', RISK_COLORS.high,
        RISK_COLORS.unknown,
      ] as unknown as string;
      map.addLayer({
        id: 'segments-known',
        type: 'line',
        source: 'segments',
        filter: ['!=', ['get', 'level'], 'unknown'],
        paint: { 'line-color': riskColor, 'line-width': 3, 'line-opacity': 0.85 },
      });
      map.addLayer({
        id: 'segments-unknown',
        type: 'line',
        source: 'segments',
        filter: ['==', ['get', 'level'], 'unknown'],
        paint: { 'line-color': RISK_COLORS.unknown, 'line-width': 2.5, 'line-dasharray': [1, 1.5], 'line-opacity': 0.9 },
      });

      // Routes: one source, ids = variant; selection and hover are feature state (no setData on hover/select).
      map.addSource('routes', { type: 'geojson', data: EMPTY, promoteId: 'variant' });
      const width = (sel: number, hov: number, other: number) =>
        ['case', fsBool('selected'), sel, fsBool('hover'), hov, other] as unknown as number;
      for (const v of VARIANTS) {
        const st = ROUTE_STYLE[v];
        map.addLayer({
          id: `route-casing-${v}`,
          type: 'line',
          source: 'routes',
          filter: ['==', ['get', 'variant'], v],
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': '#ffffff', 'line-width': width(ROUTE_WIDTH.selected + 4, ROUTE_WIDTH.hovered + 4, ROUTE_WIDTH.other + 3) },
        });
        map.addLayer({
          id: `route-${v}`,
          type: 'line',
          source: 'routes',
          filter: ['==', ['get', 'variant'], v],
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: {
            'line-color': st.color,
            'line-width': width(ROUTE_WIDTH.selected, ROUTE_WIDTH.hovered, ROUTE_WIDTH.other),
            'line-opacity': ['case', fsBool('selected'), 1, fsBool('hover'), 0.95, 0.6] as unknown as number,
            ...(st.dash ? { 'line-dasharray': st.dash } : {}),
          },
        });
      }
      // Invisible wide line for pointing at / tapping a route (a 3 px line is too thin to hit).
      map.addLayer({
        id: 'route-hit',
        type: 'line',
        source: 'routes',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#000000', 'line-opacity': 0, 'line-width': coarse ? 32 : 18 },
      });

      map.addSource('hazards', { type: 'geojson', data: EMPTY });
      const hazColor = [
        'match',
        ['get', 'kind'],
        ...Object.entries(HAZARD_STYLE).flatMap(([k, v]) => [k, v.color]),
        '#64748B',
      ] as unknown as string;
      map.addLayer({
        id: 'hazards-fill',
        type: 'fill',
        source: 'hazards',
        filter: ['==', ['geometry-type'], 'Polygon'],
        paint: { 'fill-color': hazColor, 'fill-opacity': 0.25 },
      });
      map.addLayer({
        id: 'hazards-line',
        type: 'line',
        source: 'hazards',
        filter: ['==', ['geometry-type'], 'LineString'],
        paint: { 'line-color': hazColor, 'line-width': 6, 'line-dasharray': [1, 0.6] },
      });
      map.addLayer({
        id: 'hazards-point',
        type: 'circle',
        source: 'hazards',
        filter: ['==', ['geometry-type'], 'Point'],
        paint: {
          'circle-radius': 8,
          'circle-color': hazColor,
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 2,
        },
      });

      setReady(true);
      container.current?.setAttribute('data-map-ready', 'true');
      cb.current.onStatus?.('ok');
      emitViewport();
    });

    map.on('moveend', emitViewport);

    // Pointing at a route line highlights it (and its card); leaving clears it.
    const hl = useRouteHighlight.getState();
    map.on('mousemove', 'route-hit', (e: MapLayerMouseEvent) => {
      const v = e.features?.[0]?.properties?.variant;
      if (isVariant(v)) {
        hl.setHovered(v, 'map');
        map.getCanvas().style.cursor = cb.current.picking ? 'crosshair' : 'pointer';
      }
    });
    map.on('mouseleave', 'route-hit', () => {
      if (useRouteHighlight.getState().from === 'map') hl.setHovered(null, 'map');
      map.getCanvas().style.cursor = cb.current.picking ? 'crosshair' : '';
    });

    // Click: while picking a point, always pick. Otherwise a click on a route line selects that
    // route (it must not move the destination); anywhere else picks as before.
    map.on('click', (e) => {
      const p = cb.current;
      if (!p.picking && map.getLayer('route-hit')) {
        const vs = map
          .queryRenderedFeatures(e.point, { layers: ['route-hit'] })
          .map((f) => f.properties?.variant)
          .filter(isVariant);
        if (vs.length) {
          // Where both lines overlap, a click switches to the one not shown yet.
          const v = vs.find((x) => x !== p.selected) ?? vs[0]!;
          (p.onSelectRoute ?? usePlannerStore.getState().setSelected)(v);
          return;
        }
      }
      p.onPick({ lon: e.lngLat.lng, lat: e.lngLat.lat });
    });

    return () => {
      map.remove();
      mapRef.current = null;
      setReady(false);
      setChipHost(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- map is created exactly once
  }, []);

  // Cursor when picking.
  useEffect(() => {
    const map = mapRef.current;
    if (map) map.getCanvas().style.cursor = props.picking ? 'crosshair' : '';
  }, [props.picking]);

  // Data → sources.
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const src = map.getSource('segments') as GeoJSONSource | undefined;
    src?.setData({
      type: 'FeatureCollection',
      features: props.showSegments
        ? props.segments.map((f) => ({
            type: 'Feature',
            id: f.id,
            geometry: f.geometry as LineString,
            properties: { level: f.properties.risk.level },
          }))
        : [],
    });
  }, [ready, props.segments, props.showSegments]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    (map.getSource('hazards') as GeoJSONSource | undefined)?.setData({
      type: 'FeatureCollection',
      features: props.showHazards
        ? props.hazards.map((f) => ({
            type: 'Feature',
            id: f.id,
            geometry: f.geometry as Geometry,
            properties: { kind: f.properties.kind },
          }))
        : [],
    });
  }, [ready, props.hazards, props.showHazards]);

  // Route geometry: setData only when the routes themselves change.
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    (map.getSource('routes') as GeoJSONSource | undefined)?.setData({
      type: 'FeatureCollection',
      features: props.routes.map((r) => ({
        type: 'Feature',
        geometry: r.geometry as LineString,
        properties: { variant: r.variant },
      })),
    });
    container.current?.setAttribute('data-route-count', String(props.routes.length));
  }, [ready, props.routes]);

  // Selection + hover → feature state; selected drawn on top. Hover comes from the shared highlight store
  // (cards, details, map lines) and is applied without re-rendering this component.
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const apply = () => {
      const hovered = useRouteHighlight.getState().hovered;
      for (const v of VARIANTS) {
        if (props.routes.some((r) => r.variant === v)) map.setFeatureState({ source: 'routes', id: v }, { selected: v === props.selected, hover: v === hovered });
      }
      const el = container.current;
      if (el) {
        el.dataset.routeSelected = props.selected;
        el.dataset.routeHovered = hovered ?? '';
      }
    };
    apply();
    const top = props.selected;
    if (map.getLayer(`route-${top}`)) {
      map.moveLayer(`route-casing-${top}`, 'route-hit');
      map.moveLayer(`route-${top}`, 'route-hit');
    }
    return useRouteHighlight.subscribe((s, prev) => {
      if (s.hovered !== prev.hovered) apply();
    });
  }, [ready, props.routes, props.selected]);

  // Routable area from GET /coverage (Polygon now, MultiPolygon-ready); the bbox until it answers.
  const coverage = useSyncExternalStore(subscribeCoverage, getCoverage, getCoverage);
  const coverageQuery = useCoverage();
  const area = coverageQuery.data?.area as { type?: string; coordinates?: unknown } | undefined;
  const polys = useMemo(() => servedPolygons(area, coverage.box), [area, coverage.box]);
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    (map.getSource('outside') as GeoJSONSource | undefined)?.setData(maskCollection(polys));
    (map.getSource('coverage-outline') as GeoJSONSource | undefined)?.setData(outlineCollection(polys));
    container.current?.setAttribute('data-coverage-parts', String(polys.length));
  }, [ready, polys]);

  // Fit to the selected route (+ markers): on a new comparison, a new selection, or an explicit request.
  const fitCount = useRef(0);
  const pendingFit = useRef<(() => void) | null>(null);
  useEffect(() => {
    const map = mapRef.current;
    const el = container.current;
    if (!ready || !map || !el) return;
    // Also runs once when the map is ready: the initial area view must respect the sheet too.
    map.resize();
    // On mobile the attribution and the status chip stack in the top-left corner: keep the route below them.
    const corner = el.querySelector<HTMLElement>('.maplibregl-ctrl-top-left');
    const cornerH = corner ? Math.ceil(corner.getBoundingClientRect().bottom - el.getBoundingClientRect().top) : 0;
    const caller = cb.current.fitPadding ?? {};
    const pad = fitPaddingFor({ ...caller, top: Math.max(caller.top ?? 0, cornerH + 8) }, el.clientWidth, el.clientHeight);
    const reduce = !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const target = fitTarget(props.routes, props.selected, props.routes.length ? [cb.current.origin, cb.current.destination] : []);
    const mark = () => {
      el.dataset.mapFit = String(++fitCount.current);
      el.dataset.mapZoom = map.getZoom().toFixed(2);
      el.dataset.mapPadding = `${pad.top},${pad.right},${pad.bottom},${pad.left}`;
    };
    const cam = map.cameraForBounds(target, { padding: pad, maxZoom: 17 });
    const c = map.getCenter();
    // Already there (e.g. recenter without having panned): MapLibre fires no moveend for a no-op move.
    if (cam?.center && cam.zoom !== undefined && Math.abs(cam.zoom - map.getZoom()) < 0.01 && map.project(cam.center).dist(map.project(c)) < 1) {
      if (pendingFit.current) map.off('moveend', pendingFit.current);
      pendingFit.current = null;
      mark();
      return;
    }
    // A new fit interrupts a running one, which fires its own moveend: drop the old listener and attach
    // the new one only after starting, so an interrupted animation is never recorded as this fit.
    if (pendingFit.current) map.off('moveend', pendingFit.current);
    map.fitBounds(target, { padding: pad, maxZoom: 17, duration: fitDuration(boundsSpanM(target), reduce) });
    if (reduce || !map.isMoving()) {
      pendingFit.current = null;
      mark();
      return;
    }
    const done = () => {
      pendingFit.current = null;
      mark();
    };
    pendingFit.current = done;
    map.once('moveend', done);
  }, [ready, props.routes, props.selected, props.fitRequest, coverage]);

  // Keep the canvas in step with its box (sheet drag, panel collapse); MapLibre only tracks window resizes reliably.
  useEffect(() => {
    const el = container.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => mapRef.current?.resize());
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Optional endpoint metadata: explicit prop, else whatever the planner store carries (string keys
  // keep this from re-running on unrelated store changes).
  const storeOrigin = usePlannerStore((s) => metaKey(readEndpointMeta(s, 'origin')));
  const storeDest = usePlannerStore((s) => metaKey(readEndpointMeta(s, 'destination')));
  const originKey = metaKey(props.endpoints?.origin) || storeOrigin;
  const destKey = metaKey(props.endpoints?.destination) || storeDest;

  // Origin / destination markers: moved in place; rebuilt only when their kind or label changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const metaFor = (k: PointKey): EndpointMeta | undefined => cb.current.endpoints?.[k] ?? readEndpointMeta(usePlannerStore.getState(), k);
    const pts = { origin, destination };
    for (const key of ['origin', 'destination'] as const) {
      const p = pts[key];
      const existing = markers.current[key];
      if (!p) {
        existing?.marker.remove();
        markers.current[key] = undefined;
        continue;
      }
      const meta = metaFor(key);
      const searched = isSearchedPlace(meta);
      const point = t(`map:markers.${key}`);
      const ariaLabel = searched
        ? meta?.label
          ? t('map:markers.searched', { point, label: meta.label })
          : t('map:markers.searchedNoLabel', { point })
        : point;
      const k = `${searched}|${meta?.label ?? ''}|${ariaLabel}`;
      if (existing && existing.key === k) {
        existing.marker.setLngLat([p.lon, p.lat]);
        continue;
      }
      existing?.marker.remove();
      const { el, anchor } = markerElement({ key, ariaLabel, searched, placeLabel: meta?.label });
      markers.current[key] = { marker: new Marker({ element: el, anchor }).setLngLat([p.lon, p.lat]).addTo(map), key: k };
    }
  }, [origin, destination, originKey, destKey, t, ready]);

  // Status chip: computing > view (zoomed out / outside) > overlay data state.
  const computing = useIsMutating() > 0;
  const overlay = useOverlayQueryStatus();
  const layersOn = props.showSegments || props.showHazards;
  let chip: ChipState | null = null;
  if (computing) chip = { kind: 'computing' };
  else if (layersOn && reason !== 'ok') chip = { kind: 'view', reason };
  else if (layersOn && overlay.status !== 'off' && !(mobile && overlay.status === 'fresh'))
    chip = { kind: 'data', status: overlay.status, updatedAt: overlay.updatedAt, hasData: overlay.hasData };

  // Inline style on purpose: maplibre-gl.css sets `.maplibregl-map { position: relative }` as
  // unlayered CSS, which beats Tailwind 4's layered `absolute inset-0` and collapsed the map to 0 px.
  return (
    <div ref={container} className="wp-map" style={{ position: 'absolute', inset: 0 }} data-testid="planner-map">
      {chipHost && chip && createPortal(<MapStatusChip state={chip} onRetry={overlay.retry} />, chipHost)}
    </div>
  );
}

const samePadding = (a?: Partial<Padding>, b?: Partial<Padding>) =>
  a === b || (!!a && !!b && a.top === b.top && a.right === b.right && a.bottom === b.bottom && a.left === b.left);
const sameMeta = (a?: EndpointMetas, b?: EndpointMetas) =>
  a === b || (metaKey(a?.origin) === metaKey(b?.origin) && metaKey(a?.destination) === metaKey(b?.destination));

/** Memo comparison: the planner page builds new `fitPadding` / `endpoints` objects every render, so those compare by value. */
function samePlannerMapProps(a: PlannerMapProps, b: PlannerMapProps): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)] as (keyof PlannerMapProps)[]);
  for (const k of keys) {
    if (k === 'fitPadding') {
      if (!samePadding(a.fitPadding, b.fitPadding)) return false;
    } else if (k === 'endpoints') {
      if (!sameMeta(a.endpoints, b.endpoints)) return false;
    } else if (a[k] !== b[k]) return false;
  }
  return true;
}

/** Memoised: the planner page re-renders on every store change and sheet drag; the map only cares about its own inputs. */
export default memo(PlannerMap, samePlannerMapProps);
