import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import enCommon from './locales/en/common.json';
import enLanding from './locales/en/landing.json';
import enPlan from './locales/en/plan.json';
import enWinter from './locales/en/winter.json';
import enReports from './locales/en/reports.json';
import enHow from './locales/en/how.json';
import enPilot from './locales/en/pilot.json';
import enErrors from './locales/en/errors.json';
import frCommon from './locales/fr/common.json';
import frLanding from './locales/fr/landing.json';
import frPlan from './locales/fr/plan.json';
import frWinter from './locales/fr/winter.json';
import frReports from './locales/fr/reports.json';
import frHow from './locales/fr/how.json';
import frPilot from './locales/fr/pilot.json';
import frErrors from './locales/fr/errors.json';

export const LANGS = ['en', 'fr'] as const;
export type Lang = (typeof LANGS)[number];
export const NAMESPACES = ['common', 'landing', 'plan', 'winter', 'reports', 'how', 'pilot', 'errors'] as const;

export const resources = {
  en: {
    common: enCommon,
    landing: enLanding,
    plan: enPlan,
    winter: enWinter,
    reports: enReports,
    how: enHow,
    pilot: enPilot,
    errors: enErrors,
  },
  fr: {
    common: frCommon,
    landing: frLanding,
    plan: frPlan,
    winter: frWinter,
    reports: frReports,
    how: frHow,
    pilot: frPilot,
    errors: frErrors,
  },
} as const;

export function isLang(x: string | undefined): x is Lang {
  return x === 'en' || x === 'fr';
}

/** Preferred language from the browser, falling back to English. Not persisted beyond the URL. */
export function detectLang(): Lang {
  const langs = typeof navigator !== 'undefined' ? navigator.languages ?? [navigator.language] : [];
  for (const l of langs) {
    const p = l?.slice(0, 2).toLowerCase();
    if (isLang(p)) return p;
  }
  return 'en';
}

void i18n.use(initReactI18next).init({
  resources,
  lng: 'en',
  fallbackLng: false,
  supportedLngs: LANGS,
  ns: NAMESPACES,
  defaultNS: 'common',
  interpolation: { escapeValue: false },
  returnNull: false,
  saveMissing: false,
});

export default i18n;
