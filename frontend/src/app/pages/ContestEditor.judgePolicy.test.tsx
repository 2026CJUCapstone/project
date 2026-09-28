import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ContestEditor } from './ContestEditor';
import type { JudgePolicy } from '../services/judgePolicyTypes';
import type { StoredHiddenTestCase } from '../services/problemApi';
import { setAuthToken } from '../services/authIdentity';

const mocks = vi.hoisted(() => ({ getCurrentUser: vi.fn(), contestPageRequest: vi.fn(), contestRequest: vi.fn(), navigate: vi.fn() }));

vi.mock('../services/authApi', () => ({ getCurrentUser: mocks.getCurrentUser }));
vi.mock('../services/contestApi', async importOriginal => ({
  ...await importOriginal<typeof import('../services/contestApi')>(),
  contestPageRequest: mocks.contestPageRequest,
  contestRequest: mocks.contestRequest,
}));
vi.mock('react-router', async importOriginal => ({
  ...await importOriginal<typeof import('react-router')>(),
  useNavigate: () => mocks.navigate,
}));

const digest = (character: string) => `sha256:${character.repeat(64)}`;
const judgePolicy: JudgePolicy = {
  schemaVersion: 1, policyId: 'contest-policy', revision: 2, reviewStatus: 'verified', testSuiteHash: digest('a'), preparationCleanupMs: 5000,
  profiles: {
    python: {
      runtimeId: 'cpython-313', runtimeVersion: 'CPython 3.13', imageDigest: digest('b'), workerClass: 'linux-amd64', toolchainProfile: 'standard',
      compile: { cpuMs: 4000, wallMs: 4500, memoryBytes: 256 * 1024 ** 2, outputBytes: 1024 ** 2, pids: 64, tmpBytes: 512 * 1024 },
      run: { cpuMs: 2000, wallMs: 2500, memoryBytes: 256 * 1024 ** 2, outputBytes: 1024 ** 2, pids: 64, tmpBytes: 512 * 1024 },
    },
  },
  evidence: {
    python: { reportHash: digest('c'), resourceFingerprint: digest('d'), hostClass: 'linux-amd64', repetitions: 20, caseCount: 10, maxCpuMs: 1000, maxWallMs: 1200, peakMemoryBytes: 64 * 1024 ** 2, safetyMarginReason: 'measured headroom' },
  },
};

const storedHiddenTest: StoredHiddenTestCase = {
  kind: 'stored-v1',
  inputRef: { digest: digest('d') as `sha256:${string}`, byteCount: 4_096, encoding: 'utf-8' },
  expectedOutputRef: { digest: digest('e') as `sha256:${string}`, byteCount: 1_024, encoding: 'utf-8' },
};

function signedInToken(sub: string): string {
  return `header.${btoa(JSON.stringify({ sub }))}.signature`;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(nextResolve => { resolve = nextResolve; });
  return { promise, resolve };
}

