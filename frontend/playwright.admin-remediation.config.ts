import { defineConfig, devices } from '@playwright/test';

// This suite is deliberately fenced to the disposable Docker integration
// tunnel.  It must never drive a deployment or an arbitrary URL.
const suppliedTarget = process.env.ADMIN_REMEDIATION_BROWSER_BASE_URL ?? 'http://127.0.0.1:15181/webcompiler/';
const target = new URL(suppliedTarget);

if (
  target.protocol !== 'http:' ||
  target.hostname !== '127.0.0.1' ||
  target.port !== '15181' ||
  target.pathname !== '/webcompiler/' ||
  target.search ||
  target.hash
) {
  throw new Error('ADMIN_REMEDIATION_BROWSER_BASE_URL must be exactly http://127.0.0.1:15181/webcompiler/.');
}

export default defineConfig({
  testDir: './e2e',
  testMatch: 'admin-remediation.local.spec.ts',
  workers: 1,
  retries: 0,
  timeout: 90_000,
  // Do not preserve Playwright's failure-context snapshots: the suite drives
  // credential forms and must not retain their UI state.
  preserveOutput: 'never',
  reporter: [
    ['list'],
    ['json', { outputFile: '../.deploy/test-results/admin-remediation/results.json' }],
  ],
  // Keep this separate from other local Playwright suites so their cleanup
  // cannot touch this run's output while Windows has a handle open.
  outputDir: '../.deploy/test-results/admin-remediation/artifacts',
  use: {
    ...devices['Desktop Edge'],
    channel: 'msedge',
    baseURL: target.origin,
    // Credentials are entered through the UI.  Do not retain any trace,
    // screenshot, or video that could contain them.
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
});
