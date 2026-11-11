import { test, expect, IN_B, setPoint, openSheetIfMobile, IN_A } from './fixtures';

test.describe('geolocation denied', () => {
  test.use({ permissions: [] });

  test('denial is explained and manual entry stays fully functional', async ({ page, context }) => {
    await context.clearPermissions();
    await page.goto('/en/plan');
    await openSheetIfMobile(page);
    await page.getByTestId('geolocate').click();
    // In-app explanation before any browser prompt.
    await expect(page.getByRole('dialog', { name: 'Share your location?' })).toBeVisible();
    await page.getByTestId('geo-consent').click();
    await expect(page.getByTestId('geo-status')).toContainText('Location permission was denied');
    await expect(page.getByTestId('point-origin-value')).toContainText('Not set');

    await setPoint(page, 'origin', IN_A);
    await setPoint(page, 'destination', IN_B);
    await page.getByTestId('compare').click();
    await expect(page.getByTestId('compare-card')).toBeVisible();
  });

  test('cancelling the consent dialog never calls the browser API', async ({ page }) => {
    await page.addInitScript(() => {
      (window as unknown as { __geoCalls: number }).__geoCalls = 0;
      const orig = navigator.geolocation.getCurrentPosition.bind(navigator.geolocation);
      navigator.geolocation.getCurrentPosition = (...a: Parameters<typeof orig>) => {
        (window as unknown as { __geoCalls: number }).__geoCalls++;
        return orig(...a);
      };
    });
    await page.goto('/en/plan');
    await openSheetIfMobile(page);
    await page.getByTestId('geolocate').click();
    await page.getByRole('button', { name: 'Cancel' }).click();
    expect(await page.evaluate(() => (window as unknown as { __geoCalls: number }).__geoCalls)).toBe(0);
  });
});

test.describe('geolocation granted', () => {
  test.use({ permissions: ['geolocation'], geolocation: { latitude: 45.5048, longitude: -73.5772 } });

  test('sets the start point after consent', async ({ page }) => {
    await page.goto('/fr/plan');
    await openSheetIfMobile(page);
    await page.getByTestId('geolocate').click();
    await page.getByTestId('geo-consent').click();
    await expect(page.getByTestId('geo-status')).toContainText('Départ défini à partir de votre position');
    await expect(page.getByTestId('point-origin-value')).toContainText('45.50480');
  });
});
