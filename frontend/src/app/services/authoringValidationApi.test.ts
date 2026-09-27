import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  createAuthoringValidation,
  createProblemAuthoringValidation,
  createRejudgeAuthoringValidation,
  getAuthoringValidation,
  waitForRejudgeAuthoringValidation,
  waitForAuthoringValidation,
  waitForProblemAuthoringValidation,
  type AuthoringValidationReceipt,
  type AuthoringValidationRequest,
} from './authoringValidationApi';

const { getAuthHeadersMock, parseApiErrorMock } = vi.hoisted(() => ({
  getAuthHeadersMock: vi.fn(),
  parseApiErrorMock: vi.fn(),
}));

vi.mock('./apiBase', () => ({
  API_BASE_URL: 'https://api.example.test',
  getAuthHeaders: getAuthHeadersMock,
  parseApiError: parseApiErrorMock,
}));

const request: AuthoringValidationRequest = {
  code: '#include <iostream>\nint main() { return 0; }',
  language: 'cpp',
  requestId: 'request-123',
  expectedFingerprint: 'fingerprint-abc',
  referenceAssetDigest: 'digest-def',
};

function receipt(
  status: AuthoringValidationReceipt['status'],
  id = 'validation-123',
): AuthoringValidationReceipt {
  return {
    id,
    status,
    receivedAt: '2026-09-27T00:00:00.000Z',
    finishedAt: status === 'completed' ? '2026-09-27T00:00:01.000Z' : null,
    language: 'cpp',
    sourceHash: 'source-hash',
    authoringFingerprint: 'authoring-fingerprint',
    referenceAssetDigest: 'reference-digest',
    problemSnapshotHash: 'problem-hash',
    policyHash: 'policy-hash',
    testSuiteHash: 'suite-hash',
    result: status === 'completed' ? { verdict: 'AC', resourceUsage: null } : null,
  };
}

function jsonResponse(payload: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: vi.fn().mockResolvedValue(payload),
  } as unknown as Response;
}

describe('authoringValidationApi', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    getAuthHeadersMock.mockReset().mockReturnValue({ Authorization: 'Bearer current-token' });
    parseApiErrorMock.mockReset().mockImplementation(async (_response: Response, fallback: string) => new Error(fallback));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('POSTs the exact request to the encoded collection URL with current auth, no-store, redirect error, and signal', async () => {
    const expectedReceipt = receipt('queued');
    const controller = new AbortController();
    fetchMock.mockResolvedValue(jsonResponse(expectedReceipt));

    await expect(
      createAuthoringValidation('contest/west & east', 'problem/one ?', request, controller.signal),
    ).resolves.toEqual(expectedReceipt);

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      'https://api.example.test/api/v1/contests/contest%2Fwest%20%26%20east/problems/problem%2Fone%20%3F/authoring-validations',
    );
    expect(options).toMatchObject({
      method: 'POST',
      signal: controller.signal,
      cache: 'no-store',
      redirect: 'error',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer current-token',
      },
      body: JSON.stringify(request),
    });
    expect(getAuthHeadersMock).toHaveBeenCalledOnce();
  });

  it('GETs the encoded receipt URL with current auth, no-store, redirect error, and signal', async () => {
    const expectedReceipt = receipt('running', 'receipt/id ?');
    const controller = new AbortController();
    fetchMock.mockResolvedValue(jsonResponse(expectedReceipt));

    await expect(
      getAuthoringValidation('contest/a', 'problem b', 'receipt/id ?', controller.signal),
    ).resolves.toEqual(expectedReceipt);

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      'https://api.example.test/api/v1/contests/contest%2Fa/problems/problem%20b/authoring-validations/receipt%2Fid%20%3F',
    );
    expect(options).toMatchObject({
      method: 'GET',
      signal: controller.signal,
      cache: 'no-store',
      redirect: 'error',
      headers: { Authorization: 'Bearer current-token' },
      body: undefined,
    });
    expect(options.headers).not.toHaveProperty('Content-Type');
    expect(getAuthHeadersMock).toHaveBeenCalledOnce();
  });

  it('uses the standalone problem validation routes for admission and polling', async () => {
    const queued = receipt('queued');
    const completed = receipt('completed');
    fetchMock.mockResolvedValueOnce(jsonResponse(queued)).mockResolvedValueOnce(jsonResponse(completed));

    await expect(createProblemAuthoringValidation('problem/one ?', request)).resolves.toEqual(queued);
    await expect(waitForProblemAuthoringValidation('problem/one ?', queued, undefined,
      { intervalMs: 0, maxPolls: 1 })).resolves.toEqual(completed);

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      'https://api.example.test/api/v1/problems/problem%2Fone%20%3F/authoring-validations',
      'https://api.example.test/api/v1/problems/problem%2Fone%20%3F/authoring-validations/validation-123',
    ]);
  });

  it('uses the immutable rejudge candidate path for admission and polling', async () => {
    const queued = receipt('queued');
    const completed = receipt('completed');
    fetchMock.mockResolvedValueOnce(jsonResponse(queued)).mockResolvedValueOnce(jsonResponse(completed));

    await expect(createRejudgeAuthoringValidation('contest/one', 'batch/two', request)).resolves.toEqual(queued);
    await expect(waitForRejudgeAuthoringValidation('contest/one', 'batch/two', queued, undefined,
      { intervalMs: 0, maxPolls: 1 })).resolves.toEqual(completed);

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      'https://api.example.test/api/v1/contests/contest%2Fone/rejudges/batch%2Ftwo/authoring-validations',
      'https://api.example.test/api/v1/contests/contest%2Fone/rejudges/batch%2Ftwo/authoring-validations/validation-123',
    ]);
  });

  it('passes HTTP failures to the API error parser and rejects with its error', async () => {
    const response = jsonResponse(null, false, 401);
    const apiError = new Error('Unauthorized');
    fetchMock.mockResolvedValue(response);
    parseApiErrorMock.mockResolvedValue(apiError);

    await expect(createAuthoringValidation('contest', 'problem', request)).rejects.toBe(apiError);
    await expect(getAuthoringValidation('contest', 'problem', 'validation')).rejects.toBe(apiError);

    expect(parseApiErrorMock).toHaveBeenNthCalledWith(1, response, '기준 풀이 검증을 시작하지 못했습니다.');
    expect(parseApiErrorMock).toHaveBeenNthCalledWith(2, response, '기준 풀이 검증 결과를 불러오지 못했습니다.');
  });

  it('polls queued through running and returns the completed receipt', async () => {
    const completed = receipt('completed');
    fetchMock
      .mockResolvedValueOnce(jsonResponse(receipt('running')))
      .mockResolvedValueOnce(jsonResponse(completed));

    await expect(
      waitForAuthoringValidation('contest', 'problem', receipt('queued'), undefined, {
        intervalMs: 0,
        maxPolls: 3,
      }),
    ).resolves.toEqual(completed);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      'https://api.example.test/api/v1/contests/contest/problems/problem/authoring-validations/validation-123',
      'https://api.example.test/api/v1/contests/contest/problems/problem/authoring-validations/validation-123',
    ]);
  });

  it('rejects polling with AbortError when its signal is aborted during the wait', async () => {
    const controller = new AbortController();
    const pending = waitForAuthoringValidation(
      'contest',
      'problem',
      receipt('queued'),
      controller.signal,
      { intervalMs: 60_000 },
    );
    controller.abort();

    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
