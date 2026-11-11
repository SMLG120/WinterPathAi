import AxeBuilder from '@axe-core/playwright';
import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';
import { PTS_INPUT } from '../src/test/pilotPoints';

type PlanCopy = { results: { identical: string; riskLayer: Record<'model' | 'heuristic' | 'none', string> } };
const planCopy = (lang: 'en' | 'fr'): PlanCopy =>
  JSON.parse(readFileSync(new URL(`../src/i18n/locales/${lang}/plan.json`, import.meta.url), 'utf8')) as PlanCopy;

const API = process.env.E2E_API_BASE_URL ?? 'http://localhost:8104/api/v1';
const ADMIN_TOKEN = process.env.E2E_ADMIN_TOKEN; // plain token whose sha256 is the API's API_ADMIN_TOKEN_HASH
// Derived from the checked-out pilot_mini fixture — the same graph the API loads with
// ROUTING_GRAPH_SOURCE=fixture (see src/test/pilotPoints.ts).
const { A, B, OFF_NET } = PTS_INPUT;

// API_PUBLIC_WRITES=false (v1.7 read-only demo) → write endpoints answer 503 WRITES_DISABLED before
// body validation. An empty body is the probe: a write-enabled API rejects it with 422, so nothing is stored.
let writesDisabled = false;
// Hazard sources (mtl-entraves, mtl-311) as the API reports them; anything not `active` must be disclosed.
let hazardSourcesComplete = false;

test.beforeAll(async ({ request }) => {
  const r = await request.get(`${API}/health`).catch(() => null);
  if (!r || !r.ok()) throw new Error(`Real API not reachable at ${API} — start it first (apps/web/README.md).`);
  const probe = await request.post(`${API}/reports`, { data: {} });
  writesDisabled = probe.status() === 503 && ((await probe.json()) as { code?: string }).code === 'WRITES_DISABLED';
  const sources = (await (await request.get(`${API}/data-sources`)).json()) as { id: string; status: string }[];
  hazardSourcesComplete = ['mtl-entraves', 'mtl-311'].every((id) => sources.find((x) => x.id === id)?.status === 'active');
});

async function setPoint(page: Page, which: 'origin' | 'destination', p: { lat: string; lon: string }) {
  await page.getByTestId(`${which}-lat`).fill(p.lat);
  await page.getByTestId(`${which}-lon`).fill(p.lon);
  await page.getByTestId(`${which}-apply`).click();
}

test('no demo labelling in real-API mode', async ({ page }) => {
  await page.goto('/en/plan');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await expect(page.getByTestId('demo-banner')).toHaveCount(0);
  await expect(page.getByTestId('demo-badge')).toHaveCount(0);
});

for (const lang of ['en', 'fr'] as const) {
  test(`compare on the real pilot_mini graph (${lang})`, async ({ page }) => {
    await page.goto(`/${lang}/plan`);
    await setPoint(page, 'origin', A);
    await setPoint(page, 'destination', B);
    // Assert against what the API actually returned (risk layer differs by deployment:
    // RISK_PROVIDER=none → 'none', ML heuristic layer → 'heuristic', validated model → 'model').
    const [resp] = await Promise.all([
      page.waitForResponse((r) => r.url().includes('/routes/compare') && r.request().method() === 'POST'),
      page.getByTestId('compare').click(),
    ]);
    expect(resp.status()).toBe(200);
    const body = (await resp.json()) as {
      risk_layer: 'model' | 'heuristic' | 'none';
      identical?: boolean;
      routes: { explanation: { evidence_state: string }[] }[];
    };
    const copy = planCopy(lang).results;
    const card = page.getByTestId('compare-card');
    await expect(card.getByTestId('route-shortest')).toBeVisible();
    await expect(card.getByTestId('route-winter_aware')).toBeVisible();
    // Real data is never labelled simulated.
    await expect(card.locator('[data-evidence="simulated"]')).toHaveCount(0);
    // The card shows the risk layer the API reported — not a hard-coded one.
    await expect(card).toContainText(copy.riskLayer[body.risk_layer]);
    for (const other of (['model', 'heuristic', 'none'] as const).filter((k) => k !== body.risk_layer)) {
      await expect(card).not.toContainText(copy.riskLayer[other]);
    }
    // Every evidence state the API used is rendered as a badge.
    const states = new Set(body.routes.flatMap((r) => r.explanation.map((e) => e.evidence_state)));
    for (const st of states) await expect(card.locator(`[data-evidence="${st}"]`).first()).toBeVisible();
    if (body.risk_layer === 'none') await expect(card.locator('[data-evidence="unknown"]').first()).toBeVisible();
    // "Both routes are the same" appears exactly when the API says so.
    if (body.identical) await expect(card).toContainText(copy.identical);
    else await expect(card).not.toContainText(copy.identical);
    await expect(card.getByTestId('steps-winter_aware').getByRole('listitem').first()).toBeVisible();
    // Freshness lists the real source id from the API.
    await expect(card).toContainText('osm');
    // Closure/311 sources not loaded (e.g. API_STORE_BACKEND=memory) → the card says routes couldn't avoid them.
    await expect(card.getByTestId('hazard-sources-route')).toHaveCount(hazardSourcesComplete ? 0 : 1);
  });
}

