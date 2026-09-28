import { defineConfig, devices } from '@playwright/test';

// The latency suite remains serial: a run's request stream is part of its evidence.
export default defineConfig({
  testDir: './e2e',
  testMatch: 'compiler-graph-latency.local.spec.ts',
  workers: 1,
  fullyParallel: false,
  retries: 0,
  reporter: 'list',
  timeout: 45_000,
  use: {
    ...devices['Desktop Chrome'],
    channel: process.env.PLAYWRIGHT_CHANNEL ?? 'chrome',
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:15173',
    trace: 'retain-on-failure',
  },
});
