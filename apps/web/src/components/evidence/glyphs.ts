import type { EvidenceState } from '@/api/types';

/** Glyphs from docs/ux-spec.md. Always paired with a text label — never colour alone. */
export const EVIDENCE_GLYPH: Record<EvidenceState, string> = {
  confirmed: '✓',
  unverified_report: '⚑',
  model_estimate: '≈',
  unknown: '?',
  simulated: '!',
};
