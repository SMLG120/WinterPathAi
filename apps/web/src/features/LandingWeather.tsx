import { useTranslation } from 'react-i18next';
import { CloudOff, Snowflake, Thermometer, Wind } from 'lucide-react';
import { useWeatherCurrent } from '@/api/queries';
import { EvidenceBadge } from '@/components/evidence/EvidenceBadge';
import { Freshness } from '@/components/evidence/Freshness';
import { Skeleton } from '@/components/ui/skeleton';
import { formatDateTime } from '@/lib/format';

const fmt = (v: number | null | undefined, unit: string, lang: string) =>
  v == null ? null : `${new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(v)} ${unit}`;

/**
 * "Montréal now" on the landing hero, from the existing GET /weather/current (ECCC observation).
 * Missing values stay missing ("—"), a failure shows no values at all, and the evidence state and
 * observation age are always visible. Fixed min-height: no layout shift while it loads.
 */
export function LandingWeather() {
  const { t, i18n } = useTranslation(['landing', 'winter']);
  const L = i18n.language;
  const q = useWeatherCurrent();
  const dash = t('winter:current.noValue');

  return (
    <section aria-labelledby="now-title" className="min-h-[112px] rounded-xl bg-card p-4 text-card-foreground shadow-sm" data-testid="landing-weather" aria-busy={q.isPending}>
      <h2 id="now-title" className="text-sm font-semibold">
        {t('weather.title')}
      </h2>
      {q.isPending && (
        <div className="mt-2 space-y-2">
          <span className="sr-only">{t('weather.loading')}</span>
          <Skeleton className="h-7 w-40" />
          <Skeleton className="h-4 w-56" />
        </div>
      )}
      {q.isError && (
        <p className="mt-2 flex items-center gap-2 text-sm" data-testid="landing-weather-unavailable">
          <CloudOff className="size-4 shrink-0" aria-hidden="true" />
          {t('weather.unavailable')}
        </p>
      )}
      {q.isSuccess && (
        <div className="mt-1 space-y-2">
          <p className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <span className="flex items-center gap-1.5 text-2xl font-semibold">
              <Thermometer className="size-5" aria-hidden="true" />
              <span className="sr-only">{t('winter:current.temperature')}: </span>
              {fmt(q.data.temperature_c, '°C', L) ?? dash}
            </span>
            <span className="flex items-center gap-1.5 text-sm">
              <Wind className="size-4" aria-hidden="true" />
              {t('winter:current.wind')}: {fmt(q.data.wind_speed_kmh, 'km/h', L) ?? dash}
            </span>
            <span className="flex items-center gap-1.5 text-sm">
              <Snowflake className="size-4" aria-hidden="true" />
              {t('winter:current.snowDepth')}: {fmt(q.data.snow_depth_cm, 'cm', L) ?? dash}
            </span>
          </p>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <EvidenceBadge state={q.data.evidence.state} />
            <span className="text-muted-foreground">
              {t('weather.observed', { station: q.data.station_name ?? q.data.station_id, time: formatDateTime(q.data.observed_at, L) })}
            </span>
            <Freshness at={q.data.evidence.retrieved_at ?? q.data.observed_at} />
          </div>
        </div>
      )}
    </section>
  );
}
