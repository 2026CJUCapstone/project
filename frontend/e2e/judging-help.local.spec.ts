import { expect, test } from '@playwright/test';

const stage = (cpuMs: number, memoryBytes = 268435456) => ({ cpuMs, wallMs: cpuMs + 500, memoryBytes, outputBytes: 1048576, pids: 64, tmpBytes: 524288 });
const policy = { policyId: 'legacy-compatibility-v1', revision: 1, reviewStatus: 'compatibility', languages: Object.fromEntries([
  ['bpp', 2000], ['c', 2000], ['cpp', 2000], ['python', 4000], ['java', 4000], ['javascript', 4000],
].map(([language, cpu]) => [language, { runtimeVersion: '검증 런타임', run: stage(Number(cpu)), compile: stage(8000) }])) };
const fixture = { id: 'help-test', title: '도움말 검증 문제', description: '채점 안내 화면 검증용 문제입니다.', difficulty: 'bronze5', tags: [], points: 100,
  testCases: [], hiddenTestCases: [], solved: false, attempted: false, bestAwardedPoints: 0,
  judgeLimits: policy, judgePolicyLegacy: false, judgePolicyCompatibility: true };
const supplied = process.env.JUDGING_HELP_BASE_URL;
const appPath = (path: string) => supplied ? '/webcompiler' + path : path;

for (const theme of ['dark', 'light'] as const) for (const width of [320, 390, 820, 1440]) {
  test(`judging help ${theme}/${width}px: compact problem, full contextual help, direct refresh`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => localStorage.clear());
    // Isolated UI fixtures even for deployed rendering; no production enrollment,
    // source/history requests, code execution, mail or other mutations permitted.
    await page.route('**/api/v1/**', route => {
      if (route.request().method() !== 'GET') return route.abort();
      const url = new URL(route.request().url());
      if (url.pathname.endsWith('/problems/help-test')) return route.fulfill({ json: fixture });
      if (url.pathname.endsWith('/contests/help-event/problems/A')) return route.fulfill({ json: { ...fixture, id: 'A', title: '대회 스냅샷 제한', contest: {} } });
      if (url.pathname.endsWith('/submissions/')) return route.fulfill({ json: { submissions: [], total: 0, filteredTotal: 0 } });
      return route.fulfill({ status: 404, json: { detail: 'UI fixture only' } });
    });
    await page.goto(appPath('/problems/help-test'));
    await expect(page.getByRole('heading', { name: fixture.title, exact: true })).toBeVisible();
    if (theme === 'light') await page.getByTitle('라이트 테마로 전환').click();
    await expect.poll(() => page.locator('html').evaluate(node => node.classList.contains('dark'))).toBe(theme === 'dark');
    const summary = page.getByRole('region', { name: 'B++ 채점 제한' });
    await expect(summary).toBeVisible();
    await expect(summary).toContainText('2초');
    await expect(summary).toContainText('256 MiB');
    expect((await summary.boundingBox())!.height).toBeLessThan(155);
    await expect(page.getByRole('table', { name: '언어별 채점 제한' })).toHaveCount(0);
    await expect(page.getByText('기존 문제 호환 정책', { exact: true })).toHaveCount(0);
    await page.screenshot({ path: info.outputPath(`compact-${theme}-${width}.png`) });
    await summary.getByRole('link', { name: '채점 도움말' }).click();
    await expect(page.getByRole('heading', { name: '도움말·FAQ' })).toBeVisible();
    await expect(page.getByRole('heading', { name: '이 문제의 채점 제한' })).toBeVisible();
    await expect(page.getByRole('table', { name: '언어별 채점 제한' })).toBeVisible();
    await page.getByRole('combobox', { name: '언어', exact: true }).selectOption('python');
    await expect(page.getByRole('heading', { name: 'Python 실행 기준' })).toBeVisible();
    await page.getByText('컴파일·출력·PID·임시 저장소 제한 자세히 보기', { exact: true }).click();
    await expect(page.getByRole('region', { name: '컴파일 제한' })).toBeVisible();
    await page.getByText('시간 제한은 어떻게 계산하나요?', { exact: true }).click();
    await expect(page.getByText(/CPU 시간은 코드가 CPU를 사용한 시간/)).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    const footer = await page.locator('footer').boundingBox();
    expect(footer!.y + footer!.height).toBeLessThanOrEqual(901);
    await page.screenshot({ path: info.outputPath(`help-${theme}-${width}.png`) });
    await page.reload();
    await expect(page.getByRole('table', { name: '언어별 채점 제한' })).toBeVisible();
    await page.getByRole('link', { name: '문제로 돌아가기' }).click();
    await expect(page.getByRole('heading', { name: fixture.title, exact: true })).toBeVisible();
    await page.getByRole('button', { name: '문제 풀기', exact: true }).click();
    if (width < 768) await page.getByRole('tab', { name: '문제', exact: true }).click();
    await expect(page.getByRole('region', { name: 'B++ 채점 제한' })).toBeVisible();
    await expect(page.getByRole('table', { name: '언어별 채점 제한' })).toHaveCount(0);
    await expect(page.getByRole('link', { name: '채점 도움말' })).toHaveAttribute('href', appPath('/help/judging?problem=help-test&language=bpp'));
    await page.locator('footer').getByRole('link', { name: '도움말·FAQ' }).click();
    await expect(page.getByRole('heading', { name: '도움말·FAQ' })).toBeVisible();
    await expect(page.getByRole('heading', { name: '이 문제의 채점 제한' })).toHaveCount(0);
    await page.goto(appPath('/help/judging?contest=help-event&problem=A&language=cpp'));
    await expect(page.getByText('대회 스냅샷 제한', { exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'C++ 실행 기준' })).toBeVisible();
    await expect(page.getByRole('link', { name: '문제로 돌아가기' })).toHaveAttribute('href', appPath('/contests/help-event/problems/A'));
  });
}
