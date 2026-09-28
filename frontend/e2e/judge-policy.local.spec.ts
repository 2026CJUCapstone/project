// Browser layout/import only. All API calls are intercepted; no real policy or DB write.
import { test, expect } from '@playwright/test';
import { createHash } from 'node:crypto';

const limits = { cpuMs: 1000, wallMs: 2000, memoryBytes: 128 * 1024 ** 2,
  outputBytes: 1024, pids: 16, tmpBytes: 4 * 1024 ** 2 };
const draft = { schemaVersion: 1, policyId: 'browser-draft-only', revision: 1, reviewStatus: 'draft',
  testSuiteHash: 'sha256:' + 'a'.repeat(64), preparationCleanupMs: 1000,
  profiles: { python: { runtimeId: 'python-test', runtimeVersion: 'Synthetic Python',
    imageDigest: 'sha256:' + 'b'.repeat(64), workerClass: 'fixture', toolchainProfile: 'fixture', compile: limits, run: limits } } };

for (const width of [320, 768, 1440]) {
  test(`rejudge history, correction notice and access loss at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => localStorage.setItem('authToken', 'isolated-rejudge-fixture'));
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    let denied = false;
    const batch = { id: 'batch-fixture', contestProblemId: '77ce77fd-ca85-4ece-8e09-95caff052609',
      actorId: 'operator-fixture-00000000000000000000', reason: '관리자 전용 합성 검토 사유', revision: 1,
      status: 'applied', createdAt: '2030-01-01T00:00:00Z', finishedAt: '2030-01-01T00:01:00Z',
      total: 1, completed: 1, changed: 1, failed: 0 };
    const correction = { total: 1, items: [{ revision: 8, appliedAt: '2030-01-01T01:00:00Z', note: '정답 자료를 수정해 순위를 다시 계산했습니다.' }] };
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (path === '/api/v1/auth/me') await route.fulfill({ json: { id: 'fixture-admin', username: 'fixture-admin', role: 'admin', totalScore: 0 } });
      else if (path === '/api/v1/contests/rejudge-fixture') await route.fulfill({ json: {
        id: 'rejudge-fixture', title: '재채점 화면 격리 검증', description: '', state: 'finished', published: true,
        startsAt: '2030-01-01T00:00:00Z', endsAt: '2030-01-01T01:00:00Z', serverTime: '2030-01-01T02:00:00Z',
        joined: true, canManage: true, participantCount: 1, problems: [], corrections: correction,
      } });
      else if (path.endsWith('/scoreboard')) await route.fulfill({ json: { rows: [], problems: [], pendingCount: 0, state: 'finished', serverTime: '2030-01-01T02:00:00Z', corrections: correction } });
      else if (path.endsWith('/submissions')) await route.fulfill({ json: { submissions: [], total: 0 } });
      else if (path.endsWith('/rejudges')) await route.fulfill(denied ? { status: 403, json: { detail: 'Synthetic role revoked' } } : { json: { total: 1, batches: [batch] } });
      else if (path.endsWith('/rejudges/batch-fixture/reviews')) await route.fulfill({ json: {
        batchId: batch.id, requestHash: 'sha256:'+'a'.repeat(64), fingerprint: 'sha256:'+'b'.repeat(64),
        metadata: null, categories: { sources: 'pending', statement: 'pending', tests: 'pending', resources: 'pending' },
        events: [], canReview: false, ready: false, basis: null, applicationProvenance: null,
        snapshot: { sample: [], hidden: [], judgePolicy: null },
      } });
      else if (path.endsWith('/rejudges/batch-fixture/audit')) await route.fulfill({ json: { total: 1, offset: 0, limit: 50,
        beforeRevision: 7, afterRevision: 8, rows: [{ userId: 'audit-user-fixture',
          before: { rank: 1, totalPoints: 100, penaltySeconds: 15 }, after: { rank: 2, totalPoints: 0, penaltySeconds: 0 }, practicePointDelta: -100 }] } });
      else if (path.endsWith('/rejudges/batch-fixture')) await route.fulfill({ json: { ...batch, totalItems: 1, offset: 0, limit: 50,
        requestHash: 'sha256:' + 'a'.repeat(64), beforeScoreboardRevision: 7,
        application: { actorId: batch.actorId, appliedAt: batch.finishedAt, publicNote: correction.items[0].note, beforeRevision: 7, afterRevision: 8 },
        items: [{ id: 'item', submissionId: 'long-fixture-submission-000000000000000000000', language: 'python',
          receivedAt: '2030-01-01T00:02:00Z', status: 'completed', beforeVerdict: 'accepted', afterVerdict: 'wrong_answer', finishedAt: batch.finishedAt }] } });
      else await route.fulfill({ status: 404, json: { detail: 'No real API in this browser test' } });
    });
    await page.goto('/contests/rejudge-fixture');
    await expect(page.getByRole('region', { name: '순위 정정 안내', exact: true })).toContainText(correction.items[0].note);
    const panel = page.getByRole('region', { name: '재채점 이력', exact: true });
    await panel.getByRole('button').filter({ hasText: batch.reason }).click();
    await expect(panel.getByRole('region', { name: '제출별 단계 결과 표' }).getByRole('table')).toBeVisible();
    await panel.getByRole('button', { name: '반영 전후 기록 보기', exact: true }).click();
    await expect(panel.getByText('audit-user-fixture', { exact: true })).toBeVisible();
    expect(await page.locator('main').evaluateAll(els => els.every(el => el.scrollWidth <= el.clientWidth + 1))).toBeTruthy();
    const bounds = await panel.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width + 1);
    await panel.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.deploy/test-results/judge-policy/rejudge-${width}.png` });
    denied = true;
    await panel.getByRole('button', { name: '새로고침', exact: true }).click();
    await expect(panel.getByRole('alert')).toBeVisible();
    await expect(panel.getByText(batch.reason, { exact: false })).toHaveCount(0);
    await expect(panel.getByRole('table')).toHaveCount(0);
    expect(errors).toEqual([]);
  });
}

