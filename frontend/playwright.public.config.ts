import { defineConfig, devices } from '@playwright/test';

const suppliedBaseUrl = process.env.PLAYWRIGHT_PUBLIC_BASE_URL;

if (!suppliedBaseUrl) {
  throw new Error('Set PLAYWRIGHT_PUBLIC_BASE_URL=https://cuha.cju.ac.kr to run the public Edge smoke suite.');
}

const target = new URL(suppliedBaseUrl);
if (target.origin !== 'https://cuha.cju.ac.kr' || !['', '/'].includes(target.pathname) || target.search || target.hash) {
  throw new Error('PLAYWRIGHT_PUBLIC_BASE_URL must be exactly https://cuha.cju.ac.kr.');
}

export default defineConfig({
  testDir: './e2e',
  testMatch: 'webcompiler.spec.ts',
  workers: 1,
  retries: 0,
  reporter: [
    ['list'],
    ['json', { outputFile: 'playwright-report/public-edge/results.json' }],
  ],
  // Keep public-run evidence outside the default test-results directory:
  // another local Playwright configuration clears that directory on startup.
  outputDir: 'playwright-report/public-edge/artifacts',
  use: {
    ...devices['Desktop Edge'],
    channel: 'msedge',
    baseURL: target.origin,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
});
