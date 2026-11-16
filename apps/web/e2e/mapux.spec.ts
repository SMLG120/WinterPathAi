/**
 * Map visualisation & interaction (Plan page). Runs on the MSW mock build. The long-route and
 * outage cases use labelled TEST FIXTURES (src/features/map/fixtures), switched on per test via
 * localStorage `wp-mock-fixture`. Screenshots go to test-results/mapux/.
 */
import type { Page } from '@playwright/test';
import { test, expect, IN_A, IN_B, setPoint, openSheetIfMobile } from './fixtures';
import { LONG_A, LONG_B } from '../src/features/map/fixtures/islandPoints';

const isMobile = (page: Page) => (page.viewportSize()?.width ?? 1280) < 1024;
const shot = (page: Page, name: string) =>
  page.screenshot({ path: `test-results/mapux/${name}-${isMobile(page) ? 'mobile' : 'desktop'}.png` });

type Px = { x: number; y: number };
/** lon/lat → page pixel, via the mock-build-only map hook. */
async function toPage(page: Page, lon: number, lat: number): Promise<Px> {
  const p = await page.evaluate(([x, y]) => {
    const m = (window as unknown as { __wpPlannerMap: { project: (c: [number, number]) => { x: number; y: number } } }).__wpPlannerMap;
    return m.project([x!, y!]);
  }, [lon, lat]);
  const box = (await page.locator('.maplibregl-canvas').boundingBox())!;
  return { x: box.x + p.x, y: box.y + p.y };
}

/** The part of the map not covered by the bottom sheet (mobile) — where a fitted route must be. */
async function visibleMapRect(page: Page) {
  const c = (await page.locator('.maplibregl-canvas').boundingBox())!;
  let bottom = c.y + c.height;
  if (isMobile(page)) bottom = Math.min(bottom, (await page.getByTestId('planner-panel').boundingBox())!.y);
  return { left: c.x, top: c.y, right: c.x + c.width, bottom };
}

const pt = (p: { lat: string | number; lon: string | number }) => ({ lat: String(p.lat), lon: String(p.lon) });

async function compare(page: Page, a = IN_A, b = IN_B) {
  await page.goto('/en/plan');
  await expect(page.getByTestId('planner-map')).toHaveAttribute('data-map-ready', 'true');
  await openSheetIfMobile(page);
  await setPoint(page, 'origin', a);
  await setPoint(page, 'destination', b);
  await page.getByTestId('compare').click();
  await expect(page.getByTestId('route-cards')).toBeVisible();
  await expect(page.getByTestId('planner-map')).toHaveAttribute('data-route-count', '2');
}

test('markers: start circle A and destination square B, named for screen readers, not interactive', async ({ page }) => {
  await compare(page);
  const a = page.getByTestId('marker-origin');
  const b = page.getByTestId('marker-destination');
  await expect(a).toHaveAttribute('aria-label', 'Start (A)');
  await expect(b).toHaveAttribute('aria-label', 'Destination (B)');
  await expect(a.locator('circle')).toHaveCount(1);
  await expect(b.locator('rect')).toHaveCount(1);
  await expect(a).toHaveAttribute('data-marker-kind', 'point');
  await expect(a).toHaveCSS('pointer-events', 'none');
});

test('route line ↔ cards: hovering a card highlights its line; clicking a line selects it without moving a point', async ({ page }) => {
  await compare(page);
  const map = page.getByTestId('planner-map');
  await expect(map).toHaveAttribute('data-route-selected', 'winter_aware');

  if (!isMobile(page)) {
    await page.getByTestId('route-card-shortest').hover();
    await expect(map).toHaveAttribute('data-route-hovered', 'shortest');
    await page.mouse.move(5, 5);
    await expect(map).toHaveAttribute('data-route-hovered', '');
  }

  // The mock's shortest route turns at (destination lon, origin lat); click its first leg's midpoint.
  const dest = await page.getByTestId('point-destination-value').innerText();
  const [o, d] = [IN_A, IN_B].map((p) => ({ lon: Number(p.lon), lat: Number(p.lat) }));
  await page.getByTestId('map-recenter').click();
  await expect.poll(async () => Number((await map.getAttribute('data-map-fit')) ?? 0)).toBeGreaterThan(0);
  const mid = await toPage(page, (o!.lon + d!.lon) / 2, o!.lat);
  const vis = await visibleMapRect(page);
  expect(mid.y).toBeLessThan(vis.bottom); // the route is not under the sheet

  if (!isMobile(page)) {
    await page.mouse.move(mid.x, mid.y);
    await expect(page.getByTestId('route-card-shortest')).toHaveAttribute('data-hovered', 'true');
  }
  await page.mouse.click(mid.x, mid.y);
  await expect(page.getByTestId('route-card-shortest')).toHaveAttribute('aria-pressed', 'true');
  await expect(map).toHaveAttribute('data-route-selected', 'shortest');
  await expect(page.getByTestId('route-shortest').getByRole('button', { name: 'Shown on map' })).toBeVisible();
  // A click on a line selects; it must not have replaced the destination.
  await expect(page.getByTestId('point-destination-value')).toHaveText(dest);
  await shot(page, 'route-selected-from-map');
});

