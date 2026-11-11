import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useTranslation } from 'react-i18next';
import { BarChart3, Building2, CheckCircle2, GraduationCap, Landmark, School } from 'lucide-react';
import { useCreatePilotRequest } from '@/api/queries';
import { isApiError } from '@/api/client';
import { DemoBadge } from '@/components/evidence/DemoBadge';
import { PageHeader, Section } from '@/components/layout/Section';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { FieldError, Input, Label, Select, Textarea } from '@/components/ui/input';
import { PILOT_SEGMENTS, pilotSchema, toPilotRequest, type PilotFormValues } from '@/features/pilotSchema';
import { WritesDisabled } from '@/features/WritesDisabled';
import { PUBLIC_WRITES } from '@/lib/env';
import { useLang } from '@/lib/i18n-routing';
import { useDocumentTitle } from '@/lib/useDocumentTitle';

type Item = { title: string; body: string };
const ICONS = [GraduationCap, School, Landmark, Building2];

export default function Pilot() {
  const { t } = useTranslation(['pilot', 'errors']);
  const lang = useLang();
  useDocumentTitle(t('title'));
  const segments = t('segments.items', { returnObjects: true }) as Item[];
  const includes = t('includes.items', { returnObjects: true }) as string[];
  const send = useCreatePilotRequest();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<PilotFormValues>({
    resolver: zodResolver(pilotSchema(t)),
    defaultValues: { organization: '', contact_name: '', contact_email: '', segment: undefined, message: '', consent: false },
  });
  const onSubmit = handleSubmit((v) => send.mutate(toPilotRequest(v, lang)));
  const err = (id: string) => (e: { message?: string } | undefined) => ({
    'aria-invalid': !!e,
    'aria-describedby': e ? `${id}-err` : undefined,
  });

  return (
    <>
      <PageHeader title={t('title')} intro={t('intro')} />

      <Section id="segments" title={t('segments.title')}>
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {segments.map((s, i) => {
            const Icon = ICONS[i] ?? Building2;
            return (
              <li key={s.title} className="rounded-lg border border-border bg-card p-5">
                <Icon className="size-6 text-accent-text" aria-hidden="true" />
                <h3 className="mt-2 font-semibold">{s.title}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{s.body}</p>
              </li>
            );
          })}
        </ul>
      </Section>

      <div className="mx-auto grid max-w-6xl gap-6 px-4 pb-14 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>{t('includes.title')}</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {includes.map((x) => (
                <li key={x} className="flex gap-2">
                  <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-accent-text" aria-hidden="true" />
                  {x}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BarChart3 className="size-5 text-accent-text" aria-hidden="true" />
              {t('analytics.title')}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p>{t('analytics.body')}</p>
            <p className="text-sm text-muted-foreground">{t('honesty')}</p>
          </CardContent>
        </Card>
      </div>

      <Section id="request" title={t('form.title')} className="pt-0">
        <div className="max-w-2xl">
          <DemoBadge className="mb-4" />
          {!PUBLIC_WRITES || (isApiError(send.error) && send.error.code === 'WRITES_DISABLED') ? (
            <WritesDisabled form="pilot" />
          ) : send.isSuccess ? (
            <Alert variant="success" role="status" data-testid="pilot-success">
              <CheckCircle2 aria-hidden="true" />
              <span>{t('form.success')}</span>
            </Alert>
          ) : (
            <form onSubmit={onSubmit} noValidate className="space-y-4" data-testid="pilot-form">
              <div className="space-y-1">
                <Label htmlFor="organization">{t('form.organization')}</Label>
                <Input id="organization" autoComplete="organization" {...register('organization')} {...err('organization')(errors.organization)} />
                <FieldError id="organization-err">{errors.organization?.message}</FieldError>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1">
                  <Label htmlFor="contact_name">{t('form.contactName')}</Label>
                  <Input id="contact_name" autoComplete="name" {...register('contact_name')} />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="contact_email">{t('form.email')}</Label>
                  <Input id="contact_email" type="email" autoComplete="email" {...register('contact_email')} {...err('contact_email')(errors.contact_email)} />
                  <FieldError id="contact_email-err">{errors.contact_email?.message}</FieldError>
                </div>
              </div>
              <div className="space-y-1">
                <Label htmlFor="segment">{t('form.segment')}</Label>
                <Select id="segment" defaultValue="" {...register('segment')} {...err('segment')(errors.segment)}>
                  <option value="" disabled>
                    —
                  </option>
                  {PILOT_SEGMENTS.map((s) => (
                    <option key={s} value={s}>
                      {t(`form.segments.${s}`)}
                    </option>
                  ))}
                </Select>
                <FieldError id="segment-err">{errors.segment?.message}</FieldError>
              </div>
              <div className="space-y-1">
                <Label htmlFor="message">{t('form.message')}</Label>
                <Textarea id="message" maxLength={1000} {...register('message')} />
              </div>
              <div className="flex items-start gap-2">
                <input id="pilot-consent" type="checkbox" className="mt-1 size-5" {...register('consent')} {...err('pilot-consent')(errors.consent)} />
                <div>
                  <Label htmlFor="pilot-consent">{t('form.consent')}</Label>
                  <FieldError id="pilot-consent-err">{errors.consent?.message}</FieldError>
                </div>
              </div>
              {send.isError && (
                <Alert variant="error" role="alert">
                  <span>{isApiError(send.error) ? t(`errors:codes.${send.error.code}`) : t('errors:generic')}</span>
                </Alert>
              )}
              <Button type="submit" size="lg" disabled={send.isPending}>
                {send.isPending ? t('form.submitting') : t('form.submit')}
              </Button>
            </form>
          )}
        </div>
      </Section>
    </>
  );
}
