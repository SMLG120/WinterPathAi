// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { fillHeaders, inlineScriptHashes, parseHeaders } from './cloudflarePages';

const template = readFileSync(new URL('../public/_headers', import.meta.url), 'utf8');
const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const csp = (text: string) =>
  Object.fromEntries(
    parseHeaders(text)
      .find((r) => r.pattern === '/*')!
      .headers.find(([k]) => k === 'Content-Security-Policy')![1]
      .split(';')
      .map((d) => d.trim().split(/\s+/))
      .map(([k, ...v]) => [k, v]),
  );

describe('Cloudflare Pages _headers', () => {
  const prod = fillHeaders(template, {
    apiBaseUrl: 'https://winterpath-api.example.onrender.com/api/v1',
    mapStyleUrl: undefined,
    useMocks: false,
    indexHtml: html,
  });

  it('CSP: self, the API origin from the build, OpenFreeMap, blob: workers; no unsafe-eval; frame-ancestors none', () => {
    const c = csp(prod);
    expect(c['default-src']).toEqual(["'self'"]);
    expect(c['connect-src']).toEqual(["'self'", 'https://winterpath-api.example.onrender.com', 'https://tiles.openfreemap.org']);
    expect(c['img-src']).toContain('https://tiles.openfreemap.org');
    expect(c['worker-src']).toEqual(["'self'", 'blob:']);
    expect(c['frame-ancestors']).toEqual(["'none'"]);
    expect(c['object-src']).toEqual(["'none'"]);
    expect(c['script-src']).not.toContain("'unsafe-eval'");
    expect(c['script-src']).not.toContain("'unsafe-inline'");
    // The inline theme script in index.html is allowed by hash only.
    expect(inlineScriptHashes(html)).toHaveLength(1);
    expect(c['script-src']).toEqual(["'self'", ...inlineScriptHashes(html)]);
  });

  it('other security headers and long-lived /assets/* cache', () => {
    const rules = parseHeaders(prod);
    const all = Object.fromEntries(rules.find((r) => r.pattern === '/*')!.headers);
    expect(all['X-Content-Type-Options']).toBe('nosniff');
    expect(all['Referrer-Policy']).toBe('strict-origin-when-cross-origin');
    expect(all['Permissions-Policy']).toMatch(/(^|, )geolocation=\(self\)/);
    expect(all['Permissions-Policy']).toMatch(/camera=\(\)/);
    const assets = Object.fromEntries(rules.find((r) => r.pattern === '/assets/*')!.headers);
    expect(assets['Cache-Control']).toBe('public, max-age=31536000, immutable');
    expect(prod).not.toMatch(/\{\{/);
  });

  it('mock builds do not add an API origin; a data: map style is allowed for MapLibre to fetch', () => {
    const c = csp(fillHeaders(template, { apiBaseUrl: 'https://x.example/api/v1', mapStyleUrl: 'data:application/json,{}', useMocks: true, indexHtml: html }));
    expect(c['connect-src']).toEqual(["'self'", 'https://tiles.openfreemap.org', 'data:']);
  });

  it('a custom map style origin is added next to OpenFreeMap', () => {
    const c = csp(fillHeaders(template, { apiBaseUrl: '/api/v1', mapStyleUrl: 'https://tiles.example.org/style.json', useMocks: false, indexHtml: html }));
    expect(c['connect-src']).toEqual(["'self'", 'https://tiles.openfreemap.org', 'https://tiles.example.org']);
  });
});
