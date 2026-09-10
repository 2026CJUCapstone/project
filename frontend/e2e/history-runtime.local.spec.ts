import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { expect, test, type APIRequestContext, type Page, type Response } from '@playwright/test';

const appPath = (path: string) => `/webcompiler${path}`;
const api = appPath('/api/v1');
const expectedPoints = 137;

type Account = {
  username: string;
  password: string;
};

type CreatedProblem = {
  id: string;
  title: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function readAccount(value: unknown): Account {
  if (!isRecord(value) || typeof value.username !== 'string' || typeof value.password !== 'string') {
    // This fixture contains credentials.  Keep diagnostics shape-only.
    throw new Error('Disposable contest account fixture has an unexpected shape.');
  }
  return { username: value.username, password: value.password };
}

async function readAdminAccount(): Promise<Account> {
  // Deliberately read only in the Node test process: do not log, attach, or
  // render the fixture contents in browser artifacts.
  const raw = await readFile(new URL('../../.deploy/contest-browser-accounts-49.json', import.meta.url), 'utf8');
  const parsed: unknown = JSON.parse(raw);
  const accounts = isRecord(parsed) && isRecord(parsed.accounts) ? parsed.accounts : parsed;
  return readAccount(isRecord(accounts) ? accounts.admin : undefined);
}

function isPath(response: Response, method: string, pathname: string): boolean {
  return response.request().method() === method && new URL(response.url()).pathname === pathname;
}

function hasQuery(response: Response, pathname: string, expected: Record<string, string>): boolean {
  if (!isPath(response, 'GET', pathname)) return false;
  const params = new URL(response.url()).searchParams;
  return Object.entries(expected).every(([key, value]) => params.get(key) === value);
}

async function assertNoBodyOverflow(page: Page) {
  const dimensions = await page.evaluate(() => ({
    viewport: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    bodyWidth: document.body.scrollWidth,
  }));
  expect(dimensions.documentWidth).toBeLessThanOrEqual(dimensions.viewport);
  expect(dimensions.bodyWidth).toBeLessThanOrEqual(dimensions.viewport);
}

async function waitForAnimationFrames(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  }));
}

async function createPublicProblem(request: APIRequestContext, admin: Account, title: string): Promise<CreatedProblem> {
  const login = await request.post(`${api}/auth/login`, { data: admin });
  expect(login.ok()).toBeTruthy();
  const loginBody = await login.json() as { accessToken?: unknown };
  expect(typeof loginBody.accessToken).toBe('string');
  const headers = { Authorization: `Bearer ${loginBody.accessToken as string}` };

  const created = await request.post(`${api}/problems/`, {
    headers,
    data: {
      title,
      difficulty: 'iron5',
      tags: ['history-runtime'],
      description: 'Print the integer 42.  This disposable browser-runtime problem is public.',
      points: expectedPoints,
      testCases: [{ input: '', expectedOutput: '42' }],
      hiddenTestCases: [{ input: '', expectedOutput: '42' }],
    },
  });
  expect(created.ok()).toBeTruthy();
  const body = await created.json() as { id?: unknown; title?: unknown; points?: unknown };
  expect(typeof body.id).toBe('string');
  expect(body.title).toBe(title);
  expect(body.points).toBe(expectedPoints);

  // Confirm that the admin-created problem is actually public before the UI
  // drives it through the participant flow.
  const publicRead = await request.get(`${api}/problems/${body.id as string}`);
  expect(publicRead.ok()).toBeTruthy();
  return { id: body.id as string, title };
}

