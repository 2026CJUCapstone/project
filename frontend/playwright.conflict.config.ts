import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e', testMatch: 'project-conflict.local.spec.ts', workers: 1, timeout: 60_000,
  use: { ...devices['Desktop Chrome'], channel: 'msedge', baseURL: 'http://127.0.0.1:5173', trace: 'retain-on-failure' },
});
