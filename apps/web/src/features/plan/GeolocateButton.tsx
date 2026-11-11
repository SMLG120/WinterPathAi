import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { LocateFixed } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { getCurrentLonLat, type GeoFailure } from '@/lib/geolocation';
import type { LonLat } from '@/api/types';

type Status = 'idle' | 'locating' | 'success' | GeoFailure;

/**
 * Consent-gated geolocation: explain first, then trigger the browser prompt.
 * Failure leaves manual entry fully functional.
 */
export function GeolocateButton({ onLocated }: { onLocated: (p: LonLat) => void }) {
  const { t } = useTranslation(['plan', 'common']);
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<Status>('idle');

  const locate = async () => {
    setOpen(false);
    setStatus('locating');
    try {
      const p = await getCurrentLonLat();
      onLocated(p);
      setStatus('success');
    } catch (e) {
      setStatus((e as GeoFailure) ?? 'unavailable');
    }
  };

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)} disabled={status === 'locating'} data-testid="geolocate">
        <LocateFixed aria-hidden="true" />
        {status === 'locating' ? t('geo.locating') : t('geo.button')}
      </Button>
      {status !== 'idle' && status !== 'locating' && (
        <p
          role={status === 'success' ? 'status' : 'alert'}
          className={status === 'success' ? 'w-full text-sm text-accent-text' : 'w-full text-sm text-danger'}
          data-testid="geo-status"
        >
          {t(`geo.${status}`)}
        </p>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent closeLabel={t('common:actions.close')}>
          <DialogTitle>{t('geo.consentTitle')}</DialogTitle>
          <DialogDescription>{t('geo.consentBody')}</DialogDescription>
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {t('common:actions.cancel')}
            </Button>
            <Button onClick={() => void locate()} data-testid="geo-consent">
              {t('geo.allow')}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
