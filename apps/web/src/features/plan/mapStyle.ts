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
