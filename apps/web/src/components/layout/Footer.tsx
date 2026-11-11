import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Logo } from './Logo';
import { useLocalizedPath } from '@/lib/i18n-routing';

const ext = 'underline underline-offset-2 hover:no-underline';

export function Footer() {
  const { t } = useTranslation('common');
  const lp = useLocalizedPath();
  return (
    <footer className="border-t border-border bg-card">
      <div className="mx-auto grid max-w-7xl gap-8 px-4 py-10 md:grid-cols-[1fr_2fr]">
        <div className="space-y-3">
          <div className="flex items-center gap-2 font-semibold">
            <Logo className="size-7" />
            {t('brand')}
          </div>
          <p className="text-sm text-muted-foreground">{t('tagline')}</p>
          <ul className="space-y-1 text-sm">
            <li>
              <Link className={ext} to={lp('/how-it-works') + '#privacy'}>
                {t('footer.privacy')}
              </Link>
            </li>
            <li>
              <Link className={ext} to={lp('/how-it-works') + '#sources'}>
                {t('footer.sources')}
              </Link>
            </li>
            <li>
              <Link className={ext} to={lp('/pilot')}>
                {t('footer.pilot')}
              </Link>
            </li>
          </ul>
        </div>
        <div className="space-y-3 text-sm">
          <h2 className="font-semibold">{t('footer.attributionTitle')}</h2>
          <ul className="space-y-1.5 text-muted-foreground">
            <li>
              <a className={ext} href="https://www.openstreetmap.org/copyright" rel="noopener noreferrer" target="_blank">
                {t('footer.osm')}
              </a>
              . {t('footer.osmLicence')}
            </li>
            <li>
              <a className={ext} href="https://openfreemap.org/" rel="noopener noreferrer" target="_blank">
                {t('footer.openfreemap')}
              </a>
            </li>
            <li>
              <a className={ext} href="https://donnees.montreal.ca/" rel="noopener noreferrer" target="_blank">
                {t('footer.vdm')}
              </a>
            </li>
            <li>
              <a
                className={ext}
                href="https://eccc-msc.github.io/open-data/licence/readme_en/"
                rel="noopener noreferrer"
                target="_blank"
              >
                {t('footer.eccc')}
              </a>
            </li>
          </ul>
          <p className="text-muted-foreground">{t('footer.disclaimer')}</p>
          <p className="text-xs text-muted-foreground">{t('footer.independent')}</p>
        </div>
      </div>
    </footer>
  );
}
