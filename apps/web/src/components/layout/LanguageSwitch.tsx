import { Link, useLocation } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useLang, switchLangPath } from '@/lib/i18n-routing';

export function LanguageSwitch() {
  const { t } = useTranslation('common');
  const lang = useLang();
  const { pathname, search, hash } = useLocation();
  const other = lang === 'en' ? 'fr' : 'en';
  return (
    <Link
      to={`${switchLangPath(pathname, other)}${search}${hash}`}
      hrefLang={other}
      lang={other}
      aria-label={t('lang.switchToLabel')}
      className="inline-flex min-h-10 items-center rounded-md px-3 text-sm font-medium hover:bg-muted"
      data-testid="lang-switch"
    >
      {t('lang.switchTo')}
    </Link>
  );
}
