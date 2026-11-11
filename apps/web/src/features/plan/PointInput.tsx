import { useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Crosshair, X } from 'lucide-react';
import type { LonLat } from '@/api/types';
import { Button } from '@/components/ui/button';
import { FieldError, Input, Label } from '@/components/ui/input';
import { formatLonLat, isInPilot, isValidLonLat } from '@/lib/geo';
import { usePlannerStore, type PointKey } from '@/stores/planner';

/** One endpoint: current value, pick-on-map toggle, manual coordinate entry. */
export function PointInput({ which, extra }: { which: PointKey; extra?: React.ReactNode }) {
  const { t } = useTranslation('plan');
  const id = useId();
  const value = usePlannerStore((s) => s[which]);
  const picking = usePlannerStore((s) => s.picking);
  const setPoint = usePlannerStore((s) => s.setPoint);
  const setPicking = usePlannerStore((s) => s.setPicking);
  const [lat, setLat] = useState('');
  const [lon, setLon] = useState('');
  const [error, setError] = useState<string | null>(null);
  const name = t(`points.${which}`);

  useEffect(() => {
    if (value) {
      setLat(value.lat.toFixed(6));
      setLon(value.lon.toFixed(6));
      setError(null);
    }
  }, [value]);

  const apply = (e: React.FormEvent) => {
    e.preventDefault();
    const p: LonLat = { lat: Number.parseFloat(lat.replace(',', '.')), lon: Number.parseFloat(lon.replace(',', '.')) };
    if (!isValidLonLat(p) || lat.trim() === '' || lon.trim() === '') {
      setError(t('manual.invalid'));
      return;
    }
    setError(null);
    setPoint(which, p);
  };

  const outside = value && !isInPilot(value);

  return (
    <fieldset className="space-y-2 rounded-lg border border-border p-3" data-testid={`point-${which}`}>
      <legend className="px-1 text-sm font-semibold">
        <span
          aria-hidden="true"
          className={`mr-1.5 inline-flex size-5 items-center justify-center rounded-full text-xs text-white ${which === 'origin' ? 'bg-teal' : 'bg-navy dark:bg-slate-brand'}`}
        >
          {which === 'origin' ? 'A' : 'B'}
        </span>
        {name}
      </legend>
      <p className="text-sm" aria-live="polite" data-testid={`point-${which}-value`}>
        {value ? formatLonLat(value) : <span className="text-muted-foreground">{t('points.notSet')}</span>}
      </p>
      {outside && <p className="text-sm text-danger">{t('manual.outsideHint')}</p>}
      <div className="flex flex-wrap gap-2">
        <Button
          variant={picking === which ? 'default' : 'outline'}
          size="sm"
          aria-pressed={picking === which}
          onClick={() => setPicking(picking === which ? null : which)}
        >
          <Crosshair aria-hidden="true" />
          {t('points.setOnMap')}
        </Button>
        {extra}
        {value && (
          <Button variant="ghost" size="sm" onClick={() => setPoint(which, null)}>
            <X aria-hidden="true" />
            {t('points.clear')}
            <span className="sr-only"> — {name}</span>
          </Button>
        )}
      </div>
      {picking === which && (
        <p className="text-sm text-accent-text" role="status">
          {t('points.picking', { point: name.toLowerCase() })}
        </p>
      )}
      <form onSubmit={apply} className="grid grid-cols-[1fr_1fr_auto] items-end gap-2" noValidate aria-label={`${t('manual.legend')} — ${name}`}>
        <div className="space-y-1">
          <Label htmlFor={`${id}-lat`}>{t('manual.lat')}</Label>
          <Input
            id={`${id}-lat`}
            inputMode="decimal"
            value={lat}
            onChange={(e) => setLat(e.target.value)}
            aria-invalid={!!error}
            aria-describedby={error ? `${id}-err` : undefined}
            placeholder="45.5048"
            data-testid={`${which}-lat`}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`${id}-lon`}>{t('manual.lon')}</Label>
          <Input
            id={`${id}-lon`}
            inputMode="decimal"
            value={lon}
            onChange={(e) => setLon(e.target.value)}
            aria-invalid={!!error}
            aria-describedby={error ? `${id}-err` : undefined}
            placeholder="-73.5772"
            data-testid={`${which}-lon`}
          />
        </div>
        <Button type="submit" variant="secondary" data-testid={`${which}-apply`}>
          {t('manual.apply', { point: name.toLowerCase() })}
        </Button>
      </form>
      <FieldError id={`${id}-err`}>{error}</FieldError>
    </fieldset>
  );
}
