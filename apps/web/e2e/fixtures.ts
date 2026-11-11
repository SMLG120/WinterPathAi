import { test as base, expect, type Page } from '@playwright/test';
import { PTS_INPUT } from '../src/test/pilotPoints';

/** The basemap stub is injected at build time (playwright.config.ts webServer.env). */
export const test = base;
export { expect };

// Derived from the checked-out pilot_mini fixture (see src/test/pilotPoints.ts).
export const IN_A = PTS_INPUT.A;
export const IN_B = PTS_INPUT.B;
/** Inside the pilot bbox but > 75 m from the pilot_mini network → 422 OFF_NETWORK. */
export const OFF_NET = PTS_INPUT.OFF_NET;
export const OUTSIDE = { lat: '45.5300', lon: '-73.6200' };

export async function setPoint(page: Page, which: 'origin' | 'destination', p: { lat: string; lon: string }) {
  await page.getByTestId(`${which}-lat`).fill(p.lat);
  await page.getByTestId(`${which}-lon`).fill(p.lon);
  await page.getByTestId(`${which}-apply`).click();
  await expect(page.getByTestId(`point-${which}-value`)).toContainText(Number(p.lat).toFixed(5));
}

/** On narrow screens the panel is a bottom sheet; expand it so all controls are reachable. */
export async function openSheetIfMobile(page: Page) {
  const toggle = page.locator('[data-testid="planner-panel"] > button[aria-expanded]');
  if (await toggle.isVisible() && (await toggle.getAttribute('aria-expanded')) === 'false') await toggle.click();
}