async function registerThroughUi(page: Page, account: Account, nickname: string) {
  await page.goto(appPath('/'));
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByRole('button', { name: '회원가입', exact: true }).click();
  await expect(page.getByRole('heading', { name: '회원가입', exact: true })).toBeVisible();
  await page.getByLabel('사용자 이름', { exact: true }).fill(account.username);
  await page.getByLabel('이메일', { exact: true }).fill(`${account.username}@example.test`);
  await page.getByLabel(/닉네임/).fill(nickname);
  await page.getByLabel('비밀번호', { exact: true }).fill(account.password);
  await page.getByLabel('비밀번호 확인', { exact: true }).fill(account.password);
  const registered = page.waitForResponse(response => isPath(response, 'POST', `${api}/auth/register`));
  const loggedIn = page.waitForResponse(response => isPath(response, 'POST', `${api}/auth/login`));
  await page.getByRole('button', { name: '계정 생성', exact: true }).click();
  expect((await registered).ok()).toBeTruthy();
  expect((await loggedIn).ok()).toBeTruthy();
  await expect(page.getByText(nickname, { exact: true })).toBeVisible();
}

test('actual public problem history stays consistent from challenge through IDE, queue, submissions, and leaderboard', async ({ page, request }, testInfo) => {
  test.setTimeout(180_000);
  const suffix = `${Date.now().toString(36)}${testInfo.workerIndex}${randomUUID().replaceAll('-', '').slice(0, 6)}`;
  const user: Account = {
    username: `history_${suffix}`,
    password: `HistoryQa!${suffix}9`,
  };
  const title = `History runtime ${suffix}`;
  const pythonCode = 'print(42)';
  const pageErrors: string[] = [];
  page.on('pageerror', error => pageErrors.push(error.message));

  const problem = await createPublicProblem(request, await readAdminAccount(), title);
  await page.setViewportSize({ width: 1440, height: 900 });
  await registerThroughUi(page, user, `History ${suffix}`);

  await page.goto(appPath('/challenges'));
  await expect(page.getByRole('heading', { name: '문제 목록', exact: true })).toBeVisible();
  await page.getByPlaceholder('문제 제목/설명 검색', { exact: true }).fill(problem.title);
  const detailLink = page.getByRole('button', { name: `${problem.title} 문제 상세 보기`, exact: true });
  await expect(detailLink).toBeVisible();
  await assertNoBodyOverflow(page);
  await page.screenshot({ path: testInfo.outputPath('history-runtime-desktop.png'), fullPage: true });

  await detailLink.click();
  await expect(page).toHaveURL(new RegExp(`/webcompiler/challenges/${problem.id}$`));
  await expect(page.getByRole('heading', { name: problem.title, exact: true })).toBeVisible();
  await assertNoBodyOverflow(page);

  const projectHydrated = page.waitForResponse(response =>
    response.request().method() === 'GET'
    && decodeURIComponent(new URL(response.url()).pathname) === `${api}/projects/problem:${problem.id}`,
    { timeout: 10_000 },
  );
  await page.getByRole('button', { name: '문제 풀기', exact: true }).click();
  await expect(page).toHaveURL(/\/webcompiler\/ide$/);
  const language = page.locator('select[title="실행 언어 선택"]');
  const editor = page.locator('.monaco-editor .view-lines').first();
  await expect(editor).toBeVisible();
  await projectHydrated;
  await waitForAnimationFrames(page);
  await expect(editor).toContainText('func main');
  await expect(language).toBeEnabled();
  await language.selectOption('python');
  await expect(language).toHaveValue('python');

  await editor.click({ position: { x: 48, y: 14 } });
  await page.keyboard.press('ControlOrMeta+A');
  await page.keyboard.insertText(pythonCode);
  await expect(editor).toContainText(pythonCode);
  await assertNoBodyOverflow(page);

  await page.getByText('채점하기', { exact: true }).click();
  const judgePanel = page.getByText(`채점 - ${problem.title}`, { exact: true }).locator('xpath=../../..');
  await expect(judgePanel).toBeVisible();
  const submitted = page.waitForResponse(response => isPath(response, 'POST', `${api}/problems/${problem.id}/submit`));
  await judgePanel.getByRole('button', { name: '제출', exact: true }).click();
  const submissionResponse = await submitted;
  expect(submissionResponse.status()).toBe(202);
  const submissionBody = submissionResponse.request().postDataJSON() as { code?: unknown; language?: unknown };
  expect(submissionBody.code).toBe(pythonCode);
  await testInfo.attach('submission-language-contract', {
    contentType: 'application/json',
    body: Buffer.from(JSON.stringify({ problemId: problem.id, expectedLanguage: 'python', observedLanguage: submissionBody.language })),
  });
  // Keep this strict: selecting Python in the IDE must produce a Python
  // grading receipt.  Do not weaken it to B++ to accommodate an old image.
  expect(submissionBody.language).toBe('python');

  await expect(judgePanel.getByText('정답', { exact: true }).first()).toBeVisible({ timeout: 90_000 });

  await page.goto(appPath('/queue'));
  await expect(page.getByRole('heading', { name: '컴파일 큐', exact: true })).toBeVisible();
  const queueSelects = page.locator('select');
  await queueSelects.nth(1).selectOption('grading');
  await queueSelects.nth(2).selectOption('accepted');
  await page.getByPlaceholder('문제 ID', { exact: true }).fill(problem.id);
  await page.getByPlaceholder('사용자 이름', { exact: true }).fill(user.username);
  const filteredQueue = page.waitForResponse(response => hasQuery(response, `${api}/compiler/queue`, {
    kind: 'grading', verdict: 'accepted', problemId: problem.id, username: user.username,
  }));
  await page.getByRole('button', { name: '적용', exact: true }).click();
  expect((await filteredQueue).ok()).toBeTruthy();
  const queueRow = page.locator('tbody tr').filter({ has: page.getByText(problem.title, { exact: true }) })
    .filter({ has: page.getByText(user.username, { exact: true }) });
  await expect(queueRow).toHaveCount(1);
  await expect(queueRow).toContainText('채점');
  await expect(queueRow).toContainText('정답');
  await assertNoBodyOverflow(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await assertNoBodyOverflow(page);

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(appPath('/submissions'));
  await expect(page.getByRole('heading', { name: '제출 이력', exact: true })).toBeVisible();
  const submissionSelects = page.locator('select');
  await submissionSelects.nth(1).selectOption('accepted');
  await page.getByPlaceholder('문제 ID', { exact: true }).fill(problem.id);
  await page.getByPlaceholder('사용자 이름', { exact: true }).fill(user.username);
  const filteredSubmissions = page.waitForResponse(response => hasQuery(response, `${api}/problems/submissions`, {
    verdict: 'accepted', problemId: problem.id, username: user.username,
  }));
  await page.getByRole('button', { name: '적용', exact: true }).click();
  expect((await filteredSubmissions).ok()).toBeTruthy();
  const submissionRow = () => page.locator('tbody tr').filter({ has: page.getByText(problem.title, { exact: true }) })
    .filter({ has: page.getByText(user.username, { exact: true }) });
  await expect(submissionRow()).toHaveCount(1);
  await expect(submissionRow()).toContainText('정답');

  const mine = page.waitForResponse(response => hasQuery(response, `${api}/problems/submissions`, {
    verdict: 'accepted', problemId: problem.id, mine: 'true',
  }));
  await page.getByRole('button', { name: '내 제출', exact: true }).click();
  expect((await mine).ok()).toBeTruthy();
  await expect(submissionRow()).toHaveCount(1);
  await submissionRow().getByRole('button', { name: problem.title, exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/webcompiler/challenges/${problem.id}$`));
  await expect(page.getByRole('heading', { name: problem.title, exact: true })).toBeVisible();
  await assertNoBodyOverflow(page);

  await page.goto(appPath('/leaderboard'));
  await expect(page.getByRole('heading', { name: '리더보드', exact: true })).toBeVisible();
  const leaderboardRow = page.getByText(user.username, { exact: true }).locator('xpath=../..');
  await expect(leaderboardRow).toContainText(expectedPoints.toLocaleString(), { timeout: 30_000 });
  await page.setViewportSize({ width: 390, height: 844 });
  await assertNoBodyOverflow(page);
  await page.screenshot({ path: testInfo.outputPath('history-runtime-mobile.png'), fullPage: true });
  expect(pageErrors).toEqual([]);
});
