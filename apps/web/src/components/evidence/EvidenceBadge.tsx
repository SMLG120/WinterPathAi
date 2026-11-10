import { useTranslation } from 'react-i18next';
import type { EvidenceState } from '@/api/types';
import { cn } from '@/lib/utils';
import { EVIDENCE_GLYPH } from './glyphs';


const STYLE: Record<EvidenceState, string> = {
  confirmed: 'border-teal bg-teal/10 text-foreground',
  unverified_report: 'border-amber-brand bg-amber-brand/15 text-foreground',
  model_estimate: 'border-[#5b6bbf] bg-[#5b6bbf]/10 text-foreground',
  unknown: 'border-dashed border-muted-foreground bg-transparent text-foreground',
  simulated: 'simulated-stripes border-navy font-bold tracking-wide',
};

export function EvidenceBadge({
  state,
  className,
  withDescription = false,
}: {
  state: EvidenceState;
  className?: string;
  withDescription?: boolean;
}) {
  const { t } = useTranslation('common');
  const label = t(`evidence.${state}`);
  const desc = t(`evidence.desc.${state}`);
  return (
    <span className={cn('inline-flex flex-col gap-1', className)}>
      <span
        className={cn('inline-flex w-fit items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium', STYLE[state])}
        data-evidence={state}
        title={withDescription ? undefined : desc}
      >
        <span aria-hidden="true" className="font-bold leading-none">
          {EVIDENCE_GLYPH[state]}
        </span>
        <span>
          <span className="sr-only">{t('evidence.label')}: </span>
          {label}
        </span>
      </span>
      {withDescription && <span className="text-sm text-muted-foreground">{desc}</span>}
    </span>
  );
}

/** Conspicuous banner for any view containing simulated data. */
export function SimulatedBanner({ children, className }: { children?: React.ReactNode; className?: string }) {
  const { t } = useTranslation('common');
  return (
    <div
      role="note"
      data-evidence="simulated"
      className={cn('simulated-stripes flex items-center gap-2 rounded-md border border-navy px-3 py-2 text-sm font-semibold', className)}
    >
      <span aria-hidden="true">!</span>
      <span>
        {t('evidence.simulated')}
        {children ? <> — {children}</> : <> — {t('evidence.desc.simulated')}</>}
      </span>
    </div>
  );
}
