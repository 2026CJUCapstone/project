import { randomUUID } from 'node:crypto';

import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const serverOrigin = 'http://127.0.0.1:15181';
const appPath = (path: string) => `/webcompiler${path}`;
const apiPath = (path: string) => `${serverOrigin}/webcompiler/api/v1${path}`;

type Identity = {
  username: string;
  email: string;
  nickname: string;
  password: string;
};

function suffix(): string {
  return randomUUID().replaceAll('-', '').slice(0, 14);
}

function identity(prefix: string): Identity {
  const id = suffix();
  return {
    username: `${prefix}_${id}`,
    email: `${prefix}-${id}@example.test`,
    nickname: `${prefix} ${id}`,
    password: `IdentityQa!${id}9`,
  };
}

function twoCharacterNickname(): string {
  const value = Number.parseInt(suffix().slice(0, 4), 16);
  const first = 0xac00 + (value % 11172);
  const second = 0xac00 + (Math.floor(value / 11172) % 11172);
  return String.fromCodePoint(first, second);
}

async function register(request: APIRequestContext, user: Identity) {
  const response = await request.post(apiPath('/auth/register'), { data: user });
  expect(response.ok()).toBeTruthy();
}

async function loginToken(request: APIRequestContext, user: Identity): Promise<string> {
  const response = await request.post(apiPath('/auth/login'), { data: user });
  expect(response.ok()).toBeTruthy();
  const payload = await response.json() as { accessToken?: string; access_token?: string };
  const token = payload.accessToken ?? payload.access_token;
  expect(token).toBeTruthy();
  return token as string;
}

function collectPageErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  return errors;
}

function isCurrentUserRead(response: { url(): string; request(): { method(): string } }): boolean {
  return response.request().method() === 'GET'
    && new URL(response.url()).pathname === '/webcompiler/api/v1/auth/me';
}

async function loginUi(page: Page, user: Identity, expectedAvatar: string = user.nickname) {
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('heading', { name: '로그인', exact: true })).toBeVisible();
  await page.getByLabel('사용자 이름', { exact: true }).fill(user.username);
  await page.getByLabel('비밀번호', { exact: true }).fill(user.password);
  const submitted = page.waitForResponse(response =>
    response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/webcompiler/api/v1/auth/login',
  );
  await page.getByRole('button', { name: '로그인', exact: true }).last().click();
  const response = await submitted;
  expect(response.status()).toBe(200);
  await expect(page.locator(`img[alt="${expectedAvatar}"]`)).toBeVisible();
}

async function logoutUi(page: Page, avatar: string) {
  await page.locator(`img[alt="${avatar}"]`).click();
  await page.getByRole('menuitem', { name: '로그아웃' }).click();
  await expect(page.getByRole('button', { name: '로그인', exact: true })).toBeVisible();
}

async function openProfile(page: Page, expectedEmail: string) {
  const refreshed = page.waitForResponse(isCurrentUserRead);
  await page.getByTitle('설정', { exact: true }).click();
  await expect(page.getByRole('heading', { name: '내 프로필', exact: true })).toBeVisible();
  expect((await refreshed).ok()).toBeTruthy();
  await expect(page.getByLabel('이메일', { exact: true })).toHaveValue(expectedEmail);
}

async function saveProfile(
  page: Page,
  expected: { email: string | null; nickname: string | null; avatarUrl: string | null },
) {
  const saved = page.waitForResponse(response =>
    response.request().method() === 'PATCH'
    && new URL(response.url()).pathname === '/webcompiler/api/v1/auth/profile',
  );
  await page.getByRole('button', { name: '저장', exact: true }).click();
  const response = await saved;
  expect(response.ok()).toBeTruthy();
  expect(response.request().postDataJSON()).toEqual(expected);
  expect(await response.json()).toMatchObject(expected);
  await expect(page.getByRole('heading', { name: '내 프로필', exact: true })).toHaveCount(0);
}

