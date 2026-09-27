import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e', testMatch: 'history-filters.local.spec.ts', workers: 1, retries: 0,
  timeout: 45_000, reporter: 'list',
  outputDir: '../.deploy/test-results/history-filters',
  use: { ...devices['Desktop Edge'], channel: 'msedge',
    baseURL: 'http://127.0.0.1:4180', screenshot: 'only-on-failure', trace: 'off' },
});
