import AxeBuilder from '@axe-core/playwright';
import { test, expect } from './fixtures';

const PAGES = [
  { path: '', en: "Walk smarter through Montreal's winter.", fr: "Marchez plus malin dans l'hiver montréalais." },
  { path: '/plan', en: 'Plan a winter walk', fr: 'Planifier une marche hivernale' },
  { path: '/winter', en: 'Winter conditions', fr: 'Conditions hivernales' },
  { path: '/reports', en: 'Report a winter issue', fr: 'Signaler un problème hivernal' },
  { path: '/how-it-works', en: 'How WinterPath works', fr: 'Fonctionnement de WinterPath' },
  { path: '/pilot', en: 'Pilot programs', fr: 'Projets pilotes' },
  { path: '/admin', en: 'Moderation', fr: 'Modération' },
] as const;

for (const lang of ['en', 'fr'] as const) {
  for (const theme of ['light', 'dark'] as const) {
    for (const p of PAGES) {
      test(`${lang} ${theme} ${p.path || '/'}: renders, no horizontal overflow, no axe violations`, async ({ page }) => {
        await page.addInitScript((t) => localStorage.setItem('wp-theme', t), theme);
        await page.goto(`/${lang}${p.path}`);
        await expect(page.getByRole('heading', { level: 1, name: p[lang] })).toBeVisible();
        await expect(page.locator('html')).toHaveClass(theme === 'dark' ? /dark/ : /^(?!.*dark).*$/);
        await expect(page.getByTestId('demo-banner')).toBeVisible();
        // Wait for mock data to settle (skeletons gone).
        await expect(page.locator('[role="status"][aria-live="polite"] .skeleton')).toHaveCount(0);

        // Reveal every whileInView section and let fades finish so axe audits final, visible content.
        await page.evaluate(async () => {
          for (let y = 0; y < document.body.scrollHeight; y += window.innerHeight / 2) {
            window.scrollTo(0, y);
            await new Promise((r) => setTimeout(r, 60));
          }
          window.scrollTo(0, 0);
        });
        await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== 'running' || a.effect?.getTiming().iterations === Infinity));
        await page.waitForTimeout(300);

        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        expect(overflow, 'horizontal overflow (px)').toBeLessThanOrEqual(0);

        const results = await new AxeBuilder({ page })
          .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
          .exclude('.maplibregl-canvas')
          .analyze();
        const summary = results.violations.map((v) => `${v.id}: ${v.nodes.length} × ${v.nodes[0]?.target.join(' ')}`);
        expect(summary).toEqual([]);
      });
    }
  }
}

test('root redirects to a language prefix', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/(en|fr)$/);
});

test('footer carries required attributions', async ({ page }) => {
  await page.goto('/fr');
  const footer = page.getByRole('contentinfo');
  await expect(footer).toContainText("© les contributeurs d'OpenStreetMap");
  await expect(footer).toContainText('Ville de Montréal, sous licence CC BY 4.0');
  await expect(footer).toContainText('Environnement et Changement climatique Canada');
  await expect(footer).toContainText('OpenFreeMap');
});

test('winter page shows SIMULATED weather, honest missing-history state, disabled model', async ({ page }) => {
  await page.goto('/en/winter');
  await expect(page.locator('[data-evidence="simulated"]').first()).toBeVisible();
  await expect(page.getByTestId('history-unavailable')).toContainText('no endpoint');
  await expect(page.getByTestId('model-enabled')).toContainText('Disabled — not yet validated');
  await expect(page.getByTestId('alerts-none')).toBeVisible();
});

test('community report: consent required, receipt with one-time deletion token, delete', async ({ page }) => {
  await page.goto('/en/reports');
  await page.getByLabel('What did you see?').selectOption('ice');
  await page.getByLabel('Latitude').fill('45.5048');
  await page.getByLabel('Longitude').fill('-73.5772');
  await page.getByTestId('report-submit').click();
  await expect(page.getByText('You need to consent to sending the location.')).toBeVisible();
  await page.getByLabel('I consent to sending this exact location with my report.').check();
  await page.getByLabel('Description (optional)').fill('Icy patch near the corner');
  await expect(page.getByText('25 / 280 characters')).toBeVisible();
  await page.getByTestId('report-submit').click();
  const receipt = page.getByTestId('report-receipt');
  await expect(receipt).toContainText('Report received');
  await expect(page.getByTestId('deletion-token')).toHaveText(/^[0-9a-f]{48}$/);
  await receipt.getByRole('button', { name: 'Delete my report' }).click();
  await expect(page.getByText('Your report has been deleted.')).toBeVisible();
});

