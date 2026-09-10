import { afterEach, describe, expect, it, vi } from 'vitest';
import { contestPageRequest } from './contestApi';
import { getProblemsPage } from './problemApi';

describe('paginated list clients', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('sends bounded problem page parameters and reads the total header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('[]', {
      status: 200, headers: { 'Content-Type': 'application/json', 'X-Total-Count': '73' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(getProblemsPage(24, 48, {
      search: '문자열', difficultyMin: 'bronze5', difficultyMax: 'gold1', tags: ['io', 'func'],
    })).resolves.toEqual({ items: [], total: 73 });
    const url = new URL(fetchMock.mock.calls[0][0], 'http://local');
    expect(url.pathname).toBe('/api/v1/problems/');
    expect(Object.fromEntries(url.searchParams)).toMatchObject({ limit: '24', offset: '48', search: '문자열', difficultyMin: 'bronze5', difficultyMax: 'gold1' });
    expect(url.searchParams.getAll('tag')).toEqual(['io', 'func']);
  });

  it('paginates the contest problem library without changing its array payload', async () => {
    const item = { id: 'p1', title: '문제', points: 100 };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify([item]), {
      status: 200, headers: { 'Content-Type': 'application/json', 'X-Total-Count': '101' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(contestPageRequest<typeof item>('/library', 50, 50, undefined, { state: 'running', search: '가을' })).resolves.toEqual({ items: [item], total: 101 });
    expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/contests/library?limit=50&offset=50&state=running&search=');
  });
});
