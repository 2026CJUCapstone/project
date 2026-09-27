import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e', testMatch: 'learning.local.spec.ts', workers: 1,
  timeout: 60_000, reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:4176', trace: 'retain-on-failure', ...devices['Desktop Chrome'], channel: 'msedge' },
});
