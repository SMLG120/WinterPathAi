import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowDownUp, ChevronDown, ChevronUp, Route as RouteIcon, Search } from 'lucide-react';
import { useCompareRoutes, useHazards, useSegments } from '@/api/queries';
import type { HazardFeature, RouteCompareRequest, SegmentFeature } from '@/api/types';
import { DemoBadge } from '@/components/evidence/DemoBadge';
import { SimulatedBanner } from '@/components/evidence/EvidenceBadge';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input, Label, Select } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { CompareCard } from '@/features/plan/CompareCard';
import { GeolocateButton } from '@/features/plan/GeolocateButton';
import { HazardList } from '@/features/plan/HazardList';
import { Legend } from '@/features/plan/Legend';
import { PointInput } from '@/features/plan/PointInput';
import { RouteError } from '@/features/plan/RouteError';
import { useOverlayBbox } from '@/features/plan/useOverlayBbox';
import { ErrorBoundary } from '@/components/layout/ErrorBoundary';
import { USE_MOCKS } from '@/lib/env';
import { useLang } from '@/lib/i18n-routing';
import { useDocumentTitle } from '@/lib/useDocumentTitle';
import { cn } from '@/lib/utils';
import { usePlannerStore } from '@/stores/planner';
import type { RouteProfile } from '@/api/types';

const PlannerMap = lazy(() => import('@/features/plan/PlannerMap'));
const PROFILES: RouteProfile[] = ['standard', 'step_free', 'reduced_mobility'];
const NO_SEGMENTS: SegmentFeature[] = [];
const NO_HAZARDS: HazardFeature[] = [];

export default function Plan() {
  const { t } = useTranslation(['plan', 'common']);
  const lang = useLang();
  useDocumentTitle(t('title'));
  const s = usePlannerStore();
  const compare = useCompareRoutes();
  const [lastReq, setLastReq] = useState<RouteCompareRequest | null>(null);
  const [needPoints, setNeedPoints] = useState(false);
  const [mapStatus, setMapStatus] = useState<'ok' | 'no-webgl' | 'style-error' | 'loading'>('loading');
  const [sheetOpen, setSheetOpen] = useState(false);
  const [showSegments, setShowSegments] = useState(true);
  const [showHazards, setShowHazards] = useState(true);
  const resultsHeading = useRef<HTMLHeadingElement>(null);

  const overlay = useOverlayBbox();
  const segments = useSegments(showSegments ? overlay.bbox : null);
  const hazards = useHazards(showHazards ? overlay.bbox : null);

  const run = useCallback(
    (req: RouteCompareRequest) => {
      setLastReq(req);
      compare.mutate(req, {
        onSuccess: () => {
          setSheetOpen(true);
          requestAnimationFrame(() => resultsHeading.current?.focus());
        },
      });
    },
    [compare],
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

  const routes = compare.data?.routes ?? [];
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

  const panel = (
    <div className="space-y-4 p-4">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="font-serif text-2xl font-semibold">{t('title')}</h1>
          <DemoBadge />
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

      <Button size="lg" className="w-full" onClick={onCompare} disabled={compare.isPending} data-testid="compare">
        <RouteIcon aria-hidden="true" />
        {compare.isPending ? t('computing') : t('compare')}
      </Button>
      {needPoints && (
        <p role="alert" className="text-sm text-danger">
          {t('needPoints')}
        </p>
      )}

      <div aria-live="polite" aria-busy={compare.isPending}>
        {compare.isPending && (
          <div className="space-y-2">
            <span className="sr-only">{t('computing')}</span>
            <Skeleton className="h-6 w-1/2" />
            <Skeleton className="h-32 w-full" />
            <Skeleton className="h-32 w-full" />
          </div>
        )}
        {compare.isError && <RouteError error={compare.error} />}
        {compare.isSuccess && compare.data && (
          <CompareCard ref={resultsHeading} data={compare.data} selected={s.selected} onSelect={s.setSelected} />
        )}
      </div>

      <section aria-labelledby="layers-title" className="space-y-3 border-t border-border pt-4">
        <h2 id="layers-title" className="text-base font-semibold">
          {t('overlays.title')}
        </h2>
        {USE_MOCKS && <SimulatedBanner />}
        <div className="flex flex-wrap gap-4 text-sm">
          <label className="flex items-center gap-2">
            <input type="checkbox" className="size-5" checked={showSegments} onChange={(e) => setShowSegments(e.target.checked)} />
            {t('overlays.segments')}
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" className="size-5" checked={showHazards} onChange={(e) => setShowHazards(e.target.checked)} />
            {t('overlays.hazards')}
          </label>
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
            <HazardList hazards={hazards.data?.features ?? NO_HAZARDS} />
          </div>
        )}
      </section>
    </div>
  );

  return (
    <div className="relative flex min-h-0 flex-1 flex-col lg:grid lg:grid-cols-[440px_1fr]">
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
              />
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
      </div>

      {/* Panel: side panel ≥ lg, bottom sheet below */}
      <aside
        aria-label={t('title')}
        className={cn(
          'z-20 flex flex-col border-border bg-background lg:order-1 lg:h-full lg:overflow-y-auto lg:border-r',
          'max-lg:absolute max-lg:inset-x-0 max-lg:bottom-0 max-lg:rounded-t-2xl max-lg:border-t max-lg:shadow-[0_-8px_24px_rgba(16,27,44,0.18)]',
          sheetOpen ? 'max-lg:h-[85%]' : 'max-lg:h-[42%]',
        )}
        data-testid="planner-panel"
      >
        <button
          type="button"
          className="flex min-h-10 w-full items-center justify-center gap-2 border-b border-border text-sm font-medium lg:hidden"
          aria-expanded={sheetOpen}
          onClick={() => setSheetOpen((o) => !o)}
        >
          <span aria-hidden="true" className="h-1 w-10 rounded-full bg-muted-foreground/50" />
          {sheetOpen ? <ChevronDown aria-hidden="true" className="size-4" /> : <ChevronUp aria-hidden="true" className="size-4" />}
          <span className="sr-only">{sheetOpen ? t('sheet.collapse') : t('sheet.expand')}</span>
        </button>
        <div className="min-h-0 flex-1 overflow-y-auto">{panel}</div>
      </aside>
    </div>
  );
}
