import { API_BASE_URL, getAuthHeaders, parseApiError } from './apiBase';
import type { CompilerLanguage } from './compilerApi';
import type { JudgeResourceUsage } from './judgeMetricsTypes';

export type AuthoringValidationStatus = 'queued' | 'running' | 'completed' | 'failed';

export interface AuthoringValidationRequest {
  code: string;
  language: CompilerLanguage;
  requestId: string;
  expectedFingerprint: string;
  referenceAssetDigest: string;
}

export interface AuthoringValidationResult {
  verdict: string;
  resourceUsage: JudgeResourceUsage | null;
  error?: string;
}

/** Private, bounded receipt. It deliberately contains neither source nor test-case details. */
export interface AuthoringValidationReceipt {
  id: string;
  status: AuthoringValidationStatus;
  receivedAt: string;
  finishedAt: string | null;
  language: CompilerLanguage;
  sourceHash: string;
  authoringFingerprint: string;
  referenceAssetDigest: string;
  problemSnapshotHash: string;
  policyHash: string;
  testSuiteHash: string;
  result: AuthoringValidationResult | null;
}

function collectionPath(contestId: string, contestProblemId: string): string {
  return `${API_BASE_URL}/api/v1/contests/${encodeURIComponent(contestId)}/problems/${encodeURIComponent(contestProblemId)}/authoring-validations`;
}

function problemCollectionPath(problemId: string): string {
  return `${API_BASE_URL}/api/v1/problems/${encodeURIComponent(problemId)}/authoring-validations`;
}

function rejudgeCollectionPath(contestId: string, batchId: string): string {
  return `${API_BASE_URL}/api/v1/contests/${encodeURIComponent(contestId)}/rejudges/${encodeURIComponent(batchId)}/authoring-validations`;
}

async function requestJson<T>(url: string, fallback: string, method: 'GET' | 'POST', body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, {
    method,
    signal,
    cache: 'no-store',
    redirect: 'error',
    headers: {
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...getAuthHeaders(),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw await parseApiError(response, fallback);
  return response.json() as Promise<T>;
}

/** One durable admission attempt. Mutations are never retried implicitly. */
export function createAuthoringValidation(
  contestId: string,
  contestProblemId: string,
  request: AuthoringValidationRequest,
  signal?: AbortSignal,
): Promise<AuthoringValidationReceipt> {
  return requestJson(
    collectionPath(contestId, contestProblemId),
    '기준 풀이 검증을 시작하지 못했습니다.',
    'POST',
    request,
    signal,
  );
}

export function getAuthoringValidation(
  contestId: string,
  contestProblemId: string,
  validationId: string,
  signal?: AbortSignal,
): Promise<AuthoringValidationReceipt> {
  return requestJson(
    `${collectionPath(contestId, contestProblemId)}/${encodeURIComponent(validationId)}`,
    '기준 풀이 검증 결과를 불러오지 못했습니다.',
    'GET',
    undefined,
    signal,
  );
}

/** Standalone practice problem validation, scoped to the saved problem itself. */
export function createProblemAuthoringValidation(
  problemId: string,
  request: AuthoringValidationRequest,
  signal?: AbortSignal,
): Promise<AuthoringValidationReceipt> {
  return requestJson(
    problemCollectionPath(problemId),
    '기준 풀이 검증을 시작하지 못했습니다.',
    'POST',
    request,
    signal,
  );
}

export function getProblemAuthoringValidation(
  problemId: string,
  validationId: string,
  signal?: AbortSignal,
): Promise<AuthoringValidationReceipt> {
  return requestJson(
    `${problemCollectionPath(problemId)}/${encodeURIComponent(validationId)}`,
    '기준 풀이 검증 결과를 불러오지 못했습니다.',
    'GET',
    undefined,
    signal,
  );
}

export function createRejudgeAuthoringValidation(
  contestId: string,
  batchId: string,
  request: AuthoringValidationRequest,
  signal?: AbortSignal,
): Promise<AuthoringValidationReceipt> {
  return requestJson(rejudgeCollectionPath(contestId, batchId), '정정 기준 풀이 검증을 시작하지 못했습니다.', 'POST', request, signal);
}

export function getRejudgeAuthoringValidation(
  contestId: string,
  batchId: string,
  validationId: string,
  signal?: AbortSignal,
): Promise<AuthoringValidationReceipt> {
  return requestJson(`${rejudgeCollectionPath(contestId, batchId)}/${encodeURIComponent(validationId)}`,
    '정정 기준 풀이 검증 결과를 불러오지 못했습니다.', 'GET', undefined, signal);
}

function delay(milliseconds: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) return Promise.reject(new DOMException('Aborted', 'AbortError'));
  return new Promise((resolve, reject) => {
    const completed = () => {
      signal?.removeEventListener('abort', aborted);
      resolve();
    };
    const timer = setTimeout(completed, milliseconds);
    const aborted = () => {
      clearTimeout(timer);
      signal?.removeEventListener('abort', aborted);
      reject(new DOMException('Aborted', 'AbortError'));
    };
    signal?.addEventListener('abort', aborted, { once: true });
  });
}

/** Bounded private polling; source and hidden-test data never pass through this response. */
export async function waitForAuthoringValidation(
  contestId: string,
  contestProblemId: string,
  initial: AuthoringValidationReceipt,
  signal?: AbortSignal,
  options: { intervalMs?: number; maxPolls?: number } = {},
): Promise<AuthoringValidationReceipt> {
  return waitForValidation(initial,
    (validationId, nextSignal) => getAuthoringValidation(contestId, contestProblemId, validationId, nextSignal),
    signal, options);
}

export async function waitForProblemAuthoringValidation(
  problemId: string,
  initial: AuthoringValidationReceipt,
  signal?: AbortSignal,
  options: { intervalMs?: number; maxPolls?: number } = {},
): Promise<AuthoringValidationReceipt> {
  return waitForValidation(initial,
    (validationId, nextSignal) => getProblemAuthoringValidation(problemId, validationId, nextSignal),
    signal, options);
}

export async function waitForRejudgeAuthoringValidation(
  contestId: string,
  batchId: string,
  initial: AuthoringValidationReceipt,
  signal?: AbortSignal,
  options: { intervalMs?: number; maxPolls?: number } = {},
): Promise<AuthoringValidationReceipt> {
  return waitForValidation(initial,
    (validationId, nextSignal) => getRejudgeAuthoringValidation(contestId, batchId, validationId, nextSignal),
    signal, options);
}

async function waitForValidation(
  initial: AuthoringValidationReceipt,
  read: (validationId: string, signal?: AbortSignal) => Promise<AuthoringValidationReceipt>,
  signal?: AbortSignal,
  options: { intervalMs?: number; maxPolls?: number } = {},
): Promise<AuthoringValidationReceipt> {
  let current = initial;
  const intervalMs = options.intervalMs ?? 1_000;
  const maxPolls = options.maxPolls ?? 600;
  for (let poll = 0; poll < maxPolls && (current.status === 'queued' || current.status === 'running'); poll += 1) {
    await delay(intervalMs, signal);
    current = await read(current.id, signal);
  }
  if (current.status === 'queued' || current.status === 'running') {
    throw new Error('기준 풀이 검증 대기 시간이 길어지고 있습니다. 잠시 후 다시 시도하세요.');
  }
  return current;
}
