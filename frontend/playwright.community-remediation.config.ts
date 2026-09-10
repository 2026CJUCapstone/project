import { defineConfig, devices } from '@playwright/test';

// This suite is intentionally fenced to the disposable loopback image.  Keep
// the origin literal so an operator cannot accidentally point it at production.
const targetOrigin = 'http://127.0.0.1:15181';

export default defineConfig({
  testDir: './e2e',
  testMatch: 'community-remediation.local.spec.ts',
  workers: 1,
  retries: 0,
  timeout: 120_000,
  reporter: [
    ['list'],
    ['json', { outputFile: '../.deploy/test-results/community-remediation/results.json' }],
  ],
  outputDir: '../.deploy/test-results/community-remediation/artifacts',
  use: {
    ...devices['Desktop Edge'],
    channel: 'msedge',
    baseURL: targetOrigin,
    // Credentials are generated in memory; avoid recording them in artifacts.
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
});
