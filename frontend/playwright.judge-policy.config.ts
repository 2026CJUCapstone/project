import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e', testMatch: 'judge-policy.local.spec.ts', workers: 1, retries: 0,
  timeout: 30_000, reporter: 'list', outputDir: '../.deploy/test-results/judge-policy',
  use: { ...devices['Desktop Edge'], channel: 'msedge', baseURL: 'http://127.0.0.1:4181',
    screenshot: 'only-on-failure', trace: 'off' },
  webServer: { command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4181 --strictPort',
    url: 'http://127.0.0.1:4181', reuseExistingServer: false, timeout: 30_000,
    env: { VITE_API_URL: 'http://127.0.0.1:4181', VITE_BASE_PATH: '/' } },
});
