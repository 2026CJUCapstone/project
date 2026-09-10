import { expect, test, type Page } from '@playwright/test';

async function isolateFromApi(page: Page) {
  await page.route('**/api/**', route => route.fulfill({
    status: 404,
    contentType: 'application/json',
    body: '{"detail":"E2E API mock"}',
  }));
}

test('production preview editor and worker run under strict CSP without remote scripts or unsafe-eval', async ({ page }) => {
  await isolateFromApi(page);
  await page.route('**/ide', async route => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      headers: {
        ...response.headers(),
        'Content-Security-Policy': "default-src 'self'; script-src 'self'; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self' ws: wss:; object-src 'none'; base-uri 'self'",
      },
    });
  });
  const errors: string[] = [];
  const requests: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.context().on('request', request => requests.push(request.url()));

  await page.goto('ide');
  await expect(page.locator('script[src*="/@vite/client"]')).toHaveCount(0);
  await expect(page.locator('.monaco-editor')).toBeVisible({ timeout: 30_000 });
  await page.locator('select[title="실행 언어 선택"]').selectOption('javascript');
  await page.locator('.monaco-editor .view-lines').click({ position: { x: 80, y: 12 } });
  await page.keyboard.press('ControlOrMeta+A');
  await page.keyboard.insertText('const = ;');
  await expect(page.locator('.monaco-editor .squiggly-error').first()).toBeVisible({ timeout: 20_000 });

  const origin = new URL(test.info().project.use.baseURL!).origin;
  expect(requests.filter(url => /^https?:/.test(url)).every(url => new URL(url).origin === origin)).toBe(true);
  expect(errors).toEqual([]);
});
