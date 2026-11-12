import { useTranslation } from 'react-i18next';
import { AlertTriangle, CheckCircle2, CircleHelp, MapPinned } from 'lucide-react';
import type { Route } from '@/api/types';
import { Freshness } from '@/components/evidence/Freshness';
import { formatDistance, formatDuration, formatPercent } from '@/lib/format';
import { cn } from '@/lib/utils';
import type { RouteVariant } from '@/stores/planner-types';
import { ROUTE_STYLE } from './mapStyle';
import { oldestFreshness } from './routeInfo';

/**
 * Compact, tappable summaries (bottom sheet / panel top). Only fields the API returns: time,
 * distance, share of the route without condition data, known issues on/avoided, data age.
 * The API has no route-level risk category, so none is invented here.
 */
export function RouteCards({ routes, selected, onSelect }: { routes: Route[]; selected: RouteVariant; onSelect: (v: RouteVariant) => void }) {
  const { t, i18n } = useTranslation('plan');
  const L = i18n.language;
  const ordered = [...routes].sort((a, b) => (a.variant === 'winter_aware' ? -1 : b.variant === 'winter_aware' ? 1 : 0));
  return (
    <ul className="grid gap-2" data-testid="route-cards" aria-label={t('cards.label')}>
      {ordered.map((r) => {
        const on = r.variant === selected;
        const st = ROUTE_STYLE[r.variant];
        const onRoute = r.hazards_on_route?.length ?? 0;
        const avoided = r.hazards_avoided?.length ?? 0;
        return (
          <li key={r.variant}>
            <button
              type="button"
              aria-pressed={on}
              onClick={() => onSelect(r.variant)}
              data-testid={`route-card-${r.variant}`}
              className={cn(
                'w-full rounded-lg border bg-card p-3 text-left transition-colors hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring',
                on ? 'border-primary ring-2 ring-primary' : 'border-border',
              )}
            >
              <span className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 font-semibold">
                  <svg width="28" height="8" aria-hidden="true" className="shrink-0">
                    <line x1="2" y1="4" x2="26" y2="4" stroke={st.color} strokeWidth="4" strokeDasharray={st.dash ? '6 4' : undefined} strokeLinecap="round" />
                  </svg>
                  {t(`results.${r.variant}`)}
                </span>
                <span className={cn('inline-flex items-center gap-1 text-xs font-medium', on ? 'text-accent-text' : 'text-muted-foreground')}>
                  {on && <MapPinned className="size-4" aria-hidden="true" />}
                  {on ? t('results.shown') : t('results.show')}
                </span>
              </span>
              <span className="mt-1 flex items-baseline gap-3">
                <span className="text-xl font-semibold">{formatDuration(r.duration_s, L)}</span>
                <span className="text-sm text-muted-foreground">{formatDistance(r.distance_m, L)}</span>
              </span>
              <span className="mt-1.5 flex flex-col gap-1 text-sm">
                <span className="flex items-center gap-1.5" data-testid="card-unknown">
                  {r.unknown_share > 0 ? <CircleHelp className="size-4 shrink-0" aria-hidden="true" /> : <CheckCircle2 className="size-4 shrink-0" aria-hidden="true" />}
                  {r.unknown_share > 0 ? t('cards.unknown', { pct: formatPercent(r.unknown_share, L) }) : t('cards.known')}
                </span>
                {onRoute > 0 && (
                  <span className="flex items-center gap-1.5 text-danger">
                    <AlertTriangle className="size-4 shrink-0" aria-hidden="true" />
                    {t('results.hazardsOnRoute', { count: onRoute })}
                  </span>
                )}
                {avoided > 0 && (
                  <span className="flex items-center gap-1.5">
                    <CheckCircle2 className="size-4 shrink-0" aria-hidden="true" />
                    {t('results.hazardsAvoided', { count: avoided })}
                  </span>
                )}
                <Freshness at={oldestFreshness(r)} label={t('cards.oldest')} />
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
