import { expect, test } from '@playwright/test';

// Local UI regression only. No mocked compilation result is treated as execution proof.
for (const width of [1440, 390]) {
  test(`graph visibility and basic templates at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('/ide');
    const editor = page.locator('.view-lines').first();
    const languages = page.getByRole('combobox', { name: '실행 언어 선택' });
    await expect(languages).toBeEnabled();
    await expect(editor).toBeVisible();
    await expect(editor).toContainText('Hello, World!');
    await expect(editor).not.toContainText('spf');
    if (width === 390) await page.getByRole('tab', { name: '그래프', exact: true }).click();
    await page.getByTitle('그래프 패널 닫기').click();
    await expect(page.getByTitle('그래프 패널 닫기')).toHaveCount(0);
    await expect(editor).toBeVisible();
    await page.getByTitle('그래프 열기', { exact: true }).click();
    await expect(page.getByTitle('그래프 패널 닫기')).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`bpp-graph-${width}.png`) });

    for (const [language, syntax] of [
      ['java', 'public class Main'],
      ['cpp', '#include <iostream>'],
      ['python', 'print('],
      ['javascript', 'console.log('],
      ['c', '#include <stdio.h>'],
    ]) {
      await languages.selectOption(language);
      await expect(editor).toBeVisible();
      await expect(editor).toContainText(syntax);
      await expect(editor).toContainText('Hello, World!');
      await expect(page.getByTitle('그래프 패널 닫기')).toHaveCount(0);
      await expect(page.getByTitle('그래프 열기', { exact: true })).toHaveCount(0);
      await expect(page.getByRole('tab', { name: '그래프', exact: true })).toHaveCount(0);
    }
    await languages.selectOption('bpp');
    await expect(editor).toContainText('emitln');
    if (width === 390) await page.getByRole('tab', { name: '그래프', exact: true }).click();
    await expect(page.getByTitle('그래프 패널 닫기')).toBeVisible();

    await languages.selectOption('python');
    await editor.click();
    await page.keyboard.press('ControlOrMeta+a');
    await page.keyboard.insertText('print("my retained draft")\n');
    await expect.poll(() => page.evaluate(() => localStorage.getItem('b-compiler-editor-code:v2:guest:main'))).toContain('my retained draft');
    await page.reload();
    await expect(languages).toHaveValue('python');
    await expect(editor).toContainText('my retained draft');
    await expect(page.getByTitle('그래프 패널 닫기')).toHaveCount(0);
    page.once('dialog', dialog => dialog.dismiss());
    await page.getByTitle('기본 코드 불러오기').click();
    await expect(editor).toContainText('my retained draft');
    page.once('dialog', dialog => dialog.accept());
    await page.getByTitle('기본 코드 불러오기').click();
    await expect(editor).toContainText('Hello, World!');
    await expect(editor).not.toContainText('my retained draft');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await page.screenshot({ path: testInfo.outputPath(`python-editor-${width}.png`) });
    expect(errors).toEqual([]);
  });
}
