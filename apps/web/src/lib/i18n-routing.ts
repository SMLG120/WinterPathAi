import { useParams } from 'react-router';
import { isLang, type Lang } from '@/i18n';

export function useLang(): Lang {
  const { lang } = useParams();
  return isLang(lang) ? lang : 'en';
}

/** Build a localised path: lp('/plan') → '/fr/plan'. */
export function useLocalizedPath() {
  const lang = useLang();
  return (path: string) => `/${lang}${path === '/' ? '' : path}`;
}

/** Swap the language prefix of a pathname, preserving the rest of the route. */
export function switchLangPath(pathname: string, to: Lang): string {
  const parts = pathname.split('/');
  if (isLang(parts[1])) parts[1] = to;
  else parts.splice(1, 0, to);
  const p = parts.join('/');
  return p.endsWith('/') && p.length > 1 ? p.slice(0, -1) : p;
}
