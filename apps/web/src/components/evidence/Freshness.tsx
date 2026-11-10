import { useTranslation } from 'react-i18next';
import { formatDateTime, isStale } from '@/lib/format';
import { cn } from '@/lib/utils';

/** Last-refresh timestamp, with an amber "Stale" badge past the threshold. */
export function Freshness({ at, className, label }: { at: string | null | undefined; className?: string; label?: string }) {
  const { t, i18n } = useTranslation('common');
  const formatted = formatDateTime(at, i18n.language);
  const stale = isStale(at);
  return (
    <span className={cn('inline-flex flex-wrap items-center gap-2 text-xs text-muted-foreground', className)}>
      <span>
        {label ? `${label}: ` : ''}
        {formatted ? t('states.updated', { time: formatted }) : t('states.never')}
      </span>
      {stale && (
        <span
          className="inline-flex items-center gap-1 rounded-full border border-amber-brand bg-amber-brand px-2 py-0.5 font-semibold text-navy"
          title={t('states.staleDesc')}
        >
          <span aria-hidden="true">⏱</span>
          {t('states.stale')}
          <span className="sr-only"> — {t('states.staleDesc')}</span>
        </span>
      )}
    </span>
  );
}
