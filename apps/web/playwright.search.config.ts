import { defineConfig, devices } from '@playwright/test';

/**
 * Place-search e2e (Agent A). Needs the locally built index in public/search
 * (services/ingestion: python -m winterpath_ingestion.search_index); the specs skip when it is
 * absent, because the index is generated from raw data that is never committed.
 * Port 5176 (search agent), mock API build like the main e2e config, production CSP via preview.
 */
const PORT = 5176;

export default defineConfig({
  testDir: './e2e-search',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 2,
  reporter: [['list']],
  timeout: 45_000,
  expect: { timeout: 15_000 },
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
  webServer: {
    command: `VITE_USE_MOCKS=true npx vite build --outDir dist-search && npx vite preview --outDir dist-search --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}/en`,
    env: {
      VITE_MAP_STYLE_URL:
        'data:application/json,{"version":8,"name":"e2e-stub","sources":{},"layers":[{"id":"bg","type":"background","paint":{"background-color":"rgb(238,242,246)"}}]}',
    },
    reuseExistingServer: false,
    timeout: 180_000,
  },
});