describe('ContestEditor judge policy wiring', () => {
  beforeEach(() => {
    mocks.getCurrentUser.mockReset().mockResolvedValue({ role: 'admin' });
    mocks.contestPageRequest.mockReset().mockResolvedValue({ items: [], total: 0 });
    mocks.contestRequest.mockReset().mockResolvedValue({ id: 'created-contest' });
    mocks.navigate.mockReset();
  });

  afterEach(() => setAuthToken(null));

  it('allows an unmeasured new problem in a contest draft and preserves an explicitly imported policy in the save payload', async () => {
    render(<MemoryRouter initialEntries={['/contests/new']}><Routes><Route path="/contests/new" element={<ContestEditor />} /></Routes></MemoryRouter>);
    await screen.findByRole('heading', { name: '대회 만들기' });

    fireEvent.click(screen.getByRole('button', { name: '신규 문제 추가' }));
    expect(screen.getByText(/대회 초안은 정책 없이 저장할 수 있지만/)).toBeInTheDocument();

    fireEvent.change(screen.getByRole('textbox', { name: '정책 JSON 가져오기' }), { target: { value: JSON.stringify(judgePolicy) } });
    fireEvent.click(screen.getByRole('button', { name: '정책 JSON 확인 후 교체' }));
    expect(screen.getByText('검증됨')).toBeInTheDocument();

    fireEvent.submit(screen.getByRole('button', { name: '대회 저장' }).closest('form')!);

    await waitFor(() => expect(mocks.contestRequest).toHaveBeenCalledTimes(1));
    const [, method, body] = mocks.contestRequest.mock.calls[0];
    expect(method).toBe('POST');
    expect(body).toEqual(expect.objectContaining({
      published: false,
      problems: [expect.objectContaining({ newProblem: expect.objectContaining({ judgePolicy }) })],
    }));
  });

  it('resets the prior private editor session and ignores a late save after an account switch', async () => {
    setAuthToken(signedInToken('alice'));
    const lateSave = deferred<{ id: string }>();
    mocks.contestPageRequest
      .mockResolvedValueOnce({ items: [{ id: 'alice-problem', title: 'Alice 라이브러리', points: 100 }], total: 2 })
      .mockResolvedValueOnce({ items: [{ id: 'bob-problem', title: 'Bob 라이브러리', points: 200 }], total: 1 });
    mocks.contestRequest.mockReturnValueOnce(lateSave.promise);
    render(<MemoryRouter initialEntries={['/contests/new']}><Routes><Route path="/contests/new" element={<ContestEditor />} /><Route path="/contests/:contestId" element={<p>이전 저장 상세</p>} /></Routes></MemoryRouter>);

    const title = await screen.findByRole('textbox', { name: '대회 제목' });
    expect(screen.getByRole('option', { name: 'Alice 라이브러리' })).toBeInTheDocument();
    fireEvent.change(title, { target: { value: 'Alice의 미저장 대회' } });
    fireEvent.submit(screen.getByRole('button', { name: '대회 저장' }).closest('form')!);
    await waitFor(() => expect(mocks.contestRequest).toHaveBeenCalledTimes(1));

    act(() => setAuthToken(signedInToken('bob')));
    const resetTitle = await screen.findByRole('textbox', { name: '대회 제목' });
    expect(resetTitle).toHaveValue('');
    expect(screen.getByRole('option', { name: 'Bob 라이브러리' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Alice 라이브러리' })).not.toBeInTheDocument();

    await act(async () => lateSave.resolve({ id: 'alice-saved-contest' }));
    expect(screen.getByRole('heading', { name: '대회 만들기' })).toBeInTheDocument();
    expect(screen.queryByText('이전 저장 상세')).not.toBeInTheDocument();
  });

  it('does not append a late load-more result from a previous account session', async () => {
    setAuthToken(signedInToken('alice'));
    const oldLoadMore = deferred<{ items: { id: string; title: string; points: number }[]; total: number }>();
    mocks.contestPageRequest
      .mockResolvedValueOnce({ items: [{ id: 'alice-problem', title: 'Alice 라이브러리', points: 100 }], total: 2 })
      .mockReturnValueOnce(oldLoadMore.promise)
      .mockResolvedValueOnce({ items: [{ id: 'bob-problem', title: 'Bob 라이브러리', points: 200 }], total: 1 });
    render(<MemoryRouter initialEntries={['/contests/new']}><Routes><Route path="/contests/new" element={<ContestEditor />} /></Routes></MemoryRouter>);

    await screen.findByRole('option', { name: 'Alice 라이브러리' });
    fireEvent.click(screen.getByRole('button', { name: '문제 더 보기 (1/2)' }));
    await waitFor(() => expect(mocks.contestPageRequest).toHaveBeenCalledTimes(2));
    act(() => setAuthToken(signedInToken('bob')));
    await screen.findByRole('option', { name: 'Bob 라이브러리' });

    await act(async () => oldLoadMore.resolve({ items: [{ id: 'stale-problem', title: '이전 세션 추가 문제', points: 100 }], total: 2 }));
    expect(screen.queryByRole('option', { name: '이전 세션 추가 문제' })).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Alice 라이브러리' })).not.toBeInTheDocument();
  });

  it('does not navigate when an unmounted editor receives a late save result', async () => {
    setAuthToken(signedInToken('alice'));
    const lateSave = deferred<{ id: string }>();
    mocks.contestRequest.mockReturnValueOnce(lateSave.promise);
    const { unmount } = render(<MemoryRouter initialEntries={['/contests/new']}><Routes><Route path="/contests/new" element={<ContestEditor />} /></Routes></MemoryRouter>);

    await screen.findByRole('textbox', { name: '대회 제목' });
    fireEvent.submit(screen.getByRole('button', { name: '대회 저장' }).closest('form')!);
    await waitFor(() => expect(mocks.contestRequest).toHaveBeenCalledTimes(1));
    unmount();

    await act(async () => lateSave.resolve({ id: 'late-contest' }));
    expect(mocks.navigate).not.toHaveBeenCalled();
  });

  it('keeps a stored hidden-test reference when a saved contest changes its title or schedule', async () => {
    mocks.contestRequest.mockReset()
      .mockResolvedValueOnce({
        id: 'contest-1', title: '원래 대회', description: '', startsAt: '2030-01-01T00:00:00Z', endsAt: '2030-01-02T00:00:00Z', serverTime: '2029-12-31T00:00:00Z', state: 'draft', published: false, joined: false, canManage: true, participantCount: 0,
        problems: [{ problemId: 'problem-1', points: 100, newProblem: { title: '숨김 참조 문제', description: '설명', difficulty: 'iron5', tags: [], points: 100, testCases: [{ input: '1', expectedOutput: '1' }], hiddenTestCases: [storedHiddenTest] } }],
      })
      .mockResolvedValueOnce({ id: 'contest-1' });
    render(<MemoryRouter initialEntries={['/contests/contest-1/edit']}><Routes><Route path="/contests/:contestId/edit" element={<ContestEditor />} /></Routes></MemoryRouter>);

    fireEvent.click(await screen.findByRole('button', { name: 'A 숨김 참조 문제 편집' }));
    expect(await screen.findByText('숨겨진 테스트 1 · 저장 참조')).toBeInTheDocument();
    expect(screen.queryByLabelText('숨겨진 테스트 1 입력')).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox', { name: '대회 제목' }), { target: { value: '바뀐 대회 제목' } });
    fireEvent.change(screen.getByLabelText('시작 시각 (KST)'), { target: { value: '2030-01-03T09:00' } });
    fireEvent.submit(screen.getByRole('button', { name: '대회 저장' }).closest('form')!);

    await waitFor(() => expect(mocks.contestRequest).toHaveBeenCalledTimes(2));
    const [, method, body] = mocks.contestRequest.mock.calls[1];
    expect(method).toBe('PUT');
    expect(body).toEqual(expect.objectContaining({
      title: '바뀐 대회 제목',
      problems: [expect.objectContaining({ newProblem: expect.objectContaining({ hiddenTestCases: [storedHiddenTest] }) })],
    }));
  });
});
