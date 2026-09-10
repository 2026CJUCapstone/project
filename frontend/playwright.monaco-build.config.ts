import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: ['monaco.local.spec.ts', 'monaco.preview.spec.ts'],
  workers: 1,
  retries: 0,
  reporter: 'list',
  use: {
    ...devices['Desktop Edge'],
    channel: 'msedge',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'subpath', use: { baseURL: 'http://127.0.0.1:15189/webcompiler/' } },
    { name: 'root', use: { baseURL: 'http://127.0.0.1:15190/' } },
  ],
  webServer: [{
    command: 'node node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port 15189 --strictPort --base /webcompiler/ --outDir dist-profile-subpath',
    url: 'http://127.0.0.1:15189/webcompiler/',
    reuseExistingServer: false,
    timeout: 30_000,
  }, {
    command: 'node node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port 15190 --strictPort --base / --outDir dist-profile-root',
    url: 'http://127.0.0.1:15190/',
    reuseExistingServer: false,
    timeout: 30_000,
  }],
});
