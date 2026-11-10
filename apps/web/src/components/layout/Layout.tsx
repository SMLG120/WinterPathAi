import { Suspense, useEffect } from 'react';
import { Navigate, Outlet, useLocation, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Header } from './Header';
import { Footer } from './Footer';
import { useApplyTheme } from '@/lib/useApplyTheme';
import { ErrorBoundary } from './ErrorBoundary';
import { USE_MOCKS } from '@/lib/env';
import { isLang } from '@/i18n';
import { Skeleton } from '@/components/ui/skeleton';

export function PageFallback() {
  return (
    <div className="mx-auto max-w-5xl space-y-4 px-4 py-12" role="status" aria-live="polite">
      <Skeleton className="h-10 w-1/2" />
      <Skeleton className="h-5 w-3/4" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

function DemoBanner() {
  const { t } = useTranslation('common');
  if (!USE_MOCKS) return null;
  return (
    <div role="note" className="simulated-stripes border-b border-navy px-4 py-1.5 text-center text-sm font-semibold" data-testid="demo-banner">
      <span aria-hidden="true">! </span>
      {t('demo.banner')}
    </div>
  );
}

/** Language-prefixed shell. Syncs i18next + <html lang> with the URL. */
export function Layout({ fullBleed = false }: { fullBleed?: boolean }) {
  const { lang } = useParams();
  const { i18n, t } = useTranslation('common');
  const { pathname } = useLocation();
  useApplyTheme();

  const valid = isLang(lang);
  if (valid && i18n.language !== lang) void i18n.changeLanguage(lang);
  useEffect(() => {
    if (valid) document.documentElement.lang = lang === 'fr' ? 'fr-CA' : 'en-CA';
  }, [lang, valid]);
  useEffect(() => {
    if (!pathname.includes('#')) window.scrollTo?.(0, 0);
  }, [pathname]);

  if (!valid) return <Navigate to={`/en${pathname}`} replace />;

  return (
    <div className={fullBleed ? 'flex h-dvh flex-col' : 'flex min-h-dvh flex-col'}>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-foreground"
      >
        {t('nav.skip')}
      </a>
      <Header />
      <DemoBanner />
      <main id="main" tabIndex={-1} className={fullBleed ? 'flex min-h-0 flex-1 flex-col' : 'flex-1'}>
        <ErrorBoundary>
          <Suspense fallback={<PageFallback />}>
            <Outlet />
          </Suspense>
        </ErrorBoundary>
      </main>
      {!fullBleed && <Footer />}
    </div>
  );
}
