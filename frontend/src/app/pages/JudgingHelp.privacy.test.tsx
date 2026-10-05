import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { setAuthToken } from '../services/authIdentity';
import { contestRequest, type ContestProblemDetail } from '../services/contestApi';
import { getProblem, type Problem } from '../services/problemApi';
import { JudgingHelp } from './JudgingHelp';

vi.mock('../services/contestApi', () => ({ contestRequest: vi.fn() }));
vi.mock('../services/problemApi', () => ({ getProblem: vi.fn() }));
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(next => { resolve = next; });
  return { promise, resolve };
}
const fixture = (title: string) => ({ title, judgeLimits: null }) as ContestProblemDetail;
function view(path = '/help/judging?contest=event&problem=A') {
  const router = createMemoryRouter([{ path: '/help/judging', Component: JudgingHelp }], { initialEntries: [path] });
  const rendered = render(<RouterProvider router={router} />);
  return { router, ...rendered };
}
describe('JudgingHelp private-context boundaries', () => {
  beforeEach(() => { localStorage.clear(); vi.mocked(contestRequest).mockReset(); vi.mocked(getProblem).mockReset(); });
  afterEach(() => { localStorage.clear(); });
  it('immediately removes a loaded private title and limits on logout', async () => {
    setAuthToken('owner');
    vi.mocked(contestRequest).mockResolvedValueOnce(fixture('OWNER-PRIVATE-TITLE')).mockReturnValue(new Promise(() => {}));
    view();
    expect(await screen.findByText('OWNER-PRIVATE-TITLE')).toBeInTheDocument();
    const firstSignal = vi.mocked(contestRequest).mock.calls[0][3]!;
    act(() => setAuthToken(null));
    expect(firstSignal.aborted).toBe(true);
    expect(screen.queryByText('OWNER-PRIVATE-TITLE')).not.toBeInTheDocument();
    expect(screen.queryByText('채점 제한 정보가 없습니다.')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('불러오는 중');
  });
  it('discards a late old-account success even if the API ignores cancellation', async () => {
    setAuthToken('first-account');
    const first = deferred<ContestProblemDetail>();
    vi.mocked(contestRequest).mockReturnValueOnce(first.promise).mockReturnValue(new Promise(() => {}));
    view();
    act(() => setAuthToken('second-account'));
    await act(async () => first.resolve(fixture('LATE-PRIVATE-TITLE')));
    expect(screen.queryByText('LATE-PRIVATE-TITLE')).not.toBeInTheDocument();
    expect(contestRequest).toHaveBeenCalledTimes(2);
  });
  it('fences late responses after changing contest or switching to generic help', async () => {
    const first = deferred<ContestProblemDetail>();
    vi.mocked(contestRequest).mockReturnValueOnce(first.promise).mockResolvedValue(fixture('CURRENT-CONTEST'));
    const { router } = view();
    const oldSignal = vi.mocked(contestRequest).mock.calls[0][3]!;
    await act(async () => router.navigate('/help/judging?contest=other-event&problem=B'));
    expect(oldSignal.aborted).toBe(true);
    expect(await screen.findByText('CURRENT-CONTEST')).toBeInTheDocument();
    await act(async () => first.resolve(fixture('OLD-CONTEST-SECRET')));
    expect(screen.queryByText('OLD-CONTEST-SECRET')).not.toBeInTheDocument();
    await act(async () => router.navigate('/help/judging'));
    expect(screen.queryByText('CURRENT-CONTEST')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '이 문제의 채점 제한' })).not.toBeInTheDocument();
  });
  it('does not show an old error in a replacement route', async () => {
    let reject!: (reason: Error) => void;
    vi.mocked(contestRequest).mockReturnValue(new Promise((_, next) => { reject = next; }));
    vi.mocked(getProblem).mockResolvedValue({ title: 'PUBLIC-PROBLEM', judgeLimits: null } as Problem);
    const { router } = view();
    await act(async () => router.navigate('/help/judging?problem=public'));
    expect(await screen.findByText('PUBLIC-PROBLEM')).toBeInTheDocument();
    await act(async () => reject(new Error('OLD-PRIVATE-DETAIL')));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
  it('aborts an unmounted request and does not carry source/test/raw-policy data into presentation', async () => {
    const pending = deferred<ContestProblemDetail>();
    vi.mocked(contestRequest).mockReturnValue(pending.promise);
    const { unmount } = view();
    const signal = vi.mocked(contestRequest).mock.calls[0][3]!;
    unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => pending.resolve({ ...fixture('NO-LONGER-AUTHORIZED'), description: 'PRIVATE-STATEMENT',
      testCases: [{ input: 'PRIVATE-INPUT', expectedOutput: 'PRIVATE-OUTPUT' }] }));
    expect(screen.queryByText('NO-LONGER-AUTHORIZED')).not.toBeInTheDocument();
    expect(screen.queryByText('PRIVATE-STATEMENT')).not.toBeInTheDocument();
  });
});