for (const width of [320, 768, 1440]) {
  test(`rejudge explicit create, compare and apply at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => localStorage.setItem('authToken', 'isolated-rejudge-actions'));
    const errors: string[] = [], writes: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    let created = false, applied = false;
    const hash = 'sha256:' + 'a'.repeat(64), previewHash = 'sha256:' + 'c'.repeat(64);
    const reviewCategories: Record<string, string> = { sources: 'pending', statement: 'pending', tests: 'pending', resources: 'pending' };
    const metadata = { sources: [{ url: 'https://example.test/synthetic', title: '합성 출처', reuseBasis: 'original', reuseEvidence: 'Browser fixture only' }],
      adaptationNotes: '실제 출제 승인이 아닌 브라우저 합성 자료', requiredLanguages: ['python'], assets: [] };
    const reviewReady = () => Object.values(reviewCategories).every(value => value === 'approved');
    const policy = { ...draft, revision: 2, reviewStatus: 'verified', evidence: { python: {
      reportHash: hash, resourceFingerprint: hash, hostClass: 'fixture', repetitions: 10,
      caseCount: 2, maxCpuMs: 10, maxWallMs: 20, peakMemoryBytes: 1024,
      safetyMarginReason: 'Browser-only synthetic evidence; not actual acceptance.',
    } } };
    const publicNote = '합성 테스트 정답을 수정해 점수와 순위를 다시 계산했습니다.';
    const batch = () => ({ id: 'batch', contestProblemId: 'cp', actorId: 'fixture', reason: '합성 변경 사유를 확인했습니다.',
      revision: 2, status: applied ? 'applied' : 'ready', createdAt: '2030-01-01T02:00:00Z',
      finishedAt: '2030-01-01T02:01:00Z', total: 1, completed: 1, changed: 1, failed: 0 });
    await page.route('**/api/v1/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname;
      if (request.method() !== 'GET') writes.push(path);
      if (path === '/api/v1/auth/me') await route.fulfill({ json: { id: 'fixture', username: 'fixture', role: 'admin', totalScore: 0 } });
      else if (path === '/api/v1/contests/actions') await route.fulfill({ json: {
        id: 'actions', title: '재채점 명시적 반영 검증', state: 'finished', published: true, description: '',
        startsAt: '2030-01-01T00:00:00Z', endsAt: '2030-01-01T01:00:00Z', serverTime: '2030-01-01T02:00:00Z',
        joined: true, canManage: true, participantCount: 1, problems: [{ id: 'cp', label: 'A', title: '합성 문제', points: 100 }],
        corrections: { total: applied ? 1 : 0, items: applied ? [{ revision: 2, appliedAt: batch().finishedAt, note: publicNote }] : [] },
      } });
      else if (path.endsWith('/scoreboard')) await route.fulfill({ json: { rows: [], problems: [], pendingCount: 0, state: 'finished' } });
      else if (path.endsWith('/submissions')) await route.fulfill({ json: { submissions: [], total: 0 } });
      else if (path.endsWith('/rejudges/context')) await route.fulfill({ json: {
        contestProblemId: 'cp', snapshotHash: hash, snapshot: { sample: [{ input: '1', expectedOutput: '2' }],
          hidden: [{ input: 'private-fixture', expectedOutput: '3' }], judgePolicy: draft, authoring: metadata },
      } });
      else if (path.endsWith('/rejudges')) {
        if (request.method() === 'POST') {
          const payload = request.postDataJSON();
          expect(payload.expectedSnapshotHash).toBe(hash); expect(payload.judgePolicy).toEqual(policy);
          expect(payload.requestId).toMatch(/^[0-9a-f-]{36}$/);
          created = true; await route.fulfill({ json: batch() });
        } else await route.fulfill({ json: { total: created ? 1 : 0, batches: created ? [batch()] : [] } });
      } else if (path.endsWith('/rejudges/batch/reviews')) {
        if (request.method() === 'POST') {
          const payload = request.postDataJSON();
          expect(payload.expectedRequestHash).toBe(hash); expect(payload.expectedFingerprint).toBe(hash);
          expect(payload.note).toBe('합성 후보의 각 검수 근거를 확인했습니다.');
          expect(payload.decision).toBe('approved');
          reviewCategories[payload.category] = payload.decision;
        }
        await route.fulfill({ json: { batchId: 'batch', requestHash: hash, fingerprint: hash, metadata,
          categories: reviewCategories, events: [], canReview: !applied, ready: reviewReady(), basis: { version: 1 }, applicationProvenance: null,
          snapshot: { sample: [{ input: '1', expectedOutput: '2' }], hidden: [{ input: 'private-fixture', expectedOutput: '3' }], judgePolicy: policy, authoring: metadata } } });
      } else if (path.endsWith('/rejudges/batch/preview')) await route.fulfill({ json: {
        previewHash, requestHash: hash, beforeScoreboardRevision: 1, total: 1, offset: 0, limit: 50, blockedCount: 0, reviewBlocked: !reviewReady(),
        rows: [{ userId: 'participant', username: '합성 참가자', beforeRank: 2, afterRank: 1,
          beforePoints: 0, afterPoints: 100, beforePenaltySeconds: 0, afterPenaltySeconds: 50, practicePointDelta: 100, blocker: null }],
      } });
      else if (path.endsWith('/rejudges/batch/apply')) {
        expect(request.postDataJSON()).toEqual({ expectedRequestHash: hash, expectedPreviewHash: previewHash,
          expectedScoreboardRevision: 1, publicNote });
        applied = true; await route.fulfill({ json: batch() });
      } else if (path.endsWith('/rejudges/batch')) await route.fulfill({ json: { ...batch(),
        requestHash: hash, beforeScoreboardRevision: 1, totalItems: 0, offset: 0, limit: 50, items: [],
        application: applied ? { actorId: 'fixture', appliedAt: batch().finishedAt, beforeRevision: 1, afterRevision: 2, publicNote } : null,
      } });
      else await route.fulfill({ status: 404, json: { detail: 'Isolated mock only' } });
    });
    await page.goto('/contests/actions');
    const history = page.getByRole('region', { name: '재채점 이력', exact: true });
    await history.locator('summary').filter({ hasText: '재채점 후보 만들기' }).click();
    await history.getByLabel('재채점 문제', { exact: true }).selectOption('cp');
    await history.getByRole('button', { name: '현재 테스트 불러오기' }).click();
    await expect(history.getByLabel('수정한 숨김 테스트 JSON', { exact: true })).toContainText('private-fixture');
    await history.getByLabel('정책 JSON 가져오기', { exact: true }).fill(JSON.stringify(policy));
    await history.getByRole('button', { name: '정책 JSON 확인 후 교체' }).click();
    await history.getByLabel('관리자 변경 사유', { exact: true }).fill('합성 변경 사유를 확인했습니다.');
    expect(writes).toEqual([]);
    await history.getByRole('checkbox', { name: /후보 채점만 시작/ }).check();
    await history.getByRole('button', { name: '후보 채점 시작', exact: true }).click();
    await history.getByRole('button').filter({ hasText: '사유: 합성 변경 사유' }).click();
    await history.getByRole('button', { name: '반영 전 점수 비교' }).click();
    await expect(history.getByText('합성 참가자', { exact: true })).toBeVisible();
    expect(writes).toEqual(['/api/v1/contests/actions/rejudges']);
    await expect(history.getByRole('button', { name: '점수·순위에 반영' })).toBeDisabled();
    for (const category of ['sources', 'statement', 'tests', 'resources']) {
      await history.getByLabel('정정 검수 범주', { exact: true }).selectOption(category);
      await history.getByLabel('정정 검수 메모', { exact: true }).fill('합성 후보의 각 검수 근거를 확인했습니다.');
      await history.getByRole('button', { name: '승인 기록', exact: true }).click();
      await expect(history.getByText('합성 참가자', { exact: true })).toHaveCount(0);
      await history.getByRole('button').filter({ hasText: '사유: 합성 변경 사유' }).click();
      await expect(history.getByLabel('정정 검수 범주', { exact: true })).toBeVisible();
    }
    await history.getByRole('button', { name: '반영 전 점수 비교' }).click();
    await expect(history.getByText('합성 참가자', { exact: true })).toBeVisible();
    await expect(history.getByText('네 범주의 후보 검수가 모두 승인되었습니다.', { exact: true })).toBeVisible();
    const correctionPanel = history.getByRole('region', { name: '정정 출제 검수', exact: true });
    const correctionBounds = await correctionPanel.boundingBox();
    for (const control of await correctionPanel.locator('select, textarea, button').all()) {
      if (!(await control.isVisible())) continue;
      const bounds = await control.boundingBox();
      expect(bounds!.x).toBeGreaterThanOrEqual(correctionBounds!.x);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(correctionBounds!.x + correctionBounds!.width + 1);
    }
    expect(await page.locator('main').evaluateAll(els => els.every(el => el.scrollWidth <= el.clientWidth + 1))).toBeTruthy();
    const review = history.getByRole('region', { name: '재채점 결과 검토', exact: true });
    await review.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.deploy/test-results/judge-policy/rejudge-actions-${width}.png` });
    await review.getByLabel('참가자에게 공개할 정정 사유', { exact: true }).fill(publicNote);
    await expect(review.getByRole('button', { name: '점수·순위에 반영' })).toBeDisabled();
    await review.getByRole('checkbox', { name: /전체 후보 결과/ }).check();
    await review.getByRole('button', { name: '점수·순위에 반영' }).click();
    await history.getByRole('button').filter({ hasText: '사유: 합성 변경 사유' }).click();
    await expect(history.getByText(/반영 완료 · 점수판 개정 1 → 2/)).toBeVisible();
    expect(writes).toEqual(['/api/v1/contests/actions/rejudges', ...Array(4).fill('/api/v1/contests/actions/rejudges/batch/reviews'), '/api/v1/contests/actions/rejudges/batch/apply']);
    expect(errors).toEqual([]);
  });
}

