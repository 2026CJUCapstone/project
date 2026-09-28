import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { Learning } from './Learning';

function signedInToken(sub = 'learning-user'): string {
  return `header.${btoa(JSON.stringify({ sub }))}.signature`;
}

describe('Learning', () => {
  afterEach(() => {
    localStorage.removeItem('authToken');
    window.dispatchEvent(new Event('auth-identity-change'));
    vi.unstubAllGlobals();
  });

  it('does not leave results from the previous review filter visible while the next filter loads', async () => {
    localStorage.setItem('authToken', signedInToken());
    const nextFilter = new Promise<Response>(() => {});
    vi.stubGlobal('fetch', vi.fn((input: string) => {
      if (input.endsWith('/api/v1/learning/tracks')) {
        return Promise.resolve(new Response(JSON.stringify({ tracks: [], signedIn: true }), { status: 200 }));
      }
      if (input.includes('/api/v1/learning/review') && input.includes('filter=unresolved')) {
        return Promise.resolve(new Response(JSON.stringify({
          items: [{ id: 'old', title: '미해결 문제', difficulty: 'bronze5', tags: [], solved: false, attempted: true, bookmarked: false, note: '', reviewedAt: null, lastAttemptAt: null }],
          total: 1, offset: 0, limit: 24,
        }), { status: 200 }));
      }
      if (input.includes('/api/v1/learning/review') && input.includes('filter=bookmarked')) return nextFilter;
      throw new Error(`unexpected request: ${input}`);
    }));

    render(<MemoryRouter><Learning /></MemoryRouter>);
    await screen.findByText('등록된 문제집이 없습니다');
    fireEvent.click(screen.getByRole('tab', { name: '복습' }));
    await screen.findByText('미해결 문제');

    fireEvent.click(screen.getByRole('button', { name: '북마크' }));
    expect(screen.queryByText('미해결 문제')).not.toBeInTheDocument();
    expect(screen.getByText('복습 목록을 불러오는 중...')).toBeInTheDocument();
  });

  it('keeps the loaded list when the already-selected review filter is clicked again', async () => {
    localStorage.setItem('authToken', signedInToken());
    const fetchMock = vi.fn((input: string) => {
      if (input.endsWith('/api/v1/learning/tracks')) {
        return Promise.resolve(new Response(JSON.stringify({ tracks: [], signedIn: true }), { status: 200 }));
      }
      if (input.includes('/api/v1/learning/review') && input.includes('filter=unresolved')) {
        return Promise.resolve(new Response(JSON.stringify({
          items: [{ id: 'same-filter', title: '그대로 남는 문제', difficulty: 'bronze5', tags: [], solved: false, attempted: true, bookmarked: false, note: '', reviewedAt: null, lastAttemptAt: null }],
          total: 1, offset: 0, limit: 24,
        }), { status: 200 }));
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<MemoryRouter><Learning /></MemoryRouter>);
    await screen.findByText('등록된 문제집이 없습니다');
    fireEvent.click(screen.getByRole('tab', { name: '복습' }));
    await screen.findByText('그대로 남는 문제');

    fireEvent.click(screen.getByRole('button', { name: '미해결' }));
    expect(screen.getByText('그대로 남는 문제')).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes('/api/v1/learning/review'))).toHaveLength(1);
  });
});
