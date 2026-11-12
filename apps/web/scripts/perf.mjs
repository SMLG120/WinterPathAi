// Mobile performance probe: 390×844 viewport, 4× CPU slowdown (CDP Emulation.setCPUThrottlingRate),
// no network throttling. Run against a production (non-mock) build served by `vite preview`.
//
//   node scripts/perf.mjs [baseUrl=http://localhost:5174] [runs=5] [out.json]
//
// Per run, in a fresh browser context (cold cache):
//   landing  — LCP of /en (largest-contentful-paint, buffered), its element, TBT (sum of long-task
//              time over 50 ms until load + 3 s).
//   plan     — LCP of /en/plan; "planner usable" = the Compare button is in the DOM and enabled;
//              "map ready" = the MapLibre canvas exists and the map fired `load` (data-map-ready).
//   compare  — time from the Compare click until the result cards are visible, and until the map
//              finished fitting the route (data-map-fit), plus the map zoom after the fit.
// Prints medians and writes every raw sample to the output JSON. Nothing here is estimated.
import { readFileSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import { chromium } from '@playwright/test';

const BASE = process.argv[2] ?? 'http://localhost:5174';
const RUNS = Number(process.argv[3] ?? 5);
const OUT = process.argv[4];

// Same rule as src/test/pilotPoints.ts: endpoints of the longest non-steps pilot_mini edge.
const edges = JSON.parse(readFileSync(new URL('../../../data/fixtures/pilot_mini/edges.geojson', import.meta.url), 'utf8')).features;
const longest = edges.filter((e) => e.properties.edge_kind !== 'steps').reduce((a, b) => (b.properties.length_m > a.properties.length_m ? b : a));
const [A, B] = [longest.geometry.coordinates[0], longest.geometry.coordinates.at(-1)];

const OBSERVERS = () => {
  window.__perf = { lcp: [], long: [] };
  new PerformanceObserver((l) => {
    for (const e of l.getEntries())
      window.__perf.lcp.push({ t: e.startTime, el: e.element ? `${e.element.tagName.toLowerCase()}${e.element.dataset?.testid ? `[${e.element.dataset.testid}]` : ''}` : e.url || '?', size: e.size });
  }).observe({ type: 'largest-contentful-paint', buffered: true });
  new PerformanceObserver((l) => {
    for (const e of l.getEntries()) window.__perf.long.push({ t: e.startTime, d: e.duration });
  }).observe({ type: 'longtask', buffered: true });
};

async function newPage(browser) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true, locale: 'en-CA' });
  const page = await ctx.newPage();
  const cdp = await ctx.newCDPSession(page);
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
  await page.addInitScript(OBSERVERS);
  return { ctx, page };
}

const lcpOf = (page) =>
  page.evaluate(() => {
    const l = window.__perf.lcp.at(-1);
    const tbt = window.__perf.long.reduce((s, x) => s + Math.max(0, x.d - 50), 0);
    return { lcp: l?.t ?? null, el: l?.el ?? null, tbt };
  });

async function landing(browser) {
  const { ctx, page } = await newPage(browser);
  await page.goto(`${BASE}/en`, { waitUntil: 'load' });
  await page.waitForTimeout(3000);
  // LCP is finalised by the first input; read it before any interaction.
  const r = await lcpOf(page);
  await ctx.close();
  return r;
}

