import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e', testMatch: 'durable-execution.local.spec.ts', workers: 1, retries: 0, reporter: 'list',
  use: { ...devices['Desktop Edge'], channel: 'msedge', baseURL: 'http://127.0.0.1:5173', trace: 'retain-on-failure' },
});
