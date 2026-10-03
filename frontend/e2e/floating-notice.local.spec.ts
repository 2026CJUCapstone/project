import { expect, test } from '@playwright/test';

const fixture = {
  id: 'floating-test', title: '신입생 알고리즘 콘테스트', description: '알림 레이아웃 검증',
  published: true, startsAt: '2030-01-01T01:00:00Z', endsAt: '2030-01-01T03:00:00Z',
  serverTime: '2030-01-01T00:00:00Z', state: 'upcoming',
  joined: false, canManage: false, participantCount: 0, problems: [],
};

for (const theme of ['dark', 'light'] as const) {
  for (const width of [1440, 820, 390, 320]) {
    test('floating alert: ' + theme + ' / ' + width + 'px, no content shift', async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript(() => {
        localStorage.clear();
      });
      // Every API call stays in this fixture; no local/operational data changes.
      await page.route('**/api/v1/**', route => {
        const path = new URL(route.request().url()).pathname;
        if (path.endsWith('/contests/floating-test/join')) {
          return route.fulfill({ status: 401, json: { detail: '인증 필요' } });
        }
        if (path.endsWith('/contests/floating-test/scoreboard')) {
          return route.fulfill({ json: { state: 'upcoming', rows: [], problems: [], pendingCount: 0 } });
        }
        if (path.endsWith('/contests/floating-test')) return route.fulfill({ json: fixture });
        return route.fulfill({ status: 404, json: { detail: 'Local UI fixture only' } });
      });
      await page.goto('/contests/floating-test');
      await expect(page.getByRole('heading', { name: fixture.title })).toBeVisible();
      await expect.poll(() => page.locator('html').evaluate(element => element.classList.contains('dark'))).toBe(true);
      if (theme === 'light') {
        await page.getByTitle('라이트 테마로 전환').click();
      }
      await expect.poll(() => page.locator('html').evaluate(element => element.classList.contains('dark'))).toBe(theme === 'dark');
      await page.evaluate(() => document.fonts.ready);
      const summary = page.locator('.contest-summary');
      const before = await summary.boundingBox();
      const originalHeight = await page.evaluate(() => document.documentElement.scrollHeight);
      await page.getByRole('button', { name: '참가 신청', exact: true }).click();
      const alert = page.getByRole('alert');
      await expect(alert).toHaveText('상단 로그인 버튼으로 로그인한 후 참가하세요.');
      const layer = page.getByTestId('floating-notice-layer');
      expect(await layer.evaluate(element => getComputedStyle(element).position)).toBe('fixed');
      expect(await alert.evaluate(element => element.closest('.contest-page') === null)).toBe(true);
      const after = await summary.boundingBox();
      expect(after!.y).toBeCloseTo(before!.y, 3);
      expect(after!.height).toBeCloseTo(before!.height, 3);
      expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBe(originalHeight);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      const box = await alert.boundingBox();
      expect(box!.x).toBeGreaterThanOrEqual(16);
      expect(box!.x + box!.width).toBeLessThanOrEqual(width - 16);
      const header = await page.getByTestId('site-header').boundingBox();
      expect(box!.y).toBeGreaterThanOrEqual(header!.y + header!.height);
      await page.screenshot({ path: testInfo.outputPath('floating-notice-' + theme + '-' + width + '.png') });
      await page.getByRole('button', { name: '알림 닫기' }).click();
      await expect(alert).toHaveCount(0);
      expect((await summary.boundingBox())!.y).toBeCloseTo(before!.y, 3);
    });
  }
}
