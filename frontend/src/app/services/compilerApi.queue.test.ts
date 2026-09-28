import { afterEach, describe, expect, it, vi } from 'vitest';
import { getCompileQueue } from './compilerApi';

describe('getCompileQueue', () => {
  afterEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it('sends the extended history filters and the current authorization token', async () => {
    localStorage.setItem('authToken', 'private-token');
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      jobs: [], total: 0, filteredTotal: 0, queued: 0, running: 0, problemGroups: [], userGroups: [],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);

    await getCompileQueue({
      limit: 50,
      offset: 100,
      source: 'contest',
      contestId: 'fall-2026',
      problemId: 'A-01',
      problemSearch: '배열_%',
      language: 'cpp',
      mine: true,
      status: 'completed',
      verdict: 'accepted',
      kind: 'grading',
      username: 'alice',
      userId: 'user-1',
    });

    const [rawUrl, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const url = new URL(rawUrl, 'http://local');
    expect(url.pathname).toBe('/api/v1/compiler/queue');
    expect(Object.fromEntries(url.searchParams)).toMatchObject({
      limit: '50', offset: '100', source: 'contest', contestId: 'fall-2026', problemId: 'A-01',
      problemSearch: '배열_%', language: 'cpp', mine: 'true', status: 'completed', verdict: 'accepted',
      kind: 'grading', username: 'alice', userId: 'user-1',
    });
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer private-token');
  });

  it('keeps public history on the all source without an authorization header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      jobs: [], total: 0, filteredTotal: 0, queued: 0, running: 0, problemGroups: [], userGroups: [],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);

    await getCompileQueue();

    const [rawUrl, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new URL(rawUrl, 'http://local').searchParams.get('source')).toBe('all');
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });
});
