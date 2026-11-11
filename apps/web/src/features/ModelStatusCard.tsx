import { useTranslation } from 'react-i18next';
import { CircleOff, CircleCheck } from 'lucide-react';
import { useModelStatus } from '@/api/queries';
import type { ModelStatus } from '@/api/types';
import { DataState } from '@/components/evidence/DataState';
import { DemoBadge } from '@/components/evidence/DemoBadge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { formatDateTime } from '@/lib/format';

const METRICS = ['split', 'pr_auc', 'baseline_pr_auc', 'brier', 'precision_at_k', 'recall_at_k', 'n_test'] as const;

function Body({ m }: { m: ModelStatus }) {
  const { t, i18n } = useTranslation('winter');
  const nf = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 3 });
  const evaluation = m.evaluation;
  return (
    <div className="space-y-4 text-sm">
      <p className="flex items-center gap-2 text-base font-semibold" data-testid="model-enabled">
        {m.enabled ? <CircleCheck className="size-5 text-accent-text" aria-hidden="true" /> : <CircleOff className="size-5" aria-hidden="true" />}
        {m.enabled ? t('model.enabled') : t('model.disabled')}
        <span className="font-normal text-muted-foreground">· {t(`model.layer.${m.risk_layer}`)}</span>
      </p>
      <div>
        <p className="font-medium">{t('model.target')}</p>
        <p className="font-mono text-xs">{m.target}</p>
        <p className="mt-1 text-muted-foreground">{t('model.targetNote')}</p>
      </div>
      {(m.trained_at || m.training_window || m.model_id) && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
          {m.model_id && (
            <>
              <dt className="text-muted-foreground">ID</dt>
              <dd className="font-mono text-xs">{m.model_id}</dd>
            </>
          )}
          {m.trained_at && (
            <>
              <dt className="text-muted-foreground">{t('model.trainedAt')}</dt>
              <dd>{formatDateTime(m.trained_at, i18n.language)}</dd>
            </>
          )}
          {m.training_window && (
            <>
              <dt className="text-muted-foreground">{t('model.window')}</dt>
              <dd>{m.training_window}</dd>
            </>
          )}
        </dl>
      )}
      <div>
        <p className="font-medium">{t('model.evaluation')}</p>
        {evaluation ? (
          <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
            {METRICS.filter((k) => evaluation[k] !== undefined).map((k) => (
              <div key={k} className="contents">
                <dt className="text-muted-foreground">{t(`model.metrics.${k}`)}</dt>
                <dd>{typeof evaluation[k] === 'number' ? nf.format(evaluation[k] as number) : String(evaluation[k])}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="text-muted-foreground">{t('model.noEvaluation')}</p>
        )}
      </div>
      {m.limitations && m.limitations.length > 0 && (
        <div>
          <p className="font-medium">{t('model.limitations')}</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {m.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function ModelStatusCard({ headingLevel = 'h2' }: { headingLevel?: 'h2' | 'h3' }) {
  const { t } = useTranslation('winter');
  const q = useModelStatus();
  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between">
        <CardTitle as={headingLevel}>{t('model.title')}</CardTitle>
        <DemoBadge />
      </CardHeader>
      <CardContent>
        <DataState query={q}>{(m) => <Body m={m} />}</DataState>
      </CardContent>
    </Card>
  );
}
