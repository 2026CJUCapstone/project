import { expect, test, type Page, type Response as PlaywrightResponse } from '@playwright/test';

type RouteCheck = {
  path: string;
  ready: (page: Page) => Promise<void>;
};

const appPath = (path: string) => `/webcompiler${path}`;

const routeChecks: RouteCheck[] = [
  {
    path: '/',
    ready: async page => {
      await expect(page.getByTestId('landing-page')).toBeVisible();
    },
  },
  {
    path: '/challenges',
    ready: async page => {
      await expect(page.getByRole('heading', { name: '문제 목록', exact: true })).toBeVisible();
    },
  },
  {
    path: '/queue',
    ready: async page => {
      await expect(page.getByRole('heading', { name: '컴파일 큐', exact: true })).toBeVisible();
    },
  },
  {
    path: '/submissions',
    ready: async page => {
      await expect(page.getByRole('heading', { name: '제출 이력', exact: true })).toBeVisible();
    },
  },
  {
    path: '/leaderboard',
    ready: async page => {
      await expect(page.getByRole('heading', { name: '리더보드', exact: true })).toBeVisible();
    },
  },
  {
    path: '/community',
    ready: async page => {
      await expect(page.getByRole('heading', { name: '커뮤니티', exact: true })).toBeVisible();
    },
  },
  {
    path: '/contests',
    ready: async page => {
      await expect(page.getByTestId('contest-list-page')).toBeVisible();
    },
  },
  {
    path: '/admin',
    ready: async page => {
      await expect(page.getByRole('heading', { name: '관리자 로그인이 필요합니다', exact: true })).toBeVisible();
    },
  },
  {
    path: '/reset-password',
    ready: async page => {
      await expect(page.getByRole('heading', { name: '비밀번호 찾기', exact: true })).toBeVisible();
    },
  },
];

function collectPageErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  return errors;
}

async function assertNoHorizontalOverflow(page: Page) {
  const dimensions = await page.evaluate(() => ({
    viewport: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    bodyWidth: document.body.scrollWidth,
  }));
  expect(dimensions.documentWidth).toBeLessThanOrEqual(dimensions.viewport);
  expect(dimensions.bodyWidth).toBeLessThanOrEqual(dimensions.viewport);
}

async function assertSettledRoute(page: Page, check: RouteCheck) {
  await check.ready(page);
  // Route titles render before their data requests resolve.  Let failures turn
  // into their page-level alert rather than accepting a transient shell.
  await page.waitForTimeout(700);
  await expect(page.getByRole('alert')).toHaveCount(0);
  await assertNoHorizontalOverflow(page);
}

async function visitAndReload(page: Page, check: RouteCheck) {
  await page.goto(appPath(check.path));
  await assertSettledRoute(page, check);
  await page.reload();
  await assertSettledRoute(page, check);
}

function isExactCurrentUserRead(response: PlaywrightResponse) {
  return response.request().method() === 'GET'
    && new URL(response.url()).pathname === '/webcompiler/api/v1/auth/me';
}

async function holdOneRealCurrentUserRead(page: Page) {
  let release!: () => void;
  let resolveFetched!: () => void;
  let rejectFetched!: (reason?: unknown) => void;
  let resolveHandlerFinished!: () => void;
  let rejectHandlerFinished!: (reason?: unknown) => void;
  const releasePromise = new Promise<void>(resolve => {
    release = resolve;
  });
  const fetched = new Promise<void>((resolve, reject) => {
    resolveFetched = resolve;
    rejectFetched = reject;
  });
  const handlerFinished = new Promise<void>((resolve, reject) => {
    resolveHandlerFinished = resolve;
    rejectHandlerFinished = reject;
  });
  let intercepted = false;

  // Keep the actual upstream body intact.  Only its delivery to the browser is
  // delayed, which deterministically exercises the profile-read race.
  await page.route('**/api/v1/auth/me', async route => {
    if (intercepted || route.request().method() !== 'GET') {
      await route.continue();
      return;
    }
    intercepted = true;
    try {
      const response = await route.fetch();
      resolveFetched();
      await releasePromise;
      await route.fulfill({ response });
      resolveHandlerFinished();
    } catch (error) {
      rejectFetched(error);
      rejectHandlerFinished(error);
      throw error;
    }
  });

  return {
    fetched,
    release,
    cleanup: async () => {
      release();
      await handlerFinished;
      await page.unroute('**/api/v1/auth/me');
    },
  };
}

