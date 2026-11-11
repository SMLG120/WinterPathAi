import { defineConfig, devices } from '@playwright/test';
import base from './playwright.config';

/** Read-only public-demo build (VITE_PUBLIC_WRITES=false) against mocks, on the same port 5174. */
export default defineConfig({
  ...base,
  testDir: './e2e-readonly',
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile-390', use: { ...devices['Desktop Chrome'], viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true } },
  ],
  webServer: {
    ...(base.webServer as object),
    command: 'VITE_USE_MOCKS=true VITE_PUBLIC_WRITES=false npx vite build --outDir dist-readonly && npx vite preview --outDir dist-readonly --port 5174 --strictPort',
  },
});
