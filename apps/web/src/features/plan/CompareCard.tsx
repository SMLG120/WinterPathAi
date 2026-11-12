import { forwardRef, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Info } from 'lucide-react';
import type { Route, RouteCompareResponse } from '@/api/types';
import { EvidenceBadge, SimulatedBanner } from '@/components/evidence/EvidenceBadge';
import { DemoBadge } from '@/components/evidence/DemoBadge';
import { Freshness } from '@/components/evidence/Freshness';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { formatDateTime, formatDistance, formatDuration, formatPercent } from '@/lib/format';
import { cn } from '@/lib/utils';
import type { RouteVariant } from '@/stores/planner-types';
import { ROUTE_STYLE } from './mapStyle';
import { RouteCards } from './RouteCards';

function RouteSwatch({ variant }: { variant: RouteVariant }) {
  const s = ROUTE_STYLE[variant];
  return (
    <svg width="28" height="8" aria-hidden="true" className="shrink-0">
      <line x1="2" y1="4" x2="26" y2="4" stroke={s.color} strokeWidth="4" strokeDasharray={s.dash ? '6 4' : undefined} strokeLinecap="round" />
    </svg>
  );
}

function RouteDetails({ route, selected, onSelect }: { route: Route; selected: boolean; onSelect: () => void }) {
  const { t, i18n } = useTranslation('plan');
  const lang = i18n.language;
  const hid = `route-${route.variant}-title`;
  return (
    <article
      aria-labelledby={hid}
      className={cn('rounded-lg border p-4', selected ? 'border-primary ring-1 ring-primary' : 'border-border')}
      data-testid={`route-${route.variant}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id={hid} className="flex items-center gap-2 font-semibold">
          <RouteSwatch variant={route.variant} />
          {t(`results.${route.variant}`)}
        </h3>
        <Button size="sm" variant={selected ? 'default' : 'outline'} aria-pressed={selected} onClick={onSelect}>
          {selected ? t('results.shown') : t('results.show')}
        </Button>
      </div>
      <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
        <div>
          <dt className="text-muted-foreground">{t('results.distance')}</dt>
          <dd className="text-base font-semibold" data-testid="distance">
            {formatDistance(route.distance_m, lang)}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t('results.duration')}</dt>
          <dd className="text-base font-semibold">{formatDuration(route.duration_s, lang)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t('results.unknownShare')}</dt>
          <dd className="text-base font-semibold">{formatPercent(route.unknown_share, lang)}</dd>
        </div>
      </dl>
      {route.unknown_share > 0 && (
        <p className="mt-2 flex items-start gap-1.5 text-sm text-muted-foreground">
          <EvidenceBadge state="unknown" className="shrink-0" />
          <span>{t('results.unknownShareDesc', { pct: formatPercent(route.unknown_share, lang) })}</span>
        </p>
      )}
      <p className="mt-2 text-sm">
        {(route.hazards_avoided?.length ?? 0) > 0 && <span className="mr-3">{t('results.hazardsAvoided', { count: route.hazards_avoided!.length })}</span>}
        {(route.hazards_on_route?.length ?? 0) > 0 && (
          <span className="text-danger">{t('results.hazardsOnRoute', { count: route.hazards_on_route!.length })}</span>
        )}
      </p>

      <h4 className="mt-4 text-sm font-semibold">{t('results.explanation')}</h4>
      <ul className="mt-1 space-y-2">
        {route.explanation.map((e, i) => (
          <li key={`${e.code}-${i}`} className="flex flex-col gap-1 text-sm sm:flex-row sm:items-start sm:gap-2">
            <EvidenceBadge state={e.evidence_state} className="shrink-0" />
            <span>{e.text}</span>
          </li>
        ))}
      </ul>

      <h4 className="mt-4 text-sm font-semibold">{t('results.freshness')}</h4>
      <ul className="mt-1 space-y-0.5">
        {Object.entries(route.data_freshness).map(([src, at]) => (
          <li key={src}>
            <Freshness at={at} label={src} />
          </li>
        ))}
      </ul>

      {route.steps && route.steps.length > 0 && (
        <details className="mt-4" open={selected}>
          <summary className="cursor-pointer text-sm font-semibold">{t('results.steps')}</summary>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm" data-testid={`steps-${route.variant}`}>
            {route.steps.map((s, i) => (
              <li key={i}>
                {s.instruction}
                {s.distance_m > 0 && <span className="text-muted-foreground"> — {formatDistance(s.distance_m, lang)}</span>}
              </li>
            ))}
          </ol>
        </details>
      )}
    </article>
  );
}

export const CompareCard = forwardRef<
  HTMLHeadingElement,
  /** `notice`: e.g. which hazard sources these routes could not take into account. */
  { data: RouteCompareResponse; selected: RouteVariant; onSelect: (v: RouteVariant) => void; notice?: ReactNode }
>(function CompareCard({ data, selected, onSelect, notice }, headingRef) {
  const { t, i18n } = useTranslation('plan');
  const simulated = data.routes.some((r) => r.explanation.some((e) => e.evidence_state === 'simulated'));
  const rank = (r: Route) => (r.variant === 'winter_aware' ? 0 : 1);
  const ordered = [...data.routes].sort((a, b) => rank(a) - rank(b));
  return (
    <section aria-labelledby="compare-title" className="space-y-3" data-testid="compare-card">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="compare-title" ref={headingRef} tabIndex={-1} className="text-lg font-semibold">
          {t('results.title')}
        </h2>
        <DemoBadge />
      </div>
      {simulated && <SimulatedBanner />}
      <RouteCards routes={data.routes} selected={selected} onSelect={onSelect} />
      <p className="text-sm text-muted-foreground">
        {t('results.riskLayer.label')}: <span className="font-medium text-foreground">{t(`results.riskLayer.${data.risk_layer}`)}</span>
        {' · '}
        {t('results.computedAt', { time: formatDateTime(data.computed_at, i18n.language) })}
      </p>
      {data.identical && (
        <Alert variant="info">
          <Info aria-hidden="true" />
          <span>{t('results.identical')}</span>
        </Alert>
      )}
      {data.warnings && data.warnings.length > 0 && (
        <Alert variant="warning">
          <AlertTriangle aria-hidden="true" />
          <div>
            <p className="font-semibold">{t('results.warnings')}</p>
            <ul className="list-disc pl-4">
              {data.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </div>
        </Alert>
      )}
      {notice}
      <h3 className="pt-2 text-base font-semibold">{t('results.details')}</h3>
      {ordered.map((r) => (
        <RouteDetails key={r.variant} route={r} selected={r.variant === selected} onSelect={() => onSelect(r.variant)} />
      ))}
    </section>
  );
});
