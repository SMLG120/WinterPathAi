import { STALE_AFTER_MS } from './env';

export function formatDistance(m: number, locale: string): string {
  if (m < 1000) return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(m)} m`;
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(m / 1000)} km`;
}

export function formatDuration(s: number, locale: string): string {
  const min = Math.max(1, Math.round(s / 60));
  return `${new Intl.NumberFormat(locale).format(min)} min`;
}

export function formatPercent(x: number, locale: string): string {
  return new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 }).format(x);
}

export function formatDateTime(iso: string | null | undefined, locale: string): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return new Intl.DateTimeFormat(locale === 'fr' ? 'fr-CA' : 'en-CA', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'America/Toronto',
  }).format(d);
}

export function isStale(iso: string | null | undefined, now = Date.now(), thresholdMs = STALE_AFTER_MS): boolean {
  if (!iso) return false;
  const t = new Date(iso).getTime();
  return Number.isFinite(t) && now - t > thresholdMs;
}
