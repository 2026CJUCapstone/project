import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ContestRejudgeReview } from './ContestRejudgeReview';
import { ApiError } from '../services/apiBase';
import { setAuthToken } from '../services/authIdentity';
import type { ContestRejudgeReviews } from '../services/contestRejudgeApi';
import type { AuthoringMetadata } from '../services/problemAuthoringApi';

const api = vi.hoisted(() => ({ getContestRejudgeReviews: vi.fn(), appendContestRejudgeReview: vi.fn() }));
vi.mock('../services/contestRejudgeApi', () => api);

const digest = `sha256:${'a'.repeat(64)}` as const;
const otherDigest = `sha256:${'b'.repeat(64)}` as const;
const metadata: AuthoringMetadata = {
  sources: [{ url: 'https://example.test/problem', title: '원본', reuseBasis: 'original', reuseEvidence: '작성자가 원본임을 확인했습니다.' }],
  adaptationNotes: '정정 후보의 출처와 변경 근거를 확인합니다.', requiredLanguages: ['python'],
};
const review: ContestRejudgeReviews = {
  batchId: 'batch', requestHash: digest, fingerprint: digest, metadata,
  categories: { sources: 'pending', statement: 'pending', tests: 'pending', resources: 'pending' },
  events: [], canReview: true, ready: false, basis: { sourceFingerprint: digest }, applicationProvenance: null,
  snapshot: { sample: [{ input: '1\n', expectedOutput: '1\n' }], hidden: [], judgePolicy: { policyId: 'p', revision: 2 } },
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

function mount() {
  const onReviewed = vi.fn();
  const onAccessLost = vi.fn();
  const view = render(<ContestRejudgeReview contestId="contest" batchId="batch" onReviewed={onReviewed} onAccessLost={onAccessLost} />);
  return { ...view, onReviewed, onAccessLost };
}

function candidateFingerprint(value: string) {
  return screen.queryByText((_content, element) => element?.tagName === 'P' && element.textContent === `후보 지문: ${value}`);
}

describe('ContestRejudgeReview', () => {
  beforeEach(() => {
    setAuthToken('isolated-admin');
    api.getContestRejudgeReviews.mockResolvedValue(review);
    api.appendContestRejudgeReview.mockResolvedValue({
      ...review, categories: { ...review.categories, sources: 'approved' },
      events: [{ id: 'event', actorId: 'admin', fingerprint: digest, category: 'sources', decision: 'approved', note: '원본 출처와 이용 근거를 후보 지문에서 확인했습니다.', sequence: 1, createdAt: '2030-01-01T00:00:00Z' }],
    });
  });
  afterEach(() => { act(() => setAuthToken(null)); vi.resetAllMocks(); });

  it('loads the private frozen candidate but does not write until an administrator explicitly approves or rejects', async () => {
    const view = mount();
    expect(api.appendContestRejudgeReview).not.toHaveBeenCalled();
    await screen.findByText(/후보 지문:/);
    expect(api.getContestRejudgeReviews).toHaveBeenCalledWith('contest', 'batch', expect.any(AbortSignal));
    fireEvent.click(screen.getByText('고정된 정정 후보 전체 보기'));
    expect(screen.getByText(/expectedOutput/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('정정 검수 메모'), { target: { value: '원본 출처와 이용 근거를 후보 지문에서 확인했습니다.' } });
    fireEvent.click(screen.getByRole('button', { name: '승인 기록' }));

    await waitFor(() => expect(api.appendContestRejudgeReview).toHaveBeenCalledOnce());
    expect(api.appendContestRejudgeReview).toHaveBeenCalledWith('contest', 'batch', {
      requestId: expect.any(String), expectedRequestHash: digest, expectedFingerprint: digest,
      category: 'sources', decision: 'approved', note: '원본 출처와 이용 근거를 후보 지문에서 확인했습니다.',
    }, expect.any(AbortSignal));
    expect(view.onReviewed).toHaveBeenCalledOnce();
  });

  it('does not allow missing candidate metadata to be silently approved', async () => {
    api.getContestRejudgeReviews.mockResolvedValue({ ...review, metadata: null, canReview: true });
    mount();
    expect(await screen.findByText(/출처 메타데이터가 없습니다/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '승인 기록' })).toBeDisabled();
    expect(api.appendContestRejudgeReview).not.toHaveBeenCalled();
  });

  it.each([401, 403])('clears private candidate state through the parent on %i', async status => {
    api.getContestRejudgeReviews.mockRejectedValue(new ApiError('권한 없음', status));
    const view = mount();
    await waitFor(() => expect(view.onAccessLost).toHaveBeenCalledOnce());
    expect(screen.queryByText(digest)).not.toBeInTheDocument();
  });

  it.each([401, 403])('clears private candidate state through the parent when a %i review write loses access', async status => {
    api.appendContestRejudgeReview.mockRejectedValue(new ApiError('권한 없음', status));
    const view = mount();
    await screen.findByText(/후보 지문:/);
    fireEvent.change(screen.getByLabelText('정정 검수 메모'), { target: { value: '고정된 후보의 출처와 테스트 근거를 확인했습니다.' } });
    fireEvent.click(screen.getByRole('button', { name: '승인 기록' }));
    await waitFor(() => expect(view.onAccessLost).toHaveBeenCalledOnce());
    expect(screen.queryByText(digest)).not.toBeInTheDocument();
  });

  it('ignores a stale candidate response after authentication is lost', async () => {
    const pending = deferred<ContestRejudgeReviews>();
    api.getContestRejudgeReviews.mockReset();
    api.getContestRejudgeReviews.mockReturnValue(pending.promise);
    mount();
    await waitFor(() => expect(api.getContestRejudgeReviews).toHaveBeenCalledOnce());
    act(() => setAuthToken(null));
    await act(async () => pending.resolve(review));
    expect(candidateFingerprint(digest)).not.toBeInTheDocument();
  });

  it('immediately removes an already loaded candidate when authentication is lost', async () => {
    mount();
    await screen.findByText(/후보 지문:/);
    act(() => setAuthToken(null));
    expect(screen.queryByText(digest)).not.toBeInTheDocument();
  });

  it('drops the prior batch immediately on rerender and lets no stale response paint it', async () => {
    const prior = deferred<ContestRejudgeReviews>();
    const next = deferred<ContestRejudgeReviews>();
    api.getContestRejudgeReviews.mockReset();
    api.getContestRejudgeReviews.mockReturnValueOnce(prior.promise).mockReturnValueOnce(next.promise);
    const onReviewed = vi.fn(), onAccessLost = vi.fn();
    const view = render(<ContestRejudgeReview contestId="contest-a" batchId="batch-a" onReviewed={onReviewed} onAccessLost={onAccessLost} />);
    await waitFor(() => expect(api.getContestRejudgeReviews).toHaveBeenCalledTimes(1));
    view.rerender(<ContestRejudgeReview contestId="contest-b" batchId="batch-b" onReviewed={onReviewed} onAccessLost={onAccessLost} />);
    await waitFor(() => expect(api.getContestRejudgeReviews).toHaveBeenCalledTimes(2));
    await act(async () => prior.resolve(review));
    expect(candidateFingerprint(digest)).not.toBeInTheDocument();
    await act(async () => next.resolve({ ...review, batchId: 'batch-b', fingerprint: otherDigest }));
    await waitFor(() => expect(candidateFingerprint(otherDigest)).toBeInTheDocument());
  });
});
