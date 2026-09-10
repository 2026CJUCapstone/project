import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e', testMatch: 'list-boundaries.local.spec.ts', workers: 1, retries: 0,
  timeout: 60_000,
  reporter: [['list'], ['json', { outputFile: '../.deploy/test-results/list-boundaries/results.json' }]],
  outputDir: '../.deploy/test-results/list-boundaries/artifacts',
  use: { ...devices['Desktop Edge'], channel: 'msedge', baseURL: 'http://127.0.0.1:4175',
    trace: 'off', screenshot: 'only-on-failure', video: 'off' },
});
