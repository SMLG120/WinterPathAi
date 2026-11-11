import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';
import { Alert, AlertTitle } from '@/components/ui/alert';
import { isApiError, type ApiRequestError } from '@/api/client';

const KNOWN = ['NO_ROUTE', 'OUTSIDE_COVERAGE', 'RATE_LIMITED'] as const;

/**
 * A snap failure: v1.3 sends OFF_NETWORK; earlier API builds sent OUTSIDE_COVERAGE
 * with the same `details` (which / max_snap_distance_m / nearest_network_m).
 */
function snapDetails(e: ApiRequestError) {
  const d = e.details;
  const isSnap = e.code === 'OFF_NETWORK' || (e.code === 'OUTSIDE_COVERAGE' && typeof d.max_snap_distance_m === 'number');
  if (!isSnap) return null;
  const which = d.which === 'destination' ? 'destination' : d.which === 'origin' ? 'origin' : null;
  const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? Math.round(v) : null);
  return { which, max: num(d.max_snap_distance_m) ?? 75, nearest: num(d.nearest_network_m) };
}

/** Helpful copy for 404 NO_ROUTE / 422 OUTSIDE_COVERAGE / 422 OFF_NETWORK / 429 / anything else. */
export function RouteError({ error }: { error: unknown }) {
  const { t } = useTranslation(['plan', 'errors']);
  const code = isApiError(error) ? error.code : 'UNKNOWN';
  const snap = isApiError(error) ? snapDetails(error) : null;
  const key = snap ? 'OFF_NETWORK' : (KNOWN as readonly string[]).includes(code) ? code : 'generic';
  const retry = isApiError(error) && error.retryAfterS ? t('errors:retryAfter', { seconds: error.retryAfterS }) : null;
  const point = snap?.which ? t(`points.${snap.which}`).toLowerCase() : t('points.origin').toLowerCase() + ' / ' + t('points.destination').toLowerCase();
  return (
    <Alert variant="error" role="alert" data-testid="route-error" data-code={code} data-kind={key}>
      <AlertTriangle aria-hidden="true" />
      <div>
        <AlertTitle>{t(`errors.${key}.title`)}</AlertTitle>
        <p className="mt-1">{snap ? t('errors.OFF_NETWORK.body', { point, max: snap.max }) : t(`errors.${key}.body`)}</p>
        {snap?.nearest != null && <p className="mt-1">{t('errors.OFF_NETWORK.nearest', { nearest: snap.nearest })}</p>}
        {key === 'generic' && <p className="mt-1 text-muted-foreground">{t(`errors:codes.${code}`)}</p>}
        {retry && <p className="mt-1">{retry}</p>}
      </div>
    </Alert>
  );
}
