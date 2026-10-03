import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e', testMatch: 'floating-notice.local.spec.ts',
  workers: 1, retries: 0, timeout: 30_000, reporter: 'list',
  outputDir: '../.deploy/test-results/floating-notice',
  use: { baseURL: 'http://127.0.0.1:15174', channel: 'msedge',
    screenshot: 'only-on-failure', trace: 'retain-on-failure' },
});
