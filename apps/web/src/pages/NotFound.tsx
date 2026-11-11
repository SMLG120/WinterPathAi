import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { useLocalizedPath } from '@/lib/i18n-routing';
import { useDocumentTitle } from '@/lib/useDocumentTitle';

export default function NotFound() {
  const { t } = useTranslation('common');
  const lp = useLocalizedPath();
  useDocumentTitle(t('notFound.title'));
  return (
    <div className="mx-auto max-w-xl px-4 py-20 text-center">
      <h1 className="font-serif text-3xl font-semibold">{t('notFound.title')}</h1>
      <p className="mt-3 text-muted-foreground">{t('notFound.body')}</p>
      <Button asChild className="mt-6">
        <Link to={lp('/')}>{t('notFound.home')}</Link>
      </Button>
    </div>
  );
}
