import { expect, test, type Page } from '@playwright/test';

const apiOrigin = 'http://127.0.0.1:18001';
const password = 'LocalContestTest!123';

test('a delayed real Header read cannot restore the profile after saving on the page', async ({ page, request }) => {
  const suffix = Date.now().toString(36);
  const username = `page_race_${suffix}`;
  const initialEmail = `page-race-${suffix}@example.test`;
  expect((await request.post(`${apiOrigin}/api/v1/auth/register`, { data: { username, email: initialEmail, password } })).ok()).toBeTruthy();
  const login = await request.post(`${apiOrigin}/api/v1/auth/login`, { data: { username, password } });
  expect(login.ok()).toBeTruthy();
  await page.addInitScript(token => localStorage.setItem('authToken', token), (await login.json()).accessToken);
  let release!: () => void;
  let fetched!: () => void;
  let complete!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const firstRead = new Promise<void>(resolve => { fetched = resolve; });
  const finished = new Promise<void>(resolve => { complete = resolve; });
  let intercepted = false;
  await page.route('**/api/v1/auth/me', async route => {
    if (intercepted) return route.continue();
    intercepted = true;
    try {
      const response = await route.fetch();
      fetched();
      await gate;
      await route.fulfill({ response });
    } finally { complete(); }
  });
  try {
    await page.goto('/settings');
    await firstRead;
    await expect(page.getByLabel('이메일', { exact: true })).toHaveValue(initialEmail);
    const newEmail = `saved-page-${suffix}@example.test`;
    await page.getByLabel('이메일', { exact: true }).fill(newEmail);
    await page.getByRole('button', { name: '저장', exact: true }).click();
    await expect(page.getByText('프로필을 저장했습니다.', { exact: true })).toBeVisible();
    const delivered = page.waitForResponse(response => response.url() === `${apiOrigin}/api/v1/auth/me`);
    release();
    await (await delivered).finished();
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await expect(page.getByLabel('이메일', { exact: true })).toHaveValue(newEmail);
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem('b-compiler-user')!).email)).toBe(newEmail);
  } finally {
    release();
    await finished;
    await page.unroute('**/api/v1/auth/me');
  }
});

