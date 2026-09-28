import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: ['ide-panels.local.spec.ts', 'header-responsive.local.spec.ts'],
  workers: 1,
  timeout: 30_000,
  reporter: [['list']],
  outputDir: '../.deploy/test-results/ide-panels-local',
  use: {
    ...devices['Desktop Edge'],
    channel: 'msedge',
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:4175',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
});
