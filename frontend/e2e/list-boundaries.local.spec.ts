import { expect, test } from '@playwright/test';

const api = 'http://127.0.0.1:18001/api/v1';

test('invalid list pages produce finite requests and empty queues remain usable', async ({ page }) => {
  for (const [path, endpoint] of [['/submissions', '/problems/submissions'], ['/queue', '/compiler/queue']]) {
    const result = page.waitForResponse(response => response.url().startsWith(api + endpoint));
    await page.goto(path + '?page=Infinity');
    const response = await result;
    expect(response.status()).toBe(200);
    expect(new URL(response.url()).searchParams.get('offset')).toBe('0');
    await expect(page.getByRole('alert')).toHaveCount(0);
  }
});

test('out-of-range pages recover to page one while preserving filters on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const [path, endpoint] of [['/submissions', '/problems/submissions'], ['/queue', '/compiler/queue']]) {
    const recovered = page.waitForResponse(response => {
      const url = new URL(response.url());
      return response.url().startsWith(api + endpoint) && url.searchParams.get('offset') === '0';
    });
    await page.goto(path + '?page=99&username=no-such-local-fixture-user');
    expect((await recovered).status()).toBe(200);
    await expect(page).toHaveURL(new RegExp(path + '\\?username=no-such-local-fixture-user$'));
    await expect(page.getByRole('alert')).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  }
});

test('changing search cancels a held real load-more response without corrupting the filtered total', async ({ page, request }) => {
  const auth = await request.post(api + '/auth/login', {
    data: { username: 'contest_admin', password: 'LocalContestTest!123' },
  });
  expect(auth.ok()).toBeTruthy();
  const headers = { Authorization: `Bearer ${(await auth.json()).accessToken}` };
  const prefix = `list-${Date.now().toString(36)}`;
  const created: string[] = [];
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let held!: () => void;
  const responseHeld = new Promise<void>(resolve => { held = resolve; });
  let handled!: () => void;
  const handlerDone = new Promise<void>(resolve => { handled = resolve; });
  try {
    for (let index = 0; index < 25; index++) {
      const result = await request.post(api + '/problems/', { headers, data: {
        title: `${prefix}-${index === 0 ? 'needle' : String(index).padStart(2, '0')}`,
        description: 'Temporary local list verification.', difficulty: 'iron5', points: 1,
        testCases: [{ input: '1', expectedOutput: '1' }], hiddenTestCases: [],
      } });
      expect(result.ok()).toBeTruthy(); created.push((await result.json()).id);
    }
    await page.route('**/api/v1/problems/?*', async route => {
      const url = new URL(route.request().url());
      if (url.searchParams.get('offset') !== '24' || url.searchParams.get('search') !== prefix) {
        await route.continue(); return;
      }
      try {
        const response = await route.fetch();
        expect(response.status()).toBe(200);
        expect((await response.json()).length).toBe(1);
        held(); await gate;
        await route.fulfill({ response });
      } finally { handled(); }
    });
    await page.goto('/challenges');
    await page.getByPlaceholder('문제 제목/설명 검색').fill(prefix);
    await expect(page.getByText('25문제', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: /문제 더 보기/ }).click();
    await responseHeld;
    await page.getByPlaceholder('문제 제목/설명 검색').fill(prefix + '-needle');
    await expect(page.getByText('1문제', { exact: true })).toBeVisible();
    release(); await handlerDone;
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    await expect(page.getByText('1문제', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: /문제 더 보기/ })).toHaveCount(0);
    await expect(page.getByRole('alert')).toHaveCount(0);
  } finally {
    release();
    await page.unrouteAll({ behavior: 'wait' });
    for (const id of created) expect((await request.delete(api + '/problems/' + id, { headers })).ok()).toBeTruthy();
  }
});
