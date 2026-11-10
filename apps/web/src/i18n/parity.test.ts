import { describe, expect, it } from 'vitest';
import { NAMESPACES, resources } from './index';

type Tree = Record<string, unknown>;
const PLURAL = /_(zero|one|two|few|many|other)$/;

function leaves(obj: unknown, prefix = ''): Map<string, string> {
  const out = new Map<string, string>();
  if (typeof obj === 'string') out.set(prefix, obj);
  else if (Array.isArray(obj)) obj.forEach((v, i) => leaves(v, `${prefix}[${i}]`).forEach((s, k) => out.set(k, s)));
  else if (obj && typeof obj === 'object')
    for (const [k, v] of Object.entries(obj as Tree)) leaves(v, prefix ? `${prefix}.${k}` : k).forEach((s, kk) => out.set(kk, s));
  return out;
}
const baseKeys = (m: Map<string, string>) => new Set([...m.keys()].map((k) => k.replace(PLURAL, '')));
const vars = (s: string) => [...s.matchAll(/\{\{\s*(\w+)\s*\}\}/g)].map((m) => m[1]).sort();

/** Strings that are legitimately identical in both languages. */
const SAME_OK = new Set([
  'common:brand',
  'common:states.retry',
  'plan:manual.lat',
  'plan:manual.lon',
  'plan:profile.standard',
  'reports:form.lat',
  'reports:form.lon',
  'winter:current.noValue',
  'winter:model.metrics.pr_auc',
  'how:sources.name',
  'how:sources.licence',
  'how:sources.statusValue.active',
  'common:meta.source',
  // Identical words in Canadian French:
  'plan:results.distance',
  'winter:current.station',
  'pilot:form.organization',
  'pilot:form.segments.campus',
]);

describe('i18n EN/FR parity', () => {
  for (const ns of NAMESPACES) {
    const en = leaves(resources.en[ns]);
    const fr = leaves(resources.fr[ns]);

    it(`${ns}: same keys in both locales (plural forms normalised)`, () => {
      const missingInFr = [...baseKeys(en)].filter((k) => !baseKeys(fr).has(k));
      const missingInEn = [...baseKeys(fr)].filter((k) => !baseKeys(en).has(k));
      expect(missingInFr, 'missing in fr').toEqual([]);
      expect(missingInEn, 'missing in en').toEqual([]);
    });

    it(`${ns}: no empty strings or placeholder markers`, () => {
      for (const [lang, m] of [['en', en], ['fr', fr]] as const) {
        for (const [k, v] of m) {
          expect(v.trim(), `${lang}:${ns}:${k}`).not.toBe('');
          expect(v, `${lang}:${ns}:${k}`).not.toMatch(/TODO|FIXME|\[EN\]|\[FR\]|lorem ipsum/i);
        }
      }
    });

    it(`${ns}: interpolation variables match`, () => {
      for (const [k, v] of en) {
        const base = k.replace(PLURAL, '');
        const frVal = fr.get(k) ?? fr.get(`${base}_other`) ?? fr.get(base);
        if (frVal !== undefined) expect(vars(frVal), `${ns}:${k}`).toEqual(vars(v));
      }
    });

    it(`${ns}: French is actually translated (no English left in place)`, () => {
      const untranslated = [...en]
        .filter(([k, v]) => fr.get(k) === v && v.length > 3 && !SAME_OK.has(`${ns}:${k}`))
        .map(([k]) => k);
      expect(untranslated).toEqual([]);
    });
  }
});
