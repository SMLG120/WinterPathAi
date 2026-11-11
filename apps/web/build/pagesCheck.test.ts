// @vitest-environment node
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { checkDist, checkEnv } from './pagesCheck';

const GOOD_ENV = { VITE_API_BASE_URL: 'https://winterpath-api.example.onrender.com/api/v1', VITE_PUBLIC_WRITES: 'false' };
const HEADERS = `/*
  Content-Security-Policy: default-src 'self'; connect-src 'self' https://winterpath-api.example.onrender.com https://tiles.openfreemap.org; frame-ancestors 'none'
  X-Content-Type-Options: nosniff
  Permissions-Policy: geolocation=(self), camera=()

/assets/*
  Cache-Control: public, max-age=31536000, immutable
`;

let dir = '';
function dist(files: Record<string, string>) {
  dir = mkdtempSync(join(tmpdir(), 'pages-check-'));
  for (const [f, c] of Object.entries({ 'index.html': '<!doctype html>', _headers: HEADERS, 'assets/index-abc.js': 'console.log(1)', ...files })) {
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
