import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setAuthToken } from '../services/authIdentity';
import { ApiError } from '../services/apiBase';
import { ContestRejudgeHistory } from './ContestRejudgeHistory';
import type { ContestRejudgeBatch, ContestRejudgeBatchDetail } from '../services/contestRejudgeApi';

const mocks = vi.hoisted(() => ({ getContestRejudgeBatches: vi.fn(), getContestRejudgeBatch: vi.fn(), getContestRejudgeContext: vi.fn() }));

vi.mock('../services/contestRejudgeApi', async importOriginal => ({
  ...await importOriginal<typeof import('../services/contestRejudgeApi')>(),
  getContestRejudgeBatches: mocks.getContestRejudgeBatches,
  getContestRejudgeBatch: mocks.getContestRejudgeBatch,
  getContestRejudgeContext: mocks.getContestRejudgeContext,
}));

function signedInToken(sub = 'admin'): string {
  return `header.${btoa(JSON.stringify({ sub }))}.signature`;
}

function batch(id = 'batch-1', contestProblemId = 'cp-1', status: ContestRejudgeBatch['status'] = 'ready'): ContestRejudgeBatch {
  return {
    id, contestProblemId, actorId: 'admin', reason: '테스트 데이터 개정', revision: 3, status,
    createdAt: '2030-01-01T00:00:00Z', finishedAt: '2030-01-01T00:03:00Z', total: 55, completed: 55, changed: 2, failed: 0,
  };
}

