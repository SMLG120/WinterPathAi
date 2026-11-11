import { test, expect, IN_A, IN_B, OUTSIDE, OFF_NET, setPoint, openSheetIfMobile } from './fixtures';

const COPY = {
  en: { title: 'Plan a winter walk', results: 'Route comparison', sim: 'SIMULATED', demo: 'Demo data', winter: 'Winter-aware' },
  fr: { title: 'Planifier une marche hivernale', results: 'Comparaison des trajets', sim: 'SIMULÉ', demo: 'Données de démo', winter: "Adapté à l'hiver" },
} as const;

for (const lang of ['en', 'fr'] as const) {
  test(`planning journey against mocks (${lang})`, async ({ page }) => {
    const c = COPY[lang];
    await page.goto(`/${lang}/plan`);
    await expect(page.getByRole('heading', { level: 1, name: c.title })).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('lang', lang === 'fr' ? 'fr-CA' : 'en-CA');
    await expect(page.getByTestId('demo-banner')).toBeVisible();
    await openSheetIfMobile(page);

    await setPoint(page, 'origin', IN_A);
    await setPoint(page, 'destination', IN_B);
    await page.getByTestId('compare').click();

    const card = page.getByTestId('compare-card');
    await expect(card.getByRole('heading', { name: c.results })).toBeVisible();
    await expect(card.getByTestId('demo-badge')).toHaveText(new RegExp(c.demo));
    await expect(card.getByTestId('route-winter_aware')).toContainText(c.winter);
    await expect(card.getByTestId('route-shortest')).toBeVisible();
    await expect(card.locator('[data-evidence="simulated"]').first()).toContainText(c.sim);
    await expect(card.getByTestId('steps-winter_aware').getByRole('listitem').first()).toBeVisible();

    // Overlay text alternative is populated from /hazards by viewport bbox.
    await expect(page.getByTestId('hazard-list').getByRole('listitem').first()).toBeVisible();
  });
}

test('language switch preserves route and re-localises results', async ({ page }) => {
  await page.goto('/en/plan');
  await openSheetIfMobile(page);
  await setPoint(page, 'origin', IN_A);
  await setPoint(page, 'destination', IN_B);
  await page.getByTestId('compare').click();
  await expect(page.getByTestId('compare-card')).toContainText('Simulated demo explanation');

  // Language link lives in the header.
  await page.getByTestId('lang-switch').click();
  await expect(page).toHaveURL(/\/fr\/plan$/);
  await expect(page.locator('html')).toHaveAttribute('lang', 'fr-CA');
  await expect(page.getByTestId('compare-card')).toContainText('Explication de démonstration simulée');
  // Points are kept in memory across the switch.
  await expect(page.getByTestId('point-origin-value')).toContainText('45.50480');
});

test('outside coverage shows helpful 422 copy', async ({ page }) => {
  await page.goto('/en/plan');
  await openSheetIfMobile(page);
  await setPoint(page, 'origin', OUTSIDE);
  await expect(page.getByTestId('point-origin')).toContainText('outside the pilot area');
  await setPoint(page, 'destination', IN_B);
  await page.getByTestId('compare').click();
  const err = page.getByTestId('route-error');
  await expect(err).toHaveAttribute('data-code', 'OUTSIDE_COVERAGE');
  await expect(err).toContainText('Outside the pilot area');
});

test('point off the mapped network → 422 OFF_NETWORK copy names the point', async ({ page }) => {
  await page.goto('/fr/plan');
  await openSheetIfMobile(page);
  await setPoint(page, 'origin', IN_A);
  await setPoint(page, 'destination', OFF_NET);
  await page.getByTestId('compare').click();
  const err = page.getByTestId('route-error');
  await expect(err).toHaveAttribute('data-code', 'OFF_NETWORK');
  await expect(err).toContainText('Trop loin du réseau piétonnier');
  await expect(err).toContainText('Votre arrivée est dans la zone pilote');
});

test('step-free profile in demo → 404 NO_ROUTE copy', async ({ page }) => {
  await page.goto('/fr/plan');
  await openSheetIfMobile(page);
  await setPoint(page, 'origin', IN_A);
  await setPoint(page, 'destination', IN_B);
  await page.getByTestId('profile').selectOption('step_free');
  await page.getByTestId('compare').click();
  const err = page.getByTestId('route-error');
  await expect(err).toHaveAttribute('data-code', 'NO_ROUTE');
  await expect(err).toContainText('Aucun trajet trouvé');
});

test('missing points are reported, not silently ignored', async ({ page }) => {
  await page.goto('/en/plan');
  await openSheetIfMobile(page);
  await page.getByTestId('compare').click();
  await expect(page.getByText('Set both a start and a destination.')).toBeVisible();
});

test('address search is disabled with an explanation (no public Nominatim)', async ({ page }) => {
  await page.goto('/en/plan');
  await openSheetIfMobile(page);
  await expect(page.getByLabel('Search an address')).toBeDisabled();
  await expect(page.getByText(/no permitted geocoding provider/)).toBeVisible();
});

test('map attribution stays visible (desktop bottom-right, mobile top-left above the sheet)', async ({ page }) => {
  await page.goto('/en/plan');
  const attrib = page.locator('.maplibregl-ctrl-attrib');
  await expect(attrib).toBeVisible();
  await expect(attrib).toContainText('OpenStreetMap');
  await expect(attrib).toContainText('Ville de Montréal');
  // Not covered by the bottom sheet / panel.
  const box = (await attrib.boundingBox())!;
  const panel = (await page.getByTestId('planner-panel').boundingBox())!;
  const overlaps = box.x < panel.x + panel.width && box.x + box.width > panel.x && box.y < panel.y + panel.height && box.y + box.height > panel.y;
  expect(overlaps).toBe(false);
});

test('map fills its pane (regression: maplibre CSS collapsed the container to 0 px)', async ({ page }) => {
  await page.goto('/en/plan');
  const map = page.getByTestId('planner-map');
  await expect(map.locator('canvas.maplibregl-canvas')).toBeVisible();
  const box = (await map.boundingBox())!;
  const pane = (await map.locator('xpath=..').boundingBox())!;
  expect(box.height).toBeGreaterThan(200);
  expect(Math.abs(box.height - pane.height)).toBeLessThan(2);
  expect(Math.abs(box.width - pane.width)).toBeLessThan(2);
  const canvas = (await map.locator('canvas.maplibregl-canvas').boundingBox())!;
  expect(Math.abs(canvas.height - box.height)).toBeLessThan(2);
});

test('map attribution is legible in dark mode (own background beats maplibre default)', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.goto('/en/plan');
  const attrib = page.locator('.maplibregl-ctrl-attrib');
  await expect(attrib).toBeVisible();
  const bg = await attrib.evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(bg).toBe('rgba(16, 27, 44, 0.9)');
});
