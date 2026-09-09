import { expect, test } from '@playwright/test';

for (const width of [1440, 390]) {
  test(`approved homepage copy and navigation at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 960 });
    await page.goto('/');
    const landing = page.getByTestId('landing-page');
    await expect(landing).toBeVisible();
    await expect(landing.getByRole('heading', { level: 1 })).toContainText('B++의 컴파일 과정을 살펴보세요.');
    await expect(landing.getByRole('article')).toHaveCount(4);
    await expect(landing.getByRole('listitem')).toHaveCount(3);
    await expect(landing).not.toContainText(/READY TO BUILD|LEARNING PLAYGROUND|실력을 증명/);

    const sections = landing.locator(':scope > section');
    await expect(sections).toHaveCount(5);
    for (let index = 0; index < 5; index++) {
      const section = sections.nth(index);
      await section.scrollIntoViewIfNeeded();
      expect(await section.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
      const bounds = await section.boundingBox();
      expect(bounds!.x).toBeGreaterThanOrEqual(0);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
      await section.screenshot({ path: `test-results/landing-${width}-section-${index}.png` });
    }
    expect(await landing.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

    // The homepage scrolls inside the app shell; capture tall sections in smaller pieces.
    if (width === 390) {
      for (const role of ['article', 'listitem'] as const) {
        const items = landing.getByRole(role);
        for (let index = 0; index < await items.count(); index++) {
          await items.nth(index).scrollIntoViewIfNeeded();
          await items.nth(index).screenshot({ path: `test-results/landing-${width}-${role}-${index}.png` });
        }
      }
    }

    for (const [name, destination] of [
      ['코드 실행하기', '/ide'],
      ['챌린지 둘러보기', '/challenges'],
      ['커뮤니티 가기', '/community'],
      ['IDE 열기', '/ide'],
      ['리더보드 보기', '/leaderboard'],
    ]) {
      await page.goto('/');
      await landing.getByRole('button', { name, exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`${destination}$`));
    }
  });
}
