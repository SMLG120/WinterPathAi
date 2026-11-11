import { useTranslation } from 'react-i18next';
import { AlertTriangle, WifiOff } from 'lucide-react';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { isApiError } from '@/api/client';
import { useOnline } from '@/lib/useOnline';

type Props<T> = {
  query: { data: T | undefined; isPending: boolean; isError: boolean; error: unknown; refetch: () => unknown };
  isEmpty?: (d: T) => boolean;
  skeleton?: React.ReactNode;
  emptyText?: string;
  children: (d: T) => React.ReactNode;
};

/** Standard loading / error (retry) / empty / offline states for every data view. */
export function DataState<T>({ query, isEmpty, skeleton, emptyText, children }: Props<T>) {
  const { t } = useTranslation(['common', 'errors']);
  const online = useOnline();
  const offline = !online ? (
    <Alert variant="warning" className="mb-3">
      <WifiOff aria-hidden="true" />
      <span>{t('states.offline')}</span>
    </Alert>
  ) : null;

  if (query.isPending) {
    return (
      <div role="status" aria-live="polite">
        <span className="sr-only">{t('states.loading')}</span>
        {skeleton ?? (
          <div className="space-y-2">
            <Skeleton className="h-5 w-2/3" />
            <Skeleton className="h-5 w-1/2" />
            <Skeleton className="h-5 w-3/4" />
          </div>
        )}
      </div>
    );
  }
  if (query.isError || query.data === undefined) {
    const code = isApiError(query.error) ? query.error.code : 'UNKNOWN';
    return (
      <>
        {offline}
        <Alert variant="error" role="alert">
          <AlertTriangle aria-hidden="true" />
          <div className="flex flex-col gap-2">
            <span>{t('states.error')}</span>
            <span data-testid="error-detail">{t(`errors:codes.${code}`)}</span>
            <Button variant="outline" size="sm" className="w-fit" onClick={() => void query.refetch()}>
              {t('states.retry')}
            </Button>
          </div>
        </Alert>
      </>
    );
  }
  if (isEmpty?.(query.data)) {
    return (
      <>
        {offline}
        <p className="text-sm text-muted-foreground">{emptyText ?? t('states.empty')}</p>
      </>
    );
  }
  return (
    <>
      {offline}
      {children(query.data)}
    </>
  );
}
