import { defineConfig, devices } from '@playwright/test';

// This browser suite is intentionally fenced to the disposable integration
// tunnel.  Refuse a changed URL rather than ever driving a public deployment.
const suppliedTarget = process.env.REMEDIATION_BROWSER_BASE_URL ?? 'http://127.0.0.1:15181/webcompiler/';
const target = new URL(suppliedTarget);

if (
  target.protocol !== 'http:' ||
  target.hostname !== '127.0.0.1' ||
  target.port !== '15181' ||
  target.pathname !== '/webcompiler/' ||
  target.search ||
  target.hash
) {
  throw new Error('REMEDIATION_BROWSER_BASE_URL must be exactly http://127.0.0.1:15181/webcompiler/.');
}

export default defineConfig({
  testDir: './e2e',
  testMatch: 'remediation-browser.local.spec.ts',
  workers: 1,
  retries: 0,
  timeout: 90_000,
  reporter: [
    ['list'],
    ['json', { outputFile: '../.deploy/test-results/remediation-browser/results.json' }],
  ],
  // Do not use frontend/test-results: other local Playwright suites can clean
  // it while the integration tunnel is still writing evidence on Windows.
  outputDir: '../.deploy/test-results/remediation-browser/artifacts',
  use: {
    ...devices['Desktop Edge'],
    channel: 'msedge',
    baseURL: target.origin,
    trace: 'on',
    screenshot: 'only-on-failure',
    video: 'off',
  },
});
