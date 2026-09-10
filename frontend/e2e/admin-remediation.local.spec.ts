import { readFile } from 'node:fs/promises';
import { expect, test, type Page, type Response } from '@playwright/test';

type DisposableAccount = {
  username: string;
  password: string;
};

type DisposableAccounts = {
  admin: DisposableAccount;
  solver: DisposableAccount;
  other: DisposableAccount;
};

type ProfileResponse = {
  nickname?: unknown;
};

type ProblemResponse = {
  id?: unknown;
  title?: unknown;
  points?: unknown;
};

type AdminUserResponse = {
  role?: unknown;
};

const appPath = (path: string) => `/webcompiler${path}`;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function readAccount(value: unknown): DisposableAccount {
  if (!isRecord(value) || typeof value.username !== 'string' || typeof value.password !== 'string') {
    // Do not include parsed data in this error: this fixture contains secrets.
    throw new Error('Disposable browser account fixture has an unexpected shape.');
  }
  return { username: value.username, password: value.password };
}

async function readDisposableAccounts(): Promise<DisposableAccounts> {
  // This is intentionally read only by the Node test process.  Never print,
  // attach, or otherwise return the raw fixture contents to test output.
  const raw = await readFile(new URL('../../.deploy/browser-test-accounts-f78.json', import.meta.url), 'utf8');
  const parsed: unknown = JSON.parse(raw);
  const accounts = isRecord(parsed) && isRecord(parsed.accounts) ? parsed.accounts : parsed;
  if (!isRecord(accounts)) {
    throw new Error('Disposable browser account fixture has an unexpected shape.');
  }
  return {
    admin: readAccount(accounts.admin),
    solver: readAccount(accounts.solver),
    other: readAccount(accounts.other),
  };
}

function isPath(response: Response, method: string, pathname: string) {
  return response.request().method() === method && new URL(response.url()).pathname === pathname;
}

function currentUserRead(response: Response) {
  return isPath(response, 'GET', '/webcompiler/api/v1/auth/me');
}

function profileWrite(response: Response) {
  return isPath(response, 'PATCH', '/webcompiler/api/v1/auth/profile');
}

function problemCreate(response: Response) {
  return isPath(response, 'POST', '/webcompiler/api/v1/problems/');
}

function problemUpdate(response: Response, problemId: string) {
  return isPath(response, 'PUT', `/webcompiler/api/v1/problems/${problemId}`);
}

function problemDelete(response: Response, problemId: string) {
  return isPath(response, 'DELETE', `/webcompiler/api/v1/problems/${problemId}`);
}

function adminUsersRead(response: Response) {
  return isPath(response, 'GET', '/webcompiler/api/v1/admin/users');
}

function adminUserWrite(response: Response) {
  return response.request().method() === 'PATCH'
    && new URL(response.url()).pathname.startsWith('/webcompiler/api/v1/admin/users/');
}

function collectPageErrors(page: Page) {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  return errors;
}

async function loginThroughUi(page: Page, account: DisposableAccount) {
  await page.goto(appPath('/'));
  await page.getByRole('button', { name: '로그인', exact: true }).click();

  await expect(page.getByRole('heading', { name: '로그인', exact: true })).toBeVisible();
  const loginForm = page.locator('form').filter({
    has: page.getByLabel('사용자 이름', { exact: true }),
  });
  await expect(loginForm).toBeVisible();
  await loginForm.getByLabel('사용자 이름', { exact: true }).fill(account.username);
  await loginForm.getByLabel('비밀번호', { exact: true }).fill(account.password);

  const login = page.waitForResponse(response => isPath(response, 'POST', '/webcompiler/api/v1/auth/login'));
  await loginForm.getByRole('button', { name: '로그인', exact: true }).click();
  expect((await login).ok()).toBeTruthy();
  await expect(page.getByRole('heading', { name: '로그인', exact: true })).toHaveCount(0);
  await expect(page.getByTitle('설정')).toBeVisible();
}

