// Uses learning_browser_server.py: real API/auth/queue, explicitly fake compiler.
import { expect, test, type APIRequestContext } from '@playwright/test';

const api = 'http://127.0.0.1:18002/api/v1';
async function newUser(request: APIRequestContext) {
  const username = `learn_${crypto.randomUUID().slice(0, 8)}`;
  const password = 'LocalLearningTest!123';
  expect((await request.post(`${api}/auth/register`, { data: { username, password, email: `${username}@example.test` } })).ok()).toBeTruthy();
  const response = await request.post(`${api}/auth/login`, { data: { username, password } });
  expect(response.ok()).toBeTruthy();
  return (await response.json()).accessToken as string;
}

async function submit(request: APIRequestContext, token: string, problem: string, code: string) {
  const headers = { Authorization: `Bearer ${token}`, 'X-Request-ID': crypto.randomUUID() };
  const receipt = await request.post(`${api}/problems/${problem}/submit`, { headers, data: { code, language: 'python' } });
  expect(receipt.status()).toBe(202);
  const { executionId } = await receipt.json();
  let result: any;
  await expect.poll(async () => {
    const response = await request.get(`${api}/executions/${executionId}`, { headers });
    expect(response.ok()).toBeTruthy();
    result = await response.json();
    return result.status;
  }, { timeout: 20_000 }).toBe('completed');
  return result.result;
}

for (const width of [1440, 390]) {
  test(`learning, private notes and custom execution integrate at ${width}px`, async ({ page, request }, info) => {
    await page.setViewportSize({ width, height: 1000 });
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    const token = await newUser(request);
    const headers = { Authorization: `Bearer ${token}` };
    await page.addInitScript(token => localStorage.setItem('authToken', token), token);
    await page.goto('/learning');
    await expect(page.getByRole('heading', { name: '학습', exact: true })).toBeVisible();
    const firstCard = page.getByRole('article').filter({ has: page.getByRole('heading', { name: '학습 테스트 문제 1', exact: true }) });
    await expect(firstCard).toBeVisible();
    // Wait for the initial stored theme transition before taking visual evidence.
    await expect.poll(() => page.locator('header').evaluate(el => getComputedStyle(el).backgroundColor)).toBe('rgb(30, 30, 30)');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await page.screenshot({ path: info.outputPath(`learning-${width}.png`) });
    await firstCard.getByRole('button', { name: '문제 풀기' }).click();
    await expect(page).toHaveURL(/\/ide$/);
    if (width < 768) await page.locator('#mobile-problem-tab').click();
    await page.getByRole('checkbox', { name: '북마크', exact: true }).check();
    await page.getByLabel('개인 메모', { exact: true }).fill('입출력 형식을 다시 확인하기 <script>literal</script>');
    await page.getByRole('region', { name: '복습 메모', exact: true }).getByRole('button', { name: '저장', exact: true }).click();
    await expect(page.getByText('저장했습니다.', { exact: true })).toBeVisible();
    const beforeScore = (await (await request.get(`${api}/auth/me`, { headers })).json()).totalScore;
    const beforeSubmissions = (await (await request.get(`${api}/problems/submissions?mine=true`, { headers })).json()).total;
    if (width < 768) await page.locator('#mobile-console-tab').click();
    await page.getByRole('tab', { name: '사용자 테스트', exact: true }).click();
    await page.getByRole('button', { name: '예제 1 적용' }).click();
    await expect(page.getByLabel('표준 입력', { exact: true })).toHaveValue('42');
    const submitted = page.waitForRequest(r => r.url() === `${api}/executions` && r.method() === 'POST');
    await page.getByRole('button', { name: '테스트 실행', exact: true }).click();
    const payload = (await submitted).postDataJSON();
    expect(payload.stdin).toBe('42');
    expect(payload.kind).toBe('run');
    expect(payload).not.toHaveProperty('problem_id');
    await expect(page.getByText('사용자 테스트 비교: 출력 일치', { exact: true })).toBeVisible({ timeout: 20_000 });
    await page.screenshot({ path: info.outputPath(`custom-test-${width}.png`) });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    expect((await (await request.get(`${api}/auth/me`, { headers })).json()).totalScore).toBe(beforeScore);
    expect((await (await request.get(`${api}/problems/submissions?mine=true`, { headers })).json()).total).toBe(beforeSubmissions);
    await page.goto('/learning');
    await page.getByRole('tab', { name: '복습', exact: true }).click();
    await page.getByRole('button', { name: '북마크', exact: true }).click();
    await expect(page.getByRole('article')).toHaveCount(1);
    await expect(page.getByRole('article')).toContainText('입출력 형식을 다시 확인하기');
    await page.getByRole('button', { name: '복습 메모 열기' }).click();
    await page.getByLabel('개인 메모', { exact: true }).fill('저장 후 목록 갱신');
    await page.getByRole('button', { name: '저장', exact: true }).click();
    await expect(page.getByRole('article')).toContainText('저장 후 목록 갱신');
    await page.screenshot({ path: info.outputPath(`review-${width}.png`) });
    await page.getByRole('tab', { name: '추천', exact: true }).click();
    await expect(page.getByRole('article').first()).toContainText('추천 근거:');
    expect(errors).toEqual([]);
  });
}

test('queue publication updates unresolved/progress/recommendations without duplicate awards', async ({ request }) => {
  const token = await newUser(request);
  const headers = { Authorization: `Bearer ${token}` };
  expect((await submit(request, token, 'learning-e2e-0', 'WRONG_ANSWER')).verdict).toBe('wrong_answer');
  let review = await (await request.get(`${api}/learning/review`, { headers })).json();
  expect(review.items.map((p: any) => p.id)).toContain('learning-e2e-0');
  expect((await submit(request, token, 'learning-e2e-0', 'print(42)')).verdict).toBe('accepted');
  expect((await submit(request, token, 'learning-e2e-0', 'print(42)')).verdict).toBe('accepted');
  review = await (await request.get(`${api}/learning/review`, { headers })).json();
  expect(review.items.map((p: any) => p.id)).not.toContain('learning-e2e-0');
  const tracks = await (await request.get(`${api}/learning/tracks`, { headers })).json();
  expect(tracks.tracks.find((t: any) => t.id === 'io').solved).toBe(1);
  const recommendations = await (await request.get(`${api}/learning/recommendations`, { headers })).json();
  expect(recommendations.items.map((p: any) => p.id)).not.toContain('learning-e2e-0');
  expect((await (await request.get(`${api}/auth/me`, { headers })).json()).totalScore).toBe(100);
});

test('guest learning works and private endpoints require authentication', async ({ page, request }) => {
  await page.goto('/learning');
  await expect(page.getByRole('article').first()).toBeVisible();
  await page.getByRole('tab', { name: '복습', exact: true }).click();
  await expect(page.getByText('복습 목록과 개인 메모는 로그인한 계정에서만 볼 수 있습니다.')).toBeVisible();
  expect((await request.get(`${api}/learning/review`)).status()).toBe(401);
});
