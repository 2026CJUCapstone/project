import { expect, test } from '@playwright/test';

test('selects and runs each language template without editing the code', async ({ page }) => {
  test.setTimeout(180000);
  await page.goto('/webcompiler/ide');
  await expect(page.locator('.view-lines').first()).toBeVisible();
  for (const language of ['java', 'cpp', 'python', 'javascript', 'c', 'bpp']) {
    await page.getByRole('combobox', { name: '실행 언어 선택' }).selectOption(language);
    await expect(page.locator('.view-lines').first()).toContainText('Hello, World!');
    await page.getByTestId('compile-run-button').click();
    const terminal = page.getByTestId('terminal-output');
    await expect(terminal).toContainText(`${language.toUpperCase()} 컴파일 및 실행을 시작합니다.`, { timeout: 30000 });
    await expect(terminal).toContainText('Hello, World!', { timeout: 30000 });
    await expect(terminal).toContainText('exit code 0', { timeout: 30000 });
    await expect(page.getByTestId('compile-run-button')).toBeEnabled();
  }
});

test('keeps edited code and its language after autosave and reload', async ({ page }) => {
  await page.goto('/webcompiler/ide');
  await expect(page.locator('.view-lines').first()).toBeVisible();
  await page.getByRole('combobox', { name: '실행 언어 선택' }).selectOption('python');
  await expect(page.locator('.view-lines').first()).toContainText('print(');
  await page.locator('.view-lines').first().click();
  await page.keyboard.press('ControlOrMeta+a');
  await page.keyboard.insertText('print("my saved draft")\n');
  await expect.poll(() => page.evaluate(() => localStorage.getItem('b-compiler-editor-code:main'))).toContain('my saved draft');
  await page.reload();
  await expect(page.getByRole('combobox', { name: '실행 언어 선택' })).toHaveValue('python');
  await expect(page.locator('.view-lines').first()).toContainText('my saved draft');
});
