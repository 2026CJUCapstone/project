import { defineConfig, devices } from '@playwright/test';

const suppliedTarget = process.env.IDENTITY_RUNTIME_BASE_URL ?? 'http://127.0.0.1:15181/webcompiler/';
const target = new URL(suppliedTarget);

if (
  target.protocol !== 'http:'
  || target.hostname !== '127.0.0.1'
  || target.port !== '15181'
  || target.pathname !== '/webcompiler/'
  || target.search
  || target.hash
) {
  throw new Error('IDENTITY_RUNTIME_BASE_URL must be exactly http://127.0.0.1:15181/webcompiler/.');
}

export default defineConfig({
  testDir: './e2e',
  testMatch: 'identity-runtime.local.spec.ts',
  workers: 1,
  retries: 0,
  timeout: 120_000,
  reporter: [
    ['list'],
    ['json', { outputFile: '../.deploy/test-results/identity-runtime/results.json' }],
  ],
  outputDir: '../.deploy/test-results/identity-runtime/artifacts',
  use: {
    ...devices['Desktop Edge'],
    channel: 'msedge',
    baseURL: target.origin,
    trace: 'on',
    screenshot: 'only-on-failure',
    video: 'off',
  },
});
