import { defineConfig, devices } from '@playwright/test';

// This suite may only drive the disposable local Docker fixture.  Retain the
// app subpath in the validation even though Playwright uses the origin as its
// baseURL for root-relative route navigation.
const suppliedTarget = process.env.HISTORY_RUNTIME_BASE_URL ?? 'http://127.0.0.1:15181/webcompiler/';
const target = new URL(suppliedTarget);

if (
  target.protocol !== 'http:' ||
  target.hostname !== '127.0.0.1' ||
  target.port !== '15181' ||
  target.pathname !== '/webcompiler/' ||
  target.search ||
  target.hash
) {
  throw new Error('HISTORY_RUNTIME_BASE_URL must be exactly http://127.0.0.1:15181/webcompiler/.');
}

export default defineConfig({
  testDir: './e2e',
  testMatch: 'history-runtime.local.spec.ts',
  workers: 1,
  retries: 0,
  timeout: 180_000,
  preserveOutput: 'always',
  reporter: [
    ['list'],
    ['json', { outputFile: '../.deploy/test-results/history-runtime/results.json' }],
  ],
  // Do not start a local server.  The supplied fixture is the only target.
  outputDir: '../.deploy/test-results/history-runtime/artifacts',
  use: {
    ...devices['Desktop Edge'],
    channel: 'msedge',
    baseURL: target.origin,
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
});
