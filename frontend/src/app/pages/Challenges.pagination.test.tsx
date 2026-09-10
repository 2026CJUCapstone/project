import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Challenges } from './Challenges';
import { getProblemsPage, type Problem } from '../services/problemApi';

vi.mock('../services/problemApi', () => ({
  DIFFICULTY_LEVELS: [
    'iron5', 'iron4', 'iron3', 'iron2', 'iron1',
    'bronze5', 'bronze4', 'bronze3', 'bronze2', 'bronze1',
    'silver5', 'silver4', 'silver3', 'silver2', 'silver1',
    'gold5', 'gold4', 'gold3', 'gold2', 'gold1',
    'platinum5', 'platinum4', 'platinum3', 'platinum2', 'platinum1',
    'diamond5', 'diamond4', 'diamond3', 'diamond2', 'diamond1',
  ],
  getProblemsPage: vi.fn(),
}));

function problem(id: string, title: string): Problem {
  return {
    id,
    title,
    difficulty: 'iron5',
    tags: [],
    description: '## 문제\n설명',
    points: 100,
    testCases: [],
    hiddenTestCases: [],
    createdAt: '2030-01-01T00:00:00Z',
    solved: false,
    attempted: false,
    bestAwardedPoints: 0,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

describe('Challenges paginated filters', () => {
  afterEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it('does not append a page from an earlier filter after a new filtered page has loaded', async () => {
    vi.useFakeTimers();
    const stalePage = deferred<{ items: Problem[]; total: number }>();
    const firstPage = Array.from({ length: 24 }, (_, index) => problem(`base-${index}`, `기본 ${index}`));
    const filtered = problem('needle', 'needle 필터 결과');

    vi.mocked(getProblemsPage).mockImplementation(async (_limit, offset, filters) => {
      const search = filters?.search ?? '';
      if (offset === 0 && search === '') return { items: firstPage, total: 48 };
      if (offset === 24 && search === '') return stalePage.promise;
      if (offset === 0 && search === 'needle') return { items: [filtered], total: 1 };
      throw new Error(`unexpected request ${offset}:${search}`);
    });

    render(<MemoryRouter><Challenges /></MemoryRouter>);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    expect(screen.getByText('기본 0')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /문제 더 보기/ }));
    fireEvent.change(screen.getByPlaceholderText('문제 제목/설명 검색'), { target: { value: 'needle' } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    expect(getProblemsPage).toHaveBeenLastCalledWith(
      24,
      0,
      expect.objectContaining({ search: 'needle' }),
      expect.anything(),
    );
    expect(screen.getByText('needle 필터 결과')).toBeInTheDocument();

    await act(async () => {
      stalePage.resolve({ items: [problem('stale', 'needle 이전 페이지 결과')], total: 48 });
      await Promise.resolve();
    });

    expect(screen.queryByText('needle 이전 페이지 결과')).not.toBeInTheDocument();
    expect(screen.getByText('1문제')).toBeInTheDocument();
  });

  it('does not let a rejected stale load-more request replace new filtered results with an error', async () => {
    vi.useFakeTimers();
    const stalePage = deferred<{ items: Problem[]; total: number }>();
    const firstPage = Array.from({ length: 24 }, (_, index) => problem(`base-${index}`, `기본 ${index}`));
    const filtered = problem('needle', 'needle 필터 결과');

    vi.mocked(getProblemsPage).mockImplementation(async (_limit, offset, filters) => {
      const search = filters?.search ?? '';
      if (offset === 0 && search === '') return { items: firstPage, total: 48 };
      if (offset === 24 && search === '') return stalePage.promise;
      if (offset === 0 && search === 'needle') return { items: [filtered], total: 1 };
      throw new Error(`unexpected request ${offset}:${search}`);
    });

    render(<MemoryRouter><Challenges /></MemoryRouter>);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    fireEvent.click(screen.getByRole('button', { name: /문제 더 보기/ }));
    fireEvent.change(screen.getByPlaceholderText('문제 제목/설명 검색'), { target: { value: 'needle' } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    expect(screen.getByText('needle 필터 결과')).toBeInTheDocument();

    await act(async () => {
      stalePage.reject(new Error('오래된 요청 오류'));
      await Promise.resolve();
    });

    expect(screen.getByText('needle 필터 결과')).toBeInTheDocument();
    expect(screen.getByText('1문제')).toBeInTheDocument();
    expect(screen.queryByText('오래된 요청 오류')).not.toBeInTheDocument();
  });

  it('appends a normal next page of unique items and updates the total', async () => {
    vi.useFakeTimers();
    const firstPage = Array.from({ length: 24 }, (_, index) => problem(`base-${index}`, `기본 ${index}`));
    const additional = [
      problem('additional-1', '추가 결과 1'),
      problem('additional-2', '추가 결과 2'),
    ];

    vi.mocked(getProblemsPage).mockImplementation(async (_limit, offset) => {
      if (offset === 0) return { items: firstPage, total: 26 };
      if (offset === 24) return { items: additional, total: 26 };
      throw new Error(`unexpected request ${offset}`);
    });

    render(<MemoryRouter><Challenges /></MemoryRouter>);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    fireEvent.click(screen.getByRole('button', { name: /문제 더 보기/ }));
    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByText('추가 결과 1')).toBeInTheDocument();
    expect(screen.getByText('추가 결과 2')).toBeInTheDocument();
    expect(screen.getAllByText('기본 0')).toHaveLength(1);
    expect(screen.getByText('26문제')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /문제 더 보기/ })).not.toBeInTheDocument();
  });
});
