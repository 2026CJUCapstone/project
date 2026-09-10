import { act, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, MemoryRouter, Route, RouterProvider, Routes, useLocation } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CompileQueue } from './CompileQueue';
import { getCompileQueue } from '../services/compilerApi';

vi.mock('../services/compilerApi', () => ({
  getCompileQueue: vi.fn(),
}));

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>;
}

function CompileQueueRoute() {
  return <><CompileQueue /><LocationProbe /></>;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve;
  });
  return { promise, resolve };
}

const emptyQueue = {
  jobs: [],
  total: 0,
  filteredTotal: 0,
  queued: 0,
  running: 0,
  problemGroups: [],
  userGroups: [],
};

describe('CompileQueue pagination query boundaries', () => {
  afterEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it.each([
    ['NaN', 'NaN'],
    ['zero', '0'],
    ['negative', '-2'],
    ['fractional', '1.5'],
    ['non-finite', 'Infinity'],
    ['offset-overflowing', '9007199254740991'],
  ])('normalizes a %s page query before asking the queue client for an offset', async (_label, page) => {
    vi.mocked(getCompileQueue).mockResolvedValue(emptyQueue);

    render(
      <MemoryRouter initialEntries={[`/compile-queue?page=${page}`]}>
        <Routes>
          <Route path="/compile-queue" element={<CompileQueue />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(getCompileQueue).toHaveBeenCalled());
    expect(getCompileQueue).toHaveBeenLastCalledWith(expect.objectContaining({ limit: 50, offset: 0 }));
  });

  it('keeps a valid second page on its matching API offset', async () => {
    vi.mocked(getCompileQueue).mockResolvedValue({
      ...emptyQueue,
      total: 51,
      filteredTotal: 51,
    });

    render(
      <MemoryRouter initialEntries={['/compile-queue?page=2']}>
        <Routes>
          <Route path="/compile-queue" element={<CompileQueue />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(getCompileQueue).toHaveBeenCalledTimes(1));
    expect(getCompileQueue).toHaveBeenLastCalledWith(expect.objectContaining({ limit: 50, offset: 50 }));
    await act(async () => { await Promise.resolve(); });
    expect(getCompileQueue).toHaveBeenCalledTimes(1);
  });

  it('replaces an out-of-range page after its current successful response and refetches page one', async () => {
    vi.mocked(getCompileQueue).mockResolvedValue({ ...emptyQueue, total: 1, filteredTotal: 1 });

    render(
      <MemoryRouter initialEntries={['/compile-queue?page=99&status=running&username=alice']}>
        <Routes>
          <Route path="/compile-queue" element={<CompileQueueRoute />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(getCompileQueue).toHaveBeenCalledTimes(2));
    expect(vi.mocked(getCompileQueue).mock.calls.map(([filters]) => filters?.offset)).toEqual([4900, 0]);
    expect(vi.mocked(getCompileQueue).mock.calls[1][0]).toMatchObject({ status: 'running', username: 'alice' });
    expect(screen.getByTestId('location')).toHaveTextContent('/compile-queue?status=running&username=alice');
  });

  it('does not loop for an empty first page', async () => {
    vi.mocked(getCompileQueue).mockResolvedValue(emptyQueue);

    render(
      <MemoryRouter initialEntries={['/compile-queue?page=1']}>
        <Routes>
          <Route path="/compile-queue" element={<CompileQueue />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(getCompileQueue).toHaveBeenCalledTimes(1));
    await act(async () => { await Promise.resolve(); });
    expect(getCompileQueue).toHaveBeenCalledTimes(1);
  });

  it('does not let a superseded out-of-range response redirect the current page', async () => {
    const stale = deferred<Awaited<ReturnType<typeof getCompileQueue>>>();
    vi.mocked(getCompileQueue)
      .mockImplementationOnce(() => stale.promise)
      .mockResolvedValueOnce({ ...emptyQueue, total: 51, filteredTotal: 51 });
    const router = createMemoryRouter([
      { path: '/compile-queue', element: <CompileQueueRoute /> },
    ], { initialEntries: ['/compile-queue?page=99&username=old'] });

    render(<RouterProvider router={router} />);
    await waitFor(() => expect(getCompileQueue).toHaveBeenCalledTimes(1));

    await act(async () => {
      await router.navigate('/compile-queue?page=2&username=new');
    });
    await waitFor(() => expect(getCompileQueue).toHaveBeenCalledTimes(2));

    await act(async () => {
      stale.resolve({ ...emptyQueue, total: 1, filteredTotal: 1 });
      await Promise.resolve();
    });

    expect(router.state.location.search).toBe('?page=2&username=new');
    expect(vi.mocked(getCompileQueue).mock.calls.map(([filters]) => filters?.offset)).toEqual([4900, 50]);
  });

  it('keeps a slow current poll in flight rather than starving it with overlapping polls', async () => {
    vi.useFakeTimers();
    const slow = deferred<Awaited<ReturnType<typeof getCompileQueue>>>();
    vi.mocked(getCompileQueue)
      .mockImplementationOnce(() => slow.promise)
      .mockResolvedValue({ ...emptyQueue, total: 51, filteredTotal: 51 });

    render(
      <MemoryRouter initialEntries={['/compile-queue?page=2']}>
        <Routes>
          <Route path="/compile-queue" element={<CompileQueueRoute />} />
        </Routes>
      </MemoryRouter>,
    );

    await act(async () => { await Promise.resolve(); });
    expect(getCompileQueue).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(getCompileQueue).toHaveBeenCalledTimes(1);

    await act(async () => {
      slow.resolve({ ...emptyQueue, total: 51, filteredTotal: 51 });
      await Promise.resolve();
    });
    expect(screen.getByText('표시 대상 51')).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(getCompileQueue).toHaveBeenCalledTimes(2);
  });
});
