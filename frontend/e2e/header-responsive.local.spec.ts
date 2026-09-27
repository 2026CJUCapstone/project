import { expect, test } from '@playwright/test';
const apiOrigin = process.env.PLAYWRIGHT_API_ORIGIN ?? 'http://127.0.0.1:18001';

for (const signedIn of [false, true]) {
  test(`Header controls never overlap: ${signedIn ? 'long account name' : 'guest'}`, async ({ page, request }, testInfo) => {
    test.setTimeout(90_000);
    if (signedIn) {
      const suffix = Date.now().toString(36);
      const identity = {
        username: `header_${suffix}`, email: `header-${suffix}@example.test`,
        nickname: `긴닉네임반응형확인반응형확인${suffix}`, password: 'LocalHeaderTest!123',
      };
      expect((await request.post(`${apiOrigin}/api/v1/auth/register`, { data: identity })).ok()).toBeTruthy();
      const login = await request.post(`${apiOrigin}/api/v1/auth/login`, { data: { username: identity.username, password: identity.password } });
      expect(login.ok()).toBeTruthy();
      await page.addInitScript(token => localStorage.setItem('authToken', token), (await login.json()).accessToken);
    }
    for (const route of ['/ide', '/']) {
      await page.goto(route);
      if (route === '/ide') await expect(page.getByRole('combobox', { name: '실행 언어 선택' })).toBeEnabled();
      if (signedIn) await expect(page.locator('header img')).toBeVisible();
      for (const width of [320, 360, 390, 639, 640, 677, 767, 768, 1023, 1024, 1279, 1280, 1439, 1440, 1680, 1920]) {
        await page.setViewportSize({ width, height: 900 });
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        const issues = await page.evaluate(() => {
          const controls = Array.from(document.querySelectorAll<HTMLElement>('header button, [data-testid="ide-toolbar"] button, [data-testid="ide-toolbar"] select'))
            .filter(element => element.getClientRects().length > 0);
          const results: string[] = [];
          const name = (el: HTMLElement) => el.getAttribute('aria-label') || el.title || el.textContent?.trim();
          controls.forEach((el, i) => {
            const r = el.getBoundingClientRect();
            if (r.left < 0 || r.right > innerWidth + 1) results.push(`outside: ${name(el)}`);
            const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
            if (!el.contains(hit)) results.push(`covered: ${name(el)}`);
            for (const other of controls.slice(i + 1)) {
              const s = other.getBoundingClientRect();
              if (Math.min(r.right, s.right) - Math.max(r.left, s.left) > 1 && Math.min(r.bottom, s.bottom) - Math.max(r.top, s.top) > 1)
                results.push(`overlap: ${name(el)} / ${name(other)}`);
            }
          });
          return results;
        });
        expect(issues, `${route} at ${width}px`).toEqual([]);
        if (route === '/ide') {
          await expect(page.getByTitle('저장', { exact: true })).toBeVisible();
          await expect(page.getByTestId('compile-button')).toBeVisible();
          await expect(page.getByTestId('compile-run-button')).toBeVisible();
          await expect(page.getByTitle('중지', { exact: true })).toBeVisible();
          if (width === 677 || width === 1440) await page.screenshot({ path: testInfo.outputPath(`header-${width}.png`) });
        }
      }
    }
    await page.setViewportSize({ width: 677, height: 900 });
    await page.getByRole('button', { name: '메뉴 열기' }).click();
    await page.getByRole('navigation', { name: '모바일 메뉴' }).getByRole('button', { name: '문제', exact: true }).click();
    await expect(page).toHaveURL(/\/problems$/);
    await expect(page.getByRole('navigation', { name: '모바일 메뉴' })).toHaveCount(0);
    await expect(page.locator('body')).not.toContainText('챌린지');
    await page.goto('/');
    await page.getByRole('button', { name: '문제 둘러보기' }).click();
    await expect(page).toHaveURL(/\/problems$/);
  });
}
