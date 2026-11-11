import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ArrowRight, Footprints, GitCompare, ListChecks, ShieldCheck } from 'lucide-react';
import { HeroVisual } from '@/components/hero/HeroVisual';
import { Section } from '@/components/layout/Section';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { EvidenceBadge, SimulatedBanner } from '@/components/evidence/EvidenceBadge';
import { useLocalizedPath } from '@/lib/i18n-routing';
import { useDocumentTitle } from '@/lib/useDocumentTitle';
import { EVIDENCE_STATES } from '@/api/types';

type Item = { title: string; body: string };
type Faq = { q: string; a: string };

export default function Landing() {
  const { t } = useTranslation(['landing', 'common', 'plan']);
  const lp = useLocalizedPath();
  useDocumentTitle();
  const value = t('value.items', { returnObjects: true }) as Item[];
  const steps = t('how.steps', { returnObjects: true }) as Item[];
  const partners = t('partners.items', { returnObjects: true }) as Item[];
  const faq = t('faq.items', { returnObjects: true }) as Faq[];
  const privacy = t('privacy.points', { returnObjects: true }) as string[];
  const valueIcons = [GitCompare, ShieldCheck, ListChecks];

  return (
    <>
      {/* Hero */}
      <section aria-labelledby="hero-title" className="bg-navy text-ice">
        <div className="mx-auto grid max-w-7xl items-center gap-8 px-4 py-12 lg:grid-cols-[1.05fr_1fr] lg:py-20">
          <div>
            <p className="text-sm font-medium uppercase tracking-wider text-frost">{t('hero.eyebrow')}</p>
            <h1 id="hero-title" className="mt-3 font-serif text-4xl font-semibold leading-tight sm:text-5xl">
              {t('hero.title')}
            </h1>
            <p className="mt-5 max-w-xl text-lg text-ice/85">{t('hero.subtitle')}</p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Button asChild size="lg" className="bg-frost text-navy hover:bg-frost/90">
                <Link to={lp('/plan')} data-testid="hero-cta">
                  <Footprints aria-hidden="true" />
                  {t('hero.cta')}
                </Link>
              </Button>
              <Button asChild size="lg" variant="ghost" className="text-ice hover:bg-ice/10">
                <Link to={lp('/how-it-works')}>
                  {t('hero.secondary')}
                  <ArrowRight aria-hidden="true" />
                </Link>
              </Button>
            </div>
          </div>
          <HeroVisual className="aspect-[16/10] w-full" />
        </div>
      </section>

      {/* Value proposition */}
      <Section id="value" title={t('value.title')}>
        <ul className="grid gap-5 md:grid-cols-3">
          {value.map((v, i) => {
            const Icon = valueIcons[i] ?? ShieldCheck;
            return (
              <li key={v.title}>
                <Card className="h-full">
                  <CardHeader>
                    <Icon className="size-6 text-accent-text" aria-hidden="true" />
                    <CardTitle as="h3">{v.title}</CardTitle>
                  </CardHeader>
                  <CardContent className="text-muted-foreground">{v.body}</CardContent>
                </Card>
              </li>
            );
          })}
        </ul>
        <div className="mt-8 flex flex-wrap gap-2" aria-label={t('common:evidence.label')}>
          {EVIDENCE_STATES.map((s) => (
            <EvidenceBadge key={s} state={s} />
          ))}
        </div>
      </Section>

      {/* Product preview (illustration) */}
      <Section id="preview" title={t('preview.title')} intro={t('preview.body')} className="pt-0">
        <figure className="rounded-2xl border border-border bg-card p-4 shadow-sm sm:p-6">
          <SimulatedBanner>{t('preview.label')}</SimulatedBanner>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            {[
              { name: t('preview.shortest'), d: '1.4 km', m: '18 min', u: '40 %', color: 'bg-slate-brand' },
              { name: t('preview.winterAware'), d: '1.6 km', m: '21 min', u: '25 %', color: 'bg-teal' },
            ].map((r) => (
              <div key={r.name} className="rounded-lg border border-border p-4">
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2 font-semibold">
                    <span aria-hidden="true" className={`inline-block h-1.5 w-6 rounded ${r.color}`} />
                    {r.name}
                  </span>
                  <EvidenceBadge state="simulated" />
                </div>
                <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
                  <div>
                    <dt className="text-muted-foreground">{t('plan:results.distance')}</dt>
                    <dd className="font-semibold">{r.d}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">{t('plan:results.duration')}</dt>
                    <dd className="font-semibold">{r.m}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">{t('preview.unknownShare')}</dt>
                    <dd className="font-semibold">{r.u}</dd>
                  </div>
                </dl>
              </div>
            ))}
          </div>
        </figure>
      </Section>

      {/* How it works */}
      <Section id="how" title={t('how.title')} className="pt-0">
        <ol className="grid gap-5 md:grid-cols-3">
          {steps.map((s, i) => (
            <li key={s.title} className="rounded-lg border border-border bg-card p-5">
              <span className="inline-flex size-8 items-center justify-center rounded-full bg-primary font-semibold text-primary-foreground" aria-hidden="true">
                {i + 1}
              </span>
              <h3 className="mt-3 font-semibold">{s.title}</h3>
              <p className="mt-1 text-muted-foreground">{s.body}</p>
            </li>
          ))}
        </ol>
      </Section>

      {/* Privacy */}
      <Section id="privacy" title={t('privacy.title')} className="pt-0">
        <ul className="grid gap-3">
          {privacy.map((p) => (
            <li key={p} className="flex gap-3 rounded-lg border border-border bg-card p-4">
              <ShieldCheck className="mt-0.5 size-5 shrink-0 text-accent-text" aria-hidden="true" />
              <span>{p}</span>
            </li>
          ))}
        </ul>
      </Section>

      {/* Partner use cases */}
      <Section id="partners" title={t('partners.title')} intro={t('partners.intro')} className="pt-0">
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {partners.map((p) => (
            <li key={p.title} className="rounded-lg border border-border bg-card p-5">
              <h3 className="font-semibold">{p.title}</h3>
              <p className="mt-1 text-sm text-muted-foreground">{p.body}</p>
            </li>
          ))}
        </ul>
        <Button asChild variant="outline" className="mt-6">
          <Link to={lp('/pilot')}>
            {t('partners.cta')}
            <ArrowRight aria-hidden="true" />
          </Link>
        </Button>
      </Section>

      {/* FAQ */}
      <Section id="faq" title={t('faq.title')} className="pt-0">
        <div className="divide-y divide-border rounded-lg border border-border bg-card">
          {faq.map((f) => (
            <details key={f.q} className="group p-4">
              <summary className="cursor-pointer list-none font-medium marker:hidden">
                <span className="flex items-center justify-between gap-4">
                  {f.q}
                  <span aria-hidden="true" className="transition-transform group-open:rotate-45">
                    +
                  </span>
                </span>
              </summary>
              <p className="mt-2 text-muted-foreground">{f.a}</p>
            </details>
          ))}
        </div>
      </Section>

      {/* CTA band */}
      <section aria-labelledby="cta-title" className="bg-navy text-ice">
        <div className="mx-auto flex max-w-6xl flex-col items-start gap-4 px-4 py-12 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 id="cta-title" className="font-serif text-2xl font-semibold">
              {t('ctaBand.title')}
            </h2>
            <p className="text-ice/85">{t('ctaBand.body')}</p>
          </div>
          <Button asChild size="lg" className="bg-frost text-navy hover:bg-frost/90">
            <Link to={lp('/plan')}>{t('ctaBand.cta')}</Link>
          </Button>
        </div>
      </section>
    </>
  );
}
