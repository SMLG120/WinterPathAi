import { test, expect, IN_A, IN_B, OUTSIDE, setPoint, openSheetIfMobile } from './fixtures';

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
