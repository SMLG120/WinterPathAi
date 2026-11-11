import { useTranslation } from 'react-i18next';
import { EvidenceBadge } from '@/components/evidence/EvidenceBadge';
import type { HazardCoverage } from './hazardCoverage';

/**
 * Says plainly that closures / 311 reports are missing or unchecked. `context` picks the
 * consequence: the overlay list (an empty list isn't "none") or the routes (not avoided).
 */
export function HazardSourceNotice({ coverage, context }: { coverage: HazardCoverage; context: 'overlay' | 'route' }) {
  const { t } = useTranslation('plan');
  if (coverage.state === 'complete') return null;
  const detail =
    coverage.state === 'partial'
      ? coverage.gaps.map((g) => t('hazardSources.item', { name: g.name, status: t(`hazardSources.status.${g.status}`) })).join(' · ')
      : t('hazardSources.unchecked');
  return (
    <div className="space-y-1 rounded-md border border-border bg-muted p-3 text-sm" data-testid={`hazard-sources-${context}`} data-state={coverage.state}>
      <EvidenceBadge state="unknown" />
      <p>{t(`hazardSources.${context}`)}</p>
      <p>{detail}</p>
    </div>
  );
}
