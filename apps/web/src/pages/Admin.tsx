import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useAdminReports, useModerateReport } from '@/api/queries';
import { isApiError } from '@/api/client';
import type { ModerationStatus, ReportAdminView } from '@/api/types';
import { DemoBadge } from '@/components/evidence/DemoBadge';
import { EvidenceBadge } from '@/components/evidence/EvidenceBadge';
import { PageHeader } from '@/components/layout/Section';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input, Label, Select } from '@/components/ui/input';
import { formatDateTime } from '@/lib/format';
import { formatLonLat } from '@/lib/geo';
import { useDocumentTitle } from '@/lib/useDocumentTitle';

const STATUSES: Array<ModerationStatus | 'all'> = ['pending', 'approved', 'rejected', 'expired', 'deleted', 'all'];

function Row({ r, token }: { r: ReportAdminView; token: string }) {
  const { t, i18n } = useTranslation('reports');
  const qc = useQueryClient();
  const moderate = useModerateReport(token);
  const [note, setNote] = useState('');
  const act = (decision: 'approve' | 'reject' | 'expire') =>
    moderate.mutate(
      { id: r.id, decision, note: note.trim() || undefined },
      { onSuccess: () => void qc.invalidateQueries({ queryKey: ['admin', 'reports'] }) },
    );
  return (
    <li className="space-y-2 rounded-lg border border-border bg-card p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{t(`form.categories.${r.category}`)}</span>
        <EvidenceBadge state="unverified_report" />
        <span className="text-muted-foreground">{r.status}</span>
      </div>
      <p>{r.description ?? <span className="text-muted-foreground">{t('admin.noDescription')}</span>}</p>
      <p className="text-muted-foreground">
        {formatLonLat(r.location, 4)} · {t('admin.created')} {formatDateTime(r.created_at, i18n.language)} · {t('receipt.expires')}{' '}
        {formatDateTime(r.expires_at, i18n.language)}
      </p>
      {r.status === 'pending' && (
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-48 flex-1 space-y-1">
            <Label htmlFor={`note-${r.id}`}>{t('admin.note')}</Label>
            <Input id={`note-${r.id}`} value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
          </div>
          <Button size="sm" onClick={() => act('approve')} disabled={moderate.isPending}>
            {t('admin.approve')}
          </Button>
          <Button size="sm" variant="outline" onClick={() => act('reject')} disabled={moderate.isPending}>
            {t('admin.reject')}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => act('expire')} disabled={moderate.isPending}>
            {t('admin.expire')}
          </Button>
        </div>
      )}
    </li>
  );
}

/** Hidden moderation view (not linked publicly). Token held in memory only. */
export default function Admin() {
  const { t } = useTranslation('reports');
  useDocumentTitle(t('admin.title'));
  const [draft, setDraft] = useState('');
  const [token, setToken] = useState<string | null>(null);
  const [status, setStatus] = useState<ModerationStatus | 'all'>('pending');
  const q = useAdminReports(token, status);

  useEffect(() => {
    const m = document.createElement('meta');
    m.name = 'robots';
    m.content = 'noindex, nofollow';
    document.head.appendChild(m);
    return () => m.remove();
  }, []);

  const unauthorized = isApiError(q.error) && q.error.status === 401;

  return (
    <>
      <PageHeader title={t('admin.title')} intro={t('admin.intro')}>
        <DemoBadge />
      </PageHeader>
      <div className="mx-auto max-w-4xl space-y-6 px-4 py-10">
        {!token ? (
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (draft.trim()) setToken(draft.trim());
            }}
          >
            <div className="min-w-64 flex-1 space-y-1">
              <Label htmlFor="admin-token">{t('admin.token')}</Label>
              <Input id="admin-token" type="password" autoComplete="off" value={draft} onChange={(e) => setDraft(e.target.value)} />
            </div>
            <Button type="submit">{t('admin.signIn')}</Button>
          </form>
        ) : (
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <Label htmlFor="status-filter">{t('admin.filter')}</Label>
              <Select id="status-filter" value={status} onChange={(e) => setStatus(e.target.value as ModerationStatus | 'all')}>
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s === 'all' ? t('admin.all') : s}
                  </option>
                ))}
              </Select>
            </div>
            <Button
              variant="ghost"
              onClick={() => {
                setToken(null);
                setDraft('');
              }}
            >
              {t('admin.signOut')}
            </Button>
          </div>
        )}
        {unauthorized && (
          <Alert variant="error" role="alert">
            <span>{t('admin.unauthorized')}</span>
          </Alert>
        )}
        {token && q.data && (
          <>
            {q.data.items.length === 0 ? (
              <p className="text-muted-foreground">{t('admin.empty')}</p>
            ) : (
              <ul className="space-y-3">
                {q.data.items.map((r) => (
                  <Row key={r.id} r={r} token={token} />
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </>
  );
}
