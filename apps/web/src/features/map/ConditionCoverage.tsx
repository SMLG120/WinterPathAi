import { useTranslation } from 'react-i18next';
import { CircleHelp } from 'lucide-react';
import type { RouteCompareResponse } from '@/api/types';
import { formatPercent } from '@/lib/format';
import { cn } from '@/lib/utils';

type RiskLayer = RouteCompareResponse['risk_layer'];

/**
 * How much of a route has winter-condition data, as a bar + text. This is data coverage, not a
 * safety rating: the known part is an estimate (model/heuristic), the rest is unknown — and unknown
 * is drawn hatched and named, never left blank or shown as "low". With no risk layer active
 * (`risk_layer: none`) nothing was assessed, so the bar shows the whole route as unknown even if
 * `unknown_share` says otherwise.
 * Only spans: it is rendered inside the card buttons.
 */
export function ConditionCoverage({ unknownShare, riskLayer, compact = false, className }: { unknownShare: number; riskLayer?: RiskLayer; compact?: boolean; className?: string }) {
  const { t, i18n } = useTranslation('map');
  const L = i18n.language;
  const noLayer = riskLayer === 'none';
  const u = noLayer ? 1 : Math.min(1, Math.max(0, Number.isFinite(unknownShare) ? unknownShare : 1));
  const known = 1 - u;
  const kp = formatPercent(known, L);
  const up = formatPercent(u, L);
  return (
    <span className={cn('flex flex-col gap-1', className)} data-testid="condition-coverage" data-unknown-share={u.toFixed(3)}>
      {!compact && <span className="text-xs font-semibold">{t('confidence.title')}</span>}
      <span
        role="img"
        aria-label={t('confidence.meter', { known: kp, unknown: up })}
        className="flex h-2.5 w-full overflow-hidden rounded-full border border-border bg-card"
      >
        {known > 0 && <span className="h-full bg-teal" style={{ width: `${known * 100}%` }} />}
        {u > 0 && <span className="hatch h-full" style={{ width: `${u * 100}%` }} />}
      </span>
      {/* Compact cards already say the unknown share in words next to the bar. */}
      {!compact && (
        <span className="flex flex-wrap gap-x-3 text-xs text-muted-foreground" aria-hidden="true">
          <span>{t('confidence.known', { pct: kp })}</span>
          <span className="inline-flex items-center gap-1">
            <CircleHelp className="size-3.5" aria-hidden="true" />
            {t('confidence.unknown', { pct: up })}
          </span>
        </span>
      )}
      {riskLayer && (!compact || noLayer) && <span className="text-xs text-muted-foreground">{t(`confidence.source.${riskLayer}`)}</span>}
      {u >= 0.5 && (
        <span className="text-xs font-medium" data-testid="mostly-unknown">
          {t('confidence.mostlyUnknown')}
        </span>
      )}
    </span>
  );
}
