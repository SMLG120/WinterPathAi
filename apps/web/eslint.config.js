import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import jsxA11y from 'eslint-plugin-jsx-a11y';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['dist', 'dist-mock', 'dist-real', 'dist-shots', 'coverage', 'playwright-report', 'test-results', 'public/mockServiceWorker.js', 'src/api/schema.d.ts'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: { ecmaVersion: 2022, globals: { ...globals.browser, ...globals.node } },
    plugins: { 'react-hooks': reactHooks, 'react-refresh': reactRefresh, 'jsx-a11y': jsxA11y },
    rules: {
      ...reactHooks.configs.recommended.rules,
      ...jsxA11y.flatConfigs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      // Precise user coordinates must never be logged (CLAUDE.md privacy rules).
      'no-console': ['error', { allow: ['warn', 'error'] }],
    },
  },
  {
    files: ['src/components/ui/**', 'src/**/*.test.{ts,tsx}', 'src/test/**', 'e2e/**'],
    rules: { 'react-refresh/only-export-components': 'off' },
  },
);
