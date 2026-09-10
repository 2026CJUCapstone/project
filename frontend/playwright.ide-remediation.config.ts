import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e', testMatch: 'ide-remediation.local.spec.ts', workers: 1, retries: 0,
  timeout: 120_000,
  reporter: [['list'], ['json', { outputFile: '../.deploy/test-results/ide-remediation/results.json' }]],
  outputDir: '../.deploy/test-results/ide-remediation/artifacts',
  use: { ...devices['Desktop Edge'], channel: 'msedge',
    baseURL: 'http://127.0.0.1:15181', trace: 'off', video: 'off', screenshot: 'only-on-failure' },
});
