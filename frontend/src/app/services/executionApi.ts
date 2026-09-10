import { API_BASE_URL, getAuthHeaders } from './apiBase';

export type ExecutionKind = 'compile' | 'run';
export interface ExecutionReceipt { id: string; status: string; receivedAt: string; requestId: string }
interface ExecutionResult<T> { ok: boolean; value?: T; error?: string; verdict?: string }
interface ExecutionStatus<T> extends Omit<ExecutionReceipt, 'requestId'> { result?: ExecutionResult<T> | null }

export interface ExecutionWaitOptions {
  signal?: AbortSignal;
  pollIntervalMs?: number;
  maxWaitMs?: number;
  maxSubmitRetries?: number;
}

const abortError = () => new DOMException('요청이 취소되었습니다.', 'AbortError');

function retryDelay(response: Response, fallbackMs: number) {
  const raw = response.headers.get('Retry-After');
  if (!raw) return fallbackMs;
  const seconds = Number(raw);
  if (Number.isFinite(seconds)) return Math.min(30_000, Math.max(0, seconds * 1000));
  const date = Date.parse(raw);
  return Number.isNaN(date) ? fallbackMs : Math.min(30_000, Math.max(0, date - Date.now()));
}

async function wait(ms: number, signal?: AbortSignal) {
  if (signal?.aborted) throw abortError();
  await new Promise<void>((resolve, reject) => {
    const onAbort = () => { clearTimeout(timer); reject(abortError()); };
    const timer = setTimeout(() => { signal?.removeEventListener('abort', onAbort); resolve(); }, ms);
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

async function errorMessage(response: Response) {
  const body = await response.json().catch(() => ({})) as { detail?: string; message?: string };
  return body.detail || body.message || `HTTP ${response.status}: ${response.statusText}`;
}

async function postWithIdentity<T>(path: string, body: unknown, requestId: string, options: ExecutionWaitOptions) {
  const retries = options.maxSubmitRetries ?? 3;
  for (let attempt = 0; ; attempt += 1) {
    if (options.signal?.aborted) throw abortError();
    try {
      const response = await fetch(`${API_BASE_URL}${path}`, {
        method: 'POST', credentials: 'include', signal: options.signal,
        headers: { 'Content-Type': 'application/json', 'X-Request-ID': requestId, ...getAuthHeaders() },
        body: JSON.stringify(body),
      });
      if (response.status === 429 && attempt < retries) {
        await wait(retryDelay(response, 1000), options.signal);
        continue;
      }
      if (!response.ok) {
        const error = new Error(await errorMessage(response));
        error.name = 'ExecutionHttpError';
        throw error;
      }
      return await response.json() as T;
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw error;
      if (attempt >= retries || error instanceof Error && error.name === 'ExecutionHttpError') throw error;
      await wait(250 * (attempt + 1), options.signal);
    }
  }
}

export async function waitForExecution<T>(executionId: string, options: ExecutionWaitOptions = {}): Promise<T> {
  const started = Date.now();
  const maximum = options.maxWaitMs ?? 300_000;
  while (Date.now() - started <= maximum) {
    if (options.signal?.aborted) throw abortError();
    const response = await fetch(`${API_BASE_URL}/api/v1/executions/${encodeURIComponent(executionId)}`, {
      credentials: 'include', signal: options.signal, headers: { Accept: 'application/json', ...getAuthHeaders() },
    });
    if (response.status === 429) {
      await wait(retryDelay(response, options.pollIntervalMs ?? 750), options.signal);
      continue;
    }
    if (!response.ok) throw new Error(await errorMessage(response));
    const execution = await response.json() as ExecutionStatus<T>;
    if (execution.status === 'completed') {
      if (execution.result?.ok && execution.result.value !== undefined) return execution.result.value;
      throw new Error(execution.result?.error || '실행 결과가 없습니다.');
    }
    if (execution.status === 'failed') throw new Error(execution.result?.error || '실행 작업이 실패했습니다.');
    await wait(options.pollIntervalMs ?? 750, options.signal);
  }
  throw new Error(`실행 대기 시간이 초과되었습니다. 작업 ID ${executionId}는 서버에서 계속 처리될 수 있으며 자동으로 다시 제출하지 않았습니다.`);
}

export async function submitExecution<T>(body: {
  source_code: string; language: string; stdin?: string; optimize: boolean; problem_id?: string; kind: ExecutionKind; target: string;
}, options: ExecutionWaitOptions = {}): Promise<T> {
  const requestId = crypto.randomUUID();
  const receipt = await postWithIdentity<ExecutionReceipt>('/api/v1/executions', body, requestId, options);
  return waitForExecution<T>(receipt.id, options);
}

export async function submitPracticeExecution<T>(problemId: string, body: { code: string; language: string },
  options: ExecutionWaitOptions = {}): Promise<T> {
  const requestId = crypto.randomUUID();
  const receipt = await postWithIdentity<{ executionId: string }>(
    `/api/v1/problems/${encodeURIComponent(problemId)}/submit`, body, requestId, options,
  );
  if (!receipt.executionId) throw new Error('채점 작업 ID를 받지 못했습니다.');
  return waitForExecution<T>(receipt.executionId, options);
}
