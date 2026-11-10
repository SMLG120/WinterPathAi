import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';
import { Alert, AlertTitle } from '@/components/ui/alert';
import { isApiError } from '@/api/client';

const KNOWN = ['NO_ROUTE', 'OUTSIDE_COVERAGE', 'RATE_LIMITED'] as const;

/** Helpful copy for 404 NO_ROUTE / 422 OUTSIDE_COVERAGE / 429 / anything else. */
export function RouteError({ error }: { error: unknown }) {
  const { t } = useTranslation(['plan', 'errors']);
  const code = isApiError(error) ? error.code : 'UNKNOWN';
  const key = (KNOWN as readonly string[]).includes(code) ? code : 'generic';
  const retry = isApiError(error) && error.retryAfterS ? t('errors:retryAfter', { seconds: error.retryAfterS }) : null;
  return (
    <Alert variant="error" role="alert" data-testid="route-error" data-code={code}>
      <AlertTriangle aria-hidden="true" />
      <div>
        <AlertTitle>{t(`errors.${key}.title`)}</AlertTitle>
        <p className="mt-1">{t(`errors.${key}.body`)}</p>
        {key === 'generic' && <p className="mt-1 text-muted-foreground">{t(`errors:codes.${code}`)}</p>}
        {retry && <p className="mt-1">{retry}</p>}
      </div>
    </Alert>
  );
}
