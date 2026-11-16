/**
 * TEST-ONLY synthetic index (format winterpath-search/1) for unit and component tests.
 * The rows are invented test fixtures, never shown to users; real data comes only from the
 * index built by services/ingestion (python -m winterpath_ingestion.search_index).
 */
import { createHash } from 'node:crypto';
import { FORMAT, type Manifest } from './staticProvider';

const munis: [string, string][] = [
  ['65005', 'Laval'],
  ['66023', 'Montréal'],
];
const qualities = ['Bâtiment', 'Front lot', 'Accès propriété', 'Centre lot', 'Site', 'Géocodée', 'Incertaine'];

// street rows: ['s', sid, display, muni, tokens, generic, dir, count, lonE5, latE5]
const S0 = ['s', 0, 'Boulevard De Maisonneuve Ouest', 1, 'maisonneuve', 'boulevard', 'o', 3, -7357900, 4549730];
const S1 = ['s', 1, 'Boulevard De Maisonneuve Est', 1, 'maisonneuve', 'boulevard', 'e', 1, -7355000, 4551500];
const S2 = ['s', 2, 'Rue Maisonneuve', 0, 'maisonneuve', 'rue', '', 1, -7374000, 4456000];
// place rows: ['p', pid, name, muni, tokens, kind, lonE5, latE5, ref, primary]
const P0 = ['p', 0, 'Gare Centrale', 1, 'gare centrale', 'station', -7356669, 4549993, 'n1', ''];
const P1 = ['p', 1, 'Université McGill', 1, 'universite mcgill', 'university', -7357871, 4550689, 'r2', ''];
const P1en = ['p', 1, 'McGill University', 1, 'mcgill university', 'university', -7357871, 4550689, 'r2', 'Université McGill'];

export const TEST_SHARDS: Record<string, unknown> = {
  's/ma.json': { v: 1, e: [S0, S1, S2] },
  's/ga.json': { v: 1, e: [P0] },
  's/ce.json': { v: 1, e: [P0] },
  's/un.json': { v: 1, e: [P1, P1en] },
  's/mc.json': { v: 1, e: [P1, P1en] },
  // Address bucket 0 holds street 0 (sid % 2 buckets), deltas from the previous row.
  'a/0.json': {
    v: 1,
    s: {
      '0': [
        ['1451', -7357905, 4549725, 5],
        ['1455', 5, 5, 0],
        ['1455A', 0, 1, 6],
      ],
      '2': [['12', -7374000, 4456000, 6]],
    },
  },
  'a/1.json': { v: 1, s: { '1': [['10', -7355000, 4551500, 5]] } },
};

const sha = (s: string) => createHash('sha256').update(s, 'utf8').digest('hex');

export function testManifest(): Manifest {
  const shards: Record<string, string> = {};
  for (const [k, v] of Object.entries(TEST_SHARDS)) shards[k] = sha(JSON.stringify(v));
  return {
    format: FORMAT,
    build_id: 'test',
    base: 'v/test/',
    key_len: 2,
    address_buckets: 2,
    municipalities: munis,
    qualities,
    sources: [],
    counts: {},
    shards,
  };
}

/** A fetch serving the synthetic index under /search/, with Pages-like HTML fallback for misses. */
export function testFetch(opts: { manifest?: Manifest | null; delayMs?: number; tamper?: string } = {}) {
  const manifest = opts.manifest === undefined ? testManifest() : opts.manifest;
  const calls: string[] = [];
  const f: typeof fetch = async (input) => {
    const url = String(input);
    calls.push(url);
    if (opts.delayMs) await new Promise((r) => setTimeout(r, opts.delayMs));
    const rel = url.replace(/^\/search\//, '');
    let body: unknown;
    if (rel === 'manifest.json') body = manifest;
    else if (rel.startsWith('v/test/')) body = TEST_SHARDS[rel.slice('v/test/'.length)];
    if (body == null) return new Response('<!doctype html><title>SPA</title>', { status: 200, headers: { 'content-type': 'text/html' } });
    let text = JSON.stringify(body);
    if (opts.tamper && rel.endsWith(opts.tamper)) text = text.replace('Gare', 'Gaar');
    return new Response(text, { status: 200, headers: { 'content-type': 'application/json' } });
  };
  return { fetch: f, calls };
}
