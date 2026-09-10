import { defineConfig, devices } from '@playwright/test';

// Explicit local-only suite: never reuse production E2E base URLs or accounts.
export default defineConfig({
  testDir: './e2e', testMatch: 'contests.local.spec.ts', workers: 1, timeout: 90000,
  // The loopback fixture keeps its server logs under test-results/contest-fixture.
  // Do not let Playwright's startup cleanup delete open fixture log files on Windows.
  // Keep artifacts outside Vite's watched frontend tree as well; trace writes
  // must not trigger a development-server reload during this browser test.
  outputDir: '../.deploy/test-results/contests-local/artifacts',
  use: { ...devices['Desktop Chrome'], channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge',
    baseURL: 'http://127.0.0.1:4175', trace: 'retain-on-failure' },
});
