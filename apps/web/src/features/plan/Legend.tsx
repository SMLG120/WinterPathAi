import { useTranslation } from 'react-i18next';
import type { Coverage, HazardKind, RiskLevel } from '@/api/types';
import { useCoverage } from '@/api/queries';
import { markerSvg } from '@/features/map/markers';
import { formatDateTime } from '@/lib/format';
import { COVERAGE_STYLE, HAZARD_STYLE, RISK_COLORS, ROUTE_STYLE, ROUTE_WIDTH } from './mapStyle';

const LEVELS: RiskLevel[] = ['low', 'moderate', 'elevated', 'high', 'unknown'];
const KINDS = Object.keys(HAZARD_STYLE) as HazardKind[];

/** Static SVG strings generated in markers.ts (no user input). */
function MarkerIcon({ k, searched }: { k: 'origin' | 'destination'; searched?: boolean }) {
  return <span aria-hidden="true" className="inline-flex w-8 shrink-0 justify-center" dangerouslySetInnerHTML={{ __html: markerSvg(k, !!searched, 22) }} />;
}

function CoverageInfo({ q }: { q: { data?: Coverage; isPending: boolean; isError: boolean } }) {
  const { t, i18n } = useTranslation('map');
  if (q.isPending) return <p className="text-xs text-muted-foreground">{t('legend.coverageLoading')}</p>;
  if (q.isError || !q.data) return <p className="text-xs text-muted-foreground">{t('legend.coverageError')}</p>;
  const c = q.data;
  const built = formatDateTime(c.graph.built_at ?? null, i18n.language);
  const gaps = c.known_gaps ?? [];
  return (
    <div className="space-y-0.5 text-xs text-muted-foreground" data-testid="legend-coverage-info">
      <p className="font-medium text-foreground">{c.pilot_name}</p>
      {built && <p>{t('legend.graphBuilt', { time: built })}</p>}
      {c.graph.osm_snapshot && <p>{t('legend.osmSnapshot', { date: c.graph.osm_snapshot })}</p>}
      {gaps.length > 0 && (
        <details>
          <summary className="cursor-pointer py-1">{t('legend.gaps', { count: gaps.length })}</summary>
          <ul className="list-disc space-y-1 pl-4">
            {gaps.map((g, i) => (
              <li key={i}>{g.description}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/** Legend uses text + line pattern + shape/symbol — never colour alone. */
export function Legend() {
  const { t } = useTranslation(['plan', 'map']);
  const coverage = useCoverage();
  return (
    <details className="rounded-lg border border-border p-3 text-sm" open data-testid="legend">
      <summary className="cursor-pointer font-semibold">{t('legend.title')}</summary>
      <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-1">
        <div>
          <h3 className="mb-1 text-sm font-medium">{t('map:legend.pointsTitle')}</h3>
          <ul className="space-y-1">
            <li className="flex items-center gap-2">
              <MarkerIcon k="origin" />
              {t('map:legend.origin')}
            </li>
            <li className="flex items-center gap-2">
              <MarkerIcon k="destination" />
              {t('map:legend.destination')}
            </li>
            <li className="flex items-center gap-2">
              <MarkerIcon k="destination" searched />
              {t('map:legend.searched')}
            </li>
          </ul>
        </div>
        <div>
          <h3 className="mb-1 text-sm font-medium">{t('legend.routeTitle')}</h3>
          <ul className="space-y-1">
            {(['winter_aware', 'shortest'] as const).map((v) => (
              <li key={v} className="flex items-center gap-2">
                <svg width="32" height="8" aria-hidden="true" className="shrink-0">
                  <line x1="2" y1="4" x2="30" y2="4" stroke={ROUTE_STYLE[v].color} strokeWidth="4" strokeDasharray={ROUTE_STYLE[v].dash ? '6 4' : undefined} strokeLinecap="round" />
                </svg>
                {t(`results.${v}`)}
              </li>
            ))}
            <li className="flex items-center gap-2">
              <svg width="32" height="10" aria-hidden="true" className="shrink-0">
                <line x1="3" y1="5" x2="29" y2="5" stroke="#64748B" strokeWidth={ROUTE_WIDTH.selected} strokeLinecap="round" />
              </svg>
              {t('map:legend.selected')}
            </li>
            <li className="flex items-center gap-2">
              <svg width="32" height="10" aria-hidden="true" className="shrink-0">
                <line x1="3" y1="5" x2="29" y2="5" stroke="#64748B" strokeOpacity="0.6" strokeWidth={ROUTE_WIDTH.other} strokeLinecap="round" />
              </svg>
              {t('map:legend.alternative')}
            </li>
          </ul>
        </div>
        <div>
          <h3 className="mb-1 text-sm font-medium">{t('legend.riskTitle')}</h3>
          <ul className="space-y-1">
            {LEVELS.map((l) => (
              <li key={l} className="flex items-center gap-2">
                <svg width="32" height="8" aria-hidden="true" className="shrink-0">
                  <line x1="2" y1="4" x2="30" y2="4" stroke={RISK_COLORS[l]} strokeWidth="3" strokeDasharray={l === 'unknown' ? '3 4' : undefined} />
                </svg>
                {t(`legend.risk.${l}`)}
              </li>
            ))}
          </ul>
          <p className="mt-1 text-xs text-muted-foreground">{t('map:legend.unknownNote')}</p>
        </div>
        <div>
          <h3 className="mb-1 text-sm font-medium">{t('legend.hazardTitle')}</h3>
          <ul className="space-y-1">
            {KINDS.map((k) => (
              <li key={k} className="flex items-center gap-2">
                <span aria-hidden="true" className="inline-flex size-5 items-center justify-center rounded-full border-2 border-white text-[10px] text-white" style={{ background: HAZARD_STYLE[k].color }}>
                  {HAZARD_STYLE[k].symbol}
                </span>
                {t(`hazard.kind.${k}`)}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3 className="mb-1 text-sm font-medium">{t('map:legend.coverageTitle')}</h3>
          <ul className="mb-1 space-y-1">
            <li className="flex items-center gap-2">
              <svg width="32" height="10" aria-hidden="true" className="shrink-0">
                <line x1="2" y1="5" x2="30" y2="5" stroke={COVERAGE_STYLE.casing} strokeWidth={COVERAGE_STYLE.width + 3} />
                <line x1="2" y1="5" x2="30" y2="5" stroke={COVERAGE_STYLE.line} strokeWidth={COVERAGE_STYLE.width} />
              </svg>
              {t('map:legend.boundary')}
            </li>
            <li className="flex items-center gap-2">
              <span aria-hidden="true" className="hatch inline-block h-5 w-8 shrink-0 rounded border border-navy" />
              {t('map:legend.outside')}
            </li>
          </ul>
          <CoverageInfo q={coverage} />
        </div>
      </div>
    </details>
  );
}
