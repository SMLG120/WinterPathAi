import { describe, expect, it } from 'vitest';
import { StaticIndexProvider } from './staticProvider';
import { testFetch, testManifest } from './testIndex';
import { SearchUnavailableError } from './types';

const provider = (o?: Parameters<typeof testFetch>[0]) => {
  const t = testFetch(o);
  return { p: new StaticIndexProvider('/search/', t.fetch), calls: t.calls };
};

describe('StaticIndexProvider — shard lookup', () => {
  it('fetches the manifest once and only the shard of the query token', async () => {
    const { p, calls } = provider();
    await p.search('gare centrale');
    await p.search('gare cen');
    expect(calls).toEqual(['/search/manifest.json', '/search/v/test/s/ga.json']);
  });

  it('civic number: token shard + only the address bucket of the matching streets', async () => {
    const { p, calls } = provider();
    const { results } = await p.search('1455 boul De Maisonneuve O');
    expect(calls).toEqual(['/search/manifest.json', '/search/v/test/s/ma.json', '/search/v/test/a/0.json']);
    expect(results[0]).toMatchObject({
      kind: 'address',
      label: '1455 Boulevard De Maisonneuve Ouest',
      detail: 'Montréal',
      source: 'rqa',
      quality: 'building',
      evidence: 'confirmed',
      point: { lon: -73.579, lat: 45.4973 },
    });
    // The suffixed 1455A is offered too, with its own (uncertain) quality.
    expect(results[1]).toMatchObject({ label: '1455A Boulevard De Maisonneuve Ouest', quality: 'uncertain', evidence: 'unknown' });
  });

  it('direction and type words rank streets; locality filters', async () => {
    const { p } = provider();
    const est = await p.search('maisonneuve est');
    expect(est.results[0]).toMatchObject({ kind: 'street', label: 'Boulevard De Maisonneuve Est', point: null });
    const laval = await p.search('maisonneuve, Laval');
    expect(laval.results.map((r) => r.label)).toEqual(['Rue Maisonneuve']);
    expect(laval.results[0]!.completion).toBe('Rue Maisonneuve, Laval');
  });

  it('interpolated RQA positions are model estimates, never confirmed', async () => {
    const { p } = provider();
    const { results } = await p.search('1451 de maisonneuve ouest');
    expect(results[0]).toMatchObject({ quality: 'interpolated', evidence: 'model_estimate' });
  });

  it('a civic number that is not listed → closest listed number, labelled', async () => {
    const { p } = provider();
    const { results } = await p.search('1453 boul de maisonneuve o');
    expect(results[0]).toMatchObject({ note: 'nearest_civic' });
    expect(['1451 Boulevard De Maisonneuve Ouest', '1455 Boulevard De Maisonneuve Ouest']).toContain(results[0]!.label);
  });

  it('places: French and English names, OSM evidence is an unverified report', async () => {
    const { p } = provider();
    const fr = await p.search('Université McGill');
    expect(fr.results).toHaveLength(1);
    expect(fr.results[0]).toMatchObject({ kind: 'place', source: 'osm', evidence: 'unverified_report', placeKind: 'university' });
    const en = await p.search('mcgill university');
    expect(en.results[0]).toMatchObject({ label: 'McGill University', detail: 'Université McGill · Montréal' });
  });

  it('nonsense → ok with no results; one letter → too_short; coordinates bypass the index', async () => {
    const { p, calls } = provider();
    expect(await p.search('zzqx')).toEqual({ status: 'ok', results: [] }); // no "zz" shard: nothing fetched
    expect(await p.search('g')).toEqual({ status: 'too_short', results: [] });
    const c = await p.search('45.5, -73.57');
    expect(c.results[0]).toMatchObject({ kind: 'coordinates', source: 'typed', evidence: null, point: { lat: 45.5, lon: -73.57 } });
    expect(await p.search('145.5, -273.5')).toEqual({ status: 'coords_out_of_range', results: [] });
    expect(calls).toEqual(['/search/manifest.json']);
  });
});

describe('StaticIndexProvider — failures', () => {
  it('missing index (Pages SPA fallback serves HTML) → SearchUnavailableError, and retry refetches', async () => {
    const { p, calls } = provider({ manifest: null });
    await expect(p.search('gare')).rejects.toBeInstanceOf(SearchUnavailableError);
    await expect(p.search('gare')).rejects.toMatchObject({ reason: 'missing' });
    expect(calls.filter((c) => c.endsWith('manifest.json'))).toHaveLength(2);
  });

  it('wrong format is refused', async () => {
    const { p } = provider({ manifest: { ...testManifest(), format: 'other/9' } });
    await expect(p.search('gare')).rejects.toMatchObject({ reason: 'format' });
  });

  it('a shard that does not match its manifest sha256 is refused', async () => {
    const { p } = provider({ tamper: 's/ga.json' });
    await expect(p.search('gare')).rejects.toMatchObject({ reason: 'integrity' });
  });

  it('network failure → unavailable (network)', async () => {
    const p = new StaticIndexProvider('/search/', async () => {
      throw new TypeError('Failed to fetch');
    });
    await expect(p.search('gare')).rejects.toMatchObject({ reason: 'network' });
  });
});
