import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowDownUp, Eraser, Layers, LocateFixed, PanelLeftClose, PanelLeftOpen, Route as RouteIcon, Search } from 'lucide-react';
import { useCompareRoutes, useHazards, useSegments } from '@/api/queries';
import { useBackendStore } from '@/stores/backend';
import type { HazardFeature, Route, RouteCompareRequest, SegmentFeature } from '@/api/types';
import { DemoBadge } from '@/components/evidence/DemoBadge';
import { SimulatedBanner } from '@/components/evidence/EvidenceBadge';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input, Label, Select } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { CompareCard } from '@/features/plan/CompareCard';
import { GeolocateButton } from '@/features/plan/GeolocateButton';
import { HazardList } from '@/features/plan/HazardList';
import { HazardSourceNotice } from '@/features/plan/HazardSourceNotice';
import { useHazardCoverage } from '@/features/plan/hazardCoverage';
import { Legend } from '@/features/plan/Legend';
import { PointInput } from '@/features/plan/PointInput';
import { RouteError } from '@/features/plan/RouteError';
import { RecentDestinations } from '@/features/plan/RecentDestinations';
import { nextSnap, settleSnap, snapHeight, type Snap } from '@/features/plan/sheet';
import type { Padding } from '@/features/plan/mapFit';
import { formatDistance, formatDuration } from '@/lib/format';
import { useMediaQuery } from '@/lib/useMediaQuery';
import { useRecentDestinations } from '@/stores/recentDestinations';
import { useOverlayBbox } from '@/features/plan/useOverlayBbox';
import { ErrorBoundary } from '@/components/layout/ErrorBoundary';
import { USE_MOCKS } from '@/lib/env';
import { useLang } from '@/lib/i18n-routing';
import { useDocumentTitle } from '@/lib/useDocumentTitle';
import { cn } from '@/lib/utils';
import { afterPaint } from '@/lib/afterLoad';
import { usePlannerStore } from '@/stores/planner';
import type { RouteProfile } from '@/api/types';

const PlannerMap = lazy(() => import('@/features/plan/PlannerMap'));
const PROFILES: RouteProfile[] = ['standard', 'step_free', 'reduced_mobility'];
const NO_SEGMENTS: SegmentFeature[] = [];
const NO_HAZARDS: HazardFeature[] = [];
const NO_ROUTES: Route[] = [];

