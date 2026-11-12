import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AttributionControl,
  Map as MlMap,
  Marker,
  NavigationControl,
  setWorkerUrl,
  type GeoJSONSource,
  type LngLatBoundsLike,
} from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
// MapLibre v6 loads its worker from a sibling URL that bundlers rewrite; point it at the emitted asset.
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import type { Geometry, LineString } from 'geojson';
import type { HazardFeature, LonLat, Route, SegmentFeature } from '@/api/types';
import { MAP_STYLE_URL, PILOT_BBOX } from '@/lib/env';
import type { Bbox } from '@/lib/geo';
import type { PointKey } from '@/stores/planner';
import type { RouteVariant } from '@/stores/planner-types';
import { HAZARD_STYLE, RISK_COLORS, ROUTE_STYLE } from './mapStyle';
import { clampPadding, fitTarget, type Padding } from './mapFit';

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
  fitPadding?: Padding;
  /** Bump to re-fit (recenter button, sheet snap, panel toggle). New routes / selection re-fit by themselves. */
  fitRequest?: number;
};

const DEFAULT_PADDING: Padding = { top: 60, right: 60, bottom: 60, left: 60 };

setWorkerUrl(maplibreWorkerUrl);

const EMPTY = { type: 'FeatureCollection' as const, features: [] };
const { west: W, south: S, east: E, north: N } = PILOT_BBOX;

/** World polygon with the pilot bbox punched out → hatched "outside coverage" mask. */
const OUTSIDE_MASK = {
  type: 'Feature' as const,
  properties: {},
  geometry: {
    type: 'Polygon' as const,
    coordinates: [
      [
        [-180, -85],
        [180, -85],
        [180, 85],
        [-180, 85],
        [-180, -85],
      ],
      [
        [W, S],
        [W, N],
        [E, N],
        [E, S],
        [W, S],
      ],
    ],
  },
};

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

function markerEl(label: string, text: string, color: string) {
  const el = document.createElement('div');
  el.setAttribute('role', 'img');
  el.setAttribute('aria-label', label);
  el.style.cssText = `width:30px;height:30px;border-radius:9999px;background:${color};color:#fff;display:flex;align-items:center;justify-content:center;font:600 14px/1 Inter Variable,system-ui,sans-serif;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4)`;
  el.textContent = text;
  return el;
}

