/**
 * Cloudflare Pages output (v1.7 free-tier deployment):
 *  - fills public/_headers placeholders: CSP connect/img origins from the build env
 *    (API origin, map style origin, OpenFreeMap) and sha256 hashes of index.html inline scripts;
 *  - drops the MSW service worker from non-mock builds;
 *  - fails the build on sourcemaps or a 404.html (which would disable Pages' SPA fallback);
 *  - `vite preview` serves the generated headers, so e2e runs under the production CSP.
 */
import { createHash } from 'node:crypto';
import { existsSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import type { Plugin, ResolvedConfig } from 'vite';

export const OPENFREEMAP = 'https://tiles.openfreemap.org';

/** Origin of an absolute http(s) URL; null for relative/data: URLs. */
export function httpOrigin(url: string | undefined): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === 'https:' || u.protocol === 'http:' ? u.origin : null;
  } catch {
    return null;
  }
}

export function inlineScriptHashes(html: string): string[] {
  const out: string[] = [];
  for (const m of html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)) {
    out.push(`'sha256-${createHash('sha256').update(m[1] ?? '', 'utf8').digest('base64')}'`);
  }
  return out;
}

export type HeaderInputs = { apiBaseUrl?: string; mapStyleUrl?: string; useMocks: boolean; indexHtml: string };

export function fillHeaders(template: string, i: HeaderInputs): string {
  const api = i.useMocks ? null : httpOrigin(i.apiBaseUrl);
  const style = httpOrigin(i.mapStyleUrl);
  const map = [...new Set([OPENFREEMAP, style].filter(Boolean))].join(' ');
  // A data: style (e2e stub) is fetched by MapLibre, so connect-src must allow it.
  const dataStyle = i.mapStyleUrl?.startsWith('data:') ? ' data:' : '';
  const out = template
    .replaceAll('{{API_ORIGIN}}', api ?? '')
    .replaceAll('{{MAP_ORIGINS}}', map + dataStyle)
    .replaceAll('{{SCRIPT_HASHES}}', inlineScriptHashes(i.indexHtml).join(' '))
    .replace(/ {2,}(?=\S)/g, (m, off: number, s: string) => (s[off - 1] === '\n' ? m : ' '))
    .replace(/ ;/g, ';');
  if (/\{\{[A-Z_]+\}\}/.test(out)) throw new Error('_headers: unfilled placeholder');
  return out;
}

/** Minimal Cloudflare `_headers` parser (path patterns with a trailing `*`) for vite preview. */
export function parseHeaders(text: string): { pattern: string; headers: [string, string][] }[] {
  const rules: { pattern: string; headers: [string, string][] }[] = [];
  for (const line of text.split('\n')) {
    if (!line.trim() || line.trimStart().startsWith('#')) continue;
    if (!/^\s/.test(line)) rules.push({ pattern: line.trim(), headers: [] });
    else {
      const i = line.indexOf(':');
      rules.at(-1)?.headers.push([line.slice(0, i).trim(), line.slice(i + 1).trim()]);
    }
  }
  return rules;
}

const matches = (pattern: string, path: string) =>
  pattern.endsWith('*') ? path.startsWith(pattern.slice(0, -1)) : path === pattern;

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

export function cloudflarePages(env: Record<string, string | undefined>): Plugin {
  let config: ResolvedConfig;
  return {
    name: 'winterpath-cloudflare-pages',
    configResolved(c) {
      config = c;
    },
    closeBundle() {
      if (config.command !== 'build' || config.build.ssr || config.mode === 'test') return;
      const out = resolve(config.root, config.build.outDir);
      const headersPath = join(out, '_headers');
      if (!existsSync(headersPath)) return;
      const useMocks = env.VITE_USE_MOCKS === 'true';
      writeFileSync(
        headersPath,
        fillHeaders(readFileSync(headersPath, 'utf8'), {
          apiBaseUrl: env.VITE_API_BASE_URL,
          mapStyleUrl: env.VITE_MAP_STYLE_URL,
          useMocks,
          indexHtml: readFileSync(join(out, 'index.html'), 'utf8'),
        }),
      );
      if (!useMocks) rmSync(join(out, 'mockServiceWorker.js'), { force: true });
      const files = walk(out);
      // Prebuilt dependencies (e.g. MapLibre's worker) keep a sourceMappingURL comment to a map we
      // don't ship: strip it so nothing points at sourcemaps.
      for (const f of files.filter((x) => /\.(m?js|css)$/.test(x))) {
        const text = readFileSync(f, 'utf8');
        const stripped = text.replace(/\n?\/[/*][#@] sourceMappingURL=[^\n]*?(\*\/)?(?=\n|$)/g, '');
        if (stripped !== text) writeFileSync(f, stripped);
      }
      const maps = files.filter((f) => f.endsWith('.map'));
      if (maps.length) throw new Error(`public sourcemaps are not allowed: ${maps.join(', ')}`);
      if (existsSync(join(out, '404.html'))) throw new Error('404.html would disable the Cloudflare Pages SPA fallback');
    },
    configurePreviewServer(server) {
      const p = resolve(server.config.root, server.config.build.outDir, '_headers');
      if (!existsSync(p)) return;
      const rules = parseHeaders(readFileSync(p, 'utf8'));
      server.middlewares.use((req, res, next) => {
        const path = (req.url ?? '/').split('?')[0]!;
        for (const r of rules) if (matches(r.pattern, path)) for (const [k, v] of r.headers) res.setHeader(k, v);
        next();
      });
    },
  };
}