async function releaseReadAndWaitForRender(page: Page, read: { release: () => void }) {
  // Install this before release so it observes the browser's fulfilled response,
  // not merely the upstream response returned by route.fetch().
  const delivered = page.waitForResponse(isExactCurrentUserRead);
  read.release();
  await (await delivered).finished();
  await page.evaluate(() => new Promise<void>(resolve => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  }));
}

test('desktop deep-links, refreshes, and protected routes work in the isolated Docker image', async ({ page }) => {
  const pageErrors = collectPageErrors(page);

  for (const check of routeChecks) {
    await visitAndReload(page, check);
  }

  await page.goto(appPath('/'));
  await page.getByRole('button', { name: '챌린지', exact: true }).click();
  await expect(page).toHaveURL(/\/webcompiler\/challenges$/);
  await expect(page.getByRole('heading', { name: '문제 목록', exact: true })).toBeVisible();
  await assertNoHorizontalOverflow(page);
  expect(pageErrors).toEqual([]);
});

test.describe('390px mobile navigation', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('every public and protected route survives direct navigation and refresh without overflow', async ({ page }) => {
    const pageErrors = collectPageErrors(page);

    for (const check of routeChecks) {
      await visitAndReload(page, check);
    }

    await page.goto(appPath('/'));
    await page.getByRole('button', { name: '메뉴 열기', exact: true }).click();
    const mobileMenu = page.getByRole('navigation', { name: '모바일 메뉴', exact: true });
    await expect(mobileMenu).toBeVisible();
    await mobileMenu.getByRole('button', { name: '콘테스트', exact: true }).click();
    await expect(page).toHaveURL(/\/webcompiler\/contests$/);
    await expect(page.getByTestId('contest-list-page')).toBeVisible();
    await assertNoHorizontalOverflow(page);
    expect(pageErrors).toEqual([]);
  });
});

