// @vitest-environment node
import { createHash } from 'node:crypto';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { checkDist, checkEnv, checkSearchIndex, PAGES_MAX_FILE_BYTES } from './pagesCheck';

const GOOD_ENV = { VITE_API_BASE_URL: 'https://winterpath-api.example.onrender.com/api/v1', VITE_PUBLIC_WRITES: 'false' };
const HEADERS = `/*
  Content-Security-Policy: default-src 'self'; connect-src 'self' https://winterpath-api.example.onrender.com https://tiles.openfreemap.org; frame-ancestors 'none'
  X-Content-Type-Options: nosniff
  Permissions-Policy: geolocation=(self), camera=()

/assets/*
  Cache-Control: public, max-age=31536000, immutable
`;

const SHARD = JSON.stringify({ v: 1, e: [] });
const sha = (t: string) => createHash('sha256').update(t).digest('hex');
const attribution = { fr: 'Adresses : RQA (CC BY 4.0)', en: 'Addresses: RQA (CC BY 4.0)' };
function manifest(over: Record<string, unknown> = {}) {
  return JSON.stringify({
    format: 'winterpath-search/1',
    build_id: 'b1',
    base: 'v/b1/',
    shards: { 's/ga.json': sha(SHARD) },
    sources: [
      { id: 'rqa', licence: 'CC BY 4.0', attribution },
      { id: 'osm', licence: 'ODbL 1.0', attribution: { fr: '© OpenStreetMap (ODbL)', en: '© OpenStreetMap (ODbL)' } },
    ],
    ...over,
  });
}
const INDEX = { 'search/manifest.json': manifest(), 'search/v/b1/s/ga.json': SHARD };

let dir = '';
function dist(files: Record<string, string | null>, index: Record<string, string> = INDEX) {
  dir = mkdtempSync(join(tmpdir(), 'pages-check-'));
  const all = { 'index.html': '<!doctype html>', _headers: HEADERS, 'assets/index-abc.js': 'console.log(1)', ...index, ...files };
  for (const [f, c] of Object.entries(all)) {
    if (c === null) continue;
    mkdirSync(join(dir, f, '..'), { recursive: true });
    writeFileSync(join(dir, f), c);
  }
  return dir;
}
afterEach(() => dir && rmSync(dir, { recursive: true, force: true }));

describe('production build environment guard', () => {
  it('accepts the read-only production settings', () => {
    expect(checkEnv(GOOD_ENV)).toEqual([]);
  });
  it('refuses mocks, a non-https or relative API URL, writes on, a bad timeout, a secret in VITE_*', () => {
    expect(checkEnv({ ...GOOD_ENV, VITE_USE_MOCKS: 'true' })).toHaveLength(1);
    expect(checkEnv({ ...GOOD_ENV, VITE_API_BASE_URL: 'http://localhost:8104/api/v1' })).toHaveLength(1);
    expect(checkEnv({ ...GOOD_ENV, VITE_API_BASE_URL: '/api/v1' })).toHaveLength(1);
    expect(checkEnv({ ...GOOD_ENV, VITE_API_BASE_URL: 'https://x.onrender.com/' })).toHaveLength(1);
    expect(checkEnv({ ...GOOD_ENV, VITE_PUBLIC_WRITES: undefined })).toHaveLength(1);
    expect(checkEnv({ ...GOOD_ENV, VITE_API_TIMEOUT_MS: 'abc' })).toHaveLength(1);
    expect(checkEnv({ ...GOOD_ENV, VITE_X: 'postgresql://u:p@db.example.supabase.co:5432/postgres' })[0]).toMatch(/VITE_X looks like it contains a secret/);
  });
});

describe('production dist guard', () => {
  it('passes a clean dist', () => {
    expect(checkDist(dist({}))).toEqual([]);
  });
  it('flags mock code, sourcemaps, 404.html, secrets and unfilled or test-only headers', () => {
    const p = checkDist(
      dist({
        'mockServiceWorker.js': '//',
        '404.html': 'x',
        'assets/a.js': 'localStorage.getItem("wp-mock-asleep-ms")\n//# sourceMappingURL=a.js.map',
        'assets/a.js.map': '{}',
        'assets/b.js': 'const u="postgres://user:pw@host/db"',
        _headers: HEADERS.replace('https://winterpath-api.example.onrender.com', '{{API_ORIGIN}}') + "\n# connect-src 'self' data:",
      }),
    ).join('\n');
    for (const s of ['404.html', 'mockServiceWorker.js present', 'mock code (mock-switch)', 'sourcemap', 'sourceMappingURL', 'possible secret (postgres-url)', 'unfilled placeholders', 'no https API origin'])
      expect(p).toContain(s);
    expect(p).not.toContain('pw@host'); // never echoes matched values
  });
});

describe('search index in the production bundle', () => {
  it('a dist without the index is refused unless explicitly allowed (CI)', () => {
    const d = dist({}, {});
    expect(checkDist(d)).toEqual(['search/manifest.json missing: build the index first (scripts/build-search-index.sh)']);
    expect(checkDist(d, { allowNoSearchIndex: true })).toEqual([]);
  });

  it('a present index is checked even when a missing one is allowed', () => {
    const d = dist({ 'search/v/b1/s/ga.json': '{"v":1,"e":[1]}' });
    expect(checkDist(d, { allowNoSearchIndex: true })).toEqual(['search index: 1 shard file(s) do not match their manifest sha256']);
  });

  it('flags missing shards, stale build directories, a wrong base and missing attribution', () => {
    expect(checkSearchIndex(dist({ 'search/v/b1/s/ga.json': null }))).toEqual(['search index: 1 shard file(s) listed in the manifest are missing']);
    expect(checkSearchIndex(dist({ 'search/v/old/s/ga.json': SHARD }))).toEqual(['search/v/old: stale build directory (not in the manifest)']);
    expect(checkSearchIndex(dist({ 'search/manifest.json': manifest({ base: 'v/other/' }) }))).toEqual(['search/manifest.json base does not match its build_id']);
    expect(checkSearchIndex(dist({ 'search/manifest.json': manifest({ sources: [{ id: 'rqa', licence: 'CC BY 4.0', attribution }] }) }))).toEqual([
      'search/manifest.json: source osm or its fr/en attribution and licence missing',
    ]);
    expect(checkSearchIndex(dist({ 'search/manifest.json': '<!doctype html>' }))).toEqual(['search/manifest.json is not JSON']);
    expect(checkSearchIndex(dist({ 'search/manifest.json': manifest({ format: 'other/2' }) }))).toEqual(['search/manifest.json format is not winterpath-search/1']);
  });

  it('enforces the Cloudflare Pages 25 MiB per-file limit', () => {
    const d = dist({ 'assets/big.bin': 'x'.repeat(PAGES_MAX_FILE_BYTES + 1) });
    expect(checkDist(d)).toEqual(['assets/big.bin: over the Cloudflare Pages 25 MiB file limit']);
  });
});
