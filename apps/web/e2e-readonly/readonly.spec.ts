import AxeBuilder from '@axe-core/playwright';
import { test, expect } from '../e2e/fixtures';

const NOTICE = { en: 'Not available in this public demo', fr: 'Non disponible dans cette démo publique' } as const;

for (const lang of ['en', 'fr'] as const) {
  test(`read-only demo (${lang}): report and pilot forms are replaced by a notice; nothing can be sent`, async ({ page }) => {
    const posts: string[] = [];
    page.on('request', (r) => {
      if (r.method() === 'POST' && /\/api\/v1\/(reports|pilot-requests)/.test(r.url())) posts.push(r.url());
    });

    await page.goto(`/${lang}/reports`);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    const n1 = page.getByTestId('writes-disabled');
    await expect(n1).toContainText(NOTICE[lang]);
    await expect(n1).toHaveAttribute('data-form', 'reports');
    await expect(page.getByTestId('report-form')).toHaveCount(0);
    await expect(page.getByTestId('report-submit')).toHaveCount(0);

    await page.goto(`/${lang}/pilot`);
    const n2 = page.getByTestId('writes-disabled');
    await expect(n2).toContainText(NOTICE[lang]);
    await expect(n2).toHaveAttribute('data-form', 'pilot');
    await expect(page.getByTestId('pilot-form')).toHaveCount(0);

    expect(posts).toEqual([]);
  });
}

for (const path of ['/reports', '/pilot']) {
  test(`read-only ${path}: axe clean`, async ({ page }) => {
    await page.goto(`/en${path}`);
    await expect(page.getByTestId('writes-disabled')).toBeVisible();
    await page.evaluate(async () => {
      for (let y = 0; y < document.body.scrollHeight; y += window.innerHeight / 2) {
        window.scrollTo(0, y);
        await new Promise((r) => setTimeout(r, 60));
      }
    });
    await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== 'running' || a.effect?.getTiming().iterations === Infinity));
    const res = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
    expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => `${n.target.join(' ')} [${n.any[0]?.message ?? ''}]`).join(' | ')}`)).toEqual([]);
  });
}

test('read-only demo: the planner still works (reads are unaffected)', async ({ page }) => {
  await page.goto('/en/plan');
  await expect(page.getByRole('heading', { level: 1, name: 'Plan a winter walk' })).toBeVisible();
  await expect(page.getByTestId('compare')).toBeEnabled();
});
