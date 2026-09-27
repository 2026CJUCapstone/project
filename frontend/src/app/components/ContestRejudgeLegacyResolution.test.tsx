import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../services/apiBase';
import { setAuthToken } from '../services/authIdentity';
import type { ContestRejudgeLegacyResolutionEvent, ContestRejudgeLegacyResolutions } from '../services/contestRejudgeApi';
import { ContestRejudgeLegacyResolution } from './ContestRejudgeLegacyResolution';

const api = vi.hoisted(() => ({ getContestRejudgeLegacyResolutions: vi.fn(), appendContestRejudgeLegacyResolution: vi.fn() }));
vi.mock('../services/contestRejudgeApi', () => api);

const digest = `sha256:${'a'.repeat(64)}` as const;
const candidate = {
  userId: 'legacy-user', username: '기존 참가자', points: 120,
  solvedAt: '2030-01-01T00:00:00Z', legacyFingerprint: digest, resolution: null,
};
const list: ContestRejudgeLegacyResolutions = {
  batchId: 'batch', requestHash: digest, candidates: [candidate], resolutions: [],
};
const resolution: ContestRejudgeLegacyResolutionEvent = {
  id: 'resolution-1', userId: candidate.userId, problemId: 'problem-1', legacyFingerprint: digest,
  decision: 'link_verified_receipt', sourceKind: 'contest', sourceId: 'submission-1', sourceFingerprint: digest,
  actorId: 'admin-1', note: '기존 점수와 정답 제출의 사용자 및 배점을 대조했습니다.', createdAt: '2030-01-02T00:00:00Z',
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

function mount({ readOnly = false, requestHash = digest } = {}) {
  const onResolved = vi.fn(), onAccessLost = vi.fn();
  const view = render(<ContestRejudgeLegacyResolution contestId="contest" batchId="batch" expectedRequestHash={requestHash}
    readOnly={readOnly} onResolved={onResolved} onAccessLost={onAccessLost} />);
  return { ...view, onResolved, onAccessLost };
}

function selectCandidate() {
  fireEvent.click(screen.getByRole('button', { name: `검수: ${candidate.username}` }));
}

function enterNote() {
  fireEvent.change(screen.getByLabelText('검수 근거 메모'), {
    target: { value: '기존 점수 기록과 현재 해결 근거를 비교해 결정했습니다.' },
  });
}

describe('ContestRejudgeLegacyResolution', () => {
  beforeEach(() => {
    setAuthToken('isolated-admin');
    api.getContestRejudgeLegacyResolutions.mockResolvedValue(list);
    api.appendContestRejudgeLegacyResolution.mockResolvedValue({
      ...list, candidates: [{ ...candidate, resolution }], resolutions: [resolution],
    });
  });
  afterEach(() => { act(() => setAuthToken(null)); vi.resetAllMocks(); });

  it('requires an explicit retain decision and a meaningful note before saving', async () => {
    const view = mount();
    expect(await screen.findByText('미결 1명 · 결정 완료 0명')).toBeInTheDocument();
    expect(api.getContestRejudgeLegacyResolutions).toHaveBeenCalledWith('contest', 'batch', expect.any(AbortSignal));
    selectCandidate();

    const save = screen.getByRole('button', { name: '과거 점수 결정 기록' });
    expect(save).toBeDisabled();
    enterNote();
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText('과거 점수 결정'), { target: { value: 'retain_unattributed' } });
    expect(save).toBeEnabled();
    fireEvent.click(save);

    await waitFor(() => expect(api.appendContestRejudgeLegacyResolution).toHaveBeenCalledOnce());
    const request = api.appendContestRejudgeLegacyResolution.mock.calls[0][2];
    expect(request).toEqual({
      requestId: expect.stringMatching(/^legacy-resolution-/), expectedRequestHash: digest,
      userId: candidate.userId, expectedLegacyFingerprint: digest,
      decision: 'retain_unattributed', note: '기존 점수 기록과 현재 해결 근거를 비교해 결정했습니다.',
    });
    expect(request).not.toHaveProperty('sourceKind');
    expect(request).not.toHaveProperty('sourceId');
    expect(view.onResolved).toHaveBeenCalledOnce();
  });

  it('requires both source fields for a verified-receipt link and shows the saved decision', async () => {
    const view = mount();
    await screen.findByText('미결 1명 · 결정 완료 0명');
    selectCandidate();
    fireEvent.change(screen.getByLabelText('과거 점수 결정'), { target: { value: 'link_verified_receipt' } });
    enterNote();
    const save = screen.getByRole('button', { name: '과거 점수 결정 기록' });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText('검증된 영수증 ID'), { target: { value: 'submission-1' } });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText('영수증 종류'), { target: { value: 'contest' } });
    expect(save).toBeEnabled();
    fireEvent.click(save);

    await waitFor(() => expect(api.appendContestRejudgeLegacyResolution).toHaveBeenCalledOnce());
    expect(api.appendContestRejudgeLegacyResolution).toHaveBeenCalledWith('contest', 'batch', {
      requestId: expect.stringMatching(/^legacy-resolution-/), expectedRequestHash: digest,
      userId: candidate.userId, expectedLegacyFingerprint: digest, decision: 'link_verified_receipt',
      sourceKind: 'contest', sourceId: 'submission-1',
      note: '기존 점수 기록과 현재 해결 근거를 비교해 결정했습니다.',
    }, expect.any(AbortSignal));
    expect(view.onResolved).toHaveBeenCalledOnce();
    expect(await screen.findByText('미결 0명 · 결정 완료 1명')).toBeInTheDocument();
  });

  it('shows only the secret-free resolution projection after the batch is applied', async () => {
    api.getContestRejudgeLegacyResolutions.mockResolvedValue({ batchId: 'batch', requestHash: digest, candidates: [], resolutions: [resolution] });
    mount({ readOnly: true });

    expect(await screen.findByText('참가자 legacy-user · 검증 영수증에 연결')).toBeInTheDocument();
    expect(screen.getByText(/대회 제출 · submission-1/)).toBeInTheDocument();
    expect(screen.getByText(`검수 메모: ${resolution.note}`)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '과거 점수 결정 기록' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('검증된 영수증 ID')).not.toBeInTheDocument();
    expect(screen.queryByText(/sourceCode|hiddenTests|expectedOutput/)).not.toBeInTheDocument();
  });

  it.each([401, 403])('notifies the parent and clears private state on GET authorization loss (%i)', async status => {
    api.getContestRejudgeLegacyResolutions.mockRejectedValue(new ApiError('권한 없음', status));
    const view = mount();
    await waitFor(() => expect(view.onAccessLost).toHaveBeenCalledOnce());
    expect(screen.queryByText(candidate.username)).not.toBeInTheDocument();
  });

  it.each([401, 403])('notifies the parent and clears private state on POST authorization loss (%i)', async status => {
    api.appendContestRejudgeLegacyResolution.mockRejectedValue(new ApiError('권한 없음', status));
    const view = mount();
    await screen.findByText('미결 1명 · 결정 완료 0명');
    selectCandidate(); enterNote();
    fireEvent.change(screen.getByLabelText('과거 점수 결정'), { target: { value: 'retain_unattributed' } });
    fireEvent.click(screen.getByRole('button', { name: '과거 점수 결정 기록' }));
    await waitFor(() => expect(view.onAccessLost).toHaveBeenCalledOnce());
    expect(screen.queryByText(candidate.username)).not.toBeInTheDocument();
    expect(view.onResolved).not.toHaveBeenCalled();
  });

  it('drops an old candidate response when the authenticated scope changes', async () => {
    const pending = deferred<ContestRejudgeLegacyResolutions>();
    const next = { ...list, candidates: [{ ...candidate, username: '다른 관리자 범위의 참가자' }] };
    api.getContestRejudgeLegacyResolutions.mockReset().mockReturnValueOnce(pending.promise).mockResolvedValueOnce(next);
    const view = mount();
    await waitFor(() => expect(api.getContestRejudgeLegacyResolutions).toHaveBeenCalledOnce());
    const oldSignal = api.getContestRejudgeLegacyResolutions.mock.calls[0][2] as AbortSignal;
    act(() => setAuthToken('replacement-admin'));
    expect(oldSignal.aborted).toBe(true);
    expect(await screen.findByText('다른 관리자 범위의 참가자')).toBeInTheDocument();
    await act(async () => pending.resolve(list));
    expect(screen.queryByText(candidate.username)).not.toBeInTheDocument();
    expect(view.onResolved).not.toHaveBeenCalled();
  });

  it('aborts a pending decision when the component unmounts and ignores its late response', async () => {
    const pending = deferred<ContestRejudgeLegacyResolutions>();
    api.appendContestRejudgeLegacyResolution.mockReturnValue(pending.promise);
    const view = mount();
    await screen.findByText('미결 1명 · 결정 완료 0명');
    selectCandidate(); enterNote();
    fireEvent.change(screen.getByLabelText('과거 점수 결정'), { target: { value: 'retain_unattributed' } });
    fireEvent.click(screen.getByRole('button', { name: '과거 점수 결정 기록' }));
    const signal = api.appendContestRejudgeLegacyResolution.mock.calls[0][3] as AbortSignal;
    view.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => pending.resolve(list));
    expect(view.onResolved).not.toHaveBeenCalled();
  });
});
