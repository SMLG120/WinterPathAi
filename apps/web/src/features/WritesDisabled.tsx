import { useTranslation } from 'react-i18next';
import { Info } from 'lucide-react';
import { Alert } from '@/components/ui/alert';

/** Replaces a write form in the read-only public demo (VITE_PUBLIC_WRITES=false or API 503 WRITES_DISABLED). */
export function WritesDisabled({ form }: { form: 'reports' | 'pilot' }) {
  const { t } = useTranslation('common');
  return (
    <Alert variant="info" data-testid="writes-disabled" data-form={form}>
      <Info aria-hidden="true" />
      <div>
        <h2 className="font-semibold">{t('writesDisabled.title')}</h2>
        <p className="mt-1">{t(`writesDisabled.${form}`)}</p>
      </div>
    </Alert>
  );
}
