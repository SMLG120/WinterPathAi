import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { useBackendStore } from '@/stores/backend';

/** Shown while any API request is waiting for the free-tier backend to wake (cold start). */
export function BackendWaking() {
  const { t } = useTranslation('common');
  const waking = useBackendStore((s) => s.waking > 0);
  return (
    <div role="status" aria-live="polite" data-testid="backend-waking-region">
      {waking && (
        <div className="flex items-center justify-center gap-2 border-b border-amber-brand bg-amber-brand/15 px-4 py-2 text-center text-sm" data-testid="backend-waking">
          <Loader2 aria-hidden="true" className="size-4 shrink-0 animate-spin motion-reduce:animate-none" />
          <span>{t('backend.waking')}</span>
        </div>
      )}
    </div>
  );
}
