import type { HazardKind, RiskLevel } from '@/api/types';
import { riskColors } from '@/styles/tokens';

export const RISK_COLORS: Record<RiskLevel, string> = riskColors;

export const HAZARD_STYLE: Record<HazardKind, { color: string; symbol: string }> = {
  sidewalk_closure: { color: '#B4233C', symbol: '⛔' },
  construction_impact: { color: '#D9622B', symbol: '▲' },
  report_311_aggregate: { color: '#C99A2E', symbol: '⚑' },
  community_report: { color: '#5B6BBF', symbol: '●' },
};

export const ROUTE_STYLE = {
  shortest: { color: '#64748B', dash: [2, 1.5] as [number, number] },
  winter_aware: { color: '#087F8C', dash: null },
} as const;

/** Line widths (px) by route state: selected > pointed at (card hover / map hover) > alternative. */
export const ROUTE_WIDTH = { selected: 6, hovered: 5, other: 3 } as const;

/** Routable-area boundary: navy line on a white casing, readable on light and dark basemaps. */
export const COVERAGE_STYLE = { line: '#101B2C', casing: '#FFFFFF', width: 2, dim: 'rgba(100,116,139,0.18)' } as const;
