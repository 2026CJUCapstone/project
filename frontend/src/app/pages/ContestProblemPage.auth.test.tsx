import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router';
import { setAuthToken } from '../services/authIdentity';
import { contestRequest, type ContestProblemDetail } from '../services/contestApi';
import { ContestProblemPage } from './ContestProblemPage';

vi.mock('../services/contestApi', async importOriginal => ({
  ...await importOriginal<typeof import('../services/contestApi')>(),
  contestRequest: vi.fn(),
}));

vi.mock('./IDE', () => ({
  IDE: ({ contestProblem }: { contestProblem: ContestProblemDetail }) => (
    <section aria-label="대회 문제 IDE">{contestProblem.description}</section>
  ),
}));

function problem(description: string): ContestProblemDetail {
  return {
    id: 'contest-problem-1', problemId: 'problem-1', label: 'A', title: '비공개 문제',
    points: 500, difficulty: 'iron5', description, tags: ['private'],
    testCases: [{ input: 'sample-input', expectedOutput: 'sample-output' }],
    contest: {
      id: 'contest-1', title: '신입생 대회', description: '', published: true,
      startsAt: '2030-01-01T00:00:00Z', endsAt: '2030-01-01T02:00:00Z',
      serverTime: '2030-01-01T01:00:00Z', state: 'running', joined: true,
      canManage: false, participantCount: 1, problems: [],
    },
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(next => { resolve = next; });
  return { promise, resolve };
}

describe('ContestProblemPage authorization scope', () => {
  beforeEach(() => {
    vi.mocked(contestRequest).mockReset();
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('removes a loaded private problem immediately and fences a late old-account refresh', async () => {
    let refresh: (() => void) | undefined;
    vi.spyOn(globalThis, 'setInterval').mockImplementation((handler, delay) => {
      if (delay === 5_000) refresh = handler as () => void;
      return 1 as unknown as ReturnType<typeof setInterval>;
    });
    const oldRefresh = deferred<ContestProblemDetail>();
    const replacementRequest = new Promise<ContestProblemDetail>(() => {});
    vi.mocked(contestRequest)
      .mockResolvedValueOnce(problem('FIRST-ACCOUNT-PRIVATE-MARKER'))
      .mockReturnValueOnce(oldRefresh.promise)
      .mockReturnValue(replacementRequest);
    setAuthToken('first-private-account');

    render(
      <MemoryRouter initialEntries={['/contests/contest-1/problems/contest-problem-1']}>
        <Routes>
          <Route path="/contests/:contestId/problems/:contestProblemId" element={<ContestProblemPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText('FIRST-ACCOUNT-PRIVATE-MARKER')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: '대회 문제 IDE' })).toBeInTheDocument();

    expect(refresh).toBeDefined();
    await act(async () => { refresh?.(); });
    await waitFor(() => expect(contestRequest).toHaveBeenCalledTimes(2));
    const oldSignal = vi.mocked(contestRequest).mock.calls[1][3] as AbortSignal;

    act(() => setAuthToken('replacement-account'));
    expect(oldSignal.aborted).toBe(true);
    expect(screen.queryByText('FIRST-ACCOUNT-PRIVATE-MARKER')).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: '대회 문제 IDE' })).not.toBeInTheDocument();
    expect(contestRequest).toHaveBeenCalledTimes(3);

    await act(async () => oldRefresh.resolve(problem('LATE-OLD-ACCOUNT-MARKER')));
    expect(screen.queryByText('LATE-OLD-ACCOUNT-MARKER')).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: '대회 문제 IDE' })).not.toBeInTheDocument();
  });
});