for (const width of [320, 768, 1440]) {
  test(`hidden file upload creates only references at ${width}px`, async ({ page }) => {
    const writes: string[] = [];
    const failures: string[] = [];
    page.on('pageerror', error => failures.push(error.message));
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => localStorage.setItem('authToken', 'isolated-file-fixture'));
    await page.route('**/api/v1/**', async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.pathname === '/api/v1/auth/me') {
        await route.fulfill({ json: { id: 'fixture', username: 'fixture', role: 'admin', totalScore: 0 } });
      } else if (url.pathname === '/api/v1/contests/library') {
        await route.fulfill({ headers: { 'X-Total-Count': '0' }, json: [] });
      } else if (url.pathname.startsWith('/api/v1/admin/judge-test-data/') && request.method() === 'PUT') {
        writes.push(url.pathname);
        const bytes = request.postDataBuffer()!;
        const digest = createHash('sha256').update(bytes).digest('hex');
        expect(url.pathname.endsWith(digest)).toBeTruthy();
        expect(Number(url.searchParams.get('byteCount'))).toBe(bytes.length);
        await route.fulfill({ json: { digest: `sha256:${digest}`, byteCount: bytes.length, encoding: 'utf-8', replayed: false } });
      } else await route.fulfill({ status: 404, json: { detail: 'Isolated mock only' } });
    });
    await page.goto('/contests/new');
    await page.getByRole('button', { name: '신규 문제 추가', exact: true }).click();
    const panel = page.getByRole('region', { name: '숨김 테스트 파일 업로드', exact: true });
    await panel.getByLabel('숨김 테스트 입력 파일', { exact: true }).setInputFiles({ name: 'private.in', mimeType: 'text/plain', buffer: Buffer.from('private-input-not-for-display\n') });
    await panel.getByLabel('숨김 테스트 정답 파일', { exact: true }).setInputFiles({ name: 'private.out', mimeType: 'text/plain', buffer: Buffer.from('private-answer-not-for-display\n') });
    expect(writes).toEqual([]);
    await panel.getByRole('button', { name: '숨김 테스트 업로드', exact: true }).click();
    await expect(panel.getByRole('status')).toContainText('저장 참조를 추가');
    expect(writes).toHaveLength(2);
    await expect(page.getByText('private-input-not-for-display', { exact: true })).toHaveCount(0);
    await expect(page.getByText('private-answer-not-for-display', { exact: true })).toHaveCount(0);
    expect(await page.locator('main').evaluateAll(elements => elements.every(el => el.scrollWidth <= el.clientWidth + 1))).toBeTruthy();
    const bounds = await panel.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width + 1);
    await panel.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.deploy/test-results/judge-policy/upload-${width}.png` });
    expect(failures).toEqual([]);
  });
}

for (const width of [320, 768, 1440]) {
  test(`submission resource totals stay phase-specific and bounded at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const row = { id: 'fixture', problemId: 'fixture-problem', problemTitle: '합성 문제', userId: 'fixture-user',
      username: 'fixture-user', language: 'python', status: 'Accepted', verdict: 'accepted', sampleTotalCases: 1,
      samplePassedCases: 1, gradingCompleted: true, gradingPassed: true, awardedPoints: 0, createdAt: '2030-01-01T00:00:00Z' };
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (path === '/api/v1/problems/submissions') {
        await route.fulfill({ json: { total: 2, filteredTotal: 2, submissions: [
          { ...row, resourceUsage: { version: 1, measurement: 'cgroup-v2-whole-phase', policyId: 'fixture', policyRevision: 1,
            compile: { cpuMs: 50, wallMs: 90, peakMemoryBytes: 134217728 },
            run: { cpuMs: 8, wallMs: 10, maxCpuMs: 5, maxWallMs: 6, peakMemoryBytes: 1048576 } } },
          { ...row, id: 'legacy-fixture', resourceUsage: null },
        ] } });
      } else await route.fulfill({ status: 401, json: { detail: 'No real API: isolated public fixture' } });
    });
    await page.goto('/submissions');
    await expect(page.getByText('자원 측정 미기록', { exact: true })).toBeVisible();
    const detail = page.locator('details').filter({ hasText: '실행 CPU 최대 5ms' });
    await detail.locator('summary').click();
    await expect(detail.getByText('CPU 합계', { exact: true })).toBeVisible();
    await expect(detail.getByText('8ms', { exact: true })).toBeVisible();
    await expect(detail.getByText('50ms', { exact: true })).toBeVisible();
    await expect(detail.getByText('실행 메모리 최대 1 MiB', { exact: true })).toBeVisible();
    expect(await page.locator('main').evaluateAll(elements => elements.every(el => el.scrollWidth <= el.clientWidth + 1))).toBeTruthy();
    await detail.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.deploy/test-results/judge-policy/metrics-${width}.png` });
  });
}

for (const width of [320, 768, 1440]) {
  test(`admin imports a draft without fabricated verification at ${width}px`, async ({ page }) => {
    const failures: string[] = [];
    page.on('pageerror', error => failures.push(error.message));
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => localStorage.setItem('authToken', 'local-browser-fixture-only'));
    await page.route('**/api/v1/**', async route => {
      const pathname = new URL(route.request().url()).pathname;
      if (pathname === '/api/v1/auth/me') {
        await route.fulfill({ json: { id: 'fixture', username: 'fixture', nickname: '테스트 관리자', role: 'admin', totalScore: 0 } });
      } else if (pathname === '/api/v1/contests/library') {
        await route.fulfill({ headers: { 'X-Total-Count': '0' }, json: [] });
      } else {
        await route.fulfill({ status: 404, json: { detail: 'No real API calls permitted in this fixture' } });
      }
    });
    await page.goto('/contests/new');
    await page.getByRole('button', { name: '신규 문제 추가', exact: true }).click();
    const input = page.getByRole('textbox', { name: '정책 JSON 가져오기', exact: true });
    await input.fill(JSON.stringify(draft));
    await page.getByRole('button', { name: '정책 JSON 확인 후 교체', exact: true }).click();
    await expect(page.getByText('초안', { exact: true })).toBeVisible();
    await expect(page.getByText('검증됨', { exact: true })).toHaveCount(0);
    await expect(page.getByRole('table', { name: '가져온 언어별 채점 정책' })).toBeVisible();
    const region = page.getByRole('region', { name: '채점 정책 가져오기·검토' });
    const bounds = await region.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width + 1);
    expect(await page.locator('main').evaluateAll(elements => elements.every(el => el.scrollWidth <= el.clientWidth + 1))).toBeTruthy();
    await region.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.deploy/test-results/judge-policy/admin-${width}.png` });
    await input.fill('{"schemaVersion":1}');
    await page.getByRole('button', { name: '정책 JSON 확인 후 교체', exact: true }).click();
    await expect(page.getByRole('alert')).toBeVisible();
    await expect(page.getByText('초안', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: '신규 문제 추가', exact: true }).click();
    const inputs = page.getByRole('textbox', { name: '정책 JSON 가져오기', exact: true });
    expect(await inputs.count()).toBe(2);
    expect(await inputs.nth(0).getAttribute('id')).not.toBe(await inputs.nth(1).getAttribute('id'));
    expect(failures).toEqual([]);
  });
}