function detail(offset = 0): ContestRejudgeBatchDetail {
  return {
    ...batch(),
    requestHash: `sha256:${'a'.repeat(64)}`, beforeScoreboardRevision: 1, application: null,
    items: [{ id: `item-${offset}`, submissionId: `submission-${offset}`, language: 'python', receivedAt: '2030-01-01T00:00:00Z', status: 'ready', beforeVerdict: 'wrong_answer', afterVerdict: 'accepted', finishedAt: '2030-01-01T00:02:00Z' }],
    totalItems: 55, offset, limit: 50,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(nextResolve => { resolve = nextResolve; });
  return { promise, resolve };
}

describe('ContestRejudgeHistory', () => {
  afterEach(() => {
    act(() => setAuthToken(null));
    mocks.getContestRejudgeBatches.mockReset();
    mocks.getContestRejudgeBatch.mockReset();
    mocks.getContestRejudgeContext.mockReset();
  });

  it.each([401, 403])('clears sibling private history and the authoring form after a context %i', async status => {
    setAuthToken(signedInToken());
    mocks.getContestRejudgeBatches.mockResolvedValue({ batches: [batch()], total: 1 });
    mocks.getContestRejudgeBatch.mockResolvedValue(detail());
    mocks.getContestRejudgeContext.mockResolvedValueOnce({ contestProblemId: 'cp-1', snapshotHash: `sha256:${'b'.repeat(64)}`,
      snapshot: { sample: [], hidden: [{ input: 'private-rejudge-input', expectedOutput: 'secret' }], judgePolicy: null } })
      .mockRejectedValueOnce(new ApiError('권한 상실', status));
    render(<ContestRejudgeHistory contestId="contest-1" canManage finished problems={[{ id: 'cp-1', label: 'A', title: '합성 문제' }]} />);
    fireEvent.click(await screen.findByRole('button', { name: /문제 cp-1/ }));
    await screen.findByText('submission-0');
    fireEvent.change(screen.getByLabelText('재채점 문제'), { target: { value: 'cp-1' } });
    fireEvent.click(screen.getByRole('button', { name: '현재 테스트 불러오기' }));
    expect((await screen.findByLabelText('수정한 숨김 테스트 JSON') as HTMLTextAreaElement).value).toContain('private-rejudge-input');
    fireEvent.click(screen.getByRole('button', { name: '현재 테스트 불러오기' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('관리자 권한을 다시 확인');
    expect(screen.queryByText('submission-0')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('수정한 숨김 테스트 JSON')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /문제 cp-1/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '반영 전 점수 비교' })).not.toBeInTheDocument();
  });

  it('does not render or request private history outside the canManage boundary', () => {
    setAuthToken(signedInToken());
    render(<ContestRejudgeHistory contestId="contest-1" canManage={false} />);

    expect(screen.queryByRole('region', { name: '재채점 이력' })).not.toBeInTheDocument();
    expect(mocks.getContestRejudgeBatches).not.toHaveBeenCalled();
  });

  it('shows read-only staged history, supports explicit refresh and paged batch details', async () => {
    setAuthToken(signedInToken());
    mocks.getContestRejudgeBatches.mockResolvedValue({ batches: [batch()], total: 1 });
    mocks.getContestRejudgeBatch.mockImplementation((_contestId: string, _batchId: string, offset: number) => Promise.resolve(detail(offset)));
    render(<ContestRejudgeHistory contestId="contest-1" canManage />);

    expect(await screen.findByRole('heading', { name: '재채점 이력' })).toBeInTheDocument();
    expect(screen.getByText(/검토 준비까지는 원래 점수와 순위를 유지합니다/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^반영/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /문제 cp-1/ }));
    expect(await screen.findByText('submission-0')).toBeInTheDocument();
    expect(screen.getByText('오답')).toBeInTheDocument();
    expect(screen.getByText('정답')).toBeInTheDocument();
    expect(mocks.getContestRejudgeBatch).toHaveBeenLastCalledWith('contest-1', 'batch-1', 0, 50, expect.any(AbortSignal));
    expect(screen.getByText('표를 좌우로 스크롤하여 모든 결과를 확인하세요.')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: '제출별 단계 결과 표' })).toHaveAttribute('tabindex', '0');

    fireEvent.click(screen.getByRole('button', { name: '다음' }));
    expect(await screen.findByText('submission-50')).toBeInTheDocument();
    expect(mocks.getContestRejudgeBatch).toHaveBeenLastCalledWith('contest-1', 'batch-1', 50, 50, expect.any(AbortSignal));

    fireEvent.click(screen.getByRole('button', { name: '새로고침' }));
    await waitFor(() => expect(mocks.getContestRejudgeBatches).toHaveBeenCalledTimes(2));
  });

  it('paginates bounded batch summaries and displays applied batches without controls', async () => {
    setAuthToken(signedInToken());
    mocks.getContestRejudgeBatches.mockImplementation((_contestId: string, offset: number, _limit: number) => Promise.resolve({
      batches: [batch(offset === 0 ? 'batch-1' : 'batch-2', offset === 0 ? 'cp-1' : 'cp-2', offset === 0 ? 'applied' : 'ready')], total: 21,
    }));
    render(<ContestRejudgeHistory contestId="contest-1" canManage />);

    expect(await screen.findByRole('button', { name: /문제 cp-1/ })).toBeInTheDocument();
    expect(screen.getByText('반영됨')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^반영/ })).not.toBeInTheDocument();
    expect(mocks.getContestRejudgeBatches).toHaveBeenLastCalledWith('contest-1', 0, 20, expect.any(AbortSignal));

    fireEvent.click(screen.getByRole('button', { name: '다음' }));
    expect(await screen.findByRole('button', { name: /문제 cp-2/ })).toBeInTheDocument();
    expect(screen.getByText('21–21 / 21')).toBeInTheDocument();
    expect(mocks.getContestRejudgeBatches).toHaveBeenLastCalledWith('contest-1', 20, 20, expect.any(AbortSignal));
  });

  it.each([
    [403, '재채점 이력은 이 대회를 관리할 수 있는 관리자만 볼 수 있습니다.'],
    [404, '요청한 재채점 이력을 찾을 수 없습니다.'],
  ])('explains a %i list error and offers an explicit retry', async (status, message) => {
    setAuthToken(signedInToken());
    mocks.getContestRejudgeBatches.mockRejectedValue(new ApiError('private endpoint', status));
    render(<ContestRejudgeHistory contestId="contest-1" canManage />);

    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    await waitFor(() => expect(mocks.getContestRejudgeBatches).toHaveBeenCalledTimes(2));
  });

  it('clears all loaded private history when a refresh is denied', async () => {
    setAuthToken(signedInToken());
    mocks.getContestRejudgeBatches.mockResolvedValueOnce({ batches: [batch()], total: 1 }).mockRejectedValueOnce(new ApiError('private endpoint', 403));
    mocks.getContestRejudgeBatch.mockResolvedValue(detail());
    render(<ContestRejudgeHistory contestId="contest-1" canManage />);

    fireEvent.click(await screen.findByRole('button', { name: /문제 cp-1/ }));
    expect(await screen.findByText('submission-0')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '새로고침' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('재채점 이력은 이 대회를 관리할 수 있는 관리자만 볼 수 있습니다.');
    expect(screen.queryByRole('button', { name: /문제 cp-1/ })).not.toBeInTheDocument();
    expect(screen.queryByText('submission-0')).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: '선택한 재채점 배치' })).not.toBeInTheDocument();
  });

  it('clears summary history when a selected-batch request fails', async () => {
    setAuthToken(signedInToken());
    mocks.getContestRejudgeBatches.mockResolvedValue({ batches: [batch()], total: 1 });
    mocks.getContestRejudgeBatch.mockRejectedValue(new Error('temporary network failure'));
    render(<ContestRejudgeHistory contestId="contest-1" canManage />);

    fireEvent.click(await screen.findByRole('button', { name: /문제 cp-1/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('temporary network failure');
    expect(screen.queryByRole('button', { name: /문제 cp-1/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: '선택한 재채점 배치' })).not.toBeInTheDocument();
  });

  it('does not apply a late private response after a contest route change', async () => {
    setAuthToken(signedInToken('alice'));
    const old = deferred<{ batches: ContestRejudgeBatch[]; total: number }>();
    mocks.getContestRejudgeBatches
      .mockReturnValueOnce(old.promise)
      .mockResolvedValueOnce({ batches: [batch('batch-2', 'cp-2')], total: 1 });
    const { rerender } = render(<ContestRejudgeHistory contestId="contest-1" canManage />);
    rerender(<ContestRejudgeHistory contestId="contest-2" canManage />);

    expect(await screen.findByRole('button', { name: /문제 cp-2/ })).toBeInTheDocument();
    await act(async () => { old.resolve({ batches: [batch('old-batch', 'stale-problem')], total: 1 }); });
    expect(screen.queryByRole('button', { name: /stale-problem/ })).not.toBeInTheDocument();
  });
});
