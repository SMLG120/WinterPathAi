import { defineConfig, devices } from '@playwright/test';

const PORT = 5174;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // WebGL runs on SwiftShader (CPU); more workers starve each other.
  workers: 2,
  reporter: [['list']],
  timeout: 45_000,
  expect: { timeout: 20_000 },
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: 'retain-on-failure',
    locale: 'en-CA',
    timezoneId: 'America/Toronto',
    launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] },
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile-390', use: { ...devices['Desktop Chrome'], viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true } },
  ],
  // E2E runs against the MSW mock build (VITE_USE_MOCKS=true), served by `vite preview`.
  webServer: {
    command: 'VITE_USE_MOCKS=true npx vite build --outDir dist-mock && npx vite preview --outDir dist-mock --port 5174 --strictPort',
    url: `http://localhost:${PORT}/en`,
    // Deterministic stub basemap: Playwright can't route requests made through MSW's service worker,
    // so the test build gets an inline style via the normal env switch (no OpenFreeMap traffic in tests).
    env: {
      VITE_MAP_STYLE_URL:
        'data:application/json,{"version":8,"name":"e2e-stub","sources":{},"layers":[{"id":"bg","type":"background","paint":{"background-color":"rgb(238,242,246)"}}]}',
    },
    reuseExistingServer: false,
    timeout: 180_000,
  },
});
