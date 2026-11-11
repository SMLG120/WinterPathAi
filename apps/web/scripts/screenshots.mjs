// Captures review screenshots from the MOCK build (every view carries the Demo-mode banner).
// Usage: VITE_USE_MOCKS=true npx vite build --outDir dist-shots && npx vite preview --outDir dist-shots --port 5174 &
//        node scripts/screenshots.mjs [baseUrl]
// Reduced motion is emulated so the static poster (not WebGL) and un-faded sections are captured.
import { mkdirSync, readFileSync } from 'node:fs';
import { chromium } from '@playwright/test';

const BASE = process.argv[2] ?? 'http://localhost:5174';
const OUT = new URL('../docs/screenshots/', import.meta.url).pathname;
mkdirSync(OUT, { recursive: true });

// Same rule as src/test/pilotPoints.ts: endpoints of the longest non-steps pilot_mini edge.
const edges = JSON.parse(readFileSync(new URL('../../../data/fixtures/pilot_mini/edges.geojson', import.meta.url), 'utf8')).features;
const longest = edges.filter((e) => e.properties.edge_kind !== 'steps').reduce((a, b) => (b.properties.length_m > a.properties.length_m ? b : a));
const ends = [longest.geometry.coordinates[0], longest.geometry.coordinates.at(-1)];

const pages = ['', 'plan', 'winter', 'reports', 'how-it-works', 'pilot'];
const variants = [
  { name: 'desktop-en-light', lang: 'en', scheme: 'light', viewport: { width: 1280, height: 800 } },
  { name: 'mobile-fr-dark', lang: 'fr', scheme: 'dark', viewport: { width: 390, height: 844 } },
];

const browser = await chromium.launch();
for (const v of variants) {
  const ctx = await browser.newContext({ viewport: v.viewport, colorScheme: v.scheme, reducedMotion: 'reduce', locale: v.lang });
  const page = await ctx.newPage();
  for (const p of pages) {
    await page.goto(`${BASE}/${v.lang}/${p}`, { waitUntil: 'networkidle' });
    await page.getByRole('heading', { level: 1 }).waitFor();
    if (p === 'plan') {
      for (const [which, [lon, lat]] of [['origin', ends[0]], ['destination', ends[1]]]) {
        await page.getByTestId(`${which}-lat`).fill(lat.toFixed(6));
        await page.getByTestId(`${which}-lon`).fill(lon.toFixed(6));
        await page.getByTestId(`${which}-apply`).click();
      }
      await page.getByTestId('compare').click();
      await page.getByTestId('compare-card').waitFor();
      await page.waitForTimeout(1500); // let map tiles/overlays settle
    }
    const file = `${OUT}${p || 'landing'}-${v.name}.png`;
    await page.screenshot({ path: file, fullPage: p !== 'plan' });
    console.log(file.replace(OUT, 'docs/screenshots/'));
  }
  await ctx.close();
}
await browser.close();
