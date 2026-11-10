// Measures gzip sizes from a built dist/: initial JS (entry + modulepreloads) vs lazy chunks.
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { join } from 'node:path';

const dir = process.argv[2] ?? 'dist';
const html = readFileSync(join(dir, 'index.html'), 'utf8');
const initial = new Set([...html.matchAll(/(?:src|href)="\/(assets\/[^"]+\.js)"/g)].map((m) => m[1]));
const gz = (f) => gzipSync(readFileSync(join(dir, f))).length;
const kb = (n) => (n / 1024).toFixed(1).padStart(8) + ' KB';

const files = readdirSync(join(dir, 'assets')).filter((f) => f.endsWith('.js')).map((f) => `assets/${f}`);
let initialTotal = 0;
const rows = files
  .map((f) => ({ f, raw: statSync(join(dir, f)).size, gz: gz(f), initial: initial.has(f) }))
  .sort((a, b) => b.gz - a.gz);
for (const r of rows) if (r.initial) initialTotal += r.gz;

console.log(`dir: ${dir}`);
console.log('initial (entry + modulepreload):');
for (const r of rows.filter((r) => r.initial)) console.log(`  ${kb(r.gz)} gz  ${r.f}`);
console.log(`  TOTAL initial JS: ${kb(initialTotal)} gz  (budget 250 KB, excludes map + 3D chunks)`);
console.log('largest lazy chunks:');
for (const r of rows.filter((r) => !r.initial).slice(0, 8)) console.log(`  ${kb(r.gz)} gz  ${r.f}`);
if (initialTotal > 250 * 1024) {
  console.error('FAIL: initial JS over budget');
  process.exit(1);
}
