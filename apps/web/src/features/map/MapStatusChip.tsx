import { useTranslation } from 'react-i18next';
import { AlertTriangle, CloudOff, Loader2, RefreshCw, ZoomIn, Clock, Database, CheckCircle2, Ban } from 'lucide-react';
import { formatTime } from './time';
import type { DataStatus } from './dataStatus';
import { cn } from '@/lib/utils';

export type ChipState =
  | { kind: 'computing' }
  | { kind: 'view'; reason: 'too-large' | 'outside' }
  | { kind: 'data'; status: Exclude<DataStatus, 'off'>; updatedAt: number | null; hasData: boolean };

const ICON = {
  loading: Loader2,
  updating: Loader2,
  fresh: CheckCircle2,
  cached: Database,
  stale: Clock,
  unavailable: CloudOff,
  error: AlertTriangle,
} as const;

/**
 * One-line status over the map: what the overlay layers currently show and how old they are.
 * Always icon + text (never colour alone); a Retry button (44 px) on failures.
 */
export function MapStatusChip({ state, onRetry }: { state: ChipState; onRetry?: () => void }) {
  const { t, i18n } = useTranslation('map');
  let Icon: typeof Loader2 = Loader2;
  let text: string;
  let tone: 'neutral' | 'warn' | 'error' = 'neutral';
  let spin = false;
  let retry = false;
  if (state.kind === 'computing') {
    text = t('status.computing');
    spin = true;
  } else if (state.kind === 'view') {
    Icon = state.reason === 'outside' ? Ban : ZoomIn;
    text = t(state.reason === 'outside' ? 'status.outside' : 'status.zoomIn');
  } else {
    const time = state.updatedAt ? formatTime(state.updatedAt, i18n.language) : null;
    Icon = ICON[state.status];
    spin = state.status === 'loading' || state.status === 'updating';
    text = time && (state.status === 'fresh' || state.status === 'cached' || state.status === 'stale') ? t(`status.${state.status}`, { time }) : t(`status.${state.status}Plain`);
    if (state.status === 'stale') tone = 'warn';
    if (state.status === 'unavailable' || state.status === 'error') {
      tone = 'error';
      retry = !!onRetry;
      if (state.hasData) text = `${text} — ${t('status.keptOlder')}`;
    }
  }
  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="map-status"
      data-status={state.kind === 'data' ? state.status : state.kind === 'view' ? state.reason : 'computing'}
      className={cn(
        'pointer-events-auto flex max-w-[min(22rem,calc(100vw-7rem))] items-center gap-2 rounded-lg border bg-card px-2.5 py-1.5 text-xs font-medium text-foreground shadow',
        tone === 'warn' && 'border-amber-brand',
        tone === 'error' && 'border-danger',
        tone === 'neutral' && 'border-border',
      )}
    >
      <Icon className={cn('size-4 shrink-0', spin && 'motion-safe:animate-spin')} aria-hidden="true" />
      <span className="min-w-0">{text}</span>
      {retry && (
        <button
          type="button"
          onClick={onRetry}
          className="-my-1 ml-1 inline-flex min-h-11 min-w-11 items-center justify-center gap-1 rounded-md px-2 underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-ring"
          data-testid="map-status-retry"
        >
          <RefreshCw className="size-4" aria-hidden="true" />
          {t('status.retry')}
        </button>
      )}
    </div>
  );
}
