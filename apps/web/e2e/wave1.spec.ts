import type { Page } from '@playwright/test';
import { test, expect, IN_A, IN_B, setPoint, openSheetIfMobile } from './fixtures';

const isMobile = (page: Page) => (page.viewportSize()?.width ?? 1280) < 1024;
const fitCount = async (page: Page) => Number((await page.getByTestId('planner-map').getAttribute('data-map-fit')) ?? 0);

async function compare(page: Page) {
  await page.goto('/en/plan');
  await openSheetIfMobile(page);
  await setPoint(page, 'origin', IN_A);
  await setPoint(page, 'destination', IN_B);
  await page.getByTestId('compare').click();
  await expect(page.getByTestId('route-cards')).toBeVisible();
}

test('after compare the map fits the selected route, inside the area the panel/sheet leaves visible', async ({ page }) => {
  await page.goto('/en/plan');
  await expect(page.getByTestId('planner-map')).toHaveAttribute('data-map-ready', 'true');
  await openSheetIfMobile(page);
  await setPoint(page, 'origin', IN_A);
  await setPoint(page, 'destination', IN_B);
  const map = page.getByTestId('planner-map');
  await expect(map).toHaveAttribute('data-map-fit', /\d+/); // initial pilot-area fit
  const initial = await fitCount(page);
  await page.getByTestId('compare').click();
  await expect.poll(() => fitCount(page)).toBeGreaterThan(initial);
  // Initial view is the whole pilot bbox; a fitted single route is several zoom levels closer.
  await expect.poll(async () => Number(await map.getAttribute('data-map-zoom'))).toBeGreaterThan(15);
  if (isMobile(page)) {
    // Half, not the old 85 % sheet that hid the route.
    await expect(page.getByTestId('planner-panel')).toHaveAttribute('data-snap', 'half');
    const sheet = (await page.getByTestId('planner-panel').boundingBox())!;
    const canvas = (await page.locator('.maplibregl-canvas').boundingBox())!;
    expect(sheet.y - canvas.y).toBeGreaterThan(300); // a real strip of map stays visible above the sheet
    // The results, not the form, fill the half sheet.
    await expect
      .poll(async () => (await page.getByRole('heading', { name: 'Route comparison' }).boundingBox())!.y - sheet.y)
      .toBeLessThan(120);
  }

  // Selecting the other card highlights it and re-fits the map to it.
  const before = await fitCount(page);
  await page.getByTestId('route-card-shortest').click();
  await expect(page.getByTestId('route-card-shortest')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('route-card-winter_aware')).toHaveAttribute('aria-pressed', 'false');
  await expect.poll(() => fitCount(page)).toBeGreaterThan(before);

  // Recenter re-fits too.
  const n = await fitCount(page);
  await page.getByTestId('map-recenter').click();
  await expect.poll(() => fitCount(page)).toBeGreaterThan(n);
});

test('mobile bottom sheet: tap cycles peek/half/full, arrows step, summary names the selected route', async ({ page }) => {
  test.skip(!isMobile(page), 'mobile only');
  await compare(page);
  const panel = page.getByTestId('planner-panel');
  const handle = page.getByTestId('sheet-handle');
  await expect(page.getByTestId('sheet-summary')).toContainText('Winter-aware');
  await handle.click();
  await expect(panel).toHaveAttribute('data-snap', 'full');
  await handle.click();
  await expect(panel).toHaveAttribute('data-snap', 'peek');
  // Peek: the map is usable, the summary still says what is shown.
  await expect.poll(async () => (await panel.boundingBox())!.height).toBeLessThan(100);
  await handle.focus();
  await page.keyboard.press('ArrowUp');
  await expect(panel).toHaveAttribute('data-snap', 'half');
  await page.keyboard.press('ArrowDown');
  await expect(panel).toHaveAttribute('data-snap', 'peek');
  // Large touch targets on the handle.
  expect((await handle.boundingBox())!.height).toBeGreaterThanOrEqual(44);
});

test('mobile: picking on the map lowers the sheet, then brings it back', async ({ page }) => {
  test.skip(!isMobile(page), 'mobile only');
  await page.goto('/en/plan');
  await expect(page.getByTestId('planner-map')).toHaveAttribute('data-map-ready', 'true');
  await page.getByTestId('point-origin').getByRole('button', { name: 'Pick on map' }).click();
  await expect(page.getByTestId('planner-panel')).toHaveAttribute('data-snap', 'peek');
  const c = (await page.locator('.maplibregl-canvas').boundingBox())!;
  await page.mouse.click(c.x + c.width / 2, c.y + c.height / 3);
  await expect(page.getByTestId('planner-panel')).toHaveAttribute('data-snap', 'half');
  await expect(page.getByTestId('point-origin-value')).not.toContainText('Not set');
});

