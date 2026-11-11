import { useEffect, useState } from 'react';
import { Link, NavLink, useLocation } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Menu, X } from 'lucide-react';
import { Logo } from './Logo';
import { LanguageSwitch } from './LanguageSwitch';
import { ThemeToggle } from './ThemeToggle';
import { useLocalizedPath } from '@/lib/i18n-routing';
import { cn } from '@/lib/utils';

export const NAV = [
  { to: '/plan', key: 'plan' },
  { to: '/winter', key: 'winter' },
  { to: '/reports', key: 'reports' },
  { to: '/how-it-works', key: 'how' },
  { to: '/pilot', key: 'pilot' },
] as const;

export function Header() {
  const { t } = useTranslation('common');
  const lp = useLocalizedPath();
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => setOpen(false), [pathname]);

  const link = ({ isActive }: { isActive: boolean }) =>
    cn(
      'inline-flex min-h-10 items-center rounded-md px-3 text-sm font-medium hover:bg-muted',
      isActive ? 'text-accent-text underline underline-offset-8 decoration-2' : 'text-foreground',
    );

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
      <div className="mx-auto flex h-16 max-w-7xl items-center gap-3 px-4">
        <Link to={lp('/')} className="flex items-center gap-2 rounded-md font-semibold">
          <Logo className="size-8" />
          <span>{t('brand')}</span>
        </Link>
        <nav aria-label={t('nav.label')} className="ml-6 hidden lg:block">
          <ul className="flex items-center gap-1">
            {NAV.map((n) => (
              <li key={n.key}>
                <NavLink to={lp(n.to)} className={link}>
                  {t(`nav.${n.key}`)}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <LanguageSwitch />
          <ThemeToggle className="hidden sm:inline-flex" />
          <button
            type="button"
            className="inline-flex size-10 items-center justify-center rounded-md hover:bg-muted lg:hidden"
            aria-expanded={open}
            aria-controls="mobile-nav"
            onClick={() => setOpen((o) => !o)}
          >
            {open ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
            <span className="sr-only">{open ? t('nav.closeMenu') : t('nav.menu')}</span>
          </button>
        </div>
      </div>
      {open && (
        <nav id="mobile-nav" aria-label={t('nav.label')} className="border-t border-border px-4 pb-4 lg:hidden">
          <ul className="flex flex-col gap-1 pt-2">
            {NAV.map((n) => (
              <li key={n.key}>
                <NavLink to={lp(n.to)} className={link}>
                  {t(`nav.${n.key}`)}
                </NavLink>
              </li>
            ))}
          </ul>
          <ThemeToggle className="mt-3 sm:hidden" />
        </nav>
      )}
    </header>
  );
}
