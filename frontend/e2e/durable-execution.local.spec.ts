import { expect, test, type Page, type Request } from '@playwright/test';

const receiptHeaders = { 'Content-Type': 'application/json', 'Set-Cookie': 'guest_execution=e2e-owner; Path=/; HttpOnly; SameSite=Lax' };
const hasGuestCookie = (request: Request) => request.headers().cookie?.includes('guest_execution=e2e-owner') ?? false;

async function rejectUnexpectedApi(page: Page) {
  const unexpected: string[] = [];
  await page.route('**/api/**', async route => {
    unexpected.push(`${route.request().method()} ${route.request().url()}`);
    await route.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"unexpected E2E API"}' });
  });
  return unexpected;
}

test('compiler UI follows its durable receipt without resubmitting', async ({ page }) => {
  const unexpected = await rejectUnexpectedApi(page);
  const external: string[] = [];
  page.on('request', request => { if (/^https?:/.test(request.url()) && new URL(request.url()).origin !== 'http://127.0.0.1:5173') external.push(request.url()); });
  const posts: { requestId?: string; body: Record<string, unknown> }[] = [];
  let polls = 0;
  await page.route('**/api/v1/executions', async route => {
    posts.push({ requestId: route.request().headers()['x-request-id'], body: route.request().postDataJSON() });
    await route.fulfill({ status: 202, headers: receiptHeaders, body: JSON.stringify({ id: 'compile-e2e', status: 'queued', receivedAt: 'now', requestId: posts[0].requestId }) });
  });
  await page.route('**/api/v1/executions/compile-e2e', async route => {
    expect(hasGuestCookie(route.request())).toBe(true); polls += 1;
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(polls === 1
      ? { id: 'compile-e2e', status: 'queued', receivedAt: 'now', result: null }
      : { id: 'compile-e2e', status: 'completed', receivedAt: 'now', result: { ok: true, value: { success: true, execution_time: 7, errors: [], warnings: [] } } }) });
  });

  await page.goto('/ide');
  await expect(page.locator('.monaco-editor')).toBeVisible({ timeout: 30_000 });
  await page.getByRole('button', { name: '컴파일 (Ctrl+Shift+B)' }).click();
  await expect(page.getByText(/컴파일 성공/)).toBeVisible();
  await page.screenshot({ path: 'test-results/durable-compile-completed.png' });

  expect(posts).toHaveLength(1);
  expect(posts[0].requestId).toMatch(/^[0-9a-f-]{36}$/i);
  expect(posts[0].body).toMatchObject({ kind: 'compile', target: 'all', source_code: expect.any(String) });
  expect(polls).toBe(2); expect(unexpected).toEqual([]); expect(external).toEqual([]);
});

test('practice JudgePanel resolves a wrong answer through execution polling', async ({ page }) => {
  const unexpected = await rejectUnexpectedApi(page);
  const problem = { id: 'practice-e2e', title: 'E2E 연습 문제', difficulty: 'iron5', tags: ['io'], description: '출력하세요.', points: 100,
    testCases: [{ input: '', expectedOutput: '42' }], hiddenTestCases: [], createdAt: 'now', solved: false, attempted: false, bestAwardedPoints: 0 };
  await page.route('**/api/v1/problems/practice-e2e', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify(problem) }));
  await page.route('**/api/v1/problems/submissions**', route => route.fulfill({ contentType: 'application/json', body: '{"submissions":[],"total":0,"filteredTotal":0}' }));
  let posts = 0; let polls = 0;
  await page.route('**/api/v1/problems/practice-e2e/submit', async route => {
    posts += 1; expect(route.request().headers()['x-request-id']).toMatch(/^[0-9a-f-]{36}$/i);
    await route.fulfill({ status: 202, headers: receiptHeaders, body: '{"id":"submission-e2e","executionId":"judge-e2e","status":"queued","receivedAt":"now"}' });
  });
  await page.route('**/api/v1/executions/judge-e2e', async route => {
    expect(hasGuestCookie(route.request())).toBe(true); polls += 1;
    const value = { status: 'Rejected', verdict: 'wrong_answer', sampleTotalCases: 1, samplePassedCases: 0, gradingCompleted: false,
      gradingPassed: false, totalCases: 1, passedCases: 0, totalScore: 0, details: [], message: '틀렸습니다.' };
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(polls === 1
      ? { id: 'judge-e2e', status: 'running', receivedAt: 'now', result: null }
      : { id: 'judge-e2e', status: 'completed', receivedAt: 'now', result: { ok: true, verdict: 'wrong_answer', value } }) });
  });

  await page.goto('/challenges/practice-e2e');
  await page.getByRole('button', { name: '문제 풀기' }).click();
  await page.getByRole('button', { name: /채점하기/ }).click();
  await page.getByRole('button', { name: '제출', exact: true }).click();
  await expect(page.getByText('틀렸습니다.')).toBeVisible();
  await page.screenshot({ path: 'test-results/durable-practice-completed.png' });
  expect(posts).toBe(1); expect(polls).toBe(2); expect(unexpected).toEqual([]);
});