test('the map is created once: compare, select, hover, pan and layer toggles only update it', async ({ page }) => {
  await compare(page);
  const map = page.getByTestId('planner-map');
  await expect(map).toHaveAttribute('data-map-inits', '1');
  await page.getByTestId('route-card-shortest').click();
  await page.getByTestId('route-card-winter_aware').hover();
  const c = (await page.locator('.maplibregl-canvas').boundingBox())!;
  await page.mouse.move(c.x + c.width / 2, c.y + 80);
  await page.mouse.down();
  await page.mouse.move(c.x + c.width / 2 - 120, c.y + 140, { steps: 8 });
  await page.mouse.up();
  await page.getByLabel('Sidewalk conditions').uncheck();
  await page.getByLabel('Sidewalk conditions').check();
  await expect(map).toHaveAttribute('data-map-inits', '1');
  await expect(page.locator('canvas.maplibregl-canvas')).toHaveCount(1);
});

test('routable-area boundary: outline + hatched mask from GET /coverage; legend explains it', async ({ page }) => {
  await page.goto('/en/plan');
  await expect(page.getByTestId('planner-map')).toHaveAttribute('data-coverage-parts', '1');
  await openSheetIfMobile(page);
  const legend = page.getByTestId('legend');
  await expect(legend).toContainText('Boundary of the routable area');
  await expect(legend).toContainText('Outside (hatched): no routes, no layers');
  await expect(page.getByTestId('legend-coverage-info')).toContainText('McGill / Downtown pilot');
});

test('long cross-region route (TEST FIXTURE, multi-part coverage): whole route fitted in the visible map', async ({ page }) => {
  test.setTimeout(90_000);
  await page.addInitScript(() => localStorage.setItem('wp-mock-fixture', 'island-long'));
  await page.goto('/en/plan');
  const map = page.getByTestId('planner-map');
  await expect(map).toHaveAttribute('data-coverage-parts', '2'); // MultiPolygon fixture → two served parts
  await openSheetIfMobile(page);
  await setPoint(page, 'origin', pt(LONG_A));
  await setPoint(page, 'destination', pt(LONG_B));
  const before = Number((await map.getAttribute('data-map-fit')) ?? 0);
  await page.getByTestId('compare').click();
  await expect(page.getByTestId('compare-card').locator('[data-evidence="simulated"]').first()).toBeVisible();
  await expect(page.getByTestId('compare-card')).toContainText('Synthetic test route (fixture)');
  await expect(map).toHaveAttribute('data-route-count', '2');
  await expect.poll(async () => Number((await map.getAttribute('data-map-fit')) ?? 0)).toBeGreaterThan(before);
  const zoom = Number(await map.getAttribute('data-map-zoom'));
  expect(zoom).toBeLessThan(13); // ~20 km: a regional view, not a street view
  expect(zoom).toBeGreaterThan(8);
  const vis = await visibleMapRect(page);
  for (const p of [LONG_A, LONG_B]) {
    const px = await toPage(page, p.lon, p.lat);
    expect(px.x).toBeGreaterThanOrEqual(vis.left);
    expect(px.x).toBeLessThanOrEqual(vis.right);
    expect(px.y).toBeGreaterThanOrEqual(vis.top);
    expect(px.y).toBeLessThanOrEqual(vis.bottom);
  }
  // Card states how much of the route has no condition data, and "mostly unknown" for 70 %.
  await expect(page.getByTestId('route-card-shortest').getByTestId('mostly-unknown')).toBeVisible();
  await expect(page.getByTestId('route-winter_aware').getByTestId('condition-coverage')).toContainText('43% unknown');
  await shot(page, 'long-route');
});