export default function PlannerMap(props: PlannerMapProps) {
  const { t } = useTranslation(['plan', 'common']);
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const markers = useRef<{ origin?: Marker; destination?: Marker }>({});
  const [ready, setReady] = useState(false);
  const { origin, destination } = props;
  const cb = useRef(props);
  cb.current = props;

  // Init once.
  useEffect(() => {
    if (!container.current) return;
    let map: MlMap;
    try {
      const mobile = window.matchMedia?.('(max-width: 1023px)').matches;
      map = new MlMap({
        container: container.current,
        style: MAP_STYLE_URL,
        bounds: [W, S, E, N] as LngLatBoundsLike,
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
      map.getCanvas().setAttribute('aria-label', t('map.label'));
    } catch {
      cb.current.onStatus?.('no-webgl');
      return;
    }
    mapRef.current = map;

    const emitViewport = () => {
      const b = map.getBounds();
      cb.current.onViewport([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]);
    };

    map.on('error', (e) => {
      // Style/tile failures must not break the planner; panel remains fully usable.
      if (!map.isStyleLoaded()) cb.current.onStatus?.('style-error');
      console.warn('map error', e.error?.message ?? 'unknown');
    });

    map.on('load', () => {
      map.addImage('hatch', hatchImage());
      map.addSource('outside', { type: 'geojson', data: OUTSIDE_MASK });
      map.addLayer({ id: 'outside-fill', type: 'fill', source: 'outside', paint: { 'fill-pattern': 'hatch' } });
      map.addLayer({ id: 'outside-line', type: 'line', source: 'outside', paint: { 'line-color': '#101B2C', 'line-width': 1.5 } });

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

      map.addSource('routes', { type: 'geojson', data: EMPTY });
      for (const v of ['shortest', 'winter_aware'] as const) {
        const st = ROUTE_STYLE[v];
        map.addLayer({
          id: `route-casing-${v}`,
          type: 'line',
          source: 'routes',
          filter: ['==', ['get', 'variant'], v],
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': '#ffffff', 'line-width': ['case', ['get', 'selected'], 10, 6] },
        });
        map.addLayer({
          id: `route-${v}`,
          type: 'line',
          source: 'routes',
          filter: ['==', ['get', 'variant'], v],
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: {
            'line-color': st.color,
            'line-width': ['case', ['get', 'selected'], 6, 3],
            'line-opacity': ['case', ['get', 'selected'], 1, 0.6],
            ...(st.dash ? { 'line-dasharray': st.dash } : {}),
          },
        });
      }

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
    map.on('click', (e) => cb.current.onPick({ lon: e.lngLat.lng, lat: e.lngLat.lat }));

    return () => {
      map.remove();
      mapRef.current = null;
      setReady(false);
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

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    (map.getSource('routes') as GeoJSONSource | undefined)?.setData({
      type: 'FeatureCollection',
      features: props.routes.map((r) => ({
        type: 'Feature',
        geometry: r.geometry as LineString,
        properties: { variant: r.variant, selected: r.variant === props.selected },
      })),
    });
    // Draw the selected route on top.
    const top = props.selected;
    if (map.getLayer(`route-${top}`)) {
      map.moveLayer(`route-casing-${top}`);
      map.moveLayer(`route-${top}`);
    }
  }, [ready, props.routes, props.selected]);

  // Fit to the selected route: on a new comparison, a new selection, or an explicit request.
  const fitCount = useRef(0);
  const pendingFit = useRef<(() => void) | null>(null);
  useEffect(() => {
    const map = mapRef.current;
    const el = container.current;
    if (!ready || !map || !el) return;
    // Also runs once when the map is ready: the initial pilot-area view must respect the sheet too.
    map.resize();
    const pad = clampPadding({ ...DEFAULT_PADDING, ...cb.current.fitPadding }, el.clientWidth, el.clientHeight);
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const mark = () => {
      el.dataset.mapFit = String(++fitCount.current);
      el.dataset.mapZoom = map.getZoom().toFixed(2);
    };
    const target = fitTarget(props.routes, props.selected);
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
    map.fitBounds(target, { padding: pad, maxZoom: 17, duration: reduce ? 0 : 600 });
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
  }, [ready, props.routes, props.selected, props.fitRequest]);

  // Keep the canvas in step with its box (sheet drag, panel collapse); MapLibre only tracks window resizes reliably.
  useEffect(() => {
    const el = container.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => mapRef.current?.resize());
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Origin / destination markers.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const pts = { origin, destination };
    for (const key of ['origin', 'destination'] as const) {
      const p = pts[key];
      const existing = markers.current[key];
      if (!p) {
        existing?.remove();
        markers.current[key] = undefined;
        continue;
      }
      if (existing) existing.setLngLat([p.lon, p.lat]);
      else {
        const label = key === 'origin' ? t('points.origin') : t('points.destination');
        markers.current[key] = new Marker({
          element: markerEl(label, key === 'origin' ? 'A' : 'B', key === 'origin' ? '#087F8C' : '#101B2C'),
        })
          .setLngLat([p.lon, p.lat])
          .addTo(map);
      }
    }
  }, [origin, destination, t]);

  // Inline style on purpose: maplibre-gl.css sets `.maplibregl-map { position: relative }` as
  // unlayered CSS, which beats Tailwind 4's layered `absolute inset-0` and collapsed the map to 0 px.
  return <div ref={container} style={{ position: 'absolute', inset: 0 }} data-testid="planner-map" />;
}
