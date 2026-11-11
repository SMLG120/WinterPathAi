/**
 * Guard for the Cloudflare Pages production bundle (docs/SECURITY.md: "production build made with
 * VITE_USE_MOCKS unset — not yet enforced"). Used by `npm run build:pages`:
 *   node build/pagesCheck.ts env   → refuses an unsafe build environment (before building)
 *   node build/pagesCheck.ts dist  → scans the built dist/ (after building)
 * Exit code 1 with a list of problems; prints only file names and rule ids, never matched values.
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

export function checkEnv(env: Record<string, string | undefined>): string[] {
  const p: string[] = [];
  if (env.VITE_USE_MOCKS === 'true') p.push('VITE_USE_MOCKS must be unset/false for a production build');
  const api = env.VITE_API_BASE_URL ?? '';
  let url: URL | null = null;
  try {
    url = new URL(api);
  } catch {
    /* not absolute */
  }
  if (!url || url.protocol !== 'https:') p.push('VITE_API_BASE_URL must be an absolute https:// URL (the Render API)');
  else if (!url.pathname.replace(/\/$/, '').endsWith('/api/v1')) p.push('VITE_API_BASE_URL must end with /api/v1');
  if (env.VITE_PUBLIC_WRITES !== 'false') p.push('VITE_PUBLIC_WRITES must be "false" (user decision: read-only public demo)');
  const t = env.VITE_API_TIMEOUT_MS;
  if (t !== undefined && t !== '' && !(Number(t) > 0)) p.push('VITE_API_TIMEOUT_MS must be a positive number of milliseconds');
  for (const [k, v] of Object.entries(env)) {
    if (k.startsWith('VITE_') && v && SECRET_RULES.some(([, re]) => re.test(v))) p.push(`${k} looks like it contains a secret; VITE_* values are public`);
  }
  return p;
}

/** Patterns that must never appear in a public bundle. */
export const SECRET_RULES: [string, RegExp][] = [
  ['postgres-url', /postgres(?:ql)?:\/\/[^\s"'`]+@/i],
  ['private-key', /-----BEGIN [A-Z ]*PRIVATE KEY-----/],
  ['jwt', /eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/],
  ['supabase-service-role', /service_role/],
  ['admin-token-env', /API_ADMIN_TOKEN/],
  ['database-url-env', /DATABASE_URL/],
];

/** Code that only exists in mock builds (MSW worker, e2e switches). An i18n string naming the fixture is fine. */
const MOCK_RULES: [string, RegExp][] = [
  ['msw-setupWorker', /setupWorker/],
  ['msw-worker-file', /mockServiceWorker/],
  ['mock-switch', /wp-mock-/],
];

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

export function checkDist(dir: string): string[] {
  const p: string[] = [];
  if (!existsSync(join(dir, 'index.html'))) return [`${dir}/index.html missing — build first`];
  if (existsSync(join(dir, '404.html'))) p.push('404.html present: disables the Pages SPA fallback');
  if (existsSync(join(dir, 'mockServiceWorker.js'))) p.push('mockServiceWorker.js present: mock build?');
  const headersPath = join(dir, '_headers');
  if (!existsSync(headersPath)) p.push('_headers missing');
  else {
    const h = readFileSync(headersPath, 'utf8');
    if (/\{\{[A-Z_]+\}\}/.test(h)) p.push('_headers has unfilled placeholders');
    const connect = /connect-src ([^;]+)/.exec(h)?.[1] ?? '';
    if (!connect.split(/\s+/).some((s) => s.startsWith('https://') && s !== 'https://tiles.openfreemap.org'))
      p.push('_headers CSP connect-src has no https API origin');
    if (/connect-src[^;]*\bdata:/.test(h)) p.push('_headers CSP allows data: in connect-src (e2e stub map style?)');
    for (const need of ["frame-ancestors 'none'", 'X-Content-Type-Options: nosniff', 'geolocation=(self)', 'max-age=31536000, immutable'])
      if (!h.includes(need)) p.push(`_headers missing: ${need}`);
  }
  for (const f of walk(dir)) {
    const rel = relative(dir, f);
    if (f.endsWith('.map')) p.push(`${rel}: sourcemap`);
    if (!/\.(js|mjs|css|html|json|txt|svg|webmanifest)$/.test(f) && !rel.endsWith('_headers')) continue;
    const text = readFileSync(f, 'utf8');
    if (/sourceMappingURL=/.test(text)) p.push(`${rel}: sourceMappingURL comment`);
    for (const [id, re] of MOCK_RULES) if (re.test(text)) p.push(`${rel}: mock code (${id})`);
    for (const [id, re] of SECRET_RULES) if (re.test(text)) p.push(`${rel}: possible secret (${id})`);
  }
  return p;
}

const isMain = import.meta.url === `file://${process.argv[1]}`;
if (isMain) {
  const mode = process.argv[2];
  const problems = mode === 'env' ? checkEnv(process.env) : mode === 'dist' ? checkDist(process.argv[3] ?? 'dist') : ['usage: node build/pagesCheck.ts env|dist [dir]'];
  if (problems.length) {
    console.error(`pages-check ${mode}: FAILED\n` + problems.map((x) => `  - ${x}`).join('\n'));
    process.exit(1);
  }
  process.stdout.write(`pages-check ${mode}: OK\n`);
}
