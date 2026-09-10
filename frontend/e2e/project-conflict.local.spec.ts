import { expect, test, type Page } from '@playwright/test';

async function edit(page: Page, code: string) {
  await page.bringToFront();
  const input = page.getByRole('textbox', { name: 'Editor content', exact: true });
  await input.focus();
  await page.keyboard.press('Control+A');
  await page.keyboard.insertText(code);
  await expect(page.locator('.monaco-editor .view-lines').first()).toContainText(code);
}

test('two real editor tabs cannot silently overwrite the other tab and can resolve the conflict', async ({ context, page }) => {
  let remote = { id: 'isolated-project', scope: 'main', title: 'main', language: 'python', code: 'print(1)', revision: 'v1',
    createdAt: '2026-09-09T00:00:00Z', updatedAt: '2026-09-09T00:00:00Z' };
  const writes: { code: string; expectedRevision: string }[] = [];
  await context.addInitScript(() => {
    localStorage.setItem('authToken', `header.${btoa(JSON.stringify({ sub: 'isolated-conflict-user' }))}.signature`);
  });
  // All API traffic stays in this fixture; neither local nor production DB is changed.
  await context.route('**/api/**', async route => {
    const request = route.request();
    if (request.url().endsWith('/projects/main')) {
      if (request.method() === 'PUT') {
        const body = request.postDataJSON();
        writes.push(body);
        if (body.expectedRevision !== remote.revision) {
          await route.fulfill({ status: 409, json: { detail: '다른 창에서 변경됨' } });
          return;
        }
        remote = { ...remote, code: body.code, revision: `v${Number(remote.revision.slice(1)) + 1}` };
      }
      await route.fulfill({ json: remote });
    } else if (request.url().endsWith('/auth/me')) {
      await route.fulfill({ json: { id: 'fixture-user', username: 'isolated-conflict-user', role: 'user', totalScore: 0 } });
    } else {
      await route.fulfill({ json: [] });
    }
  });
  await page.goto('/ide');
  await expect(page.locator('.monaco-editor .view-lines').first()).toContainText('print(1)');
  const other = await context.newPage();
  await other.goto('/ide');
  await expect(other.locator('.monaco-editor .view-lines').first()).toContainText('print(1)');

  await edit(page, 'print(2)');
  await expect.poll(() => remote.code).toBe('print(2)');
  expect(remote.revision).toBe('v2');
  await edit(other, 'print(3)');
  const conflict = other.getByRole('alert').filter({ hasText: '서버 코드와 이 기기의 코드가 다릅니다' });
  await expect(conflict).toContainText('자동저장을 멈췄으니');
  expect(remote.code).toBe('print(2)');
  expect(writes.at(-1)).toMatchObject({ code: 'print(3)', expectedRevision: 'v1' });
  await expect(conflict).toContainText('print(2)');
  await other.getByRole('button', { name: '현재 코드로 덮어쓰기' }).click();
  await expect(conflict).toHaveCount(0);
  expect(remote.code).toBe('print(3)');
  expect(writes.at(-1)).toMatchObject({ code: 'print(3)', expectedRevision: 'v2' });
});
