/** Short local time (Montréal) for status chips; the full date is in the panel's freshness lines. */
export function formatTime(ms: number, locale: string): string {
  return new Intl.DateTimeFormat(locale === 'fr' ? 'fr-CA' : 'en-CA', { timeStyle: 'short', timeZone: 'America/Toronto' }).format(new Date(ms));
}
