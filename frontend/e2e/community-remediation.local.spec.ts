import { expect, test } from '@playwright/test';

const appPath = (path: string) => `/webcompiler${path}`;
const postsPath = '/webcompiler/api/v1/community/posts';

test('a disposable user can manage a free post while notices remain admin-only', async ({ page, request }, testInfo) => {
  const suffix = `${Date.now().toString(36)}${testInfo.workerIndex}`;
  const username = `community_${suffix}`;
  const email = `community-${suffix}@example.test`;
  const password = `CommunityQa!${suffix}9`;
  const originalContent = `community original ${suffix}`;
  const editedContent = `community edited ${suffix}`;

  // Prepare one disposable account through the real API.  The response body
  // is intentionally not inspected because it is not needed for this flow.
  const registration = await request.post('/webcompiler/api/v1/auth/register', {
    data: { username, email, password },
  });
  expect(registration.ok()).toBeTruthy();

  await page.goto(appPath('/'));
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('heading', { name: '로그인', exact: true })).toBeVisible();

  const credentialForm = page.locator('form').filter({ has: page.getByLabel('사용자 이름', { exact: true }) });
  await credentialForm.getByLabel('사용자 이름', { exact: true }).fill(username);
  await credentialForm.getByLabel('비밀번호', { exact: true }).fill(password);
  await credentialForm.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByText(username, { exact: true })).toBeVisible();

  await page.goto(appPath('/community'));
  await expect(page.getByRole('heading', { name: '커뮤니티', exact: true })).toBeVisible();
  await expect(page.getByText('공지는 관리자만 작성할 수 있습니다.', { exact: true })).toBeVisible();
  await expect(page.locator('textarea')).toHaveCount(0);

  const openFreeBoard = async () => {
    const loaded = page.waitForResponse(response =>
      response.url().includes(postsPath) &&
      response.url().includes('problemId=__free__') &&
      response.request().method() === 'GET',
    );
    await page.getByRole('tab', { name: '자유', exact: true }).click();
    expect((await loaded).ok()).toBeTruthy();
    await expect(page.getByPlaceholder('자유롭게 이야기를 나눠보세요...', { exact: true })).toBeVisible();
  };

  await openFreeBoard();
  const composer = page.getByPlaceholder('자유롭게 이야기를 나눠보세요...', { exact: true });
  await composer.fill(originalContent);
  const created = page.waitForResponse(response =>
    response.url().includes(postsPath) && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: '게시', exact: true }).click();
  expect((await created).ok()).toBeTruthy();
  await expect(page.getByText(originalContent, { exact: true })).toBeVisible();

  const ownPost = () => page.locator('li').filter({ hasText: username }).first();
  await expect(ownPost()).toBeVisible();
  await ownPost().getByTitle('수정').click();
  await ownPost().locator('textarea').fill(editedContent);
  const updated = page.waitForResponse(response =>
    response.url().includes(postsPath) && response.request().method() === 'PATCH',
  );
  await ownPost().getByRole('button', { name: '저장', exact: true }).click();
  expect((await updated).ok()).toBeTruthy();
  await expect(page.getByText(editedContent, { exact: true })).toBeVisible();
  await expect(page.getByText(originalContent, { exact: true })).toHaveCount(0);

  await page.reload();
  await expect(page.getByRole('heading', { name: '커뮤니티', exact: true })).toBeVisible();
  await openFreeBoard();
  await expect(page.getByText(editedContent, { exact: true })).toBeVisible();

  const deleted = page.waitForResponse(response =>
    response.url().includes(postsPath) && response.request().method() === 'DELETE',
  );
  await ownPost().getByTitle('삭제').click();
  expect((await deleted).status()).toBe(204);
  await expect(ownPost()).toHaveCount(0);

  await page.reload();
  await expect(page.getByRole('heading', { name: '커뮤니티', exact: true })).toBeVisible();
  await openFreeBoard();
  await expect(ownPost()).toHaveCount(0);
  await expect(page.getByText(editedContent, { exact: true })).toHaveCount(0);
});
