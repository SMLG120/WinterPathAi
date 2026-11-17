/**
 * Place search → route compare against a REAL API serving the island graph.
 * Opt-in: E2E_ISLAND=1, an API on E2E_API_BASE_URL started with the island artifact, and a local
 * search index in public/search (never committed). Not run by the default real-API suite.
 */
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test, expect, type Page } from '@playwright/test';

const HERE = fileURLToPath(new URL('.', import.meta.url));
const HAVE_INDEX = existsSync(join(HERE, '../public/search/manifest.json'));
test.skip(process.env.E2E_ISLAND !== '1' || !HAVE_INDEX, 'needs E2E_ISLAND=1, an island-graph API and a local search index');

async function pick(page: Page, target: 'origin' | 'destination', query: string, expected: RegExp) {
  await page.getByTestId(`search-fill-${target}`).check();
  const box = page.getByTestId('search-input');
  await box.fill(query);
  const first = page.getByRole('listbox').getByRole('option').first();
  await expect(first).toContainText(expected);
  await box.press('ArrowDown');
  await box.press('Enter');
  await expect(page.getByTestId(`point-${target}-label`)).toContainText(expected);
}

test('searched island places route; unknown winter data is stated, never "safe"', async ({ page }) => {
  await page.goto('/en/plan');
  await pick(page, 'origin', 'Université McGill', /McGill/);
  await pick(page, 'destination', 'Gare Centrale', /Gare Centrale/);
  await page.getByTestId('compare').click();
  await expect(page.getByTestId('route-card-shortest')).toBeVisible();
  await expect(page.getByTestId('route-cards')).toContainText(/unknown/i);
  await expect(page.getByTestId('route-cards')).not.toContainText(/\bsafe\b|ice-free|cleared/i);
});

for (const [city, query] of [
  ['Laval', '1555 boul Chomedey, Laval'],
  ['Longueuil', '151 rue St-Charles O, Longueuil'],
  ['Terrebonne', '1000 boul des Seigneurs, Terrebonne'],
] as const) {
  test(`searched ${city} address is found but reported outside routing coverage`, async ({ page }) => {
    await page.goto('/en/plan');
    await pick(page, 'origin', 'Université McGill', /McGill/);
    await pick(page, 'destination', query, new RegExp(city === 'Laval' ? 'Chomedey' : city === 'Longueuil' ? 'Saint-Charles' : 'Seigneurs'));
    await page.getByTestId('compare').click();
    const err = page.getByTestId('route-error');
    await expect(err).toHaveAttribute('data-kind', 'OUTSIDE_COVERAGE');
    await expect(err).toContainText('Outside the coverage area');
    await expect(err).not.toContainText('75 m');
  });
}
