import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';

export function useDocumentTitle(title?: string) {
  const { t } = useTranslation('common');
  useEffect(() => {
    document.title = title ? `${title} · ${t('brand')}` : `${t('brand')} — ${t('tagline')}`;
  }, [title, t]);
}