for (const width of [1440, 390]) {
  test(`own profile is a navigable page at ${width}px with reload and browser history`, async ({ page, context, request }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    const username = `profile_page_${width}_${Date.now().toString(36)}`;
    const identity = { username, email: `${username}@example.test`, nickname: `프로필확인${width}${Date.now().toString(36)}`, password };
    const updatedNickname = `변경확인${width}${Date.now().toString(36)}`;
    expect((await request.post(`${apiOrigin}/api/v1/auth/register`, { data: identity })).ok()).toBeTruthy();
    const login = await request.post(`${apiOrigin}/api/v1/auth/login`, { data: { username, password } });
    expect(login.ok()).toBeTruthy();
    await page.addInitScript(token => localStorage.setItem('authToken', token), (await login.json()).accessToken);
    await page.goto('/');
    await page.locator('header').getByRole('img', { name: identity.nickname }).click();
    await page.getByRole('menuitem', { name: '내 프로필' }).click();
    await expect(page).toHaveURL(/\/profile$/);
    await expect(page.getByRole('heading', { level: 1, name: '내 프로필' })).toBeVisible();
    await expect(page.getByRole('heading', { name: identity.nickname, exact: true })).toBeVisible();
    await expect(page.getByLabel('이메일', { exact: true })).toHaveCount(0);
    expect(context.pages()).toHaveLength(1);
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.goBack();
    await expect(page.getByTestId('landing-page')).toBeVisible();
    await page.goForward();
    await expect(page.getByRole('heading', { name: identity.nickname, exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByRole('heading', { name: identity.nickname, exact: true })).toBeVisible();
    const region = page.getByRole('region', { name: '내 프로필', exact: true });
    await region.evaluate(element => { element.scrollTop = 0; });
    expect(await region.evaluate(element => element.scrollWidth <= element.clientWidth)).toBeTruthy();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    // Detect clipped fixed-width content inside the stats panel, too.
    const stats = region.locator('section').first();
    expect(await stats.evaluate(element => element.scrollWidth <= element.clientWidth)).toBeTruthy();
    await page.screenshot({ path: testInfo.outputPath(`profile-page-${width}.png`) });
    await page.getByRole('link', { name: '프로필 편집', exact: true }).click();
    await expect(page).toHaveURL(/\/settings$/);
    await expect(page.getByRole('heading', { name: '설정', exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: '에디터 설정', exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: '화면 설정', exact: true })).toBeVisible();
    await expect(page.getByLabel('이메일', { exact: true })).toHaveValue(identity.email);
    await page.getByLabel('자동저장', { exact: true }).uncheck();
    await expect(page.getByLabel('자동저장', { exact: true })).not.toBeChecked();
    await page.getByLabel('테마', { exact: true }).selectOption('light');
    await expect(page.locator('html')).not.toHaveClass(/dark/);
    await page.getByLabel('테마', { exact: true }).selectOption('dark');
    await expect(page.locator('html')).toHaveClass(/dark/);
    const settingsRegion = page.getByRole('region', { name: '설정', exact: true });
    expect(await settingsRegion.evaluate(element => element.scrollWidth <= element.clientWidth)).toBeTruthy();
    await settingsRegion.evaluate(element => { element.scrollTop = 0; });
    await page.screenshot({ path: testInfo.outputPath('settings-page.png') });
    await page.getByLabel('닉네임', { exact: true }).fill(updatedNickname);
    await page.getByRole('button', { name: '저장', exact: true }).click();
    await expect(page.getByText('프로필을 저장했습니다.', { exact: true })).toBeVisible();
    await expect(page.locator('header').getByRole('img', { name: updatedNickname })).toBeVisible();
    await expect(page).toHaveURL(/\/settings$/);
    await page.getByRole('link', { name: '내 프로필로', exact: true }).click();
    await expect(page.getByRole('heading', { name: updatedNickname, exact: true })).toBeVisible();
    await expect(page.getByLabel('이메일', { exact: true })).toHaveCount(0);
    expect(errors).toEqual([]);
  });
}

test('login supports a two-character nickname and an email longer than 64 characters', async ({ page, request }) => {
  const now = Date.now();
  const suffix = now.toString(36);
  const nickname = String.fromCodePoint(0xac00 + now % 11172, 0xac00 + Math.floor(now / 11172) % 11172);
  const identity = {
    username: `identity_${suffix}`, nickname,
    email: `${'long-mail-'.repeat(5)}${suffix}@example.test`, password,
  };
  expect(identity.email.length).toBeGreaterThan(64);
  expect((await request.post(`${apiOrigin}/api/v1/auth/register`, { data: identity })).ok()).toBeTruthy();
  await page.goto('/');
  for (const loginIdentity of [identity.nickname, identity.email]) {
    await page.getByRole('button', { name: '로그인', exact: true }).click();
    await page.getByLabel('사용자 이름', { exact: true }).fill(loginIdentity);
    await page.getByLabel('비밀번호', { exact: true }).fill(password);
    const submitted = page.waitForResponse(response => response.url() === `${apiOrigin}/api/v1/auth/login`);
    await page.getByRole('button', { name: '로그인', exact: true }).last().click();
    const response = await submitted;
    expect(response.request().postDataJSON().username).toBe(loginIdentity);
    expect(response.status()).toBe(200);
    await expect(page.locator(`img[alt="${nickname}"]`)).toBeVisible();
    await page.locator(`img[alt="${nickname}"]`).click();
    await page.getByRole('menuitem', { name: '로그아웃' }).click();
  }
});

test('two real tabs switch account without carrying the previous profile draft into the new account', async ({ page, context, request }) => {
  const suffix = Date.now().toString(36);
  const identities = ['a', 'b'].map(letter => ({
    username: `tabs_${letter}_${suffix}`, email: `tabs-${letter}-${suffix}@example.test`, password,
  }));
  const tokens: string[] = [];
  for (const identity of identities) {
    expect((await request.post(`${apiOrigin}/api/v1/auth/register`, { data: identity })).ok()).toBeTruthy();
    const response = await request.post(`${apiOrigin}/api/v1/auth/login`, { data: identity });
    expect(response.ok()).toBeTruthy(); tokens.push((await response.json()).accessToken);
  }
  const loginUi = async (tab: Page, identity: typeof identities[number]) => {
    await tab.getByRole('button', { name: '로그인', exact: true }).click();
    await tab.getByLabel('사용자 이름', { exact: true }).fill(identity.username);
    await tab.getByLabel('비밀번호', { exact: true }).fill(password);
    await tab.getByRole('button', { name: '로그인', exact: true }).last().click();
    await expect(tab.locator(`img[alt="${identity.username}"]`)).toBeVisible();
  };
  await page.goto('/');
  await loginUi(page, identities[0]);
  const second = await context.newPage();
  try {
    await second.goto('/');
    await expect(second.locator(`img[alt="${identities[0].username}"]`)).toBeVisible();
    await page.getByTitle('설정', { exact: true }).click();
    await page.getByLabel('이메일', { exact: true }).fill('old-account-draft@example.test');
    await second.locator(`img[alt="${identities[0].username}"]`).click();
    await second.getByRole('menuitem', { name: '로그아웃' }).click();
    await expect(page.getByLabel('이메일', { exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '로그인', exact: true })).toBeVisible();
    await loginUi(second, identities[1]);
    await expect(page.locator('header').locator(`img[alt="${identities[1].username}"]`)).toBeVisible();
    await page.getByTitle('설정', { exact: true }).click();
    await expect(page.getByLabel('이메일', { exact: true })).toHaveValue(identities[1].email);
    for (let index = 0; index < identities.length; index++) {
      const profile = await request.get(`${apiOrigin}/api/v1/auth/profile`, {
        headers: { Authorization: `Bearer ${tokens[index]}` },
      });
      expect(profile.ok()).toBeTruthy();
      expect((await profile.json()).email).toBe(identities[index].email);
    }
  } finally { await second.close(); }
});

test('regular user clears explicit profile fields after reload while omitted fields are retained', async ({ page, request }) => {
  const login = await request.post(`${apiOrigin}/api/v1/auth/login`, {
    data: { username: 'contest_solver', password },
  });
  expect(login.ok()).toBeTruthy();
  const tokenPayload = await login.json() as { accessToken?: string; access_token?: string };
  const token = tokenPayload.accessToken ?? tokenPayload.access_token;
  expect(token).toBeTruthy();
  const headers = { Authorization: `Bearer ${token}` };

  const readProfile = async () => {
    const response = await request.get(`${apiOrigin}/api/v1/auth/profile`, { headers });
    expect(response.ok()).toBeTruthy();
    return await response.json() as {
      email: string | null;
      nickname: string | null;
      avatarUrl: string | null;
    };
  };
  const openProfile = async () => {
    await page.getByTitle('설정').click();
    await expect(page.getByRole('heading', { name: '설정', exact: true })).toBeVisible();
  };
  const saveProfile = async () => {
    const saved = page.waitForResponse(response =>
      response.url() === `${apiOrigin}/api/v1/auth/profile` && response.request().method() === 'PATCH',
    );
    await page.getByRole('button', { name: '저장', exact: true }).click();
    expect((await saved).ok()).toBeTruthy();
    await expect(page.getByText('프로필을 저장했습니다.', { exact: true })).toBeVisible();
  };

  await page.addInitScript(accessToken => localStorage.setItem('authToken', accessToken), token);
  await page.goto('/');
  await expect(page.locator('header img[alt="contest_solver"]')).toBeVisible();

  // Exercise the user-facing editor first: all three fields receive concrete
  // values, so later blank fields must become explicit JSON null values.
  await openProfile();
  await page.getByLabel('이메일', { exact: true }).fill('profile-solver@example.test');
  await page.getByLabel('닉네임', { exact: true }).fill('Profile Solver');
  await page.getByLabel('아바타 URL', { exact: true }).fill('https://example.test/profile-solver.png');
  await saveProfile();

  expect(await readProfile()).toMatchObject({
    email: 'profile-solver@example.test',
    nickname: 'Profile Solver',
    avatarUrl: 'https://example.test/profile-solver.png',
  });

  // The visual form submits every field.  Verify the complementary partial
  // PATCH contract against the same real fixture: omitted keys retain values.
  const partial = await request.patch(`${apiOrigin}/api/v1/auth/profile`, {
    headers: { ...headers, 'Content-Type': 'application/json' },
    data: { nickname: 'Partial Profile Solver' },
  });
  expect(partial.ok()).toBeTruthy();
  expect(await partial.json()).toMatchObject({
    email: 'profile-solver@example.test',
    nickname: 'Partial Profile Solver',
    avatarUrl: 'https://example.test/profile-solver.png',
  });

  const retained = await readProfile();
  expect(retained).toMatchObject({
    email: 'profile-solver@example.test',
    nickname: 'Partial Profile Solver',
    avatarUrl: 'https://example.test/profile-solver.png',
  });

  await page.reload();
  await expect(page.locator('header').getByText('Partial Profile Solver', { exact: true })).toBeVisible();
  await openProfile();
  await expect(page.getByLabel('이메일', { exact: true })).toHaveValue('profile-solver@example.test');
  await expect(page.getByLabel('닉네임', { exact: true })).toHaveValue('Partial Profile Solver');
  await expect(page.getByLabel('아바타 URL', { exact: true })).toHaveValue('https://example.test/profile-solver.png');

  // The browser editor maps blanks to null, not to omitted keys.
  await page.getByLabel('이메일', { exact: true }).fill('');
  await page.getByLabel('닉네임', { exact: true }).fill('');
  await page.getByLabel('아바타 URL', { exact: true }).fill('');
  await saveProfile();

  expect(await readProfile()).toMatchObject({ email: null, nickname: null, avatarUrl: null });

  // Remove the cached profile before reloading.  This makes the assertions
  // below depend on the authenticated GET /auth/me response, not stale UI state.
  await page.evaluate(() => localStorage.removeItem('b-compiler-user'));
  const refreshed = page.waitForResponse(response =>
    response.url() === `${apiOrigin}/api/v1/auth/me` && response.request().method() === 'GET',
  );
  await page.reload();
  expect((await refreshed).ok()).toBeTruthy();
  await expect(page.locator('header img[alt="contest_solver"]')).toBeVisible();
  await openProfile();
  await expect(page.getByLabel('이메일', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('닉네임', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('아바타 URL', { exact: true })).toHaveValue('');
});
