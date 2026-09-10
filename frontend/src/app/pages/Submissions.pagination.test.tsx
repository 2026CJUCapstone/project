import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, MemoryRouter, Route, RouterProvider, Routes, useLocation } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Submissions } from './Submissions';
import { getSubmissions } from '../services/problemApi';

vi.mock('../services/problemApi', () => ({
  getSubmissions: vi.fn(),
}));

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>;
}

function SubmissionsRoute() {
  return <><Submissions /><LocationProbe /></>;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve;
  });
  return { promise, resolve };
}

describe('Submissions pagination query boundaries', () => {
  afterEach(() => vi.clearAllMocks());

  it.each([
    ['NaN', 'NaN'],
    ['zero', '0'],
    ['negative', '-2'],
    ['fractional', '1.5'],
    ['non-finite', 'Infinity'],
    ['offset-overflowing', '9007199254740991'],
  ])('normalizes a %s page query before asking the submissions client for an offset', async (_label, page) => {
    vi.mocked(getSubmissions).mockResolvedValue({ submissions: [], total: 0, filteredTotal: 0 });

    render(
      <MemoryRouter initialEntries={[`/submissions?page=${page}`]}>
        <Routes>
          <Route path="/submissions" element={<Submissions />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(getSubmissions).toHaveBeenCalled());
    expect(getSubmissions).toHaveBeenLastCalledWith(expect.objectContaining({ limit: 50, offset: 0 }));
  });

  it('keeps a valid second page on its matching API offset', async () => {
    vi.mocked(getSubmissions).mockResolvedValue({ submissions: [], total: 51, filteredTotal: 51 });

    render(
      <MemoryRouter initialEntries={['/submissions?page=2']}>
        <Routes>
          <Route path="/submissions" element={<Submissions />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(getSubmissions).toHaveBeenCalledTimes(1));
    expect(getSubmissions).toHaveBeenLastCalledWith(expect.objectContaining({ limit: 50, offset: 50 }));
    await act(async () => { await Promise.resolve(); });
    expect(getSubmissions).toHaveBeenCalledTimes(1);
  });

  it('replaces an out-of-range page after its current successful response and refetches page one', async () => {
    vi.mocked(getSubmissions).mockResolvedValue({ submissions: [], total: 1, filteredTotal: 1 });

    render(
      <MemoryRouter initialEntries={['/submissions?page=99&verdict=accepted&username=alice']}>
        <Routes>
          <Route path="/submissions" element={<SubmissionsRoute />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(getSubmissions).toHaveBeenCalledTimes(2));
    expect(vi.mocked(getSubmissions).mock.calls.map(([filters]) => filters?.offset)).toEqual([4900, 0]);
    expect(vi.mocked(getSubmissions).mock.calls[1][0]).toMatchObject({ verdict: 'accepted', username: 'alice' });
    expect(screen.getByTestId('location')).toHaveTextContent('/submissions?verdict=accepted&username=alice');
  });

  it('does not loop for an empty first page', async () => {
    vi.mocked(getSubmissions).mockResolvedValue({ submissions: [], total: 0, filteredTotal: 0 });

    render(
      <MemoryRouter initialEntries={['/submissions?page=1']}>
        <Routes>
          <Route path="/submissions" element={<Submissions />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(getSubmissions).toHaveBeenCalledTimes(1));
    await act(async () => { await Promise.resolve(); });
    expect(getSubmissions).toHaveBeenCalledTimes(1);
  });

  it('does not let a superseded out-of-range response redirect the current page', async () => {
    const stale = deferred<Awaited<ReturnType<typeof getSubmissions>>>();
    vi.mocked(getSubmissions)
      .mockImplementationOnce(() => stale.promise)
      .mockResolvedValueOnce({ submissions: [], total: 51, filteredTotal: 51 });
    const router = createMemoryRouter([
      { path: '/submissions', element: <SubmissionsRoute /> },
    ], { initialEntries: ['/submissions?page=99&username=old'] });

    render(<RouterProvider router={router} />);
    await waitFor(() => expect(getSubmissions).toHaveBeenCalledTimes(1));

    await act(async () => {
      await router.navigate('/submissions?page=2&username=new');
    });
    await waitFor(() => expect(getSubmissions).toHaveBeenCalledTimes(2));

    await act(async () => {
      stale.resolve({ submissions: [], total: 1, filteredTotal: 1 });
      await Promise.resolve();
    });

    expect(router.state.location.search).toBe('?page=2&username=new');
    expect(vi.mocked(getSubmissions).mock.calls.map(([filters]) => filters?.offset)).toEqual([4900, 50]);
  });

  it('single-flights a double refresh for the same page', async () => {
    const slow = deferred<Awaited<ReturnType<typeof getSubmissions>>>();
    const emptyResponse = { submissions: [], total: 0, filteredTotal: 0 };
    vi.mocked(getSubmissions)
      .mockResolvedValueOnce(emptyResponse)
      .mockImplementationOnce(() => slow.promise)
      .mockResolvedValue(emptyResponse);

    render(
      <MemoryRouter initialEntries={['/submissions?page=1']}>
        <Routes>
          <Route path="/submissions" element={<Submissions />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(getSubmissions).toHaveBeenCalledTimes(1));
    await act(async () => { await Promise.resolve(); });
    const refresh = screen.getByRole('button', { name: '새로고침' });
    fireEvent.click(refresh);
    fireEvent.click(refresh);

    expect(getSubmissions).toHaveBeenCalledTimes(2);
    expect(refresh).toBeDisabled();

    await act(async () => {
      slow.resolve(emptyResponse);
      await Promise.resolve();
    });
  });
});