test('desktop: the panel collapses and comes back, focus follows, map re-fits', async ({ page }) => {
  test.skip(isMobile(page), 'desktop only');
  await compare(page);
  const canvasW = (await page.locator('.maplibregl-canvas').boundingBox())!.width;
  const n = await fitCount(page);
  await page.getByTestId('panel-hide').click();
  await expect(page.getByTestId('planner-panel')).toBeHidden();
  await expect(page.getByTestId('panel-show')).toBeFocused();
  await expect.poll(async () => (await page.locator('.maplibregl-canvas').boundingBox())!.width).toBeGreaterThan(canvasW + 300);
  await expect.poll(() => fitCount(page)).toBeGreaterThan(n);
  await page.getByTestId('panel-show').click();
  await expect(page.getByTestId('planner-panel')).toBeVisible();
  await expect(page.getByTestId('panel-hide')).toBeFocused();
});

test('clear all and reset layers', async ({ page }) => {
  await compare(page);
  await page.getByTestId('clear-all').click();
  await expect(page.getByTestId('route-cards')).toHaveCount(0);
  await expect(page.getByTestId('point-origin-value')).toContainText('Not set');
  await expect(page.getByTestId('point-destination-value')).toContainText('Not set');
  await expect(page.getByTestId('clear-all')).toBeDisabled();

  await page.getByLabel('Sidewalk conditions').uncheck();
  await page.getByLabel('Closures & reports', { exact: true }).uncheck();
  await page.getByTestId('layers-reset').click();
  await expect(page.getByLabel('Sidewalk conditions')).toBeChecked();
  await expect(page.getByLabel('Closures & reports', { exact: true })).toBeChecked();
});

test('recent destinations: nothing stored without opt-in; opt-in keeps a rounded destination; clear and opt-out delete', async ({ page }) => {
  await compare(page);
  expect(await page.evaluate(() => localStorage.getItem('wp-recent-destinations'))).toBeNull();

  await page.getByTestId('recent-optin').check();
  await page.getByTestId('compare').click();
  await expect(page.getByTestId('recent-list').getByRole('listitem')).toHaveCount(1);
  const stored = JSON.parse((await page.evaluate(() => localStorage.getItem('wp-recent-destinations')))!) as { lat: number; lon: number }[];
  expect(stored).toHaveLength(1);
  expect(stored[0]!.lat).toBe(Math.round(Number(IN_B.lat) * 1e4) / 1e4);
  // Only the destination: the start point is never stored.
  expect(JSON.stringify(stored)).not.toContain(String(Math.round(Number(IN_A.lat) * 1e4) / 1e4));

  // Survives a reload (this device only) and fills the destination when chosen.
  await page.reload();
  await openSheetIfMobile(page);
  await page.getByTestId('recent-list').getByRole('button').first().click();
  await expect(page.getByTestId('point-destination-value')).toContainText((Math.round(Number(IN_B.lat) * 1e4) / 1e4).toFixed(4));

  await page.getByTestId('recent-clear').click();
  await expect(page.getByTestId('recent-list')).toHaveCount(0);
  await page.getByTestId('recent-optin').uncheck();
  expect(await page.evaluate(() => [localStorage.getItem('wp-recent-destinations'), localStorage.getItem('wp-recent-optin')])).toEqual([null, null]);
});

test('landing: new headline, "Plan a walk" first, live current weather with evidence; FR too', async ({ page }) => {
  await page.goto('/en');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText("Walk smarter through Montreal's winter.");
  const w = page.getByTestId('landing-weather');
  await expect(w).toContainText('°C');
  await expect(w.locator('[data-evidence]').first()).toBeVisible();
  await page.getByTestId('hero-cta').click();
  await expect(page).toHaveURL(/\/en\/plan$/);

  await page.goto('/fr');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText("Marchez plus malin dans l'hiver montréalais.");
  await expect(page.getByTestId('hero-cta')).toHaveText(/Planifier une marche/);
});

test('landing: weather outage shows no values, and the call to action still works', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('wp-mock-upstream', 'weather'));
  await page.goto('/en');
  await expect(page.getByTestId('landing-weather-unavailable')).toBeVisible();
  await expect(page.getByTestId('landing-weather')).not.toContainText('°C');
  await page.getByTestId('hero-cta').click();
  await expect(page).toHaveURL(/\/en\/plan$/);
});
