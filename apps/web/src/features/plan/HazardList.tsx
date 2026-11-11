import { useTranslation } from 'react-i18next';
import type { HazardFeature } from '@/api/types';
import { EvidenceBadge } from '@/components/evidence/EvidenceBadge';
import { formatDateTime } from '@/lib/format';
import { HAZARD_STYLE } from './mapStyle';
import type { HazardCoverage } from './hazardCoverage';

/** Text alternative to the hazard overlay. */
export function HazardList({ hazards, coverage }: { hazards: HazardFeature[]; coverage: HazardCoverage }) {
  const { t, i18n } = useTranslation('plan');
  const fr = i18n.language === 'fr';
  // "None" only when every hazard source is loaded; otherwise HazardSourceNotice says what is missing.
  if (hazards.length === 0)
    return coverage.state === 'complete' ? <p className="text-sm text-muted-foreground">{t('overlays.none')}</p> : null;
  return (
    <ul className="space-y-2" data-testid="hazard-list">
      {hazards.map((h) => {
        const p = h.properties;
        const title = (fr ? p.title_fr : p.title_en) ?? p.title_en ?? p.title_fr ?? t(`hazard.kind.${p.kind}`);
        const blocks = p.blocks_passage === true ? 'true' : p.blocks_passage === false ? 'false' : 'null';
        const until = formatDateTime(p.valid_to ?? null, i18n.language);
        return (
          <li key={h.id} className="rounded-md border border-border p-2.5 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span aria-hidden="true" className="inline-flex size-5 items-center justify-center rounded-full text-[10px] text-white" style={{ background: HAZARD_STYLE[p.kind].color }}>
                {HAZARD_STYLE[p.kind].symbol}
              </span>
              <span className="font-medium">{t(`hazard.kind.${p.kind}`)}</span>
              <EvidenceBadge state={p.evidence.state} />
            </div>
            <p className="mt-1">{title}</p>
            <p className="mt-0.5 text-muted-foreground">
              {t(`hazard.blocks.${blocks}`)}
              {p.report_count != null && <> · {t('hazard.reportCount', { count: p.report_count })}</>}
              {until && <> · {until}</>}
            </p>
          </li>
        );
      })}
    </ul>
  );
}
