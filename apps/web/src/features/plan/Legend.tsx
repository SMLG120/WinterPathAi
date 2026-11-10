import { useTranslation } from 'react-i18next';
import type { HazardKind, RiskLevel } from '@/api/types';
import { HAZARD_STYLE, RISK_COLORS, ROUTE_STYLE } from './mapStyle';

const LEVELS: RiskLevel[] = ['low', 'moderate', 'elevated', 'high', 'unknown'];
const KINDS = Object.keys(HAZARD_STYLE) as HazardKind[];

/** Legend uses text + line pattern + symbol — never colour alone. */
export function Legend() {
  const { t } = useTranslation('plan');
  return (
    <details className="rounded-lg border border-border p-3 text-sm" open>
      <summary className="cursor-pointer font-semibold">{t('legend.title')}</summary>
      <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-1">
        <div>
          <h4 className="mb-1 font-medium">{t('legend.routeTitle')}</h4>
          <ul className="space-y-1">
            {(['winter_aware', 'shortest'] as const).map((v) => (
              <li key={v} className="flex items-center gap-2">
                <svg width="32" height="8" aria-hidden="true">
                  <line x1="2" y1="4" x2="30" y2="4" stroke={ROUTE_STYLE[v].color} strokeWidth="4" strokeDasharray={ROUTE_STYLE[v].dash ? '6 4' : undefined} strokeLinecap="round" />
                </svg>
                {t(`results.${v}`)}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h4 className="mb-1 font-medium">{t('legend.riskTitle')}</h4>
          <ul className="space-y-1">
            {LEVELS.map((l) => (
              <li key={l} className="flex items-center gap-2">
                <svg width="32" height="8" aria-hidden="true">
                  <line x1="2" y1="4" x2="30" y2="4" stroke={RISK_COLORS[l]} strokeWidth="3" strokeDasharray={l === 'unknown' ? '3 4' : undefined} />
                </svg>
                {t(`legend.risk.${l}`)}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h4 className="mb-1 font-medium">{t('legend.hazardTitle')}</h4>
          <ul className="space-y-1">
            {KINDS.map((k) => (
              <li key={k} className="flex items-center gap-2">
                <span aria-hidden="true" className="inline-flex size-5 items-center justify-center rounded-full border-2 border-white text-[10px] text-white" style={{ background: HAZARD_STYLE[k].color }}>
                  {HAZARD_STYLE[k].symbol}
                </span>
                {t(`hazard.kind.${k}`)}
              </li>
            ))}
            <li className="flex items-center gap-2">
              <span aria-hidden="true" className="hatch inline-block size-5 rounded border border-navy" />
              {t('legend.outside')}
            </li>
          </ul>
        </div>
      </div>
    </details>
  );
}
