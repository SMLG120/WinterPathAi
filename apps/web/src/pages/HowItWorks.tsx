import { useTranslation } from 'react-i18next';
import { useCoverage, useDataSources } from '@/api/queries';
import { EVIDENCE_STATES, type Coverage, type DataSource } from '@/api/types';
import { DataState } from '@/components/evidence/DataState';
import { DemoBadge } from '@/components/evidence/DemoBadge';
import { EvidenceBadge } from '@/components/evidence/EvidenceBadge';
import { Freshness } from '@/components/evidence/Freshness';
import { PageHeader, Section } from '@/components/layout/Section';
import { ConditionExplainer } from '@/features/ConditionExplainer';
import { ModelStatusCard } from '@/features/ModelStatusCard';
import { formatDateTime } from '@/lib/format';
import { useDocumentTitle } from '@/lib/useDocumentTitle';

const SECTIONS = ['sources', 'attribution', 'evidence', 'conditions', 'model', 'coverage', 'privacy', 'limitations'] as const;

function SourcesTable({ rows }: { rows: DataSource[] }) {
  const { t } = useTranslation('how');
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-[720px] text-left text-sm">
        <caption className="sr-only">{t('sources.title')}</caption>
        <thead className="bg-muted">
          <tr>
            {(['name', 'publisher', 'licence', 'commercial', 'status', 'lastSuccess'] as const).map((h) => (
              <th key={h} scope="col" className="px-3 py-2 font-semibold">
                {t(`sources.${h}`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((s) => (
            <tr key={s.id} className="align-top">
              <th scope="row" className="px-3 py-2 font-medium">
                <a href={s.url} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
                  {s.name}
                </a>
                <p className="mt-1 text-xs font-normal text-muted-foreground">{s.attribution}</p>
                {s.notes && <p className="mt-1 text-xs font-normal text-muted-foreground">{s.notes}</p>}
              </th>
              <td className="px-3 py-2">{s.publisher}</td>
              <td className="px-3 py-2">
                <a href={s.license_url} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
                  {s.license}
                </a>
              </td>
              <td className="px-3 py-2">{t(`sources.commercialUse.${s.commercial_use}`)}</td>
              <td className="px-3 py-2">{t(`sources.statusValue.${s.status}`)}</td>
              <td className="px-3 py-2">
                <Freshness at={s.last_success_at} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CoverageView({ c }: { c: Coverage }) {
  const { t, i18n } = useTranslation(['how', 'common']);
  const [w, s, e, n] = c.bbox as [number, number, number, number];
  const ring = (c.area.coordinates[0] ?? []) as [number, number][];
  // Equirectangular schematic scaled by cos(lat) — illustrative only.
  const k = Math.cos(((s + n) / 2) * (Math.PI / 180));
  const W = 300;
  const H = Math.max(80, Math.round((W * (n - s)) / ((e - w) * k)));
  const pts = ring.map(([x, y]) => `${(((x - w) / (e - w)) * W).toFixed(1)},${(((n - y) / (n - s)) * H).toFixed(1)}`).join(' ');
  const nf = new Intl.NumberFormat(i18n.language);
  return (
    <div className="grid gap-6 md:grid-cols-[320px_1fr]">
      <figure>
        <svg viewBox={`-10 -10 ${W + 20} ${H + 20}`} className="w-full rounded-lg border border-border bg-card" role="img" aria-label={`${t('coverage.pilot')}: ${c.pilot_name}`}>
          <rect x="-10" y="-10" width={W + 20} height={H + 20} className="hatch" fill="transparent" />
          <polygon points={pts} fill="var(--card)" stroke="var(--accent-text)" strokeWidth="3" />
          <text x={W / 2} y={H / 2} textAnchor="middle" fontSize="14" fill="currentColor">
            {c.pilot_name}
          </text>
        </svg>
        <figcaption className="mt-1 text-xs text-muted-foreground">{t('coverage.schematic')}</figcaption>
      </figure>
      <dl className="grid grid-cols-[auto_1fr] content-start gap-x-4 gap-y-2 text-sm">
        <dt className="text-muted-foreground">{t('coverage.pilot')}</dt>
        <dd className="font-medium">{c.pilot_name}</dd>
        <dt className="text-muted-foreground">{t('coverage.bbox')}</dt>
        <dd className="font-mono text-xs">{c.bbox.map((v) => v.toFixed(4)).join(', ')}</dd>
        <dt className="text-muted-foreground">{t('coverage.nodes')}</dt>
        <dd>{nf.format(c.graph.node_count)}</dd>
        <dt className="text-muted-foreground">{t('coverage.edges')}</dt>
        <dd>{nf.format(c.graph.edge_count)}</dd>
        <dt className="text-muted-foreground">{t('coverage.built')}</dt>
        <dd>{formatDateTime(c.graph.built_at, i18n.language) ?? t('common:states.never')}</dd>
        <dt className="text-muted-foreground">{t('coverage.snapshot')}</dt>
        <dd>{c.graph.osm_snapshot ?? t('common:states.notAvailable')}</dd>
        <dt className="text-muted-foreground">{t('coverage.gaps')}</dt>
        <dd>
          {c.known_gaps.length === 0 ? (
            t('coverage.noGaps')
          ) : (
            <ul className="list-disc space-y-1 pl-4">
              {c.known_gaps.map((g) => (
                <li key={g.description}>{g.description}</li>
              ))}
            </ul>
          )}
        </dd>
      </dl>
    </div>
  );
}

export default function HowItWorks() {
  const { t } = useTranslation(['how', 'common']);
  useDocumentTitle(t('title'));
  const sources = useDataSources();
  const coverage = useCoverage();
  const privacy = t('privacy.points', { returnObjects: true }) as string[];
  const limits = t('limitations.points', { returnObjects: true }) as string[];

  return (
    <>
      <PageHeader title={t('title')} intro={t('intro')}>
        <DemoBadge />
      </PageHeader>
      <nav aria-label={t('toc')} className="mx-auto max-w-6xl px-4 pt-8">
        <h2 className="text-sm font-semibold">{t('toc')}</h2>
        <ul className="mt-2 flex flex-wrap gap-2 text-sm">
          {SECTIONS.map((s) => (
            <li key={s}>
              <a href={`#${s}`} className="inline-flex min-h-8 items-center rounded-full border border-border px-3 hover:bg-muted">
                {t(`${s}.title`)}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <Section id="sources" title={t('sources.title')} intro={t('sources.intro')}>
        <DataState query={sources} isEmpty={(d) => d.length === 0}>
          {(rows) => <SourcesTable rows={rows} />}
        </DataState>
      </Section>

      <Section id="attribution" title={t('attribution.title')} intro={t('attribution.body')} className="pt-0">
        <ul className="space-y-1 text-sm">
          <li>
            <a className="underline" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">
              {t('common:footer.osm')}
            </a>{' '}
            — {t('common:footer.osmLicence')}
          </li>
          <li>{t('common:footer.openfreemap')}</li>
          <li>{t('common:footer.vdm')}</li>
          <li>{t('common:footer.eccc')}</li>
        </ul>
      </Section>

      <Section id="evidence" title={t('evidence.title')} intro={t('evidence.intro')} className="pt-0">
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" data-testid="evidence-legend">
          {EVIDENCE_STATES.map((s) => (
            <li key={s} className="rounded-lg border border-border bg-card p-4">
              <EvidenceBadge state={s} withDescription />
            </li>
          ))}
        </ul>
      </Section>

      <Section id="conditions" title={t('conditions.title')} intro={t('conditions.intro')} className="pt-0">
        <ConditionExplainer />
      </Section>

      <Section id="model" title={t('model.title')} intro={t('model.intro')} className="pt-0">
        <ModelStatusCard headingLevel="h3" />
      </Section>

      <Section id="coverage" title={t('coverage.title')} className="pt-0">
        <DataState query={coverage}>{(c) => <CoverageView c={c} />}</DataState>
      </Section>

      <Section id="privacy" title={t('privacy.title')} className="pt-0">
        <ul className="list-disc space-y-2 pl-5">
          {privacy.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
        <p className="mt-4 text-sm text-muted-foreground">{t('privacy.review')}</p>
      </Section>

      <Section id="limitations" title={t('limitations.title')} className="pt-0">
        <ul className="list-disc space-y-2 pl-5">
          {limits.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      </Section>
    </>
  );
}
