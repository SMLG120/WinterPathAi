import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { History, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { formatLonLat } from '@/lib/geo';
import { usePlannerStore } from '@/stores/planner';
import { useRecentDestinations } from '@/stores/recentDestinations';

/** Opt-in list of recent destinations kept on this device only (see stores/recentDestinations.ts). */
export function RecentDestinations() {
  const { t, i18n } = useTranslation('plan');
  const id = useId();
  const { enabled, items, setEnabled, clear } = useRecentDestinations();
  const setPoint = usePlannerStore((s) => s.setPoint);
  const date = new Intl.DateTimeFormat(i18n.language === 'fr' ? 'fr-CA' : 'en-CA', { month: 'short', day: 'numeric' });

  return (
    <div className="space-y-2 rounded-lg border border-border p-3" data-testid="recent-destinations">
      <div className="flex items-start gap-2">
        <input
          id={`${id}-optin`}
          type="checkbox"
          className="mt-1 size-5 shrink-0 accent-[var(--primary)]"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
          aria-describedby={`${id}-desc`}
          data-testid="recent-optin"
        />
        <div>
          <label htmlFor={`${id}-optin`} className="text-sm font-medium">
            {t('recent.optIn')}
          </label>
          <p id={`${id}-desc`} className="text-xs text-muted-foreground">
            {t('recent.desc')}
          </p>
        </div>
      </div>
      {enabled && items.length > 0 && (
        <>
          <h3 className="flex items-center gap-1.5 text-sm font-semibold">
            <History className="size-4" aria-hidden="true" />
            {t('recent.title')}
          </h3>
          <ul className="space-y-1" data-testid="recent-list">
            {items.map((r) => (
              <li key={`${r.lon},${r.lat}`}>
                <Button variant="outline" size="sm" className="w-full justify-between" onClick={() => setPoint('destination', { lon: r.lon, lat: r.lat })}>
                  <span>{t('recent.use', { coords: formatLonLat(r, 4) })}</span>
                  <span className="text-muted-foreground">{date.format(r.at)}</span>
                </Button>
              </li>
            ))}
          </ul>
          <Button variant="ghost" size="sm" onClick={clear} data-testid="recent-clear">
            <Trash2 aria-hidden="true" />
            {t('recent.clear')}
          </Button>
        </>
      )}
    </div>
  );
}
