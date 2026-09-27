import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setAuthToken } from '../services/authIdentity';
import { getCompileQueue } from '../services/compilerApi';
import { CompileQueue } from './CompileQueue';

vi.mock('../services/compilerApi', () => ({
  getCompileQueue: vi.fn(),
}));

const emptyQueue = {
  jobs: [], total: 0, filteredTotal: 0, queued: 0, running: 0, problemGroups: [], userGroups: [],
  detailScope: 'mine' as const,
};

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.search}</output>;
}

function mount(initialEntry = '/compile-queue') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/compile-queue" element={<><CompileQueue /><LocationProbe /></>} />
      </Routes>
    </MemoryRouter>,
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((nextResolve) => { resolve = nextResolve; });
  return { promise, resolve };
}

function signedToken(subject: string) {
  return `header.${btoa(JSON.stringify({ sub: subject }))}.signature`;
}

function latestQueueFilters() {
  const calls = vi.mocked(getCompileQueue).mock.calls;
  return calls[calls.length - 1]?.[0];
}

describe('CompileQueue history filters', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetAllMocks();
  });

  afterEach(() => {
    setAuthToken(null);
    vi.useRealTimers();
  });

  it('clears contest and problem context when the source changes, and reset restores the public default', async () => {
    vi.mocked(getCompileQueue).mockResolvedValue(emptyQueue);
    mount('/compile-queue?source=contest&contestId=fall&problemId=A&problemSearch=array&mine=true');

    await waitFor(() => expect(getCompileQueue).toHaveBeenCalled());
    expect(vi.mocked(getCompileQueue).mock.calls[0][0]).toMatchObject({
      source: 'contest', contestId: 'fall', problemId: 'A', problemSearch: 'array', mine: true,
    });

    fireEvent.change(screen.getByRole('combobox', { name: '기록 범위' }), { target: { value: 'ide' } });
    await waitFor(() => expect(latestQueueFilters()).toMatchObject({
      source: 'ide', contestId: undefined, problemId: undefined, problemSearch: undefined,
    }));
    const updatedQuery = new URLSearchParams(screen.getByTestId('location').textContent || '');
    expect(updatedQuery.get('source')).toBe('ide');
    expect(updatedQuery.get('mine')).toBe('true');

    fireEvent.click(screen.getByRole('button', { name: '초기화' }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(''));
    await waitFor(() => expect(latestQueueFilters()).toMatchObject({ source: 'all', mine: undefined }));
  });

  it('uses readable options while retaining contest context for a selected problem', async () => {
    vi.mocked(getCompileQueue).mockResolvedValue({
      ...emptyQueue,
      contestOptions: [{ id: 'fall', title: '가을 대회' }],
      problemOptions: [{ id: 'A', title: '배열 정렬', contestId: 'fall' }],
    });
    mount();

    const problem = await screen.findByRole('combobox', { name: '문제' });
    expect(problem).toHaveTextContent('배열 정렬 · A (대회)');
    const optionValue = screen.getByRole('option', { name: '배열 정렬 · A (대회)' }).getAttribute('value') || '';
    fireEvent.change(problem, { target: { value: optionValue } });

    await waitFor(() => expect(latestQueueFilters()).toMatchObject({
      source: 'contest', contestId: 'fall', problemId: 'A',
    }));
  });

  it('keeps same-ID public and contest problems in their explicit context', async () => {
    vi.mocked(getCompileQueue).mockResolvedValue({
      ...emptyQueue,
      problemOptions: [
        { id: 'shared', title: '첫 번째 대회 문제', contestId: 'first' },
        { id: 'shared', title: '공개 문제', contestId: null },
        { id: 'shared', title: '두 번째 대회 문제', contestId: 'second' },
      ],
    });
    mount();

    const problem = await screen.findByRole('combobox', { name: '문제' });
    const secondContest = screen.getByRole('option', { name: '두 번째 대회 문제 · shared (대회)' }).getAttribute('value') || '';
    fireEvent.change(problem, { target: { value: secondContest } });
    await waitFor(() => expect(latestQueueFilters()).toMatchObject({
      source: 'contest', contestId: 'second', problemId: 'shared',
    }));

    const publicProblem = screen.getByRole('option', { name: '공개 문제 · shared' }).getAttribute('value') || '';
    fireEvent.change(screen.getByRole('combobox', { name: '문제' }), { target: { value: publicProblem } });
    await waitFor(() => expect(latestQueueFilters()).toMatchObject({
      source: 'all', contestId: undefined, problemId: 'shared',
    }));
  });

  it('drops an in-flight private response when the token has already changed before an identity event', async () => {
    setAuthToken(signedToken('alice'));
    const stale = deferred<Awaited<ReturnType<typeof getCompileQueue>>>();
    vi.mocked(getCompileQueue).mockImplementationOnce(() => stale.promise).mockResolvedValue(emptyQueue);
    mount('/compile-queue?source=contest');

    await waitFor(() => expect(getCompileQueue).toHaveBeenCalledTimes(1));
    localStorage.setItem('authToken', signedToken('bob'));
    await act(async () => {
      stale.resolve({
        ...emptyQueue,
        jobs: [{
          id: 'private-job', kind: 'grading', status: 'completed', verdict: 'accepted', language: 'bpp',
          source: 'contest', contestId: 'fall', contestTitle: '비공개 대회', problemId: 'A', problemTitle: '비공개 문제',
          queuedAt: '2026-09-26T00:00:00Z', sourceSizeBytes: null,
        }],
      });
      await Promise.resolve();
    });

    expect(screen.queryByText('비공개 문제')).not.toBeInTheDocument();
  });

  it('renders and filters output, process, and compiler resource limits as distinct verdicts', async () => {
    vi.mocked(getCompileQueue).mockResolvedValue({
      ...emptyQueue,
      jobs: [
        { id: 'ole', kind: 'grading', status: 'completed', verdict: 'output_limit_exceeded', language: 'python', source: 'practice', problemId: 'output-problem', problemTitle: '출력 제한', queuedAt: '2026-09-26T00:00:00Z' },
        { id: 'process-limit', kind: 'grading', status: 'completed', verdict: 'process_limit_exceeded', language: 'python', source: 'practice', problemId: 'process-problem', problemTitle: '프로세스 제한', queuedAt: '2026-09-26T00:00:00Z' },
        { id: 'compile-resource', kind: 'compile', status: 'completed', verdict: 'compile_resource_error', language: 'java', source: 'ide', queuedAt: '2026-09-26T00:00:00Z' },
      ], total: 3, filteredTotal: 3,
    });
    mount();

    expect(await screen.findByText('출력 초과')).toBeInTheDocument();
    expect(screen.getByText('프로세스 제한 초과', { selector: 'span' })).toBeInTheDocument();
    expect(screen.getAllByText('컴파일 자원 초과')).not.toHaveLength(0);
    const verdict = screen.getByRole('combobox', { name: '판정' });
    expect(screen.getByRole('option', { name: '출력 초과' })).toHaveValue('output_limit_exceeded');
    expect(screen.getByRole('option', { name: '프로세스 제한 초과' })).toHaveValue('process_limit_exceeded');
    expect(screen.getByRole('option', { name: '컴파일 자원 초과' })).toHaveValue('compile_resource_error');

    fireEvent.change(verdict, { target: { value: 'output_limit_exceeded' } });
    await waitFor(() => expect(latestQueueFilters()).toMatchObject({ verdict: 'output_limit_exceeded' }));
    fireEvent.change(verdict, { target: { value: 'process_limit_exceeded' } });
    await waitFor(() => expect(latestQueueFilters()).toMatchObject({ verdict: 'process_limit_exceeded' }));
  });
});
