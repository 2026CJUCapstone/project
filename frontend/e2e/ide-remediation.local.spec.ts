import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

const base = '/webcompiler';
const program = 'import emitln from std.io;\nfunc main() -> u64 { emitln("IDE-actual-42"); return 0; }';

async function edit(page: Page, code: string) {
  const lines = page.locator('.monaco-editor .view-lines').first();
  await expect(lines).toBeVisible();
  await lines.click({ position: { x: 60, y: 12 } });
  await page.keyboard.press('ControlOrMeta+A');
  await page.keyboard.insertText(code);
  await expect(lines).toContainText(code.split('\n').at(-1)!);
}

test('actual B++ analysis renders AST, SSA, IR and assembly, and invalid input shows diagnostics', async ({ page }) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto(base + '/ide');
  await edit(page, program);
  await page.getByTitle('컴파일 (Ctrl+Shift+B)', { exact: true }).click();
  await expect(page.locator('.react-flow__node-ast').first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole('button', { name: /^AST\s+[1-9]/ })).toBeVisible();
  await page.getByRole('button', { name: /^SSA\s/ }).click();
  await expect(page.locator('.react-flow__node-ssa').first()).toBeVisible();
  await expect(page.getByRole('button', { name: /^SSA\s+[1-9]/ })).toBeVisible();
  await page.getByRole('button', { name: /^IR\s/ }).click();
  await expect(page.getByText('Intermediate Representation', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /^IR\s+[1-9]/ })).toBeVisible();
  await page.getByRole('button', { name: /^ASM\s/ }).click();
  await expect(page.getByText('Assembly Output', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /^ASM\s+[1-9]/ })).toBeVisible();
  await page.getByTestId('compile-run-button').click();
  await expect(page.getByTestId('output-console')).toContainText('IDE-actual-42', { timeout: 60_000 });
  await expect(page.getByTestId('output-console')).toContainText('exit code 0', { timeout: 30_000 });
  await edit(page, 'func main( -> u64 {');
  await page.getByTitle('컴파일 (Ctrl+Shift+B)', { exact: true }).click();
  await page.getByTestId('output-tab').click();
  await expect(page.getByTestId('output-console')).toContainText(/컴파일.*실패|오류|error/i, { timeout: 60_000 });
  expect(errors).toEqual([]);
});

test('graph tab focus does not scroll and clip the whole analysis panel', async ({ page }, testInfo) => {
  await page.goto(base + '/ide');
  await page.getByRole('button', { name: /^ASM\s/ }).click();
  const graph = page.locator('[data-panel-id="graph-viewer-panel"]');
  const layout = await graph.evaluate(element => {
    const panel = element.getBoundingClientRect();
    const heading = element.querySelector('h3')!.getBoundingClientRect();
    return { scrollLeft: element.scrollLeft, panelLeft: panel.left, panelRight: panel.right,
      headingLeft: heading.left, headingRight: heading.right };
  });
  expect(layout.scrollLeft).toBe(0);
  expect(layout.headingLeft).toBeGreaterThanOrEqual(layout.panelLeft);
  expect(layout.headingRight).toBeLessThanOrEqual(layout.panelRight);
  await page.screenshot({ path: testInfo.outputPath('analysis-panel-fixed.png') });
});

test('real browser devices preserve the winning saved code and expose a stale revision conflict', async ({ browser, request }) => {
  const account = JSON.parse(readFileSync(resolve('../.deploy/browser-test-accounts-f78.json'), 'utf8')).solver as { username: string; password: string };
  const login = await request.post(base + '/api/v1/auth/login', { data: account });
  expect(login.ok()).toBeTruthy();
  const token = (await login.json()).accessToken as string;
  const headers = { Authorization: `Bearer ${token}` };
  const path = base + '/api/v1/projects/main';
  const before = await request.get(path, { headers });
  expect([200, 404]).toContain(before.status());
  const revision = before.ok() ? (await before.json()).revision : null;
  const seeded = await request.put(path, { headers, data: { title: 'Actual IDE fixture', code: 'print("BASELINE-f78")', language: 'python', expectedRevision: revision } });
  expect(seeded.ok()).toBeTruthy();
  const contexts = await Promise.all([browser.newContext({ baseURL: 'http://127.0.0.1:15181' }), browser.newContext({ baseURL: 'http://127.0.0.1:15181' })]);
  try {
    const pages: Page[] = [];
    for (const context of contexts) {
      await context.addInitScript(value => localStorage.setItem('authToken', value), token);
      const page = await context.newPage(); pages.push(page);
      await page.goto(base + '/ide');
      await expect(page.locator('.view-lines').first()).toContainText('BASELINE-f78');
    }
    const [first, second] = pages;
    await edit(first, 'print("WINNER-f78")');
    const firstSaved = first.waitForResponse(response => response.url().endsWith(path) && response.request().method() === 'PUT');
    await first.getByTitle('저장', { exact: true }).click();
    expect((await firstSaved).status()).toBe(200);
    await edit(second, 'print("LOCAL-DRAFT-f78")');
    const conflict = second.waitForResponse(response => response.url().endsWith(path) && response.request().method() === 'PUT');
    await second.getByTitle('저장', { exact: true }).click();
    expect((await conflict).status()).toBe(409);
    await expect(second.getByText('서버 코드와 이 기기의 코드가 다릅니다.', { exact: false })).toBeVisible();
    await expect(second.locator('.view-lines').first()).toContainText('LOCAL-DRAFT-f78');
    const persisted = await request.get(path, { headers });
    expect((await persisted.json()).code).toBe('print("WINNER-f78")');
    await second.getByRole('button', { name: '서버 코드 불러오기', exact: true }).click();
    await expect(second.locator('.view-lines').first()).toContainText('WINNER-f78');
    await second.reload();
    await expect(second.locator('.view-lines').first()).toContainText('WINNER-f78');
  } finally { await Promise.all(contexts.map(context => context.close())); }
});