async function logoutThroughUi(page: Page) {
  const userTrigger = page.locator('header button').filter({ has: page.locator('img') });
  await expect(userTrigger).toHaveCount(1);
  await userTrigger.click();
  await page.getByRole('menuitem', { name: '로그아웃', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그인', exact: true })).toBeVisible();
}

async function updateOwnNicknameThroughUi(page: Page, nickname: string) {
  const profileRead = page.waitForResponse(currentUserRead);
  await page.getByTitle('설정').click();
  await expect(page.getByRole('heading', { name: '내 프로필', exact: true })).toBeVisible();
  expect((await profileRead).ok()).toBeTruthy();

  const profileForm = page.locator('form').filter({
    has: page.getByRole('heading', { name: '내 프로필', exact: true }),
  });
  await profileForm.getByLabel('닉네임', { exact: true }).fill(nickname);

  const saved = page.waitForResponse(profileWrite);
  await profileForm.getByRole('button', { name: '저장', exact: true }).click();
  const response = await saved;
  expect(response.ok()).toBeTruthy();
  const body = await response.json() as ProfileResponse;
  expect(body.nickname).toBe(nickname);
  await expect(page.getByRole('heading', { name: '내 프로필', exact: true })).toHaveCount(0);
}

async function openAdmin(page: Page) {
  const session = page.waitForResponse(currentUserRead);
  await page.goto(appPath('/admin'));
  expect((await session).ok()).toBeTruthy();
  await expect(page.getByRole('heading', { name: 'B++ 관리자', exact: true })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
}

async function findUserRow(page: Page, username: string) {
  const row = page.locator('tbody tr').filter({
    has: page.getByText(username, { exact: true }),
  });
  await expect(row).toHaveCount(1);
  return row;
}

async function searchUsers(page: Page, search: string) {
  await page.getByPlaceholder('아이디/닉네임/이메일', { exact: true }).fill(search);
  const loaded = page.waitForResponse(adminUsersRead);
  await page.getByRole('button', { name: '검색', exact: true }).click();
  expect((await loaded).ok()).toBeTruthy();
}

test('disposable accounts exercise real admin problem and user-management UI without retaining credentials', async ({ page }, testInfo) => {
  const accounts = await readDisposableAccounts();
  const pageErrors = collectPageErrors(page);
  const suffix = `${Date.now().toString(36)}${testInfo.workerIndex}`;
  const otherNickname = `Other-${suffix}`;
  const firstTitle = `Admin browser ${suffix}`;
  const revisedTitle = `${firstTitle} revised`;

  // The admin page has no control to edit another user's profile fields.
  // Exercise the available real profile editor as that disposable user, then
  // prove the admin user search observes the persisted nickname.
  await loginThroughUi(page, accounts.other);
  await updateOwnNicknameThroughUi(page, otherNickname);
  await logoutThroughUi(page);

  await loginThroughUi(page, accounts.admin);
  await openAdmin(page);

  await page.getByRole('button', { name: '문제 관리', exact: true }).click();
  await expect(page.getByRole('heading', { name: '문제 목록', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '문제 추가', exact: true }).click();

  const createForm = page.locator('form').filter({
    has: page.getByRole('heading', { name: '문제 추가', exact: true }),
  });
  await expect(createForm).toBeVisible();
  await createForm.getByPlaceholder('문제 제목', { exact: true }).fill(firstTitle);
  await createForm.locator('input[type="number"]').fill('321');
  await createForm.getByPlaceholder('문제 내용을 입력하세요', { exact: true }).fill('Temporary browser-admin verification problem.');
  await createForm.getByPlaceholder('입력 1', { exact: true }).fill('2');
  await createForm.getByPlaceholder('기대 출력 1', { exact: true }).fill('2');

  const created = page.waitForResponse(problemCreate);
  await createForm.getByRole('button', { name: '저장', exact: true }).click();
  const createResponse = await created;
  expect(createResponse.ok()).toBeTruthy();
  const createdProblem = await createResponse.json() as ProblemResponse;
  expect(createdProblem.title).toBe(firstTitle);
  expect(createdProblem.points).toBe(321);
  expect(typeof createdProblem.id).toBe('string');
  const problemId = createdProblem.id as string;
  await expect(page.getByRole('heading', { name: '문제 추가', exact: true })).toHaveCount(0);
  await expect(page.getByText(firstTitle, { exact: true })).toBeVisible();

  // A reload must restore the actual newly created server row, not merely the
  // already-rendered React state.
  await page.reload();
  await expect(page.getByRole('heading', { name: 'B++ 관리자', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '문제 관리', exact: true }).click();
  const createdRow = page.locator('tbody tr').filter({ has: page.getByText(firstTitle, { exact: true }) });
  await expect(createdRow).toHaveCount(1);

  await createdRow.getByRole('button', { name: '수정', exact: true }).click();
  const editForm = page.locator('form').filter({
    has: page.getByRole('heading', { name: '문제 수정', exact: true }),
  });
  await expect(editForm).toBeVisible();
  await editForm.getByPlaceholder('문제 제목', { exact: true }).fill(revisedTitle);

  const updated = page.waitForResponse(response => problemUpdate(response, problemId));
  await editForm.getByRole('button', { name: '저장', exact: true }).click();
  const updateResponse = await updated;
  expect(updateResponse.ok()).toBeTruthy();
  const updatedProblem = await updateResponse.json() as ProblemResponse;
  expect(updatedProblem.title).toBe(revisedTitle);
  await expect(page.getByText(revisedTitle, { exact: true })).toBeVisible();

  const revisedRow = page.locator('tbody tr').filter({ has: page.getByText(revisedTitle, { exact: true }) });
  let confirmedDeletion = false;
  page.once('dialog', dialog => {
    confirmedDeletion = dialog.type() === 'confirm';
    void dialog.accept();
  });
  const deleted = page.waitForResponse(response => problemDelete(response, problemId));
  await revisedRow.getByRole('button', { name: '삭제', exact: true }).click();
  const deleteResponse = await deleted;
  expect(confirmedDeletion).toBeTruthy();
  expect(deleteResponse.ok()).toBeTruthy();
  await expect(page.getByText(revisedTitle, { exact: true })).toHaveCount(0);

  await page.getByRole('button', { name: '사용자 관리', exact: true }).click();
  await expect(page.getByRole('heading', { name: '사용자 목록', exact: true })).toBeVisible();
  await searchUsers(page, accounts.other.username);
  let otherRow = await findUserRow(page, accounts.other.username);
  await expect(otherRow.getByText(otherNickname, { exact: true })).toBeVisible();

  const promoted = page.waitForResponse(adminUserWrite);
  await otherRow.getByRole('button', { name: '관리자로 변경', exact: true }).click();
  const promoteResponse = await promoted;
  expect(promoteResponse.ok()).toBeTruthy();
  expect(promoteResponse.request().postDataJSON()).toEqual({ role: 'admin' });
  const promotedUser = await promoteResponse.json() as AdminUserResponse;
  expect(promotedUser.role).toBe('admin');
  otherRow = await findUserRow(page, accounts.other.username);
  await expect(otherRow.getByText('관리자', { exact: true })).toBeVisible();

  const revoked = page.waitForResponse(adminUserWrite);
  await otherRow.getByRole('button', { name: '사용자로 변경', exact: true }).click();
  const revokeResponse = await revoked;
  expect(revokeResponse.ok()).toBeTruthy();
  expect(revokeResponse.request().postDataJSON()).toEqual({ role: 'user' });
  const revokedUser = await revokeResponse.json() as AdminUserResponse;
  expect(revokedUser.role).toBe('user');
  otherRow = await findUserRow(page, accounts.other.username);
  await expect(otherRow.getByText('사용자', { exact: true })).toBeVisible();
  await expect(otherRow.getByRole('button', { name: '관리자로 변경', exact: true })).toBeEnabled();

  await searchUsers(page, accounts.admin.username);
  const selfRow = await findUserRow(page, accounts.admin.username);
  // This is the UI-level self-demotion refusal: the action cannot be invoked.
  await expect(selfRow.getByRole('button', { name: '사용자로 변경', exact: true })).toBeDisabled();
  await expect(page.getByRole('alert')).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});
