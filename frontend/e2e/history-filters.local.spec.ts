import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const api = 'http://127.0.0.1:18003/api/v1';
async function login(page: Page, request: APIRequestContext, username = 'alice') {
  const result = await request.post(api + '/auth/login', {
    data: { username, password: 'LocalHistoryTest!123' },
  });
  expect(result.ok()).toBeTruthy();
  const token = (await result.json()).accessToken;
  await page.addInitScript(token => localStorage.setItem('authToken', token), token);
}

test('real filters, reused problem IDs, pagination and browser navigation', async ({ page, request }) => {
  await login(page, request);
  await page.goto('/queue');
  await expect(page.getByText('표시 대상 57', { exact: true })).toBeVisible();
  await page.getByTitle('다음 페이지', { exact: true }).click();
  await expect(page).toHaveURL(/page=2/);
  await expect(page.getByText('2 / 2', { exact: true })).toBeVisible();
  await page.getByLabel('내 대회', { exact: true }).selectOption('b');
  await expect(page).not.toHaveURL(/page=/);
  await expect(page.getByText('표시 대상 1', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'B 대회 문제', exact: true }).first()).toBeVisible();
  await page.getByLabel('언어', { exact: true }).selectOption('java');
  await expect(page.getByText('표시 대상 0', { exact: true })).toBeVisible();
  await page.goBack();
  await expect(page.getByText('표시 대상 1', { exact: true })).toBeVisible();
  await page.getByLabel('내 대회', { exact: true }).selectOption('');
  await expect(page.getByText('표시 대상 2', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '초기화', exact: true }).click();
  await expect(page.getByText('표시 대상 57', { exact: true })).toBeVisible();
  const bOption = page.getByLabel('문제', { exact: true }).locator('option').filter({ hasText: 'B 대회 문제' });
  await page.getByLabel('문제', { exact: true }).selectOption((await bOption.getAttribute('value'))!);
  await expect(page).toHaveURL(/contestId=b/);
  await expect(page.getByText('표시 대상 1', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '초기화', exact: true }).click();
  await page.getByLabel('문제 제목 또는 ID 검색').fill('공개 연습');
  await page.getByRole('button', { name: '적용', exact: true }).click();
  await expect(page.getByText('표시 대상 27', { exact: true })).toBeVisible();
  await page.screenshot({ path: '../.deploy/test-results/history-filters/desktop.png', fullPage: true });
});

test('logout discards a delayed private response from the real server', async ({ page, request }) => {
  await login(page, request);
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let held!: () => void;
  const holding = new Promise<void>(resolve => { held = resolve; });
  let first = true;
  await page.route('**/api/v1/compiler/queue?*', async route => {
    if (!first) { await route.continue(); return; }
    first = false;
    const response = await route.fetch();
    expect((await response.json()).jobs.some((row: { source: string }) => row.source === 'contest')).toBeTruthy();
    held(); await gate; await route.fulfill({ response });
  });
  try {
    await page.goto('/queue');
    await holding;
    await page.evaluate(() => {
      localStorage.removeItem('authToken');
      window.dispatchEvent(new Event('auth-identity-change'));
    });
    await expect(page.getByText('표시 대상 55', { exact: true })).toBeVisible();
    release();
    await page.unrouteAll({ behavior: 'wait' });
    await expect(page.getByRole('button', { name: 'A 대회 문제', exact: true })).toHaveCount(0);
    await expect(page.getByLabel('내 대회', { exact: true }).locator('option')).toHaveCount(1);
    await expect(page.getByText('표시 대상 55', { exact: true })).toBeVisible();
  } finally { release(); }
});

for (const width of [320, 390, 768]) {
  test(`filters and results remain reachable at ${width}px`, async ({ page, request }) => {
    await login(page, request);
    await page.setViewportSize({ width, height: 844 });
    await page.goto('/queue?source=contest&contestId=a');
    await expect(page.getByText('표시 대상 1', { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    for (const label of ['기록 범위', '내 대회', '문제', '언어', '상태', '작업 종류', '판정']) {
      const box = await page.getByLabel(label, { exact: true }).boundingBox();
      expect(box?.width).toBeGreaterThanOrEqual(120);
    }
    await page.getByRole('heading', { name: '작업 목록', exact: true }).scrollIntoViewIfNeeded();
    await expect(page.getByRole('heading', { name: '작업 목록', exact: true })).toBeInViewport();
    await page.getByLabel('언어', { exact: true }).selectOption('java');
    await expect(page.getByText('표시 대상 0', { exact: true })).toBeVisible();
    await page.getByLabel('언어', { exact: true }).selectOption('python');
    await expect(page.getByText('표시 대상 1', { exact: true })).toBeVisible();
    await page.getByRole('heading', { name: '컴파일 큐', exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.deploy/test-results/history-filters/mobile-${width}.png`, fullPage: true });
  });
}
