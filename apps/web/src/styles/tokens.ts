/**
 * Brand tokens (docs/ux-spec.md). Mirrored in styles/index.css; contrast is
 * asserted in styles/contrast.test.ts so the CSS and this file must stay in sync.
 */
export const brand = {
  navy: '#101B2C',
  frost: '#BDE8F4',
  teal: '#087F8C',
  ice: '#F7FAFC',
  slate: '#64748B',
  amber: '#E7A83E',
} as const;

export const themes = {
  light: {
    background: brand.ice,
    foreground: brand.navy,
    card: '#FFFFFF',
    muted: brand.slate,
    accentText: brand.teal,
    primary: brand.teal,
    primaryForeground: '#FFFFFF',
    ring: brand.teal,
  },
  dark: {
    background: brand.navy,
    foreground: brand.ice,
    card: '#17253A',
    muted: '#A3B1C4',
    accentText: brand.frost,
    primary: brand.frost,
    primaryForeground: brand.navy,
    ring: brand.frost,
  },
} as const;

/** Map overlay colours (risk levels are always paired with a text legend + dash pattern). */
export const riskColors = {
  low: '#2E8B57',
  moderate: '#C99A2E',
  elevated: '#D9622B',
  high: '#B4233C',
  unknown: '#64748B',
} as const;
