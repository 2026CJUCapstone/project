import { afterEach, describe, expect, it, vi } from 'vitest';
import { setAuthToken } from './authIdentity';
import {
  appendContestRejudgeReview,
  applyContestRejudge,
  createContestRejudge,
  discardContestRejudge,
  getContestRejudgeAudit,
  getContestRejudgeBatch,
  getContestRejudgeBatches,
  getContestRejudgeContext,
  getContestRejudgeLegacyResolutions,
  getContestRejudgePreview,
  getContestRejudgeReviews,
  appendContestRejudgeLegacyResolution,
  type ContestRejudgeCreateRequest,
} from './contestRejudgeApi';
import type { JudgePolicy } from './judgePolicyTypes';
import type { Sha256Digest } from './problemApi';

const digest = `sha256:${'a'.repeat(64)}` as Sha256Digest;

function signedInToken(sub = 'admin'): string {
  return `header.${btoa(JSON.stringify({ sub }))}.signature`;
}

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function suppliedPolicy(): JudgePolicy {
  const limits = { cpuMs: 100, wallMs: 200, memoryBytes: 128 * 1024 * 1024, outputBytes: 1024, pids: 8, tmpBytes: 1024 };
  return {
    schemaVersion: 1,
    policyId: 'verified-policy',
    revision: 1,
    reviewStatus: 'verified',
    testSuiteHash: digest,
    profiles: {
      python: {
        runtimeId: 'python-3', runtimeVersion: '3.12', imageDigest: digest, workerClass: 'measured-linux', toolchainProfile: 'python-default',
        compile: limits, run: limits,
      },
    },
    evidence: {
      python: {
        reportHash: digest, resourceFingerprint: digest, hostClass: 'measured-linux', repetitions: 10, caseCount: 1,
        maxCpuMs: 1, maxWallMs: 1, peakMemoryBytes: 1, safetyMarginReason: 'Measured in the selected worker class.',
      },
    },
    preparationCleanupMs: 1_000,
  };
}

function createRequest(): ContestRejudgeCreateRequest {
  return {
    requestId: 'request-1',
    contestProblemId: 'problem-1',
    expectedSnapshotHash: digest,
    reason: 'Correct the affected final results.',
    sample: [{ input: '1\n', expectedOutput: '1\n' }],
    hidden: [{ kind: 'stored-v1', inputRef: { digest, byteCount: 2, encoding: 'utf-8' }, expectedOutputRef: { digest, byteCount: 2, encoding: 'utf-8' } }],
    judgePolicy: suppliedPolicy(),
  };
}