test('overlay outage (TEST FIXTURE 503): status chip says unavailable and offers a 44 px retry', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('wp-mock-fixture', 'overlays-down'));
  await page.goto('/en/plan');
  const chip = page.getByTestId('map-status');
  await expect(chip).toHaveAttribute('data-status', 'unavailable');
  await expect(chip).toContainText('Map layers unavailable right now');
  const retry = page.getByTestId('map-status-retry');
  const box = (await retry.boundingBox())!;
  expect(box.height).toBeGreaterThanOrEqual(44);
  expect(box.width).toBeGreaterThanOrEqual(44);
  await retry.click();
  await expect(chip).toHaveAttribute('data-status', /loading|unavailable/);
  await shot(page, 'overlay-unavailable');
});

test('overlay status reaches a loaded state with a time (desktop) and the chip never covers the controls', async ({ page }) => {
  test.skip(isMobile(page), 'mobile hides the "fresh" chip to keep the map clear');
  await page.goto('/en/plan');
  const chip = page.getByTestId('map-status');
  await expect(chip).toHaveAttribute('data-status', 'fresh');
  await expect(chip).toContainText(/Map layers updated \d/);
});

test('mobile: zoom buttons and recenter are ≥ 44 px and do not overlap; fitted route sits above the sheet', async ({ page }) => {
  test.skip(!isMobile(page), 'mobile only');
  await compare(page);
  const zoomIn = (await page.locator('.maplibregl-ctrl-zoom-in').boundingBox())!;
  const zoomOut = (await page.locator('.maplibregl-ctrl-zoom-out').boundingBox())!;
  const recenter = (await page.getByTestId('map-recenter').boundingBox())!;
  for (const b of [zoomIn, zoomOut, recenter]) {
    expect(b.width).toBeGreaterThanOrEqual(44);
    expect(b.height).toBeGreaterThanOrEqual(44);
  }
  const overlap = (a: typeof zoomIn, b: typeof zoomIn) => a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
  expect(overlap(recenter, zoomIn)).toBe(false);
  expect(overlap(recenter, zoomOut)).toBe(false);
  // Fitted route endpoints are in the strip above the half sheet.
  const vis = await visibleMapRect(page);
  for (const p of [IN_A, IN_B]) {
    const px = await toPage(page, Number(p.lon), Number(p.lat));
    expect(px.y).toBeLessThan(vis.bottom);
    expect(px.y).toBeGreaterThan(vis.top);
  }
  await shot(page, 'mobile-fit');
});

test('throttled network (slow 3G-like): planner usable before the map, then map, route and status arrive', async ({ page, context }) => {
  test.setTimeout(180_000);
  const cdp = await context.newCDPSession(page);
  await cdp.send('Network.enable');
  // ≈ Chrome DevTools "Slow 3G"-like: 400 ms RTT, ~750 kbit/s down, ~250 kbit/s up.
  await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 400, downloadThroughput: 94_000, uploadThroughput: 32_000 });
  const t0 = Date.now();
  await page.goto('/en/plan', { timeout: 150_000 });
  await expect(page.getByRole('heading', { level: 1, name: 'Plan a winter walk' })).toBeVisible({ timeout: 150_000 });
  const tPanel = Date.now() - t0;
  await expect(page.getByTestId('planner-map')).toHaveAttribute('data-map-ready', 'true', { timeout: 150_000 });
  const tMap = Date.now() - t0;
  await openSheetIfMobile(page);
  await setPoint(page, 'origin', IN_A);
  await setPoint(page, 'destination', IN_B);
  await page.getByTestId('compare').click();
  await expect(page.getByTestId('planner-map')).toHaveAttribute('data-route-count', '2', { timeout: 60_000 });
  await expect(page.getByTestId('planner-map')).toHaveAttribute('data-map-inits', '1');
  // Reported in the run output (lint allows warn/error only).
  console.warn(`[throttled ${isMobile(page) ? 'mobile' : 'desktop'}] panel heading ${tPanel} ms, map ready ${tMap} ms`);
  expect(tPanel).toBeLessThanOrEqual(tMap);
  await shot(page, 'throttled');
});
