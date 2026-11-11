import { useTranslation } from 'react-i18next';
import { USE_MOCKS } from '@/lib/env';
import { cn } from '@/lib/utils';

/** Shown on every mock-backed view. Renders nothing when talking to the real API. */
export function DemoBadge({ className }: { className?: string }) {
  const { t } = useTranslation('common');
  if (!USE_MOCKS) return null;
  return (
    <span
      data-testid="demo-badge"
      className={cn(
        'simulated-stripes inline-flex w-fit items-center gap-1 rounded-full border border-navy px-2 py-0.5 text-xs font-bold',
        className,
      )}
    >
      <span aria-hidden="true">!</span>
      {t('demo.badge')}
    </span>
  );
}
