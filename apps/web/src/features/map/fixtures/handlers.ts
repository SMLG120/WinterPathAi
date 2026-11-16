/**
 * MSW handlers for map e2e fixtures (mock builds only). Inert unless localStorage `wp-mock-fixture`
 * names a fixture; otherwise every handler returns undefined and the normal mocks answer.
 *   island-long   — multi-part coverage + a long synthetic cross-region route (islandLongRoute.ts)
 *   overlays-down — /map/segments and /hazards answer 503 UPSTREAM_UNAVAILABLE
 */
import { delay, http, HttpResponse } from 'msw';
import { FIXTURE_FLAG, ISLAND_LONG, islandCoverage, islandLongCompare } from './islandLongRoute';

const fixture = (): string | null => {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage.getItem(FIXTURE_FLAG);
  } catch {
    return null;
  }
};

const down = () =>
  HttpResponse.json({ code: 'UPSTREAM_UNAVAILABLE', message: 'Test fixture: overlay service unavailable', request_id: 'fixture' }, { status: 503 });

export const mapFixtureHandlers = [
  http.get('*/api/v1/coverage', async () => {
    if (fixture() !== ISLAND_LONG) return undefined;
    await delay(250);
    return HttpResponse.json(islandCoverage());
  }),
  http.post('*/api/v1/routes/compare', async ({ request }) => {
    if (fixture() !== ISLAND_LONG) return undefined;
    await delay(500);
    const body = (await request.json()) as { locale?: 'en' | 'fr' };
    return HttpResponse.json(islandLongCompare(body?.locale ?? 'en'));
  }),
  http.get('*/api/v1/map/segments', async () => {
    if (fixture() !== 'overlays-down') return undefined;
    await delay(150);
    return down();
  }),
  http.get('*/api/v1/hazards', async () => {
    if (fixture() !== 'overlays-down') return undefined;
    await delay(150);
    return down();
  }),
];
