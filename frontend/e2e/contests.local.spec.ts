import { test, expect } from '@playwright/test';

const api = 'http://127.0.0.1:18001';
test('admin creates → participant solves → scoreboard → automatic public release', async ({ page, request, browser }) => {
  // This endpoint exists only in tests/contest_browser_server.py.
  expect((await request.post(`${api}/__test/clock`, {data:{at:'2030-01-01T00:00:00'}})).ok()).toBeTruthy();
  const login = async (username: string) => {
    const response = await request.post(`${api}/api/v1/auth/login`, {data:{username,password:'LocalContestTest!123'}});
    expect(response.ok()).toBeTruthy();
    const data = await response.json(); return data.accessToken || data.access_token;
  };
  const adminToken = await login('contest_admin'); const solverToken = await login('contest_solver');
  await page.addInitScript(token => localStorage.setItem('authToken', token), adminToken);
  await page.goto('/contests/new');
  await page.getByLabel('대회 제목', {exact:true}).fill('Local contest verification');
  await page.getByLabel('설명 및 규칙 (Markdown)').fill('시간 안에 42를 출력하세요.');
  await page.getByLabel('시작 시각 (KST)').fill('2030-01-01T09:01');
  await page.getByLabel('종료 시각 (KST)').fill('2030-01-01T10:00');
  await page.getByRole('button',{name:'신규 문제 추가',exact:true}).click();
  await page.getByLabel('문제 제목',{exact:true}).fill('Secret Forty Two');
  await page.getByLabel('문제 설명 (Markdown)').fill('정수 42를 출력하세요.');
  await page.getByLabel('대회 배점',{exact:true}).fill('500');
  await page.getByLabel('공개 예제 1 출력').fill('42');
  await page.getByRole('group',{name:'숨겨진 테스트',exact:true}).getByRole('button',{name:'+ 테스트 추가'}).click();
  await page.getByLabel('숨겨진 테스트 1 입력').fill('HIDDEN_INPUT_NEVER_PUBLIC');
  await page.getByLabel('숨겨진 테스트 1 출력').fill('42');
  await page.getByLabel('대회 공개 및 참가 신청 받기').check();
  await page.getByRole('button',{name:'대회 저장',exact:true}).click();
  await expect(page).toHaveURL(/\/contests\/[a-f0-9-]+$/);
  const contestId = page.url().split('/').pop()!;
  const root = `${api}/api/v1/contests/${contestId}`;
  const adminDetail = await (await request.get(root,{headers:{Authorization:`Bearer ${adminToken}`}})).json();
  const problem = adminDetail.problems[0];
  expect((await request.get(`${api}/api/v1/problems/${problem.problemId}`)).status()).toBe(404);
  expect((await (await request.get(root)).json()).problems).toEqual([]);

  const context = await browser.newContext({viewport:{width:1440,height:900}});
  await context.addInitScript(token => localStorage.setItem('authToken',token), solverToken);
  const solver = await context.newPage();
  await solver.goto(`http://127.0.0.1:4175/contests/${contestId}`);
  await solver.getByRole('button',{name:'참가 신청',exact:true}).click();
  await expect(solver.getByText('참가 신청 완료',{exact:true})).toBeVisible();
  await request.post(`${api}/__test/clock`,{data:{at:'2030-01-01T00:01:00'}});
  await solver.getByRole('link',{name:/Secret Forty Two/}).click({timeout:10000});
  const editor = solver.locator('.view-lines').first();
  await expect(editor).toBeVisible({timeout:30000});
  for (const [language, text] of [['python','print('],['java','public class Main'],['cpp','#include'],['c','#include'],['javascript','console.log'],['bpp','func main']] ) {
    await solver.getByRole('combobox',{name:'실행 언어 선택'}).selectOption(language);
    await expect(editor).toContainText(text);
  }
  await solver.getByRole('combobox',{name:'실행 언어 선택'}).selectOption('python');
  await editor.click(); await solver.keyboard.press('ControlOrMeta+a'); await solver.keyboard.insertText('print(42) # contest-only-code');
  await expect(editor).toContainText('contest-only-code');
  await solver.getByRole('button',{name:'대회 제출',exact:true}).click();
  await expect(solver.getByTestId('contest-verdict')).toHaveText('정답',{timeout:20000});
  await expect.poll(async () => {
    const projects = await request.get(`${api}/api/v1/projects/${encodeURIComponent(`contest:${contestId}:${problem.id}`)}`, {headers:{Authorization:`Bearer ${solverToken}`}});
    return projects.status();
  }).toBe(200);
  await solver.reload(); await expect(editor).toContainText('contest-only-code');
  await expect(solver.getByRole('combobox',{name:'실행 언어 선택'})).toHaveValue('python');
  await solver.screenshot({path:'test-results/contest-ide.png',fullPage:true});
  await solver.goto(`http://127.0.0.1:4175/contests/${contestId}`);
  await solver.getByRole('button',{name:'스코어보드',exact:true}).click();
  await expect(solver.getByRole('cell',{name:/^\+500/})).toBeVisible();
  await solver.screenshot({path:'test-results/contest-scoreboard.png',fullPage:true});
  await solver.setViewportSize({width:390,height:844});
  await solver.screenshot({path:'test-results/contest-mobile.png',fullPage:true});
  expect(await solver.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
  await solver.getByRole('button',{name:'내 제출',exact:true}).click();
  await expect(solver.getByText('정답',{exact:true})).toBeVisible();

  await request.post(`${api}/__test/clock`,{data:{at:'2030-01-01T01:00:00'}});
  await expect.poll(async () => (await (await request.get(root)).json()).state).toBe('finished');
  const publicProblem = await request.get(`${api}/api/v1/problems/${problem.problemId}`);
  expect(publicProblem.status()).toBe(200); expect(await publicProblem.text()).not.toContain('HIDDEN_INPUT_NEVER_PUBLIC');
  const user = await (await request.get(`${api}/api/v1/auth/me`,{headers:{Authorization:`Bearer ${solverToken}`}})).json();
  expect(user.totalScore).toBe(100);
  const queueText = await (await request.get(`${api}/api/v1/compiler/queue`)).text();
  expect(queueText).not.toContain('Secret Forty Two'); expect(queueText).not.toContain('HIDDEN_INPUT_NEVER_PUBLIC');
  await solver.goto('http://127.0.0.1:4175/challenges');
  await expect(solver.getByText('Secret Forty Two',{exact:true})).toBeVisible();
  await solver.goto('http://127.0.0.1:4175/ide');
  await expect(editor).not.toContainText('contest-only-code');
  await context.close();
});
