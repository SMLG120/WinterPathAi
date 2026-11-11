/// <reference types="vitest/config" />
import { defineConfig, loadEnv, searchForWorkspaceRoot } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath, URL } from 'node:url';
import { cloudflarePages } from './build/cloudflarePages';

export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss(), cloudflarePages({ ...loadEnv(mode, process.cwd(), 'VITE_'), ...process.env })],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5174,
    strictPort: true,
    // Mock mode reads the Data agent's real fixture read-only from ../../data/fixtures.
    fs: { allow: [searchForWorkspaceRoot(process.cwd()), '../../data/fixtures/pilot_mini'] },
  },
  preview: { port: 5174, strictPort: true },
  build: {
    target: 'es2022',
    sourcemap: false,
    // Map (maplibre) and 3D (three/R3F) are split out by their React.lazy() imports.
    chunkSizeWarningLimit: 1200,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}', 'build/**/*.test.ts'],
    css: false,
  },
}));