async function plan(browser) {
  const { ctx, page } = await newPage(browser);
  await page.goto(`${BASE}/en/plan`, { waitUntil: 'commit' });
  await page.getByTestId('compare').waitFor();
  await page.waitForFunction(() => !document.querySelector('[data-testid=compare]')?.hasAttribute('disabled'));
  const usable = await page.evaluate(() => performance.now());
  await page.locator('.maplibregl-canvas').waitFor({ timeout: 60_000 });
  await page.waitForFunction(() => document.querySelector('[data-testid=planner-map]')?.getAttribute('data-map-ready') === 'true' || !!document.querySelector('.maplibregl-canvas'), null, { timeout: 60_000 });
  const mapReady = await page.evaluate(() => performance.now());
  await page.waitForTimeout(1500);
  const { lcp, el, tbt } = await lcpOf(page);

  // Set both points the way a keyboard user can (coordinate entry), then compare.
  const sheetToggle = page.getByRole('button', { name: /Expand|Show/ });
  if (await sheetToggle.count()) await sheetToggle.first().click().catch(() => {});
  for (const [which, [lon, lat]] of [['origin', A], ['destination', B]]) {
    const latInput = page.getByTestId(`${which}-lat`);
    if (!(await latInput.isVisible())) await page.getByTestId(`point-${which}`).getByText(/coordinates/i).first().click().catch(() => {});
    await latInput.fill(lat.toFixed(6));
    await page.getByTestId(`${which}-lon`).fill(lon.toFixed(6));
    await page.getByTestId(`${which}-apply`).click();
  }
  const fit0 = Number((await page.getByTestId('planner-map').getAttribute('data-map-fit')) ?? 0);
  const t0 = await page.evaluate(() => performance.now());
  await page.getByTestId('compare').click();
  await page.getByTestId('compare-card').or(page.getByTestId('route-cards')).first().waitFor({ timeout: 60_000 });
  const cards = (await page.evaluate(() => performance.now())) - t0;
  let fit = null;
  let zoom = null;
  const fitAttr = await page
    // A fit newer than the one before the click (the initial pilot-area fit also sets the attribute).
    .waitForFunction((n) => Number(document.querySelector('[data-testid=planner-map]')?.getAttribute('data-map-fit') ?? 0) > n, fit0, { timeout: 15_000 })
    .then((h) => h.jsonValue())
    .catch(() => null);
  if (fitAttr) {
    fit = (await page.evaluate(() => performance.now())) - t0;
    zoom = Number(await page.getByTestId('planner-map').getAttribute('data-map-zoom'));
  }
  await ctx.close();
  return { lcp, el, tbt, usable, mapReady, cards, fit, zoom };
}

const median = (xs) => {
  const v = xs.filter((x) => typeof x === 'number').sort((a, b) => a - b);
  if (!v.length) return null;
  const m = v.length >> 1;
  return Math.round(v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2);
};

const browser = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const samples = { landing: [], plan: [] };
// Warm-up (discarded): first launch pays one-off costs (browser start, OS file cache, preview server).
await landing(browser);
await plan(browser);
const loadBefore = os.loadavg();
for (let i = 0; i < RUNS; i++) {
  samples.landing.push(await landing(browser));
  samples.plan.push(await plan(browser));
}
await browser.close();

const summary = {
  base: BASE,
  runs: RUNS,
  load_average_1m_before_after: [loadBefore[0], os.loadavg()[0]].map((x) => Math.round(x * 100) / 100),
  cpus: os.cpus().length,
  conditions: '390x844 @3x, isMobile, 4x CPU throttling (CDP), no network throttling, SwiftShader WebGL, cold context per run',
  landing: { lcp_ms: median(samples.landing.map((s) => s.lcp)), tbt_ms: median(samples.landing.map((s) => s.tbt)), lcp_elements: [...new Set(samples.landing.map((s) => s.el))] },
  plan: {
    lcp_ms: median(samples.plan.map((s) => s.lcp)),
    lcp_elements: [...new Set(samples.plan.map((s) => s.el))],
    tbt_ms: median(samples.plan.map((s) => s.tbt)),
    usable_ms: median(samples.plan.map((s) => s.usable)),
    map_ready_ms: median(samples.plan.map((s) => s.mapReady)),
    compare_to_cards_ms: median(samples.plan.map((s) => s.cards)),
    compare_to_fit_ms: median(samples.plan.map((s) => s.fit)),
    zoom_after_fit: [...new Set(samples.plan.map((s) => s.zoom))],
  },
};
console.log(JSON.stringify(summary, null, 2));
if (OUT) writeFileSync(OUT, JSON.stringify({ summary, samples }, null, 2));
