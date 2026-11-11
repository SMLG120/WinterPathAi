// @vitest-environment node
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { brand, themes } from './tokens';

function lum(hex: string) {
  const n = Number.parseInt(hex.slice(1), 16);
  const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * ch[0]! + 0.7152 * ch[1]! + 0.0722 * ch[2]!;
}
export function contrast(a: string, b: string) {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x! + 0.05) / (y! + 0.05);
}

describe('WCAG contrast of theme tokens (text ≥ 4.5:1)', () => {
  for (const [name, th] of Object.entries(themes)) {
    it(`${name}: foreground/background, muted, accent text, primary button`, () => {
      expect(contrast(th.foreground, th.background)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(th.foreground, th.card)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(th.muted, th.background)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(th.muted, th.card)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(th.accentText, th.background)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(th.accentText, th.card)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(th.primaryForeground, th.primary)).toBeGreaterThanOrEqual(4.5);
    });
  }

  it('teal is NOT used as body text on navy (fails 4.5:1) — dark theme uses frost', () => {
    expect(contrast(brand.teal, brand.navy)).toBeLessThan(4.5);
    expect(themes.dark.accentText).toBe(brand.frost);
  });

  it('amber is never body text on ice (fails); navy on amber (SIMULATED / stale badges) passes', () => {
    expect(contrast(brand.amber, brand.ice)).toBeLessThan(4.5);
    expect(contrast(brand.navy, brand.amber)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(brand.navy, '#F2C879')).toBeGreaterThanOrEqual(4.5);
  });

  it('CSS variables match tokens.ts', () => {
    const css = readFileSync(fileURLToPath(new URL('./index.css', import.meta.url)), 'utf8').toLowerCase();
    for (const v of Object.values(brand)) expect(css).toContain(v.toLowerCase());
    expect(css).toContain(`--muted-foreground: ${themes.dark.muted.toLowerCase()}`);
    expect(css).toContain(`--card: ${themes.dark.card.toLowerCase()}`);
  });
});