test('a disposable user can register, save, clear, and reload profile fields through the real image UI', async ({ page }, testInfo) => {
  const pageErrors = collectPageErrors(page);
  const suffix = `${Date.now().toString(36)}${testInfo.workerIndex}`;
  const username = `browser_${suffix}`;
  const registrationEmail = `browser-${suffix}@example.test`;
  const profileEmail = `profile-${suffix}@example.test`;
  const initialNickname = `Browser ${suffix}`;
  const profileNickname = `Profile ${suffix}`;
  const password = `BrowserQa!${suffix}9`;
  const avatarUrl = 'data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%2F%3E';

  const openProfile = async (expectedEmail: string) => {
    const refreshed = page.waitForResponse(response =>
      response.request().method() === 'GET' && response.url().includes('/api/v1/auth/me'),
    );
    await page.getByTitle('설정').click();
    await expect(page.getByRole('heading', { name: '내 프로필', exact: true })).toBeVisible();
    expect((await refreshed).ok()).toBeTruthy();
    await expect(page.getByLabel('이메일', { exact: true })).toHaveValue(expectedEmail);
  };
  const saveProfile = async (expected: { email: string | null; nickname: string | null; avatarUrl: string | null }) => {
    const saved = page.waitForResponse(response =>
      response.request().method() === 'PATCH' && response.url().includes('/api/v1/auth/profile'),
    );
    await page.getByRole('button', { name: '저장', exact: true }).click();
    const response = await saved;
    expect(response.ok()).toBeTruthy();
    expect(response.request().postDataJSON()).toEqual(expected);
    expect(await response.json()).toMatchObject(expected);
    await expect(page.getByRole('heading', { name: '내 프로필', exact: true })).toHaveCount(0);
  };
  const readPersistedProfile = async () => await page.evaluate(async () => {
    const token = localStorage.getItem('authToken');
    const response = await fetch('/webcompiler/api/v1/auth/profile', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    const profile = await response.json() as { email: string | null; nickname: string | null; avatarUrl: string | null };
    return { status: response.status, email: profile.email, nickname: profile.nickname, avatarUrl: profile.avatarUrl };
  });
  const readCachedProfile = async () => await page.evaluate(() => {
    const stored = localStorage.getItem('b-compiler-user');
    return stored ? JSON.parse(stored) as { email?: string | null; nickname?: string | null; rawAvatarUrl?: string | null } : null;
  });

  await page.goto(appPath('/'));
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByRole('button', { name: '회원가입', exact: true }).click();
  await expect(page.getByRole('heading', { name: '회원가입', exact: true })).toBeVisible();
  await page.getByLabel('사용자 이름', { exact: true }).fill(username);
  await page.getByLabel('이메일', { exact: true }).fill(registrationEmail);
  await page.getByLabel(/닉네임/).fill(initialNickname);
  await page.getByLabel('비밀번호', { exact: true }).fill(password);
  await page.getByLabel('비밀번호 확인', { exact: true }).fill(password);
  await page.getByRole('button', { name: '계정 생성', exact: true }).click();
  await expect(page.getByRole('heading', { name: '회원가입', exact: true })).toHaveCount(0);
  await expect(page.getByText(initialNickname, { exact: true })).toBeVisible();

  await openProfile(registrationEmail);
  await page.getByLabel('이메일', { exact: true }).fill(profileEmail);
  await page.getByLabel('닉네임', { exact: true }).fill(profileNickname);
  await page.getByLabel('아바타 URL', { exact: true }).fill(avatarUrl);
  await saveProfile({ email: profileEmail, nickname: profileNickname, avatarUrl });
  expect(await readPersistedProfile()).toEqual({
    status: 200,
    email: profileEmail,
    nickname: profileNickname,
    avatarUrl,
  });
  expect(await readCachedProfile()).toMatchObject({
    email: profileEmail,
    nickname: profileNickname,
  });

  await page.evaluate(() => localStorage.removeItem('b-compiler-user'));
  await page.reload();
  await expect(page.getByText(profileNickname, { exact: true })).toBeVisible();
  expect(await readPersistedProfile()).toEqual({
    status: 200,
    email: profileEmail,
    nickname: profileNickname,
    avatarUrl,
  });
  await openProfile(profileEmail);
  await expect(page.getByLabel('닉네임', { exact: true })).toHaveValue(profileNickname);
  await expect(page.getByLabel('아바타 URL', { exact: true })).toHaveValue(avatarUrl);

  await page.getByLabel('이메일', { exact: true }).fill('');
  await page.getByLabel('닉네임', { exact: true }).fill('');
  await page.getByLabel('아바타 URL', { exact: true }).fill('');
  await saveProfile({ email: null, nickname: null, avatarUrl: null });
  expect(await readPersistedProfile()).toEqual({ status: 200, email: null, nickname: null, avatarUrl: null });

  await page.evaluate(() => localStorage.removeItem('b-compiler-user'));
  await page.reload();
  await expect(page.getByText(username, { exact: true })).toBeVisible();
  expect(await readPersistedProfile()).toEqual({ status: 200, email: null, nickname: null, avatarUrl: null });
  await openProfile('');
  await expect(page.getByLabel('닉네임', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('아바타 URL', { exact: true })).toHaveValue('');
  await assertNoHorizontalOverflow(page);
  expect(pageErrors).toEqual([]);
});

test('a delayed real current-user read cannot replace typed or newly saved profile values', async ({ page }, testInfo) => {
  const suffix = `${Date.now().toString(36)}${testInfo.workerIndex}`;
  const username = `race_${suffix}`;
  const registrationEmail = `race-${suffix}@example.test`;
  const initialNickname = `Race ${suffix}`;
  const firstEmail = `typed-${suffix}@example.test`;
  const firstNickname = `Typed ${suffix}`;
  const savedEmail = `saved-${suffix}@example.test`;
  const savedNickname = `Saved ${suffix}`;
  const password = `BrowserQa!${suffix}9`;

  const saveProfile = async (expected: { email: string; nickname: string }) => {
    const saved = page.waitForResponse(response =>
      response.request().method() === 'PATCH' && response.url().includes('/api/v1/auth/profile'),
    );
    await page.getByRole('button', { name: '저장', exact: true }).click();
    const response = await saved;
    expect(response.ok()).toBeTruthy();
    expect(response.request().postDataJSON()).toMatchObject(expected);
    expect(await response.json()).toMatchObject(expected);
    await expect(page.getByRole('heading', { name: '내 프로필', exact: true })).toHaveCount(0);
  };
  const readPersistedProfile = async () => await page.evaluate(async () => {
    const token = localStorage.getItem('authToken');
    const response = await fetch('/webcompiler/api/v1/auth/profile', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    const profile = await response.json() as { email: string | null; nickname: string | null };
    return { status: response.status, email: profile.email, nickname: profile.nickname };
  });
  const readCachedProfile = async () => await page.evaluate(() => {
    const stored = localStorage.getItem('b-compiler-user');
    return stored ? JSON.parse(stored) as { email?: string | null; nickname?: string | null } : null;
  });

  await page.goto(appPath('/'));
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByRole('button', { name: '회원가입', exact: true }).click();
  await page.getByLabel('사용자 이름', { exact: true }).fill(username);
  await page.getByLabel('이메일', { exact: true }).fill(registrationEmail);
  await page.getByLabel(/닉네임/).fill(initialNickname);
  await page.getByLabel('비밀번호', { exact: true }).fill(password);
  await page.getByLabel('비밀번호 확인', { exact: true }).fill(password);
  await page.getByRole('button', { name: '계정 생성', exact: true }).click();
  await expect(page.getByText(initialNickname, { exact: true })).toBeVisible();

  const openingRead = await holdOneRealCurrentUserRead(page);
  await page.getByTitle('설정').click();
  await expect(page.getByRole('heading', { name: '내 프로필', exact: true })).toBeVisible();
  await openingRead.fetched;
  await page.getByLabel('이메일', { exact: true }).fill(firstEmail);
  await page.getByLabel('닉네임', { exact: true }).fill(firstNickname);
  await releaseReadAndWaitForRender(page, openingRead);
  await expect(page.getByLabel('이메일', { exact: true })).toHaveValue(firstEmail);
  await expect(page.getByLabel('닉네임', { exact: true })).toHaveValue(firstNickname);
  await saveProfile({ email: firstEmail, nickname: firstNickname });
  await openingRead.cleanup();

  const preSaveRead = await holdOneRealCurrentUserRead(page);
  await page.getByTitle('설정').click();
  await expect(page.getByRole('heading', { name: '내 프로필', exact: true })).toBeVisible();
  await preSaveRead.fetched;
  await page.getByLabel('이메일', { exact: true }).fill(savedEmail);
  await page.getByLabel('닉네임', { exact: true }).fill(savedNickname);
  await saveProfile({ email: savedEmail, nickname: savedNickname });
  await releaseReadAndWaitForRender(page, preSaveRead);
  await preSaveRead.cleanup();

  expect(await readCachedProfile()).toMatchObject({ email: savedEmail, nickname: savedNickname });
  expect(await readPersistedProfile()).toEqual({ status: 200, email: savedEmail, nickname: savedNickname });
  await page.evaluate(() => localStorage.removeItem('b-compiler-user'));
  await page.reload();
  await expect(page.getByText(savedNickname, { exact: true })).toBeVisible();
  expect(await readPersistedProfile()).toEqual({ status: 200, email: savedEmail, nickname: savedNickname });
});