describe('contest rejudge API', () => {
  afterEach(() => {
    setAuthToken(null);
    vi.unstubAllGlobals();
  });

  it('uses the bounded admin history endpoints with the current authorization', async () => {
    setAuthToken(signedInToken());
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ batches: [], total: 0 }))
      .mockResolvedValueOnce(response({ id: 'batch-1', items: [], totalItems: 0, offset: 0, limit: 50 }));
    vi.stubGlobal('fetch', fetchMock);

    await getContestRejudgeBatches('contest / one', 0, 20);
    await getContestRejudgeBatch('contest / one', 'batch / one', 0, 50);

    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/contests/contest%20%2F%20one/rejudges?offset=0&limit=20');
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/contests/contest%20%2F%20one/rejudges/batch%20%2F%20one?offset=0&limit=50');
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      cache: 'no-store', redirect: 'error', headers: { Authorization: `Bearer ${signedInToken()}` },
    });
  });

  it('sends the exact context, preview, audit, and mutation payloads with encoded IDs and an abort signal', async () => {
    setAuthToken(signedInToken());
    const controller = new AbortController();
    const request = createRequest();
    const batch = { id: 'batch-1', contestProblemId: request.contestProblemId, status: 'ready' };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ contestProblemId: request.contestProblemId, snapshotHash: digest, snapshot: { sample: request.sample, hidden: request.hidden, judgePolicy: request.judgePolicy, preservedServerMetadata: { version: 4 } } }))
      .mockResolvedValueOnce(response(batch))
      .mockResolvedValueOnce(response({ previewHash: digest, requestHash: digest, beforeScoreboardRevision: 5, total: 0, offset: 0, limit: 50, blockedCount: 0, rows: [] }))
      .mockResolvedValueOnce(response({ batchId: 'batch / one', requestHash: digest, fingerprint: digest, metadata: null,
        categories: { sources: 'pending', statement: 'pending', tests: 'pending', resources: 'pending' }, events: [], canReview: true, ready: false,
        basis: null, applicationProvenance: null, snapshot: { sample: request.sample, hidden: request.hidden, judgePolicy: request.judgePolicy } }))
      .mockResolvedValueOnce(response({ batchId: 'batch / one', requestHash: digest, fingerprint: digest, metadata: null,
        categories: { sources: 'pending', statement: 'pending', tests: 'approved', resources: 'pending' }, events: [], canReview: true, ready: false,
        basis: null, applicationProvenance: null, snapshot: { sample: request.sample, hidden: request.hidden, judgePolicy: request.judgePolicy } }))
      .mockResolvedValueOnce(response(batch))
      .mockResolvedValueOnce(response(batch))
      .mockResolvedValueOnce(response({ total: 0, offset: 0, limit: 50, beforeRevision: 5, afterRevision: 6, rows: [] }));
    vi.stubGlobal('fetch', fetchMock);

    await getContestRejudgeContext('contest / one', 'problem / one', controller.signal);
    await createContestRejudge('contest / one', request, controller.signal);
    await getContestRejudgePreview('contest / one', 'batch / one', 0, 50, controller.signal);
    await getContestRejudgeReviews('contest / one', 'batch / one', controller.signal);
    await appendContestRejudgeReview('contest / one', 'batch / one', {
      requestId: 'review-request-1', expectedRequestHash: digest, expectedFingerprint: digest,
      category: 'tests', decision: 'approved', note: 'Checked the frozen candidate test suite and evidence.',
    }, controller.signal);
    await discardContestRejudge('contest / one', 'batch / one', { expectedRequestHash: digest }, controller.signal);
    await applyContestRejudge('contest / one', 'batch / one', {
      expectedRequestHash: digest, expectedScoreboardRevision: 5, expectedPreviewHash: digest, publicNote: 'Correct the final rankings for affected submissions.',
    }, controller.signal);
    await getContestRejudgeAudit('contest / one', 'batch / one', 0, 50, controller.signal);

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/v1/contests/contest%20%2F%20one/rejudges/context?contestProblemId=problem+%2F+one',
      '/api/v1/contests/contest%20%2F%20one/rejudges',
      '/api/v1/contests/contest%20%2F%20one/rejudges/batch%20%2F%20one/preview?offset=0&limit=50',
      '/api/v1/contests/contest%20%2F%20one/rejudges/batch%20%2F%20one/reviews',
      '/api/v1/contests/contest%20%2F%20one/rejudges/batch%20%2F%20one/reviews',
      '/api/v1/contests/contest%20%2F%20one/rejudges/batch%20%2F%20one/discard',
      '/api/v1/contests/contest%20%2F%20one/rejudges/batch%20%2F%20one/apply',
      '/api/v1/contests/contest%20%2F%20one/rejudges/batch%20%2F%20one/audit?offset=0&limit=50',
    ]);
    const requests = fetchMock.mock.calls.map(([, init]) => init as RequestInit);
    for (const init of requests) {
      expect(init).toMatchObject({ cache: 'no-store', redirect: 'error', signal: controller.signal });
      expect((init.headers as Record<string, string>).Authorization).toBe(`Bearer ${signedInToken()}`);
    }
    expect(requests[1]).toMatchObject({ method: 'POST', headers: expect.objectContaining({ 'Content-Type': 'application/json' }) });
    expect(JSON.parse(requests[1].body as string)).toEqual(request);
    expect(JSON.parse(requests[4].body as string)).toEqual({
      requestId: 'review-request-1', expectedRequestHash: digest, expectedFingerprint: digest,
      category: 'tests', decision: 'approved', note: 'Checked the frozen candidate test suite and evidence.',
    });
    expect(JSON.parse(requests[5].body as string)).toEqual({ expectedRequestHash: digest });
    expect(JSON.parse(requests[6].body as string)).toEqual({
      expectedRequestHash: digest, expectedScoreboardRevision: 5, expectedPreviewHash: digest,
      publicNote: 'Correct the final rankings for affected submissions.',
    });
  });

  it('returns rejected HTTP authorization and compare-and-swap errors to the caller', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ detail: 'forbidden' }, 403))
      .mockResolvedValueOnce(response({ detail: 'stale preview' }, 409));
    vi.stubGlobal('fetch', fetchMock);

    await expect(getContestRejudgeBatches('contest-1')).rejects.toMatchObject({ status: 403, message: 'forbidden' });
    await expect(applyContestRejudge('contest-1', 'batch-1', {
      expectedRequestHash: digest, expectedScoreboardRevision: 0, expectedPreviewHash: digest, publicNote: 'Correct the final rankings for affected submissions.',
    })).rejects.toMatchObject({ status: 409, message: 'stale preview' });
  });

  it('reads and appends an explicit legacy-resolution decision using the admin endpoint contract', async () => {
    setAuthToken(signedInToken());
    const legacyResponse = {
      batchId: 'batch / one', requestHash: digest,
      candidates: [{ userId: 'user-1', username: 'Legacy user', points: 120,
        solvedAt: '2030-01-01T00:00:00Z', legacyFingerprint: digest, resolution: null }],
      resolutions: [],
    };
    const request = {
      requestId: 'legacy-resolution-1', expectedRequestHash: digest, userId: 'user-1',
      expectedLegacyFingerprint: digest, decision: 'link_verified_receipt' as const,
      sourceKind: 'contest' as const, sourceId: 'submission-1',
      note: '대회 정답 영수증과 기존 점수의 사용자 및 배점을 대조했습니다.',
    };
    const controller = new AbortController();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(legacyResponse))
      .mockResolvedValueOnce(response(legacyResponse));
    vi.stubGlobal('fetch', fetchMock);

    await getContestRejudgeLegacyResolutions('contest / one', 'batch / one', controller.signal);
    await appendContestRejudgeLegacyResolution('contest / one', 'batch / one', request, controller.signal);

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/v1/contests/contest%20%2F%20one/rejudges/batch%20%2F%20one/legacy-resolutions',
      '/api/v1/contests/contest%20%2F%20one/rejudges/batch%20%2F%20one/legacy-resolutions',
    ]);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: 'GET', cache: 'no-store', redirect: 'error', signal: controller.signal,
      headers: { Authorization: `Bearer ${signedInToken()}` } });
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: 'POST', cache: 'no-store', redirect: 'error', signal: controller.signal,
      headers: { Authorization: `Bearer ${signedInToken()}`, 'Content-Type': 'application/json' } });
    expect(JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string)).toEqual(request);
  });
});