async function readProfile(request: APIRequestContext, token: string) {
  const response = await request.get(apiPath('/auth/profile'), {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(response.ok()).toBeTruthy();
  return await response.json() as { email: string | null; nickname: string | null; avatarUrl: string | null };
}

test('actual image accepts a two-character nickname and an email longer than 64 characters', async ({ page, request }) => {
  const pageErrors = collectPageErrors(page);
  const user = identity('identity');
  user.nickname = twoCharacterNickname();
  user.email = `${'e'.repeat(45)}${suffix()}@example.test`;
  expect(user.email.split('@')[0].length).toBeLessThanOrEqual(64);
  expect([...user.nickname]).toHaveLength(2);
  expect(user.email.length).toBeGreaterThan(64);
  await register(request, user);

  await page.goto(appPath('/'));
  for (const loginIdentity of [user.nickname, user.email]) {
    await page.getByRole('button', { name: '로그인', exact: true }).click();
    await expect(page.getByRole('heading', { name: '로그인', exact: true })).toBeVisible();
    await page.getByLabel('사용자 이름', { exact: true }).fill(loginIdentity);
    await page.getByLabel('비밀번호', { exact: true }).fill(user.password);
    const submitted = page.waitForResponse(response =>
      response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/webcompiler/api/v1/auth/login',
    );
    await page.getByRole('button', { name: '로그인', exact: true }).last().click();
    const response = await submitted;
    expect(response.status()).toBe(200);
    expect(response.request().postDataJSON().username).toBe(loginIdentity);
    await expect(page.locator(`img[alt="${user.nickname}"]`)).toBeVisible();
    await logoutUi(page, user.nickname);
  }
  expect(pageErrors).toEqual([]);
});

test('actual image invalidates an A-tab profile draft after a real cross-tab switch to B', async ({ page, context, request }) => {
  const pageErrors = collectPageErrors(page);
  // Keep generated email addresses canonical lowercase so the assertion is
  // about account switching, not the backend's expected email normalization.
  const accountA = identity('taba');
  const accountB = identity('tabb');
  await register(request, accountA);
  await register(request, accountB);
  const tokenA = await loginToken(request, accountA);
  const tokenB = await loginToken(request, accountB);

  const second = await context.newPage();
  try {
    await page.goto(appPath('/'));
    await loginUi(page, accountA);
    await second.goto(appPath('/'));
    await expect(second.locator(`img[alt="${accountA.nickname}"]`)).toBeVisible();

    await page.getByTitle('설정', { exact: true }).click();
    await expect(page.getByRole('heading', { name: '내 프로필', exact: true })).toBeVisible();
    await page.getByLabel('이메일', { exact: true }).fill(`stale-${suffix()}@example.test`);
    await page.getByLabel('닉네임', { exact: true }).fill(`Stale ${suffix()}`);

    await logoutUi(second, accountA.nickname);
    await expect(page.getByRole('heading', { name: '내 프로필', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '로그인', exact: true })).toBeVisible();

    await loginUi(second, accountB);
    await expect(page.locator(`img[alt="${accountB.nickname}"]`)).toBeVisible();
    await openProfile(page, accountB.email);
    await expect(page.getByLabel('닉네임', { exact: true })).toHaveValue(accountB.nickname);

    const saved = page.waitForResponse(response =>
      response.request().method() === 'PATCH'
      && new URL(response.url()).pathname === '/webcompiler/api/v1/auth/profile',
    );
    await page.getByRole('button', { name: '저장', exact: true }).click();
    const response = await saved;
    expect(response.ok()).toBeTruthy();
    const body = response.request().postDataJSON() as { email?: string; nickname?: string };
    expect(body.email).toBe(accountB.email);
    expect(body.nickname).toBe(accountB.nickname);
    expect(body.email).not.toContain('stale-');
    expect(body.nickname).not.toContain('Stale ');

    expect((await readProfile(request, tokenA)).email).toBe(accountA.email);
    expect((await readProfile(request, tokenB)).email).toBe(accountB.email);
  } finally {
    await second.close();
  }
  expect(pageErrors).toEqual([]);
});

test('actual image persists omitted profile fields and clears explicit fields to null after reload', async ({ page, request }) => {
  const pageErrors = collectPageErrors(page);
  const user = identity('clear');
  await register(request, user);
  const token = await loginToken(request, user);

  await page.addInitScript(accessToken => localStorage.setItem('authToken', accessToken), token);
  await page.goto(appPath('/'));
  await expect(page.locator(`img[alt="${user.nickname}"]`)).toBeVisible();

  const avatarUrl = `https://example.test/${suffix()}.svg`;
  const filledEmail = `filled-${suffix()}@example.test`;
  const filledNickname = `Filled ${suffix()}`;
  await openProfile(page, user.email);
  await page.getByLabel('이메일', { exact: true }).fill(filledEmail);
  await page.getByLabel('닉네임', { exact: true }).fill(filledNickname);
  await page.getByLabel('아바타 URL', { exact: true }).fill(avatarUrl);
  await saveProfile(page, { email: filledEmail, nickname: filledNickname, avatarUrl });

  const partial = await request.patch(apiPath('/auth/profile'), {
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    data: { nickname: `${filledNickname} partial` },
  });
  expect(partial.ok()).toBeTruthy();
  expect(await readProfile(request, token)).toMatchObject({
    email: filledEmail,
    nickname: `${filledNickname} partial`,
    avatarUrl,
  });

  await page.reload();
  await expect(page.getByText(`${filledNickname} partial`, { exact: true })).toBeVisible();
  await openProfile(page, filledEmail);
  await page.getByLabel('이메일', { exact: true }).fill('');
  await page.getByLabel('닉네임', { exact: true }).fill('');
  await page.getByLabel('아바타 URL', { exact: true }).fill('');
  await saveProfile(page, { email: null, nickname: null, avatarUrl: null });
  expect(await readProfile(request, token)).toMatchObject({ email: null, nickname: null, avatarUrl: null });

  await page.evaluate(() => localStorage.removeItem('b-compiler-user'));
  await page.reload();
  await expect(page.locator(`img[alt="${user.username}"]`)).toBeVisible();
  await openProfile(page, '');
  await expect(page.getByLabel('이메일', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('닉네임', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('아바타 URL', { exact: true })).toHaveValue('');
  expect(pageErrors).toEqual([]);
});
