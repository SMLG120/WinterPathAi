import { defineConfig, devices } from '@playwright/test';

/**
 * Runs the production (non-mock) build against a REAL API instance.
 * Start the API first (see README "Real-API e2e"), default http://localhost:8104/api/v1.
 */
const API = process.env.E2E_API_BASE_URL ?? 'http://localhost:8104/api/v1';

export default defineConfig({
  testDir: './e2e-real',
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  timeout: 60_000,
  expect: { timeout: 20_000 },
  use: {
    baseURL: 'http://localhost:5174',
    locale: 'en-CA',
    timezoneId: 'America/Toronto',
    launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] },
  },
  projects: [{ name: 'desktop', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'npx vite build --outDir dist-real && npx vite preview --outDir dist-real --port 5174 --strictPort',
    url: 'http://localhost:5174/en',
    env: {
      VITE_USE_MOCKS: 'false',
      VITE_API_BASE_URL: API,
      VITE_MAP_STYLE_URL:
        'data:application/json,{"version":8,"name":"e2e-stub","sources":{},"layers":[{"id":"bg","type":"background","paint":{"background-color":"rgb(238,242,246)"}}]}',
    },
    reuseExistingServer: false,
    timeout: 180_000,
  },
});
