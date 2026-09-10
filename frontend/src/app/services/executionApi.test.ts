import { afterEach, describe, expect, it, vi } from 'vitest';
import { submitExecution, submitPracticeExecution } from './executionApi';

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });

describe('durable execution client', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('submits once with a retry identity and polls the private execution', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({ id: 'exec-1', status: 'queued', receivedAt: 'now', requestId: 'request' }, 202))
      .mockResolvedValueOnce(json({ id: 'exec-1', status: 'running', receivedAt: 'now' }))
      .mockResolvedValueOnce(json({ id: 'exec-1', status: 'completed', receivedAt: 'now', result: { ok: true, value: { success: true } } }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(submitExecution<{ success: boolean }>({
      source_code: 'main', language: 'bpp', optimize: false, kind: 'compile', target: 'all',
    }, { pollIntervalMs: 0 })).resolves.toEqual({ success: true });

    const [postUrl, postInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(postUrl).toContain('/api/v1/executions');
    expect(postInit.credentials).toBe('include');
    expect((postInit.headers as Record<string, string>)['X-Request-ID']).toMatch(/^[0-9a-f-]{36}$/i);
    expect(JSON.parse(postInit.body as string)).toMatchObject({ source_code: 'main', kind: 'compile', target: 'all' });
    expect(fetchMock.mock.calls[1][0]).toContain('/api/v1/executions/exec-1');
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ credentials: 'include' });
  });

  it('reuses the same request identity after Retry-After throttling', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({ detail: 'busy' }, 429, { 'Retry-After': '0' }))
      .mockResolvedValueOnce(json({ id: 'exec-2', status: 'queued', receivedAt: 'now', requestId: 'request' }, 202))
      .mockResolvedValueOnce(json({ id: 'exec-2', status: 'completed', receivedAt: 'now', result: { ok: true, value: 42 } }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(submitExecution<number>({ source_code: 'x', language: 'bpp', optimize: false, kind: 'run', target: 'all' },
      { pollIntervalMs: 0 })).resolves.toBe(42);
    const firstHeaders = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    const secondHeaders = fetchMock.mock.calls[1][1].headers as Record<string, string>;
    expect(secondHeaders['X-Request-ID']).toBe(firstHeaders['X-Request-ID']);
  });

  it('polls practice submissions through their execution id', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({ id: 'submission-1', executionId: 'exec-3', status: 'queued', receivedAt: 'now' }, 202))
      .mockResolvedValueOnce(json({ id: 'exec-3', status: 'completed', receivedAt: 'now', result: { ok: true, verdict: 'wrong_answer', value: { verdict: 'wrong_answer' } } }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(submitPracticeExecution<{ verdict: string }>('problem/one', { code: 'x', language: 'bpp' },
      { pollIntervalMs: 0 })).resolves.toEqual({ verdict: 'wrong_answer' });
    expect(fetchMock.mock.calls[0][0]).toContain('/problems/problem%2Fone/submit');
    expect(fetchMock.mock.calls[1][0]).toContain('/executions/exec-3');
  });

  it('surfaces infrastructure failure without treating verdicts as transport errors', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(json({ id: 'exec-4', status: 'queued', receivedAt: 'now', requestId: 'request' }, 202))
      .mockResolvedValueOnce(json({ id: 'exec-4', status: 'failed', receivedAt: 'now', result: { ok: false, error: 'worker unavailable' } })));

    await expect(submitExecution({ source_code: 'x', language: 'bpp', optimize: false, kind: 'run', target: 'all' },
      { pollIntervalMs: 0 })).rejects.toThrow('worker unavailable');
  });

  it('honors cancellation before submitting and bounds polling time', async () => {
    const controller = new AbortController();
    controller.abort();
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    await expect(submitExecution({ source_code: 'x', language: 'bpp', optimize: false, kind: 'run', target: 'all' },
      { signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetchMock).not.toHaveBeenCalled();

    fetchMock.mockResolvedValueOnce(json({ id: 'exec-5', status: 'queued', receivedAt: 'now', requestId: 'request' }, 202));
    await expect(submitExecution({ source_code: 'x', language: 'bpp', optimize: false, kind: 'run', target: 'all' },
      { maxWaitMs: -1 })).rejects.toThrow('작업 ID exec-5');
  });

  it.each(['compile', 'run'] as const)('does not retry a %s submission after HTTP 410 Gone', async (kind) => {
    const fetchMock = vi.fn().mockResolvedValueOnce(json({ detail: 'content expired' }, 410));
    vi.stubGlobal('fetch', fetchMock);

    await expect(submitExecution({
      source_code: 'x', language: 'bpp', optimize: false, kind, target: 'all',
    })).rejects.toThrow('content expired');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: 'POST' });
  });

  it('stops polling on HTTP 410 Gone without resubmitting the execution', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({ id: 'expired-exec', status: 'queued', receivedAt: 'now' }, 202))
      .mockResolvedValueOnce(json({ detail: 'content expired' }, 410));
    vi.stubGlobal('fetch', fetchMock);

    await expect(submitExecution({
      source_code: 'x', language: 'bpp', optimize: false, kind: 'run', target: 'all',
    }, { pollIntervalMs: 0 })).rejects.toThrow('content expired');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: 'POST' });
    expect(fetchMock.mock.calls[1][0]).toContain('/api/v1/executions/expired-exec');
    expect(fetchMock.mock.calls.slice(2).filter(([, init]) => (init as RequestInit | undefined)?.method === 'POST')).toHaveLength(0);
  });

  it('stops polling a practice submission on HTTP 410 Gone without resubmitting', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({ executionId: 'expired-practice' }, 202))
      .mockResolvedValueOnce(json({ detail: 'content expired' }, 410));
    vi.stubGlobal('fetch', fetchMock);

    await expect(submitPracticeExecution('problem-1', { code: 'x', language: 'bpp' },
      { pollIntervalMs: 0 })).rejects.toThrow('content expired');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/problems/problem-1/submit');
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: 'POST' });
    expect(fetchMock.mock.calls[1][0]).toContain('/api/v1/executions/expired-practice');
  });
});
