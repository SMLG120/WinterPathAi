import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, Copy, LocateFixed, Trash2 } from 'lucide-react';
import { useCreateReport, useDeleteReport } from '@/api/queries';
import { isApiError } from '@/api/client';
import type { ReportReceipt } from '@/api/types';
import { DemoBadge } from '@/components/evidence/DemoBadge';
import { EvidenceBadge } from '@/components/evidence/EvidenceBadge';
import { PageHeader } from '@/components/layout/Section';
import { Alert, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { FieldError, Input, Label, Select, Textarea } from '@/components/ui/input';
import { REPORT_CATEGORIES, MAX_DESCRIPTION, reportSchema, toReportCreate, type ReportFormValues } from '@/features/reportSchema';
import { formatDateTime } from '@/lib/format';
import { getCurrentLonLat, type GeoFailure } from '@/lib/geolocation';
import { WritesDisabled } from '@/features/WritesDisabled';
import { PUBLIC_WRITES } from '@/lib/env';
import { useLang } from '@/lib/i18n-routing';
import { useDocumentTitle } from '@/lib/useDocumentTitle';

function Receipt({ r, onReset }: { r: ReportReceipt; onReset: () => void }) {
  const { t, i18n } = useTranslation(['reports', 'common']);
  const del = useDeleteReport();
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(r.deletion_token);
      setCopied(true);
    } catch {
      /* clipboard unavailable: token remains visible for manual copy */
    }
  };
  if (del.isSuccess) {
    return (
      <Alert variant="success" role="status">
        <CheckCircle2 aria-hidden="true" />
        <div className="space-y-3">
          <p>{t('receipt.deleted')}</p>
          <Button variant="outline" size="sm" onClick={onReset}>
            {t('receipt.another')}
          </Button>
        </div>
      </Alert>
    );
  }
  return (
    <Card data-testid="report-receipt">
      <CardHeader>
        <CardTitle className="flex items-center gap-2" tabIndex={-1} id="receipt-title">
          <CheckCircle2 className="size-5 text-accent-text" aria-hidden="true" />
          {t('receipt.title')}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <p>{t('receipt.body')}</p>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
          <dt className="text-muted-foreground">{t('receipt.id')}</dt>
          <dd className="break-all font-mono text-xs">{r.id}</dd>
          <dt className="text-muted-foreground">{t('receipt.status')}</dt>
          <dd>{t(`status.${r.status}`)}</dd>
          <dt className="text-muted-foreground">{t('receipt.expires')}</dt>
          <dd>{formatDateTime(r.expires_at, i18n.language)}</dd>
        </dl>
        <div className="rounded-md border-2 border-amber-brand p-3">
          <p className="font-semibold">{t('receipt.token')}</p>
          <p className="mt-1 break-all font-mono text-xs" data-testid="deletion-token">
            {r.deletion_token}
          </p>
          <p className="mt-2">{t('receipt.tokenWarn')}</p>
          <Button variant="outline" size="sm" className="mt-2" onClick={() => void copy()}>
            <Copy aria-hidden="true" />
            {copied ? t('common:actions.copied') : t('common:actions.copy')}
          </Button>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="danger" size="sm" disabled={del.isPending} onClick={() => del.mutate({ id: r.id, token: r.deletion_token })}>
            <Trash2 aria-hidden="true" />
            {del.isPending ? t('receipt.deleting') : t('receipt.delete')}
          </Button>
          <Button variant="ghost" size="sm" onClick={onReset}>
            {t('receipt.another')}
          </Button>
        </div>
        {del.isError && (
          <p role="alert" className="text-danger">
            {t('receipt.deleteFailed')}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export default function Reports() {
  const { t } = useTranslation(['reports', 'common', 'errors']);
  const lang = useLang();
  useDocumentTitle(t('title'));
  const create = useCreateReport();
  const [geo, setGeo] = useState<'idle' | 'locating' | GeoFailure>('idle');
  const {
    register,
    handleSubmit,
    setValue,
    watch,
    reset,
    formState: { errors },
  } = useForm<ReportFormValues>({
    resolver: zodResolver(reportSchema(t)),
    defaultValues: { category: undefined, lat: '', lon: '', consent: false, description: '' },
  });
  const desc = watch('description') ?? '';

  const fillFromLocation = async () => {
    setGeo('locating');
    try {
      const p = await getCurrentLonLat();
      setValue('lat', p.lat.toFixed(6), { shouldValidate: true });
      setValue('lon', p.lon.toFixed(6), { shouldValidate: true });
      setGeo('idle');
    } catch (e) {
      setGeo(e as GeoFailure);
    }
  };

  const onSubmit = handleSubmit((v) => create.mutate(toReportCreate(v, lang)));
  const err = create.error;
  const rateLimited = isApiError(err) && err.code === 'RATE_LIMITED';
  const writesDisabled = isApiError(err) && err.code === 'WRITES_DISABLED';
  const statuses = ['pending', 'approved', 'rejected', 'expired', 'deleted'] as const;

  return (
    <>
      <PageHeader title={t('title')} intro={t('intro')}>
        <DemoBadge />
      </PageHeader>
      <div className="mx-auto grid max-w-6xl gap-8 px-4 py-10 lg:grid-cols-[1.4fr_1fr]">
        <div>
          {!PUBLIC_WRITES || writesDisabled ? (
            <WritesDisabled form="reports" />
          ) : create.isSuccess && create.data ? (
            <Receipt
              r={create.data}
              onReset={() => {
                create.reset();
                reset();
              }}
            />
          ) : (
            <form onSubmit={onSubmit} noValidate className="space-y-5" aria-labelledby="report-form-title" data-testid="report-form">
              <h2 id="report-form-title" className="sr-only">
                {t('title')}
              </h2>
              <div className="space-y-1">
                <Label htmlFor="category">{t('form.category')}</Label>
                <Select id="category" {...register('category')} aria-invalid={!!errors.category} aria-describedby={errors.category ? 'category-err' : undefined} defaultValue="">
                  <option value="" disabled>
                    —
                  </option>
                  {REPORT_CATEGORIES.map((c) => (
                    <option key={c} value={c}>
                      {t(`form.categories.${c}`)}
                    </option>
                  ))}
                </Select>
                <FieldError id="category-err">{errors.category?.message}</FieldError>
              </div>

              <fieldset className="space-y-2 rounded-lg border border-border p-4">
                <legend className="px-1 text-sm font-semibold">{t('form.location')}</legend>
                <p className="text-sm text-muted-foreground">{t('form.locationHelp')}</p>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <Label htmlFor="lat">{t('form.lat')}</Label>
                    <Input id="lat" inputMode="decimal" {...register('lat')} aria-invalid={!!errors.lat} aria-describedby={errors.lat ? 'lat-err' : undefined} placeholder="45.5048" />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="lon">{t('form.lon')}</Label>
                    <Input id="lon" inputMode="decimal" {...register('lon')} aria-invalid={!!errors.lon} aria-describedby={errors.lon ? 'lon-err' : undefined} placeholder="-73.5772" />
                  </div>
                </div>
                <FieldError id="lat-err">{errors.lat?.message}</FieldError>
                <FieldError id="lon-err">{!errors.lat ? errors.lon?.message : undefined}</FieldError>
                <Button variant="outline" size="sm" onClick={() => void fillFromLocation()} disabled={geo === 'locating'}>
                  <LocateFixed aria-hidden="true" />
                  {geo === 'locating' ? t('form.locating') : t('form.useLocation')}
                </Button>
                {(geo === 'denied' || geo === 'unavailable' || geo === 'unsupported') && (
                  <p role="alert" className="text-sm text-danger">
                    {geo === 'denied' ? t('form.geoDenied') : t('form.geoUnavailable')}
                  </p>
                )}
              </fieldset>

              <div className="flex items-start gap-2">
                <input
                  id="consent"
                  type="checkbox"
                  className="mt-1 size-5"
                  {...register('consent')}
                  aria-invalid={!!errors.consent}
                  aria-describedby={`consent-help${errors.consent ? ' consent-err' : ''}`}
                />
                <div className="space-y-1">
                  <Label htmlFor="consent">{t('form.consent')}</Label>
                  <p id="consent-help" className="text-xs text-muted-foreground">
                    {t('form.consentHelp')}
                  </p>
                  <FieldError id="consent-err">{errors.consent?.message}</FieldError>
                </div>
              </div>

              <div className="space-y-1">
                <Label htmlFor="description">{t('form.description')}</Label>
                <Textarea
                  id="description"
                  maxLength={MAX_DESCRIPTION}
                  {...register('description')}
                  aria-invalid={!!errors.description}
                  aria-describedby="description-count"
                />
                <p id="description-count" className="text-xs text-muted-foreground" aria-live="polite">
                  {t('form.counter', { count: desc.length })}
                </p>
                <FieldError id="description-err">{errors.description?.message}</FieldError>
              </div>

              {rateLimited && (
                <Alert variant="warning" role="alert" data-testid="rate-limited">
                  <span>
                    {err.retryAfterS ? t('rateLimited', { minutes: Math.ceil(err.retryAfterS / 60) }) : t('rateLimitedNoTime')}
                  </span>
                </Alert>
              )}
              {create.isError && !rateLimited && (
                <Alert variant="error" role="alert">
                  <span>{isApiError(err) ? t(`errors:codes.${err.code}`) : t('errors:generic')}</span>
                </Alert>
              )}

              <Button type="submit" size="lg" disabled={create.isPending} data-testid="report-submit">
                {create.isPending ? t('form.submitting') : t('form.submit')}
              </Button>
            </form>
          )}
        </div>

        <aside className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle as="h2">{t('status.title')}</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-2 text-sm">
                {statuses.map((s) => (
                  <li key={s}>{t(`status.${s}`)}</li>
                ))}
              </ul>
              <div className="mt-3">
                <EvidenceBadge state="unverified_report" withDescription />
              </div>
            </CardContent>
          </Card>
          <Alert variant="info">
            <AlertTitle className="sr-only">{t('receipt.expires')}</AlertTitle>
            <span>{t('expiry')}</span>
          </Alert>
        </aside>
      </div>
    </>
  );
}