export default function Plan() {
  const { t } = useTranslation(['plan', 'common']);
  const lang = useLang();
  useDocumentTitle(t('title'));
  const s = usePlannerStore();
  const compare = useCompareRoutes();
  const waking = useBackendStore((st) => st.waking > 0);
  const [lastReq, setLastReq] = useState<RouteCompareRequest | null>(null);
  const [needPoints, setNeedPoints] = useState(false);
  const [mapStatus, setMapStatus] = useState<'ok' | 'no-webgl' | 'style-error' | 'loading'>('loading');
  const desktop = useMediaQuery('(min-width: 1024px)');
  // Mobile bottom sheet: snap state, live drag height, and the planner area's height (for px snaps).
  const [snap, setSnap] = useState<Snap>('half');
  const [dragH, setDragH] = useState<number | null>(null);
  const [areaH, setAreaH] = useState(0);
  const areaRef = useRef<HTMLDivElement>(null);
  const sheetBody = useRef<HTMLDivElement>(null);
  const drag = useRef<{ y0: number; h0: number; t: number; y: number; moved: boolean } | null>(null);
  // Desktop: collapsible left panel.
  const [panelOpen, setPanelOpen] = useState(true);
  const hideBtn = useRef<HTMLButtonElement>(null);
  const showBtn = useRef<HTMLButtonElement>(null);
  // Bumped to make the map re-fit (recenter, sheet snap, panel toggle).
  const [fitRequest, setFitRequest] = useState(0);
  const refit = useCallback(() => setFitRequest((n) => n + 1), []);
  const addRecent = useRecentDestinations((r) => r.add);
  const [showSegments, setShowSegments] = useState(true);
  const [showHazards, setShowHazards] = useState(true);
  const resultsHeading = useRef<HTMLHeadingElement>(null);
  // Mount the map (≈290 KB gz MapLibre chunk) only after the panel has painted, so the
  // usable, text-first planner reaches LCP before the map parse starts.
  const [mountMap, setMountMap] = useState(false);
  useEffect(() => afterPaint(() => setMountMap(true)), []);

  const overlay = useOverlayBbox();
  const segments = useSegments(showSegments ? overlay.bbox : null);
  const hazards = useHazards(showHazards ? overlay.bbox : null);
  const hazardCoverage = useHazardCoverage();
  // Stable empty array: a fresh [] per render would re-trigger the map fit on every render.
  const routes = compare.data?.routes ?? NO_ROUTES;

  const run = useCallback(
    (req: RouteCompareRequest) => {
      setLastReq(req);
      compare.mutate(req, {
        onSuccess: () => {
          // Half, not full: the fitted route stays visible above the sheet (the old 85 % sheet hid it).
          setSnap('half');
          addRecent(req.destination);
          // Bring the results to the top of the panel/sheet (focus alone doesn't scroll a heading that is
          // already just visible at the bottom edge), then focus them for screen-reader users.
          requestAnimationFrame(() => {
            const h = resultsHeading.current;
            if (!h) return;
            // Scroll only the panel's own scroller: scrollIntoView would also scroll overflow-hidden
            // ancestors (the planner area) and shift the whole layout.
            const sc = sheetBody.current;
            if (sc) sc.scrollTop += h.getBoundingClientRect().top - sc.getBoundingClientRect().top - 8;
            h.focus({ preventScroll: true });
          });
        },
      });
    },
    [compare, addRecent],
  );

  const onCompare = () => {
    if (!s.origin || !s.destination) {
      setNeedPoints(true);
      return;
    }
    setNeedPoints(false);
    run({
      origin: s.origin,
      destination: s.destination,
      profile: s.profile,
      avoid_unverified_reports: s.avoidUnverifiedReports,
      locale: lang,
    });
  };

  // Explanations are localised server-side: re-request when the language changes.
  useEffect(() => {
    if (lastReq && lastReq.locale !== lang && compare.isSuccess) run({ ...lastReq, locale: lang });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lang]);

  useEffect(() => () => usePlannerStore.getState().setPicking(null), []);

  // Planner area height → sheet snap heights in px.
  useEffect(() => {
    const el = areaRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => setAreaH(el.clientHeight));
    ro.observe(el);
    setAreaH(el.clientHeight);
    return () => ro.disconnect();
  }, []);

  // Picking a point on the map: lower the sheet out of the way, bring it back once the point is set.
  const wasPicking = useRef(false);
  useEffect(() => {
    if (desktop) return;
    if (s.picking) setSnap('peek');
    else if (wasPicking.current) setSnap('half');
    wasPicking.current = !!s.picking;
  }, [s.picking, desktop]);

  const sheetH = dragH ?? (areaH ? snapHeight(snap, areaH) : 0);
  // The map lives under the sheet on mobile: keep the fitted route in the strip above it.
  const fitPadding: Padding | undefined = desktop
    ? undefined
    : { top: 56, right: 24, left: 24, bottom: (areaH ? snapHeight(snap === 'full' ? 'half' : snap, areaH) : 0) + 16 };
  // Re-fit once a snap settles (not during a drag).
  useEffect(() => {
    if (!desktop && routes.length) refit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snap]);

  const setSnapFromHandle = (n: Snap) => {
    setSnap(n);
    setDragH(null);
  };
  const onHandleDown = (e: React.PointerEvent<HTMLButtonElement>) => {
    if (desktop || !areaH) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    drag.current = { y0: e.clientY, h0: snapHeight(snap, areaH), t: performance.now(), y: e.clientY, moved: false };
  };
  const onHandleMove = (e: React.PointerEvent<HTMLButtonElement>) => {
    const d = drag.current;
    if (!d) return;
    const dy = e.clientY - d.y0;
    if (Math.abs(dy) > 6) d.moved = true;
    if (!d.moved) return;
    d.t = performance.now();
    d.y = e.clientY;
    setDragH(Math.min(areaH, Math.max(snapHeight('peek', areaH), d.h0 - dy)));
  };
  const onHandleUp = (e: React.PointerEvent<HTMLButtonElement>) => {
    const d = drag.current;
    drag.current = null;
    if (!d?.moved) return; // a tap: handled by onClick
    const dt = Math.max(1, performance.now() - d.t + 16);
    const v = (e.clientY - d.y) / dt;
    setSnapFromHandle(settleSnap(dragH ?? d.h0, areaH, v));
    e.preventDefault();
  };
  const justDragged = () => dragH !== null;

  const clearAll = () => {
    s.reset();
    compare.reset();
    setLastReq(null);
    setNeedPoints(false);
    refit();
  };
  const togglePanel = (open: boolean) => {
    setPanelOpen(open);
    refit();
    requestAnimationFrame(() => (open ? hideBtn : showBtn).current?.focus());
  };

  const overlayMsg =
    overlay.reason === 'outside'
      ? t('overlays.outsidePilot')
      : overlay.reason === 'too-large'
        ? t('overlays.zoomIn')
        : segments.isError || hazards.isError
          ? t('overlays.error')
          : segments.isFetching || hazards.isFetching
            ? t('overlays.loading')
            : null;

  const sel = routes.find((r) => r.variant === s.selected) ?? routes[0];
  const summary = sel
    ? `${t(`results.${sel.variant}`)} · ${formatDuration(sel.duration_s, lang)} · ${formatDistance(sel.distance_m, lang)}`
    : s.origin && s.destination
      ? t('sheet.ready')
      : t('sheet.empty');

  const panel = (
    <div className="space-y-4 p-4">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="font-serif text-2xl font-semibold">{t('title')}</h1>
          <DemoBadge />
          {desktop && (
            <Button ref={hideBtn} variant="ghost" size="sm" className="ml-auto" onClick={() => togglePanel(false)} aria-controls="planner-panel" aria-expanded={panelOpen} data-testid="panel-hide">
              <PanelLeftClose aria-hidden="true" />
              {t('panel.hide')}
            </Button>
          )}
        </div>
        <p className="mt-1 text-sm text-muted-foreground">{t('intro')}</p>
      </div>

      <div className="space-y-1">
        <Label htmlFor="address-search" className="flex items-center gap-1.5">
          <Search className="size-4" aria-hidden="true" />
          {t('search.label')}
        </Label>
        <Input id="address-search" disabled aria-describedby="address-search-help" />
        <p id="address-search-help" className="text-xs text-muted-foreground">
          {t('search.disabled')}
        </p>
      </div>

      <PointInput which="origin" extra={<GeolocateButton onLocated={(p) => s.setPoint('origin', p)} />} />
      <div className="flex justify-center">
        <Button variant="ghost" size="sm" onClick={s.swap} disabled={!s.origin && !s.destination}>
          <ArrowDownUp aria-hidden="true" />
          {t('points.swap')}
        </Button>
      </div>
      <PointInput which="destination" />
      <RecentDestinations />

      <div className="space-y-1">
        <Label htmlFor="profile">{t('profile.label')}</Label>
        <Select id="profile" value={s.profile} onChange={(e) => s.setProfile(e.target.value as RouteProfile)} aria-describedby="profile-desc" data-testid="profile">
          {PROFILES.map((p) => (
            <option key={p} value={p}>
              {t(`profile.${p}`)}
            </option>
          ))}
        </Select>
        <p id="profile-desc" className="text-xs text-muted-foreground">
          {t(`profile.desc.${s.profile}`)}
        </p>
      </div>

      <div className="flex items-start gap-2">
        <input
          id="avoid-reports"
          type="checkbox"
          className="mt-1 size-5 accent-[var(--primary)]"
          checked={s.avoidUnverifiedReports}
          onChange={(e) => s.setAvoidUnverifiedReports(e.target.checked)}
          aria-describedby="avoid-reports-desc"
        />
        <div>
          <Label htmlFor="avoid-reports">{t('avoidReports.label')}</Label>
          <p id="avoid-reports-desc" className="text-xs text-muted-foreground">
            {t('avoidReports.desc')}
          </p>
        </div>
      </div>

      <div className="flex gap-2">
        <Button size="lg" className="flex-1" onClick={onCompare} disabled={compare.isPending} data-testid="compare">
          <RouteIcon aria-hidden="true" />
          {compare.isPending ? t('computing') : t('compare')}
        </Button>
        <Button size="lg" variant="outline" className="px-4" onClick={clearAll} disabled={!s.origin && !s.destination && !compare.data && !compare.isError} data-testid="clear-all">
          <Eraser aria-hidden="true" />
          {t('actions.clearAll')}
        </Button>
      </div>
      {needPoints && (
        <p role="alert" className="text-sm text-danger">
          {t('needPoints')}
        </p>
      )}

      <div aria-live="polite" aria-busy={compare.isPending}>
        {compare.isPending && (
          <div className="space-y-2">
            {waking ? (
              <p className="text-sm" data-testid="compare-waking">
                {t('errors.waking')}
              </p>
            ) : (
              <span className="sr-only">{t('computing')}</span>
            )}
            <Skeleton className="h-6 w-1/2" />
            <Skeleton className="h-32 w-full" />
            <Skeleton className="h-32 w-full" />
          </div>
        )}
        {compare.isError && <RouteError error={compare.error} onRetry={lastReq ? () => run(lastReq) : undefined} />}
        {compare.isSuccess && compare.data && (
          <CompareCard
            ref={resultsHeading}
            data={compare.data}
            selected={s.selected}
            onSelect={s.setSelected}
            notice={<HazardSourceNotice coverage={hazardCoverage} context="route" />}
          />
        )}
      </div>

      <section aria-labelledby="layers-title" className="space-y-3 border-t border-border pt-4">
        <h2 id="layers-title" className="text-base font-semibold">
          {t('overlays.title')}
        </h2>
        {USE_MOCKS && <SimulatedBanner>{t('overlays.demoNote')}</SimulatedBanner>}
        <div className="flex flex-wrap items-center gap-4 text-sm">
          <label className="flex min-h-11 items-center gap-2">
            <input type="checkbox" className="size-5" checked={showSegments} onChange={(e) => setShowSegments(e.target.checked)} />
            {t('overlays.segments')}
          </label>
          <label className="flex min-h-11 items-center gap-2">
            <input type="checkbox" className="size-5" checked={showHazards} onChange={(e) => setShowHazards(e.target.checked)} />
            {t('overlays.hazards')}
          </label>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setShowSegments(true);
              setShowHazards(true);
            }}
            disabled={showSegments && showHazards}
            data-testid="layers-reset"
          >
            <Layers aria-hidden="true" />
            {t('overlays.reset')}
          </Button>
        </div>
        {overlayMsg && (
          <p className="text-sm text-muted-foreground" role="status">
            {overlayMsg}
          </p>
        )}
        <Legend />
        {showHazards && (
          <div>
            <h3 className="mb-2 text-sm font-semibold">{t('overlays.inView')}</h3>
            <div className="space-y-2">
              <HazardSourceNotice coverage={hazardCoverage} context="overlay" />
              <HazardList hazards={hazards.data?.features ?? NO_HAZARDS} coverage={hazardCoverage} />
            </div>
          </div>
        )}
      </section>
    </div>
  );

  return (
    <div
      ref={areaRef}
      className={cn('relative flex min-h-0 flex-1 flex-col lg:grid', panelOpen ? 'lg:grid-cols-[440px_1fr]' : 'lg:grid-cols-1')}
    >
      {/* Map region */}
      <div className="relative min-h-0 flex-1 lg:order-2" role="region" aria-label={t('map.label')}>
        {mapStatus === 'no-webgl' ? (
          <div className="hatch flex h-full items-center justify-center p-6">
            <Alert variant="warning" className="max-w-md bg-card" data-testid="map-fallback">
              <span>{t('map.fallback')}</span>
            </Alert>
          </div>
        ) : (
          <ErrorBoundary fallback={<Alert variant="warning" className="m-4 max-w-md bg-card">{t('map.fallback')}</Alert>}>
            <Suspense fallback={<Skeleton className="absolute inset-0 rounded-none" />}>
              {mountMap ? (
              <PlannerMap
                origin={s.origin}
                destination={s.destination}
                routes={routes}
                selected={s.selected}
                segments={segments.data?.features ?? NO_SEGMENTS}
                hazards={hazards.data?.features ?? NO_HAZARDS}
                showSegments={showSegments}
                showHazards={showHazards}
                picking={s.picking}
                onPick={s.pickFromMap}
                onViewport={overlay.setViewport}
                onStatus={setMapStatus}
                fitPadding={fitPadding}
                fitRequest={fitRequest}
              />
              ) : (
                <Skeleton className="absolute inset-0 rounded-none" />
              )}
            </Suspense>
          </ErrorBoundary>
        )}
        {mapStatus === 'style-error' && (
          <Alert variant="warning" className="absolute left-3 right-14 top-3 z-10 bg-card sm:right-auto sm:max-w-sm" role="status">
            <span>{t('map.loadError')}</span>
          </Alert>
        )}
        {s.picking && (
          <p className="pointer-events-none absolute bottom-4 left-1/2 z-10 -translate-x-1/2 rounded-full bg-navy px-4 py-2 text-sm text-ice shadow lg:bottom-8" role="status">
            {t('points.picking', { point: t(`points.${s.picking}`).toLowerCase() })}
          </p>
        )}
        {mapStatus === 'ok' && (
          <Button
            variant="outline"
            size="icon"
            className="absolute right-2.5 top-[86px] z-10 size-11 shadow"
            onClick={refit}
            aria-label={routes.length ? t('map.recenterRoute') : t('map.recenterArea')}
            title={routes.length ? t('map.recenterRoute') : t('map.recenterArea')}
            data-testid="map-recenter"
          >
            <LocateFixed aria-hidden="true" />
          </Button>
        )}
        {desktop && !panelOpen && (
          <Button ref={showBtn} className="absolute left-3 top-3 z-10 shadow" onClick={() => togglePanel(true)} aria-controls="planner-panel" aria-expanded={false} data-testid="panel-show">
            <PanelLeftOpen aria-hidden="true" />
            {t('panel.show')}
          </Button>
        )}
      </div>

      {/* Panel: collapsible side panel ≥ lg, bottom sheet (peek / half / full) below */}
      <aside
        id="planner-panel"
        aria-label={t('title')}
        className={cn(
          'z-20 flex flex-col border-border bg-background lg:order-1 lg:h-full lg:overflow-y-auto lg:border-r',
          'max-lg:absolute max-lg:inset-x-0 max-lg:bottom-0 max-lg:rounded-t-2xl max-lg:border-t max-lg:shadow-[0_-8px_24px_rgba(16,27,44,0.18)]',
          dragH === null && 'max-lg:transition-[height] max-lg:duration-200',
          !areaH && 'max-lg:h-1/2',
          !panelOpen && 'lg:hidden',
        )}
        style={desktop || !areaH ? undefined : { height: sheetH }}
        data-testid="planner-panel"
        data-snap={desktop ? undefined : snap}
      >
        {!desktop && (
          <button
            type="button"
            className="flex min-h-[60px] w-full shrink-0 touch-none flex-col items-center justify-center gap-1 border-b border-border px-4 pb-2 pt-2"
            aria-controls="planner-sheet-body"
            aria-expanded={snap !== 'peek'}
            data-testid="sheet-handle"
            onPointerDown={onHandleDown}
            onPointerMove={onHandleMove}
            onPointerUp={onHandleUp}
            onPointerCancel={() => {
              drag.current = null;
              setDragH(null);
            }}
            onClick={() => {
              if (justDragged()) return;
              setSnapFromHandle(nextSnap(snap, 'cycle'));
            }}
            onKeyDown={(e) => {
              if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
                e.preventDefault();
                setSnapFromHandle(nextSnap(snap, e.key === 'ArrowUp' ? 'up' : 'down'));
              }
            }}
          >
            <span aria-hidden="true" className="h-1.5 w-12 rounded-full bg-muted-foreground/60" />
            <span className="max-w-full truncate text-sm font-medium" data-testid="sheet-summary">
              {summary}
            </span>
            <span className="sr-only"> — {t('sheet.toggle', { state: t(`sheet.state.${snap}`) })}</span>
          </button>
        )}
        <div ref={sheetBody} id="planner-sheet-body" className={cn('min-h-0 flex-1 overflow-y-auto', !desktop && snap === 'peek' && dragH === null && 'invisible')}>
          {panel}
        </div>
      </aside>
    </div>
  );
}