for (const width of [320, 768, 1440]) {
  test(`private authoring panel keeps drafts and stays bounded at ${width}px`, async ({ page }) => {
    const failures: string[] = [];
    const writes: string[] = [];
    page.on('pageerror', error => failures.push(error.message));
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => localStorage.setItem('authToken', 'isolated-authoring-fixture'));
    const metadata = { sources: [{ url: 'https://example.com/fixture', title: '합성 테스트 출처', reuseBasis: 'pending' }],
      adaptationNotes: '실제 이용 허락을 뜻하지 않는 합성 자료', requiredLanguages: ['python'], assets: [] };
    const record = { problemId: 'fixture-problem', fingerprint: 'sha256:' + 'c'.repeat(64), metadata,
      categories: { sources: 'pending', statement: 'pending', tests: 'pending', resources: 'pending' }, events: [] };
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (route.request().method() !== 'GET') writes.push(path);
      if (path === '/api/v1/auth/me') {
        await route.fulfill({ json: { id: 'fixture-admin', username: 'fixture-admin', role: 'admin', totalScore: 0 } });
      } else if (path === '/api/v1/contests/library') {
        await route.fulfill({ headers: { 'X-Total-Count': '0' }, json: [] });
      } else if (path === '/api/v1/contests/fixture-contest/manage') {
        await route.fulfill({ json: { id: 'fixture-contest', title: '격리된 검수 화면', description: '',
          state: 'draft', published: false, startsAt: '2030-01-01T00:00:00Z', endsAt: '2030-01-01T01:00:00Z',
          problems: [{ problemId: 'fixture-problem', points: 100 }], authoring: { 'fixture-problem': record } } });
      } else if (path === '/api/v1/problems/fixture-problem/authoring') {
        await route.fulfill(route.request().method() === 'GET' ? { json: record }
          : { status: 409, json: { detail: 'Synthetic stale content, no real write' } });
      } else {
        await route.fulfill({ status: 404, json: { detail: 'Isolated fixture: no real API' } });
      }
    });
    await page.goto('/contests/fixture-contest/edit');
    const panel = page.getByTestId('problem-authoring-fixture-problem');
    await panel.locator('summary').first().click();
    const input = panel.getByRole('textbox', { name: '출처 메타데이터 JSON', exact: true });
    await expect(input).toBeEnabled();
    const changed = JSON.stringify({ ...metadata, adaptationNotes: '내가 수정하고 아직 저장하지 않은 출처 초안' });
    await input.fill(changed);
    await panel.getByRole('button', { name: '출처 메타데이터 저장', exact: true }).click();
    await expect(panel.getByRole('alert')).toContainText('작성 중인 내용은 보존');
    await expect(input).toHaveValue(changed);
    await panel.getByRole('button', { name: '최신 내용 확인', exact: true }).click();
    await expect(input).toBeEnabled();
    await expect(input).toHaveValue(changed);
    await expect(panel.getByRole('button', { name: '승인 기록', exact: true })).toBeDisabled();
    expect(await page.locator('main').evaluateAll(elements => elements.every(el => el.scrollWidth <= el.clientWidth + 1))).toBeTruthy();
    const bounds = await panel.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width + 1);
    await input.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.deploy/test-results/judge-policy/authoring-${width}.png` });
    expect(writes).toEqual(['/api/v1/problems/fixture-problem/authoring']);
    expect(failures).toEqual([]);
  });
}
