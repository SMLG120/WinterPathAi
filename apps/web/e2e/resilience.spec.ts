import type { Page } from '@playwright/test';
import { test, expect, IN_A, IN_B, setPoint, openSheetIfMobile } from './fixtures';

/** Mock-only failure switches (src/mocks/handlers.ts) and the mock-only wake budget override (src/lib/env.ts). */
async function flags(page: Page, f: Record<string, string>) {
  await page.addInitScript((kv) => {
    for (const [k, v] of Object.entries(kv)) localStorage.setItem(k, v);
  }, f);
}

async function compare(page: Page) {
  await page.goto('/en/plan');
  await openSheetIfMobile(page);
  await setPoint(page, 'origin', IN_A);
  await setPoint(page, 'destination', IN_B);
  await page.getByTestId('compare').click();
}

test('cold start: "server is waking up" while the host sleeps, then real data once it answers', async ({ page }) => {
  await flags(page, { 'wp-mock-asleep-ms': '5000' });
  await page.goto('/en/how-it-works');
  await expect(page.getByTestId('backend-waking')).toContainText('The server is waking up');
  // No invented content while waiting: the sources table only appears once the API answers.
  await expect(page.getByRole('table')).toHaveCount(0);
  await expect(page.getByRole('table').first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('backend-waking')).toHaveCount(0);
});

test('cold start that never ends: bounded retry, then a clear error with a retry button that works', async ({ page }) => {
  await flags(page, { 'wp-mock-asleep-ms': '600000', 'wp-mock-wake-budget-ms': '4000' });
  await compare(page);
  await expect(page.getByTestId('compare-waking')).toContainText('Waking the server');
  const err = page.getByTestId('route-error');
  await expect(err).toHaveAttribute('data-kind', 'WAKE_TIMEOUT', { timeout: 15_000 });
  await expect(err).toContainText("didn't wake up");
  await expect(page.getByTestId('compare-card')).toHaveCount(0);
  await expect(page.getByTestId('backend-waking')).toHaveCount(0);

  // The host wakes up; the user retries.
  await page.evaluate(() => localStorage.removeItem('wp-mock-asleep-ms'));
  await page.getByTestId('route-retry').click();
  await expect(page.getByTestId('compare-card')).toBeVisible();
  await expect(page.getByTestId('route-error')).toHaveCount(0);
});

test('data views: cold-start give-up shows the reason and a retry button (FR)', async ({ page }) => {
  await flags(page, { 'wp-mock-asleep-ms': '600000', 'wp-mock-wake-budget-ms': '3000' });
  await page.goto('/fr/how-it-works');
  await expect(page.getByText("Le serveur ne s'est pas réveillé à temps.").first()).toBeVisible({ timeout: 15_000 });
  await page.evaluate(() => localStorage.removeItem('wp-mock-asleep-ms'));
  await page.getByRole('button', { name: 'Réessayer' }).first().click();
  await expect(page.getByRole('table').first()).toBeVisible();
});

test('external provider unavailable (503 UPSTREAM_UNAVAILABLE): weather says so, shows no values', async ({ page }) => {
  await flags(page, { 'wp-mock-upstream': 'weather' });
  await page.goto('/en/winter');
  await expect(page.getByText(/An external data provider \(such as Environment Canada weather\) is unavailable/).first()).toBeVisible();
  await expect(page.getByTestId('backend-waking')).toHaveCount(0); // a live API answered: not a cold start
});

test('compare: distinct copy for upstream unavailable and for an incomplete answer — never a partial result', async ({ page }) => {
  await flags(page, { 'wp-mock-upstream': 'compare' });
  await compare(page);
  await expect(page.getByTestId('route-error')).toHaveAttribute('data-kind', 'UPSTREAM_UNAVAILABLE');
  await expect(page.getByTestId('route-error')).toContainText('A data source is unavailable');

  await page.evaluate(() => {
    localStorage.removeItem('wp-mock-upstream');
    localStorage.setItem('wp-mock-incomplete', 'compare');
  });
  await page.getByTestId('route-retry').click();
  await expect(page.getByTestId('route-error')).toHaveAttribute('data-kind', 'INCOMPLETE');
  await expect(page.getByTestId('route-error')).toContainText('Incomplete answer');
  await expect(page.getByTestId('compare-card')).toHaveCount(0);
});

test('API answers 503 WRITES_DISABLED: report and pilot forms turn into the public-demo notice', async ({ page }) => {
  await flags(page, { 'wp-mock-writes': 'off' });
  await page.goto('/en/reports');
  await page.getByLabel('What did you see?').selectOption('ice');
  await page.getByLabel('Latitude').fill('45.5048');
  await page.getByLabel('Longitude').fill('-73.5772');
  await page.getByLabel('I consent to sending this exact location with my report.').check();
  await page.getByTestId('report-submit').click();
  await expect(page.getByTestId('writes-disabled')).toContainText('Not available in this public demo');
  await expect(page.getByTestId('report-form')).toHaveCount(0);
  await expect(page.getByTestId('report-receipt')).toHaveCount(0);

  await page.goto('/fr/pilot');
  await page.getByLabel('Organisation', { exact: true }).fill('Université test');
  await page.getByLabel('Courriel', { exact: true }).fill('contact@example.org');
  await page.getByLabel("Type d'organisation").selectOption('university');
  await page.getByLabel(/J'accepte/).check();
  await page.getByRole('button', { name: 'Envoyer la demande' }).click();
  await expect(page.getByTestId('writes-disabled')).toContainText('Non disponible dans cette démo publique');
  await expect(page.getByTestId('pilot-success')).toHaveCount(0);
});

test('production headers are served by preview and the app runs without CSP violations', async ({ page }) => {
  await page.addInitScript(() => {
    (window as unknown as { __csp: string[] }).__csp = [];
    document.addEventListener('securitypolicyviolation', (e) =>
      (window as unknown as { __csp: string[] }).__csp.push(`${e.violatedDirective} ${e.blockedURI}`),
    );
  });
  const res = await page.goto('/en');
  const csp = res!.headers()['content-security-policy'] ?? '';
  expect(csp).toContain("frame-ancestors 'none'");
  expect(csp).toContain("worker-src 'self' blob:");
  expect(res!.headers()['x-content-type-options']).toBe('nosniff');
  expect(res!.headers()['permissions-policy']).toContain('geolocation=(self)');

  const violations = () => page.evaluate(() => (window as unknown as { __csp: string[] }).__csp);
  await page.waitForTimeout(500);
  expect(await violations()).toEqual([]);

  await compare(page); // MapLibre (blob: worker) + planner
  await expect(page.getByTestId('compare-card')).toBeVisible();
  await expect(page.locator('.maplibregl-canvas')).toBeVisible();
  expect(await violations()).toEqual([]);

  await page.goto('/en/how-it-works'); // 3D explainer (WebGL)
  await page.getByTestId('condition-explainer').scrollIntoViewIfNeeded();
  await expect(page.getByTestId('explainer-stage').locator('canvas')).toHaveCount(1, { timeout: 15_000 });
  expect(await violations()).toEqual([]);

  await page.goto('/en/reports'); // zod form (jitless)
  await page.getByTestId('report-submit').click();
  await expect(page.getByText('You need to consent to sending the location.')).toBeVisible();
  expect(await violations()).toEqual([]);
});