test('snap failure from the real API (legacy OUTSIDE_COVERAGE + details) gets network-distance copy', async ({ page }) => {
  await page.goto('/en/plan');
  await setPoint(page, 'origin', A);
  await setPoint(page, 'destination', OFF_NET);
  await page.getByTestId('compare').click();
  const err = page.getByTestId('route-error');
  await expect(err).toHaveAttribute('data-kind', 'OFF_NETWORK');
  await expect(err).toContainText('Your destination is inside the pilot area but more than 75 m');
});

test('step-free on real data: refusal explains distance to verified step-free network', async ({ page }) => {
  await page.goto('/en/plan');
  await setPoint(page, 'origin', A);
  await setPoint(page, 'destination', B);
  await page.getByTestId('profile').selectOption('step_free');
  await page.getByTestId('compare').click();
  const err = page.getByTestId('route-error');
  await expect(err).toBeVisible();
  await expect(err).toHaveAttribute('data-kind', /OFF_NETWORK|NO_ROUTE/);
});

test('winter page: ECCC 503 shows an error state with retry, never invented values', async ({ page }) => {
  await page.goto('/en/winter');
  await expect(page.getByText(/An external data provider \(such as Environment Canada weather\) is unavailable/).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole('button', { name: 'Retry' }).first()).toBeVisible();
  await expect(page.getByTestId('model-enabled')).toContainText('Disabled — not yet validated');
  await expect(page.getByText('°C')).toHaveCount(0);
});

test('how-it-works renders real /data-sources and /coverage', async ({ page, request }) => {
  // Counts come from the API, so the test survives fixture regeneration.
  const cov = (await (await request.get(`${API}/coverage`)).json()) as { graph: { node_count: number; edge_count: number } };
  await page.goto('/en/how-it-works');
  await expect(page.getByRole('rowheader', { name: /OpenStreetMap/ }).first()).toBeVisible();
  await expect(page.locator('#coverage')).toContainText(String(cov.graph.edge_count));
  await expect(page.locator('#coverage')).toContainText(String(cov.graph.node_count));
});

test('hazard overlay never says "none" while closure/311 sources are not loaded', async ({ page }) => {
  test.skip(hazardSourcesComplete, 'every hazard source is active on this API');
  await page.goto('/en/plan');
  await expect(page.getByTestId('hazard-sources-overlay')).toBeVisible();
  await expect(page.getByTestId('hazard-sources-overlay')).toHaveAttribute('data-state', 'partial');
  await expect(page.getByText('No closures or reports in this view.')).toHaveCount(0);
});

