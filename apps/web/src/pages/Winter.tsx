import { useTranslation } from 'react-i18next';
import { BarChart3, Snowflake, Thermometer, Wind, Droplets } from 'lucide-react';
import { useWeatherCurrent, useWeatherForecast } from '@/api/queries';
import type { WeatherCurrent, WeatherForecast } from '@/api/types';
import { DataState } from '@/components/evidence/DataState';
import { DemoBadge } from '@/components/evidence/DemoBadge';
import { EvidenceBadge, SimulatedBanner } from '@/components/evidence/EvidenceBadge';
import { Freshness } from '@/components/evidence/Freshness';
import { PageHeader } from '@/components/layout/Section';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ModelStatusCard } from '@/features/ModelStatusCard';
import { formatDateTime } from '@/lib/format';
import { useDocumentTitle } from '@/lib/useDocumentTitle';

function num(v: number | null | undefined, unit: string, lang: string, dash: string) {
  return v == null ? dash : `${new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(v)} ${unit}`;
}

function Current({ w }: { w: WeatherCurrent }) {
  const { t, i18n } = useTranslation('winter');
  const L = i18n.language;
  const dash = t('current.noValue');
  const items = [
    { Icon: Thermometer, label: t('current.temperature'), v: num(w.temperature_c, '°C', L, dash) },
    { Icon: Droplets, label: t('current.precip'), v: num(w.precipitation_mm_1h, 'mm', L, dash) },
    { Icon: Snowflake, label: t('current.snowDepth'), v: num(w.snow_depth_cm, 'cm', L, dash) },
    { Icon: Wind, label: t('current.wind'), v: num(w.wind_speed_kmh, 'km/h', L, dash) },
  ];
  return (
    <div className="space-y-4">
      {w.evidence.state === 'simulated' && <SimulatedBanner />}
      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {items.map(({ Icon, label, v }) => (
          <div key={label} className="rounded-lg border border-border p-3">
            <dt className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <Icon className="size-4" aria-hidden="true" />
              {label}
            </dt>
            <dd className="mt-1 text-xl font-semibold">{v}</dd>
          </div>
        ))}
      </dl>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <EvidenceBadge state={w.evidence.state} />
        <span className="text-muted-foreground">
          {t('current.station')}: {w.station_name ?? w.station_id}
        </span>
        <span className="text-muted-foreground">{t('current.observed', { time: formatDateTime(w.observed_at, L) })}</span>
        <Freshness at={w.evidence.retrieved_at ?? w.observed_at} />
      </div>
    </div>
  );
}

function FreezeThaw({ w }: { w: WeatherCurrent }) {
  const { t } = useTranslation('winter');
  const v = w.freeze_thaw_24h;
  const key = v === true ? 'yes' : v === false ? 'no' : 'unknown';
  return (
    <div className="space-y-2" data-testid="freeze-thaw">
      <p className="flex items-center gap-2 text-lg font-semibold">
        <span aria-hidden="true">{v === true ? '⇅' : v === false ? '—' : '?'}</span>
        {t(`freezeThaw.${key}`)}
      </p>
      <EvidenceBadge state={v == null ? 'unknown' : w.evidence.state} />
      <p className="text-sm text-muted-foreground">{t('freezeThaw.desc')}</p>
    </div>
  );
}

function Forecast({ f }: { f: WeatherForecast }) {
  const { t, i18n } = useTranslation('winter');
  const L = i18n.language;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <EvidenceBadge state={f.evidence.state} />
        <span className="text-muted-foreground">{t('forecast.issued', { time: formatDateTime(f.issued_at, L) })}</span>
        <Freshness at={f.evidence.retrieved_at ?? f.issued_at} />
      </div>
      {f.periods.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('forecast.empty')}</p>
      ) : (
        <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {f.periods.map((p) => (
            <li key={p.start} className="rounded-lg border border-border p-3 text-sm">
              <p className="text-muted-foreground">{formatDateTime(p.start, L)}</p>
              <p className="mt-1 font-medium">{L === 'fr' ? p.summary_fr : p.summary_en}</p>
              {p.temperature_c != null && <p className="mt-1 text-lg font-semibold">{p.temperature_c} °C</p>}
              {p.pop_percent != null && <p className="text-muted-foreground">{t('forecast.pop', { pct: p.pop_percent })}</p>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

/** ECCC alerts reproduced unaltered, tagged with their original language. */
export function Alerts({ f }: { f: WeatherForecast }) {
  const { t, i18n } = useTranslation('winter');
  const L = i18n.language;
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">{t('alerts.unaltered')}</p>
      {f.alerts.length === 0 ? (
        <p className="text-sm" data-testid="alerts-none">
          {t('alerts.none')}
        </p>
      ) : (
        <ul className="space-y-3">
          {f.alerts.map((a) => (
            <li key={a.id} className="rounded-lg border-2 border-amber-brand p-4" lang={a.language === 'fr' ? 'fr-CA' : 'en-CA'}>
              <p className="font-semibold">{a.headline}</p>
              <p className="mt-2 whitespace-pre-line text-sm">{a.text}</p>
              <p className="mt-2 text-xs text-muted-foreground" lang={L}>
                {t('alerts.issued', { time: formatDateTime(a.issued_at, L) })}
                {a.expires_at && <> · {t('alerts.expires', { time: formatDateTime(a.expires_at, L) })}</>}
                {a.severity && <> · {t('alerts.severity', { value: a.severity })}</>}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function Winter() {
  const { t } = useTranslation('winter');
  useDocumentTitle(t('title'));
  const current = useWeatherCurrent();
  const forecast = useWeatherForecast(24);

  return (
    <>
      <PageHeader title={t('title')} intro={t('intro')}>
        <DemoBadge />
      </PageHeader>
      <div className="mx-auto grid max-w-6xl gap-6 px-4 py-10 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>{t('current.title')}</CardTitle>
          </CardHeader>
          <CardContent>
            <DataState query={current}>{(w) => <Current w={w} />}</DataState>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t('freezeThaw.title')}</CardTitle>
          </CardHeader>
          <CardContent>
            <DataState query={current}>{(w) => <FreezeThaw w={w} />}</DataState>
          </CardContent>
        </Card>
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle>{t('alerts.title')}</CardTitle>
          </CardHeader>
          <CardContent>
            <DataState query={forecast}>{(f) => <Alerts f={f} />}</DataState>
          </CardContent>
        </Card>
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle>{t('forecast.title')}</CardTitle>
          </CardHeader>
          <CardContent>
            <DataState query={forecast}>{(f) => <Forecast f={f} />}</DataState>
          </CardContent>
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>{t('history.title')}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="hatch flex items-start gap-3 rounded-lg border border-dashed border-muted-foreground p-4" data-testid="history-unavailable">
              <BarChart3 className="size-6 shrink-0" aria-hidden="true" />
              <div className="space-y-2 rounded-md bg-card/90 p-2 text-sm">
                <EvidenceBadge state="unknown" />
                <p>{t('history.unavailable')}</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <div>
          <ModelStatusCard />
        </div>
      </div>
    </>
  );
}
