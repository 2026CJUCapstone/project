import { defineConfig, devices } from '@playwright/test';

// This suite is deliberately local-only.  Its API fixture is started separately
// on loopback and uses a temporary SQLite database.
export default defineConfig({
  testDir: './e2e',
  testMatch: 'profile.local.spec.ts',
  workers: 1,
  timeout: 60_000,
  reporter: [
    ['list'],
    ['json', { outputFile: '../.deploy/test-results/profile-local/results.json' }],
  ],
  // Keep artifacts outside frontend/test-results: on Windows a concurrent
  // fixture log can otherwise remain open while Playwright cleans this folder.
  outputDir: '../.deploy/test-results/profile-local/artifacts',
  use: {
    ...devices['Desktop Edge'],
    channel: 'msedge',
    baseURL: 'http://127.0.0.1:4175',
    trace: 'on',
    screenshot: 'only-on-failure',
    video: 'off',
  },
});
