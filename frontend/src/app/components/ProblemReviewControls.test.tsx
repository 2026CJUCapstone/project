import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { setAuthToken } from '../services/authIdentity';
import { MemoryRouter } from 'react-router';
import { ProblemReviewControls } from './ProblemReviewControls';

function signedInToken(sub = 'review-user'): string {
  return `header.${btoa(JSON.stringify({ sub }))}.signature`;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(nextResolve => { resolve = nextResolve; });
  return { promise, resolve };
}

describe('ProblemReviewControls', () => {
  afterEach(() => {
    localStorage.removeItem('authToken');
    window.dispatchEvent(new Event('auth-identity-change'));
    vi.unstubAllGlobals();
  });

  it('does not request private review data for a guest', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    render(<MemoryRouter><ProblemReviewControls problemId="p1" /></MemoryRouter>);
    expect(screen.getByText(/로그인 후 저장/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('keeps an edited draft after an optimistic-lock conflict', async () => {
    localStorage.setItem('authToken', signedInToken());
    const conflict = deferred<Response>();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ problemId: 'p1', bookmarked: false, note: '기존 메모', reviewedAt: null, version: 1 }), { status: 200 }))
      .mockReturnValueOnce(conflict.promise);
    vi.stubGlobal('fetch', fetchMock);
    render(<MemoryRouter><ProblemReviewControls problemId="p1" /></MemoryRouter>);

    const textarea = await screen.findByRole('textbox', { name: '개인 메모' });
    fireEvent.change(textarea, { target: { value: '내가 계속 작성한 메모' } });
    fireEvent.click(screen.getByRole('button', { name: '저장' }));

    expect(screen.getByRole('textbox', { name: '개인 메모' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: '북마크' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '저장 중...' }));
    expect(fetchMock).toHaveBeenCalledTimes(2);

    conflict.resolve(new Response(JSON.stringify({ detail: 'version conflict' }), { status: 409 }));

    expect(await screen.findByText(/작성 중인 메모는 보존/)).toBeInTheDocument();
    expect(textarea).toHaveValue('내가 계속 작성한 메모');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('button', { name: /최신 버전 확인/ })).toBeInTheDocument();
  });

  it('reports a successful save so a containing review list can refresh', async () => {
    localStorage.setItem('authToken', signedInToken());
    const onSaved = vi.fn();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ problemId: 'p1', bookmarked: false, note: '', reviewedAt: null, version: 0 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ problemId: 'p1', bookmarked: true, note: '', reviewedAt: null, version: 1 }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    render(<MemoryRouter><ProblemReviewControls problemId="p1" onSaved={onSaved} /></MemoryRouter>);

    await screen.findByRole('textbox', { name: '개인 메모' });
    fireEvent.click(screen.getByRole('checkbox', { name: '북마크' }));
    fireEvent.click(screen.getByRole('button', { name: '저장' }));

    await screen.findByText('저장했습니다.');
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ problemId: 'p1', version: 1, bookmarked: true }));
  });

  it('does not mark a reopened problem reviewed merely because a historical timestamp exists', async () => {
    localStorage.setItem('authToken', signedInToken());
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      problemId: 'p1', bookmarked: false, note: '', reviewedAt: '2026-01-01T00:00:00Z', reviewed: false, version: 1,
    }))));
    render(<MemoryRouter><ProblemReviewControls problemId="p1" /></MemoryRouter>);
    expect(await screen.findByRole('checkbox', { name: '복습 완료' })).not.toBeChecked();
  });

  it('fences late private reads across both problem and account changes', async () => {
    localStorage.setItem('authToken', signedInToken('alice'));
    const oldRead = deferred<Response>();
    const anotherProblem = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn().mockReturnValueOnce(oldRead.promise).mockReturnValueOnce(anotherProblem.promise)
      .mockResolvedValueOnce(new Response(JSON.stringify({ problemId: 'p2', bookmarked: false, note: 'Bob only', reviewedAt: null, version: 0 }))));
    const tree = (id: string) => <MemoryRouter><ProblemReviewControls problemId={id} /></MemoryRouter>;
    const { rerender } = render(tree('p1'));
    rerender(tree('p2'));
    act(() => setAuthToken(signedInToken('bob')));
    expect(await screen.findByRole('textbox', { name: '개인 메모' })).toHaveValue('Bob only');
    await act(async () => {
      oldRead.resolve(new Response(JSON.stringify({ problemId: 'p1', note: 'Alice secret', version: 2, reviewedAt: null })));
      anotherProblem.resolve(new Response(JSON.stringify({ problemId: 'p2', note: 'Alice other secret', version: 3, reviewedAt: null })));
    });
    expect(screen.getByRole('textbox', { name: '개인 메모' })).toHaveValue('Bob only');
  });
});
