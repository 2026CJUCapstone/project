import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './apiBase';
import { getLearningProblemReview, getLearningTrack, getLearningTracks, updateLearningProblemReview } from './learningApi';

describe('learning API client', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('uses the learning track collection and bounded track page contract', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ tracks: [], signedIn: false }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ track: {}, items: [], total: 0, offset: 24, limit: 24 }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    await getLearningTracks();
    await getLearningTrack('starter / one', 24, 24);

    expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/learning/tracks');
    const pageUrl = new URL(fetchMock.mock.calls[1][0], 'http://local');
    expect(pageUrl.pathname).toBe('/api/v1/learning/tracks/starter%20%2F%20one');
    expect(Object.fromEntries(pageUrl.searchParams)).toEqual({ limit: '24', offset: '24' });
  });

  it('treats an absent review version as version zero and sends optimistic version fields', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ problemId: 'p1', bookmarked: false, note: '', reviewedAt: null }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ problemId: 'p1', bookmarked: true, note: 'keep', reviewedAt: null, version: 1 }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(getLearningProblemReview('p1')).resolves.toMatchObject({ version: 0 });
    await updateLearningProblemReview('p1', { bookmarked: true, note: 'keep', reviewed: false, version: 0 });
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ bookmarked: true, note: 'keep', reviewed: false, version: 0 });
  });

  it('preserves a 409 conflict for the editor to resolve explicitly', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'version conflict' }), { status: 409 })));
    await expect(updateLearningProblemReview('p1', { bookmarked: false, note: '', reviewed: false, version: 1 })).rejects.toMatchObject({ status: 409 } satisfies Partial<ApiError>);
  });
});
