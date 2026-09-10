import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir: './e2e', testMatch: 'languages-runtime.local.spec.ts', workers: 1, retries: 0,
  timeout: 90_000,
  reporter: [['list'], ['json', { outputFile: '../.deploy/test-results/languages-runtime/results.json' }]],
  outputDir: '../.deploy/test-results/languages-runtime/artifacts',
  use: { ...devices['Desktop Edge'], channel: 'msedge', baseURL: 'http://127.0.0.1:15181',
    trace: 'off', video: 'off', screenshot: 'only-on-failure' },
});
