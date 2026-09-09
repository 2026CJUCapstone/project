import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e', testMatch: 'contest-layout.local.spec.ts', workers: 1,
  use: { ...devices['Desktop Chrome'], channel: 'msedge', baseURL: 'http://127.0.0.1:5173', trace: 'retain-on-failure' },
});
