import { expect, test, type Page } from '@playwright/test';

const viewports = [
  { name: 'desktop', width: 1440, height: 960 },
  { name: 'mobile', width: 390, height: 844 },
] as const;

async function isolateFromApi(page: Page) {
  const apiRequests: string[] = [];
  await page.route('**/api/**', async route => {
    apiRequests.push(`${route.request().method()} ${route.request().url()}`);
    await route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"E2E API mock"}' });
  });
  return apiRequests;
}

for (const viewport of viewports) {
  test(`Monaco stays local and editable on ${viewport.name}`, async ({ page }) => {
    test.setTimeout(60_000);
    await page.setViewportSize(viewport);
    const apiRequests = await isolateFromApi(page);
    const requests: string[] = [];
    const workerUrls: string[] = [];
    // Context includes importScripts requests from Monaco's supplied blob
    // worker bootstrap, not only requests attributed to the page itself.
    page.context().on('request', request => requests.push(request.url()));
    page.on('worker', worker => workerUrls.push(worker.url()));

    await page.goto('ide');
    if (viewport.name === 'mobile') {
      await page.getByRole('tab', { name: '코드', exact: true }).click();
    }
    await expect(page.locator('.monaco-editor')).toBeVisible({ timeout: 30_000 });
    await expect(page.locator('.monaco-editor .view-lines')).not.toBeEmpty();

    const language = page.locator('select[title="실행 언어 선택"]');
    await language.selectOption('javascript');
    // Monaco 0.55 uses an invisible native EditContext node. A real pointer click
    // on the rendered text gives the editor its input focus; clicking the ARIA
    // textbox directly waits forever because that node intentionally has no box.
    await page.locator('.monaco-editor .view-lines').click({ position: { x: 80, y: 12 } });
    await page.keyboard.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A');
    await page.keyboard.insertText('const locallyBundledMonaco = 23;');
    await expect(page.locator('.monaco-editor .view-lines')).toContainText('locallyBundledMonaco');

    await expect.poll(() => requests.some(url => /ts\.worker-[^/]+\.js/.test(url)), {
      timeout: 20_000,
      message: 'Expected the local JavaScript/TypeScript worker script to be requested',
    }).toBe(true);
    const origin = new URL(test.info().project.use.baseURL!).origin;
    expect(workerUrls.length).toBeGreaterThan(0);
    expect(workerUrls.every(url => new URL(url).origin === origin)).toBe(true);
    expect(requests.some(url => url.includes('cdn.jsdelivr.net'))).toBe(false);
    expect(requests.filter(url => /^https?:/.test(url)).every(url => new URL(url).origin === origin)).toBe(true);
    expect(apiRequests).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}

test('JavaScript worker still returns diagnostics and completions', async ({ page }) => {
  await isolateFromApi(page);
  const failures: string[] = [];
  page.on('pageerror', error => failures.push(error.message));
  await page.goto('ide');
  await expect(page.locator('.monaco-editor')).toBeVisible({ timeout: 30_000 });
  await page.locator('select[title="실행 언어 선택"]').selectOption('javascript');
  const lines = page.locator('.monaco-editor .view-lines');
  await lines.click({ position: { x: 80, y: 12 } });
  await page.keyboard.press('ControlOrMeta+A');
  await page.keyboard.insertText('const = ;');
  await expect(page.locator('.monaco-editor .squiggly-error').first()).toBeVisible({ timeout: 20_000 });
  await page.keyboard.press('ControlOrMeta+A');
  await page.keyboard.insertText('Math.ma');
  await page.keyboard.press('Control+Space');
  await expect(page.locator('.suggest-widget')).toBeVisible({ timeout: 20_000 });
  await expect(page.locator('.suggest-widget .monaco-list-row').filter({ hasText: 'max' }).first()).toBeVisible();
  expect(failures).toEqual([]);
});

test('all six language templates remain editable and tokenized', async ({ page }) => {
  const apiRequests = await isolateFromApi(page);
  await page.goto('ide');
  await expect(page.locator('.monaco-editor')).toBeVisible({ timeout: 30_000 });
  const language = page.locator('select[title="실행 언어 선택"]');
  // The initial B++ lesson intentionally differs from the switch template.
  // Start with another language so all six iterations exercise a change.
  for (const value of ['c', 'cpp', 'python', 'java', 'javascript', 'bpp']) {
    await language.selectOption(value);
    const lines = page.locator('.monaco-editor .view-lines');
    await expect(lines).toContainText('Hello, World!');
    // More than one token color verifies that the model's grammar loaded,
    // rather than displaying every language as uncolored plaintext.
    await expect.poll(async () => lines.locator('span[class*="mtk"]').evaluateAll(spans =>
      new Set(spans.map(span => span.className)).size)).toBeGreaterThan(1);
  }
  expect(apiRequests).toEqual([]); // This is editor regression, not six-language judging.
});
