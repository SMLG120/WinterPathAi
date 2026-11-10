import { test as base, expect, type Page } from '@playwright/test';

/** The basemap stub is injected at build time (playwright.config.ts webServer.env). */
export const test = base;
export { expect };

export const IN_A = { lat: '45.5048', lon: '-73.5772' };
export const IN_B = { lat: '45.5017', lon: '-73.5698' };
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
