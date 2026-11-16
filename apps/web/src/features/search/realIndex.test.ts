/**
 * Golden queries against the REAL index built locally into public/search (or SEARCH_INDEX_DIR).
 * Skipped when no index is present (CI never has it: it is generated from raw RQA/OSM data that
 * stays out of Git). Prints the top results so they can be pasted into docs/agent-reports/search.md.
 */
import { existsSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { StaticIndexProvider } from './staticProvider';
import type { SearchResult } from './types';

const DIR = resolve(process.env.SEARCH_INDEX_DIR ?? join(__dirname, '../../../public/search'));
const HAVE = existsSync(join(DIR, 'manifest.json'));

const fsFetch: typeof fetch = async (input) => {
  const rel = String(input).replace(/^\/search\//, '');
  const p = join(DIR, rel);
  if (!existsSync(p)) return new Response('<!doctype html>', { status: 200, headers: { 'content-type': 'text/html' } });
  return new Response(readFileSync(p), { status: 200, headers: { 'content-type': 'application/json' } });
};

const show = (r: SearchResult) =>
  `${r.kind}|${r.source}|${r.label}|${r.detail}|${r.quality ?? r.placeKind ?? ''}|${r.evidence ?? '-'}|${r.point ? `${r.point.lat.toFixed(5)},${r.point.lon.toFixed(5)}` : '-'}${r.note ? `|${r.note}` : ''}`;

describe.skipIf(!HAVE)('real index (local only)', () => {
  const p = new StaticIndexProvider('/search/', fsFetch);
  const run = async (q: string) => {
    const t0 = performance.now();
    // Same kind of tie-break bias the UI passes (centre of the coverage area); downtown here.
    const out = await p.search(q, { near: { lon: -73.5673, lat: 45.5017 } });
    const ms = performance.now() - t0;
    process.stdout.write(`\nQ: ${q}  [${out.status}, ${out.results.length} results, ${ms.toFixed(0)} ms]\n  ${out.results.slice(0, 4).map(show).join('\n  ')}\n`);
    return out;
  };

  it('1455 boul De Maisonneuve O → the Montréal address', async () => {
    const { results } = await run('1455 boul De Maisonneuve O');
    expect(results[0]).toMatchObject({ kind: 'address', source: 'rqa', detail: 'Montréal' });
    expect(results[0]!.label).toMatch(/^1455 .*Maisonneuve Ouest/);
  });
  it('Université McGill and McGill University → the OSM place', async () => {
    for (const q of ['Université McGill', 'McGill University']) {
      const { results } = await run(q);
      expect(results[0]).toMatchObject({ kind: 'place', source: 'osm', evidence: 'unverified_report' });
      expect(results[0]!.label).toMatch(/McGill/);
      expect(results[0]!.detail).toMatch(/Montréal$/); // downtown campus before the Sainte-Anne-de-Bellevue one
    }
  });
  it('Gare Centrale → a station', async () => {
    const { results } = await run('Gare Centrale');
    expect(results[0]).toMatchObject({ kind: 'place', placeKind: 'station' });
  });
  it('Terrebonne and Repentigny (North Shore, outside routing coverage today)', async () => {
    const terrebonne = await run('1000 boul des Seigneurs, Terrebonne');
    expect(terrebonne.results[0]).toMatchObject({ kind: 'address', detail: 'Terrebonne' });
    const repentigny = await run('435 boul Iberville, Repentigny');
    expect(repentigny.results[0]).toMatchObject({ kind: 'address', detail: 'Repentigny' });
    const place = await run('Terrebonne');
    expect(place.results.length).toBeGreaterThan(0);
  });
  it('Laval, Longueuil, Brossard addresses', async () => {
    const laval = await run('1555 boul Chomedey, Laval');
    expect(laval.results[0]).toMatchObject({ kind: 'address', detail: 'Laval' });
    const longueuil = await run('151 rue St-Charles O, Longueuil');
    expect(longueuil.results[0]).toMatchObject({ kind: 'address', detail: 'Longueuil' });
    expect(longueuil.results[0]!.note).toBeUndefined();
    const notListed = await run('150 rue St-Charles O, Longueuil');
    expect(notListed.results[0]).toMatchObject({ kind: 'address', detail: 'Longueuil', note: 'nearest_civic' });
    const brossard = await run('6000 boul de Rome, Brossard');
    expect(brossard.results[0]).toMatchObject({ kind: 'address', detail: 'Brossard' });
  });
  it('English and abbreviation forms', async () => {
    const r1 = await run('3480 rue University');
    expect(r1.results[0]).toMatchObject({ kind: 'address', detail: 'Montréal' });
    const r2 = await run('1200 Ste-Catherine St W');
    expect(r2.results[0]!.label).toMatch(/Sainte-Catherine Ouest/);
    const r3 = await run('5664 1re avenue');
    expect(r3.results.length).toBeGreaterThan(0);
  });
  it('nonsense → empty; coordinates → typed point', async () => {
    expect((await run('xqzzv wkkkp')).results).toEqual([]);
    const c = await run('45.5048, -73.5772');
    expect(c.results[0]).toMatchObject({ kind: 'coordinates', point: { lat: 45.5048, lon: -73.5772 } });
  });
  it('street name only → street completions', async () => {
    const r = await run('sherbrooke');
    expect(r.results.some((x) => x.kind === 'street')).toBe(true);
  });
});
