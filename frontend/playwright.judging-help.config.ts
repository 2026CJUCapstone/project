import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './e2e', testMatch: 'judging-help.local.spec.ts', workers: 1, retries: 0, timeout: 45_000, reporter: 'list',
  outputDir: '../.deploy/test-results/judging-help',
  use: { baseURL: process.env.JUDGING_HELP_BASE_URL || 'http://127.0.0.1:15178', channel: 'msedge', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
});
