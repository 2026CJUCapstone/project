import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { randomUUID } from 'node:crypto';
import { test, expect, type Page } from '@playwright/test';

const origin = 'http://127.0.0.1:15181';
const base = '/webcompiler';
const api = base + '/api/v1';
type Account = { username: string; password: string; id: string };

async function loginUi(page: Page, account: Account) {
  await page.goto(base + '/');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByLabel('사용자 이름', { exact: true }).fill(account.username);
  await page.getByLabel('비밀번호', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: '로그인', exact: true }).last().click();
  await expect(page.locator(`img[alt="${account.username}"]`)).toBeVisible();
}

async function replaceCode(page: Page, code: string) {
  const editor = page.locator('.monaco-editor .view-lines').first();
  await expect(editor).toBeVisible();
  await editor.click({ position: { x: 60, y: 12 } });
  await page.keyboard.press('ControlOrMeta+A');
  await page.keyboard.insertText(code);
  await expect(editor).toContainText(code);
}

test('actual contest editor, participation, Docker grading, scoreboard and wall-clock finalization', async ({ page, request, browser }, testInfo) => {
  expect(new URL(testInfo.project.use.baseURL as string).origin).toBe(origin);
  const accounts = JSON.parse(readFileSync(resolve('../.deploy/contest-browser-accounts-49.json'), 'utf8')) as Record<string, Account>;
  const headersFor = async (account: Account) => {
    const response = await request.post(api + '/auth/login', { data: account });
    expect(response.ok()).toBeTruthy();
    return { Authorization: `Bearer ${(await response.json()).accessToken}` };
  };
  const adminHeaders = await headersFor(accounts.admin);
  const solverHeaders = await headersFor(accounts.solver);
  const otherHeaders = await headersFor(accounts.other);
  const baseline = await request.get(api + '/auth/me', { headers: solverHeaders });
  expect(baseline.ok()).toBeTruthy();
  const startingScore = (await baseline.json()).totalScore;
  const clock = await request.get(api + '/contests');
  expect(clock.ok()).toBeTruthy();
  const serverNow = Date.parse(clock.headers().date);
  expect(Number.isFinite(serverNow)).toBeTruthy();
  const starts = Math.ceil((serverNow + 30_000) / 60_000) * 60_000;
  const ends = starts + 120_000;
  const kstInput = (time: number) => new Date(time + 9 * 3600_000).toISOString().slice(0, 16);
  const title = `Actual browser contest ${randomUUID().slice(0, 8)}`;
  const problemTitle = `Actual private forty two ${randomUUID().slice(0, 8)}`;
  const hiddenMarker = 'OWNED_HIDDEN_INPUT_49_NEVER_PUBLIC';

  await loginUi(page, accounts.admin);
  await page.goto(base + '/contests/new');
  await page.getByLabel('대회 제목', { exact: true }).fill(title);
  await page.getByLabel('설명 및 규칙 (Markdown)').fill('Actual isolated Docker grading verification.');
  await page.getByLabel('시작 시각 (KST)').fill(kstInput(starts));
  await page.getByLabel('종료 시각 (KST)').fill(kstInput(ends));
  await page.getByRole('button', { name: '신규 문제 추가', exact: true }).click();
  await page.getByLabel('문제 제목', { exact: true }).fill(problemTitle);
  await page.getByLabel('문제 설명 (Markdown)').fill('정수 42를 출력하세요.');
  await page.getByLabel('대회 배점', { exact: true }).fill('500');
  await page.getByLabel('일반 문제 점수', { exact: true }).fill('17');
  await page.getByLabel('공개 예제 1 출력').fill('42');
  await page.getByRole('group', { name: '숨겨진 테스트', exact: true }).getByRole('button', { name: '+ 테스트 추가' }).click();
  await page.getByLabel('숨겨진 테스트 1 입력').fill(hiddenMarker);
  await page.getByLabel('숨겨진 테스트 1 출력').fill('42');
  await page.getByLabel('대회 공개 및 참가 신청 받기').check();
  await page.getByRole('button', { name: '대회 저장', exact: true }).click();
  await expect(page).toHaveURL(/\/contests\/[a-f0-9-]+$/);
  const contestId = page.url().split('/').pop()!;
  const root = api + '/contests/' + contestId;
  const detail = await request.get(root, { headers: adminHeaders });
  expect(detail.ok()).toBeTruthy();
  const contest = await detail.json();
  expect(Date.parse(contest.startsAt)).toBe(starts);
  expect(Date.parse(contest.endsAt)).toBe(ends);
  const problem = contest.problems[0];
  expect((await request.get(api + '/problems/' + problem.problemId)).status()).toBe(404);
  expect((await (await request.get(root)).json()).problems).toEqual([]);
  const submitPath = `${root}/problems/${problem.id}/submit`;
  expect((await request.post(submitPath, { headers: otherHeaders,
    data: { code: 'print(42)', language: 'python', requestId: randomUUID() } })).status()).toBe(403);

  const context = await browser.newContext({ baseURL: origin, viewport: { width: 1440, height: 900 } });
  const solver = await context.newPage();
  try {
    await loginUi(solver, accounts.solver);
    await solver.goto(base + '/contests/' + contestId);
    await solver.getByRole('button', { name: '참가 신청', exact: true }).click();
    await expect(solver.getByText('참가 신청 완료', { exact: true })).toBeVisible();
    // No fake clock or mutation of started schedules. Wait for real UTC time.
    await expect(solver.getByRole('link', { name: new RegExp(problemTitle) })).toBeVisible({ timeout: 100_000 });
    expect((await request.get(`${root}/problems/${problem.id}`, { headers: otherHeaders })).status()).toBe(403);
    await solver.getByRole('link', { name: new RegExp(problemTitle) }).click();
    const editor = solver.locator('.monaco-editor .view-lines').first();
    await expect(editor).toBeVisible({ timeout: 30_000 });
    for (const [language, template] of [['cpp', '#include'], ['c', '#include'], ['java', 'public class Main'],
      ['javascript', 'console.log'], ['bpp', 'func main'], ['python', 'print(']]) {
      await solver.getByRole('combobox', { name: '실행 언어 선택' }).selectOption(language);
      await expect(editor).toContainText(template);
    }
    const receipts: { id: string; verdict: string; receivedAt: string }[] = [];
    for (const [code, verdict, label] of [['print(0)', 'wrong_answer', '오답'], ['if :', 'compile_error', '컴파일 오류'],
      ['print(42) # actual-contest-only', 'accepted', '정답'], ['print(42) # duplicate-correct', 'accepted', '정답']]) {
      await replaceCode(solver, code);
      const posted = solver.waitForResponse(response => response.url() === origin + submitPath && response.request().method() === 'POST');
      await solver.getByRole('button', { name: '대회 제출', exact: true }).click();
      const response = await posted;
      expect(response.request().postDataJSON().code).toBe(code);
      expect(response.status()).toBe(202);
      const receipt = await response.json();
      await expect.poll(async () => {
        const result = await request.get(`${root}/submissions/${receipt.id}`, { headers: solverHeaders });
        expect(result.ok()).toBeTruthy();
        return (await result.json()).verdict;
      }, { timeout: 40_000, intervals: [500, 1000, 2000] }).toBe(verdict);
      await expect(solver.getByTestId('contest-verdict')).toHaveText(label);
      receipts.push({ id: receipt.id, verdict, receivedAt: receipt.receivedAt });
      expect((await request.get(`${root}/submissions/${receipt.id}`, { headers: otherHeaders })).status()).toBe(404);
    }
    const boardResponse = await request.get(root + '/scoreboard');
    expect(boardResponse.ok()).toBeTruthy();
    const board = await boardResponse.json();
    const row = board.rows.find((entry: { userId: string }) => entry.userId === accounts.solver.id);
    expect(row.totalPoints).toBe(500);
    expect(row.rank).toBe(1);
    expect(row.problems[0].wrongAttempts).toBe(1);
    expect(row.penaltySeconds).toBeCloseTo((Date.parse(receipts[2].receivedAt) - starts) / 1000 + 300, 2);
    expect((await (await request.get(api + '/auth/me', { headers: solverHeaders })).json()).totalScore).toBe(startingScore);
    await solver.reload();
    await expect(editor).toContainText('duplicate-correct');
    await solver.goto(base + '/contests/' + contestId);
    await solver.getByRole('button', { name: '스코어보드', exact: true }).click();
    await expect(solver.getByRole('cell', { name: /^\+500/ })).toBeVisible();
    await solver.setViewportSize({ width: 390, height: 844 });
    await solver.getByRole('cell', { name: /^\+500/ }).scrollIntoViewIfNeeded();
    expect(await solver.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await solver.screenshot({ path: testInfo.outputPath('actual-contest-mobile.png'), fullPage: true });
    await solver.getByRole('button', { name: '내 제출', exact: true }).click();
    await expect(solver.getByText('정답', { exact: true })).toHaveCount(2);
    await expect.poll(async () => (await (await request.get(root)).json()).state,
      { timeout: 180_000, intervals: [1000, 5000] }).toBe('finished');
    expect((await request.post(submitPath, { headers: solverHeaders,
      data: { code: 'print(42)', language: 'python', requestId: randomUUID() } })).status()).toBe(403);
    const publicProblem = await request.get(api + '/problems/' + problem.problemId);
    expect(publicProblem.ok()).toBeTruthy();
    expect(await publicProblem.text()).not.toContain(hiddenMarker);
    await expect.poll(async () => (await (await request.get(api + '/auth/me', { headers: solverHeaders })).json()).totalScore,
      { timeout: 15_000 }).toBe(startingScore + 17);
    await solver.goto(base + '/challenges');
    await expect(solver.getByText(problemTitle, { exact: true })).toBeVisible();
    await solver.goto(base + '/ide');
    await solver.getByRole('tab', { name: '코드', exact: true }).click();
    await expect(editor).toBeVisible();
    await expect(editor).not.toContainText('duplicate-correct');
    await testInfo.attach('actual-contest-evidence', { contentType: 'application/json', body: Buffer.from(JSON.stringify({
      contestId, problemId: problem.problemId, startsAt: contest.startsAt, endsAt: contest.endsAt,
      receipts, points: row.totalPoints, penaltySeconds: row.penaltySeconds, generalAward: 17,
      runtime: 'actual isolated PostgreSQL/Redis/worker/Docker; real wall clock',
    }, null, 2)) });
  } finally { await context.close(); }
});
