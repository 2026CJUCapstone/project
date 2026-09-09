import { defineConfig, devices } from '@playwright/test';

// Explicit local-only suite: never reuse production E2E base URLs or accounts.
export default defineConfig({
  testDir: './e2e', testMatch: 'contests.local.spec.ts', workers: 1, timeout: 90000,
  use: { ...devices['Desktop Chrome'], channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge',
    baseURL: 'http://127.0.0.1:4175', trace: 'retain-on-failure' },
});