test('read-only API (503 WRITES_DISABLED): report and pilot forms turn into the public-demo notice', async ({ page }) => {
  test.skip(!writesDisabled, 'API accepts writes (start it with API_PUBLIC_WRITES=false)');
  await page.goto('/en/reports');
  await page.getByLabel('What did you see?').selectOption('snow');
  await page.getByLabel('Latitude').fill(A.lat);
  await page.getByLabel('Longitude').fill(A.lon);
  await page.getByLabel('I consent to sending this exact location with my report.').check();
  await page.getByTestId('report-submit').click();
  await expect(page.getByTestId('writes-disabled')).toContainText('Not available in this public demo');
  await expect(page.getByTestId('report-receipt')).toHaveCount(0);

  await page.goto('/en/pilot');
  await page.getByLabel('Organisation', { exact: true }).fill('E2E test organisation');
  await page.getByLabel('Email', { exact: true }).fill('e2e@example.org');
  await page.getByLabel('Type of organisation').selectOption('other');
  await page.getByLabel(/I agree that WinterPath/).check();
  await page.getByRole('button', { name: 'Send request' }).click();
  await expect(page.getByTestId('writes-disabled')).toBeVisible();
  await expect(page.getByTestId('pilot-success')).toHaveCount(0);
});

test('community report lifecycle against the real API, then moderation', async ({ page }) => {
  test.skip(writesDisabled, 'API is read-only (API_PUBLIC_WRITES=false)');
  await page.goto('/en/reports');
  await page.getByLabel('What did you see?').selectOption('snow');
  await page.getByLabel('Latitude').fill(A.lat);
  await page.getByLabel('Longitude').fill(A.lon);
  await page.getByLabel('I consent to sending this exact location with my report.').check();
  await page.getByTestId('report-submit').click();
  await expect(page.getByTestId('report-receipt')).toContainText('Report received');
  await expect(page.getByTestId('deletion-token')).not.toBeEmpty();

  if (ADMIN_TOKEN) {
    const admin = await page.context().newPage();
    await admin.goto('/en/admin');
    await admin.getByLabel('Admin token').fill(ADMIN_TOKEN);
    await admin.getByRole('button', { name: 'Load reports' }).click();
    await expect(admin.getByRole('button', { name: 'Approve' }).first()).toBeVisible();
    await admin.close();
  }

  await page.getByRole('button', { name: 'Delete my report' }).click();
  await expect(page.getByText('Your report has been deleted.')).toBeVisible();
});

test('admin rejects a wrong token', async ({ page }) => {
  await page.goto('/en/admin');
  await page.getByLabel('Admin token').fill('definitely-not-the-token');
  await page.getByRole('button', { name: 'Load reports' }).click();
  await expect(page.getByText('The token was rejected.')).toBeVisible();
});

test('pilot request 201 against the real API', async ({ page }) => {
  test.skip(writesDisabled, 'API is read-only (API_PUBLIC_WRITES=false)');
  await page.goto('/en/pilot');
  await page.getByLabel('Organisation', { exact: true }).fill('E2E test organisation');
  await page.getByLabel('Email', { exact: true }).fill('e2e@example.org');
  await page.getByLabel('Type of organisation').selectOption('other');
  await page.getByLabel(/I agree that WinterPath/).check();
  await page.getByRole('button', { name: 'Send request' }).click();
  await expect(page.getByTestId('pilot-success')).toBeVisible();
});

for (const path of ['', '/plan', '/winter', '/reports', '/how-it-works', '/pilot']) {
  test(`axe clean with real data: ${path || '/'}`, async ({ page }) => {
    await page.goto(`/en${path}`);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await page.waitForLoadState('networkidle');
    await page.evaluate(async () => {
      for (let y = 0; y < document.body.scrollHeight; y += window.innerHeight / 2) {
        window.scrollTo(0, y);
        await new Promise((r) => setTimeout(r, 60));
      }
    });
    // Same settle rule as e2e/pages.spec.ts: audit final content, not text mid-fade.
    await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== 'running' || a.effect?.getTiming().iterations === Infinity));
    await page.waitForTimeout(800);
    const res = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).exclude('.maplibregl-canvas').analyze();
    expect(res.violations.map((v) => `${v.id}: ${v.nodes.length} × ${v.nodes.map((n) => `${n.target.join(' ')} [${n.any[0]?.message ?? ''}]`).join(' | ')}`)).toEqual([]);
  });
}