test('pilot request form submits with consent', async ({ page }) => {
  await page.goto('/fr/pilot');
  await page.getByLabel('Organisation', { exact: true }).fill('Université test');
  await page.getByLabel('Courriel', { exact: true }).fill('contact@example.org');
  await page.getByLabel("Type d'organisation").selectOption('university');
  await page.getByRole('button', { name: 'Envoyer la demande' }).click();
  await expect(page.getByText("Vous devez donner votre accord avant l'envoi.")).toBeVisible();
  await page.getByLabel(/J'accepte que WinterPath/).check();
  await page.getByRole('button', { name: 'Envoyer la demande' }).click();
  await expect(page.getByTestId('pilot-success')).toBeVisible();
});

test('admin moderation: token-gated, not linked from navigation', async ({ page }) => {
  await page.goto('/en');
  await expect(page.locator('a[href$="/admin"]')).toHaveCount(0);
  await page.goto('/en/admin');
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', /noindex/);
  await page.getByLabel('Admin token').fill('demo-admin-token');
  await page.getByRole('button', { name: 'Load reports' }).click();
  await expect(page.getByText('No reports with this status.')).toBeVisible();
});

test('reduced motion: sections render without fade (opacity 1 immediately)', async ({ browser }) => {
  const ctx = await browser.newContext({ reducedMotion: 'reduce' });
  const page = await ctx.newPage();
  await page.goto('http://localhost:5174/en');
  const op = await page.locator('#faq').evaluate((el) => getComputedStyle(el).opacity);
  expect(op).toBe('1');
  await ctx.close();
});

test('reduced motion → static poster, no 3D canvas', async ({ browser }) => {
  const ctx = await browser.newContext({ reducedMotion: 'reduce' });
  const page = await ctx.newPage();
  await page.goto('http://localhost:5174/en');
  await expect(page.getByTestId('hero-visual').locator('svg').first()).toBeVisible();
  await page.waitForTimeout(3000);
  await expect(page.getByTestId('hero-visual').locator('canvas')).toHaveCount(0);
  await ctx.close();
});

test('API-provided English model limitations are marked lang="en" and flagged on the French page', async ({ page }) => {
  await page.goto('/fr/winter');
  await expect(page.getByText('Texte fourni par l’API en anglais seulement.')).toBeVisible();
  const list = page.locator('ul[lang="en"]').filter({ hasText: 'evaluation gate' });
  await expect(list).toBeVisible();
  await page.goto('/en/winter');
  await expect(page.getByText('Provided by the API in English only.')).toHaveCount(0);
});

test('condition explainer: 3D stage loads near view with an illustrative caption; none under reduced motion', async ({ page, browser }) => {
  await page.goto('/en/how-it-works');
  const explainer = page.getByTestId('condition-explainer');
  await explainer.scrollIntoViewIfNeeded();
  await page.getByRole('tab', { name: 'Ice and fresh snow' }).click();
  await expect(page.getByRole('tabpanel')).toContainText('Model estimate');
  const stage = page.getByTestId('explainer-stage');
  await expect(stage.locator('canvas')).toHaveCount(1, { timeout: 15_000 });
  await expect(stage.locator('[aria-hidden="true"]').first()).toBeAttached();
  await expect(stage).toContainText('Illustrative scene');

  const ctx = await browser.newContext({ reducedMotion: 'reduce' });
  const rm = await ctx.newPage();
  await rm.goto('http://localhost:5174/fr/how-it-works');
  await expect(rm.getByRole('tab', { name: 'Escaliers extérieurs' })).toBeVisible();
  await expect(rm.getByTestId('explainer-stage')).toHaveCount(0);
  await ctx.close();
});
