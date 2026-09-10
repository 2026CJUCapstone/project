import { test, expect } from '@playwright/test';
import { CODE_TEMPLATES } from '../src/app/store/codeTemplates';

for (const [language, template] of Object.entries(CODE_TEMPLATES)) {
  test(`actual ${language} template compiles and runs in the browser terminal`, async ({ page }, testInfo) => {
    expect(testInfo.project.use.baseURL).toBe('http://127.0.0.1:15181');
    const errors: string[] = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto('/webcompiler/ide');
    // The initial B++ demo is preserved. Change away and back to explicitly
    // request the basic template, instead of assuming startup replaces drafts.
    if (language === 'bpp') await page.getByRole('combobox', { name: '실행 언어 선택' }).selectOption('python');
    await page.getByRole('combobox', { name: '실행 언어 선택' }).selectOption(language);
    await expect(page.locator('.view-lines').first()).toContainText('Hello, World!');
    const socketPromise = page.waitForEvent('websocket', { predicate: ws => ws.url().includes('/ws/terminal') });
    await page.getByTestId('compile-run-button').click();
    const socket = await socketPromise;
    await page.getByTestId('terminal-tab').click();
    await expect(page.getByTestId('terminal-output')).toContainText('Hello, World!', { timeout: 60_000 });
    await expect(page.getByTestId('terminal-output')).toContainText('터미널 실행이 정상 종료되었습니다.', { timeout: 30_000 });
    expect(socket.isClosed()).toBeTruthy();
    await expect(page.getByTestId('terminal-input')).toBeDisabled();
    expect(errors).toEqual([]);
    await testInfo.attach('runtime-language', { contentType: 'application/json', body: Buffer.from(JSON.stringify({
      language, template, actualWebSocket: true, output: 'Hello, World!', closedNormally: true,
    })) });
  });
}

test('actual browser terminal sends stdin and shows stdout, then reconnects', async ({ page }) => {
  await page.goto('/webcompiler/ide');
  await page.getByRole('combobox', { name: '실행 언어 선택' }).selectOption('python');
  const lines = page.locator('.view-lines').first();
  await lines.click({ position: { x: 60, y: 12 } });
  await page.keyboard.press('ControlOrMeta+A');
  await page.keyboard.insertText('print("GOT" + input())');
  await expect(lines).toContainText('print("GOT" + input())');
  for (const input of ['42', '43']) {
    await page.getByTestId('compile-run-button').click();
    await page.getByTestId('terminal-tab').click();
    await expect(page.getByTestId('terminal-input')).toBeEnabled({ timeout: 30_000 });
    await page.getByTestId('terminal-input').fill(input);
    await page.getByTestId('terminal-input').press('Enter');
    await expect(page.locator('[data-terminal-line-type="output"]').filter({ hasText: 'GOT' + input })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId('terminal-output')).toContainText('터미널 실행이 정상 종료되었습니다.');
    await expect(page.getByTestId('terminal-input')).toBeDisabled();
  }
});
