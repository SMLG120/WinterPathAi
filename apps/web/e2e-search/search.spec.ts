import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const HAVE_INDEX = existsSync(join(__dirname, '../public/search/manifest.json'));
test.skip(!HAVE_INDEX, 'no local search index in public/search (built from raw data, never committed)');

async function openPlanner(page: Page, lang: 'en' | 'fr' = 'en') {
  await page.goto(`/${lang}/plan`);
  const handle = page.getByTestId('sheet-handle');
  if ((await handle.isVisible()) && (await page.getByTestId('planner-panel').getAttribute('data-snap')) === 'peek') await handle.click();
  return page.getByRole('combobox');
}

async function searchAndPick(page: Page, query: string, expected: RegExp) {
  const box = page.getByRole('combobox');
  await box.fill(query);
  const list = page.getByRole('listbox');
  await expect(list).toBeVisible();
  const first = list.getByRole('option').first();
  await expect(first).toContainText(expected);
  const text = (await first.innerText()).replace(/\s+/g, ' ');
  await box.press('ArrowDown');
  await expect(box).toHaveAttribute('aria-activedescendant', (await first.getAttribute('id'))!);
  await box.press('Enter');
  return text;
}

const CASES: { name: string; q: string; expect: RegExp; muni: RegExp; target: 'origin' | 'destination' }[] = [
  { name: 'Montréal address', q: '1455 boul De Maisonneuve O', expect: /1455 Boulevard De Maisonneuve Ouest/, muni: /Montréal/, target: 'origin' },
  { name: 'Université McGill', q: 'Université McGill', expect: /Université McGill/, muni: /Montréal/, target: 'destination' },
  { name: 'Gare Centrale', q: 'Gare Centrale', expect: /Gare Centrale/, muni: /Montréal/, target: 'destination' },
  { name: 'Laval address', q: '1555 boul Chomedey, Laval', expect: /1555 Boulevard Chomedey/, muni: /Laval/, target: 'origin' },
  { name: 'Longueuil address', q: '151 rue St-Charles O, Longueuil', expect: /151 Rue Saint-Charles Ouest/, muni: /Longueuil/, target: 'destination' },
  { name: 'Brossard address', q: '6000 boul de Rome, Brossard', expect: /6000 Boulevard de Rome/, muni: /Brossard/, target: 'destination' },
];

for (const c of CASES) {
  test(`search: ${c.name}`, async ({ page }) => {
    await openPlanner(page);
    if (c.target === 'destination') await page.getByTestId('search-fill-destination').check();
    const text = await searchAndPick(page, c.q, c.expect);
    expect(text).toMatch(c.muni);
    const label = page.getByTestId(`point-${c.target}-label`);
    await expect(label).toContainText(c.expect);
    await expect(label).toContainText(/not a confirmed walking endpoint/);
    await expect(page.getByTestId(`point-${c.target}-value`)).toHaveText(/^45\.\d{5}, -73\.\d{5}$/);
    // The existing map marker follows the store (PlannerMap is unchanged).
    await expect(page.getByTestId('planner-map').getByRole('img', { name: c.target === 'origin' ? 'Start' : 'Destination' })).toBeAttached();
  });
}

test('search: nonsense query → empty state, no listbox', async ({ page }) => {
  const box = await openPlanner(page);
  await box.fill('xqzzv wkkkp');
  await expect(page.getByTestId('search-status')).toContainText('No address or place matches “xqzzv wkkkp”');
  await expect(page.getByRole('listbox')).toBeHidden();
  await expect(box).toHaveAttribute('aria-expanded', 'false');
});

test('search: coordinates (lat, lon and lon, lat)', async ({ page }) => {
  const box = await openPlanner(page);
  await searchAndPick(page, '45.5048, -73.5772', /45\.504800, -73\.577200/);
  await expect(page.getByTestId('point-origin-value')).toHaveText('45.50480, -73.57720');
  await box.fill('-73.5700, 45.5020');
  await expect(page.getByRole('option').first()).toContainText('45.502000, -73.570000');
});

test('search: French UI, keyboard Escape, coordinate entry and map pick still present', async ({ page }) => {
  const box = await openPlanner(page, 'fr');
  await expect(page.getByText('Rechercher une adresse ou un lieu')).toBeVisible();
  await box.fill('gare centrale');
  await expect(page.getByRole('listbox')).toBeVisible();
  await expect(page.getByRole('option').first()).toContainText('OpenStreetMap (cartographie communautaire)');
  await box.press('Escape');
  await expect(page.getByRole('listbox')).toBeHidden();
  await box.press('Escape');
  await expect(box).toHaveValue('');
  await expect(page.getByTestId('origin-lat')).toBeVisible();
  await expect(page.getByTestId('point-origin').getByRole('button', { name: 'Choisir sur la carte' })).toBeVisible();
});

test('search: no axe violations with the listbox open', async ({ page }) => {
  const box = await openPlanner(page);
  await box.fill('sherbrooke');
  await expect(page.getByRole('listbox')).toBeVisible();
  const r = await new AxeBuilder({ page }).include('[data-testid="place-search"]').analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
});
