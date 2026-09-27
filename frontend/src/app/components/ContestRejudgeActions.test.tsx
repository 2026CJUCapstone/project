import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ContestRejudgeActions } from './ContestRejudgeActions';
import { ApiError } from '../services/apiBase';
import { setAuthToken } from '../services/authIdentity';
import type { ContestRejudgeBatchDetail, ContestRejudgePreview } from '../services/contestRejudgeApi';

const api = vi.hoisted(() => ({
  applyContestRejudge: vi.fn(), discardContestRejudge: vi.fn(), getContestRejudgePreview: vi.fn(),
  getContestRejudgeLegacyResolutions: vi.fn(), appendContestRejudgeLegacyResolution: vi.fn(),
}));
vi.mock('../services/contestRejudgeApi', () => api);
vi.mock('./ContestRejudgeAudit', () => ({ ContestRejudgeAudit: () => <div aria-label="재채점 감사 기록" /> }));
vi.mock('./ContestRejudgeReview', () => ({
  ContestRejudgeReview: ({ onReviewed }: { onReviewed: () => void }) => <button type="button" onClick={onReviewed}>검수 완료 알림</button>,
}));
const digest = `sha256:${'a'.repeat(64)}` as const;
const detail: ContestRejudgeBatchDetail = {
  id: 'batch', contestProblemId: 'cp', actorId: 'admin', reason: '합성 테스트 자료 정정', revision: 2,
  status: 'ready', createdAt: '2030-01-01T00:00:00Z', finishedAt: '2030-01-01T00:01:00Z',
  total: 1, completed: 1, changed: 1, failed: 0, requestHash: digest, beforeScoreboardRevision: 3,
  application: null, items: [], totalItems: 1, offset: 0, limit: 50,
};
const preview: ContestRejudgePreview = {
  previewHash: `sha256:${'b'.repeat(64)}`, requestHash: digest, beforeScoreboardRevision: 3,
  total: 1, offset: 0, limit: 50, blockedCount: 0, reviewBlocked: false,
  rows: [{ userId: 'u', username: '합성 참가자', beforeRank: 2, afterRank: 1, beforePoints: 0, afterPoints: 100,
    beforePenaltySeconds: 0, afterPenaltySeconds: 120, practicePointDelta: 100, blocker: null }],
};
const legacyCandidate = {
  userId: 'legacy-user', username: '과거 점수 참가자', points: 120,
  solvedAt: '2030-01-01T00:00:00Z', legacyFingerprint: digest, resolution: null,
};
const legacyRecord = { batchId: 'batch', requestHash: digest, candidates: [legacyCandidate], resolutions: [] };
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
function mount(data = detail) {
  const onChanged = vi.fn(), onAccessLost = vi.fn();
  const view = render(<ContestRejudgeActions contestId="contest" detail={data} onChanged={onChanged} onAccessLost={onAccessLost} />);
  return { ...view, onChanged, onAccessLost };
}
async function compare() {
  fireEvent.click(screen.getByRole('button', { name: '반영 전 점수 비교' }));
  await screen.findByRole('region', { name: '점수 변경 미리보기' });
}
function confirmApply() {
  fireEvent.change(screen.getByLabelText('참가자에게 공개할 정정 사유'), { target: { value: '정답 자료를 수정하여 모든 제출을 다시 채점했습니다.' } });
  fireEvent.click(screen.getByRole('checkbox', { name: /전체 후보 결과/ }));
}

describe('explicit rejudge actions and stale response boundaries', () => {
  beforeEach(() => {
    setAuthToken('isolated-admin');
    api.getContestRejudgePreview.mockResolvedValue(preview);
    api.applyContestRejudge.mockResolvedValue({ ...detail, status: 'applied' });
    api.discardContestRejudge.mockResolvedValue({ ...detail, status: 'cancelled' });
    api.getContestRejudgeLegacyResolutions.mockResolvedValue(legacyRecord);
    api.appendContestRejudgeLegacyResolution.mockResolvedValue(legacyRecord);
  });
  afterEach(() => { act(() => setAuthToken(null)); vi.resetAllMocks(); });

  it('does not mutate on mount or preview and sends the reviewed hash only after explicit confirmation', async () => {
    const pending = deferred<unknown>();
    api.applyContestRejudge.mockReturnValue(pending.promise);
    const view = mount();
    expect(api.getContestRejudgePreview).not.toHaveBeenCalled();
    await compare();
    expect(api.getContestRejudgeLegacyResolutions).not.toHaveBeenCalled();
    expect(api.applyContestRejudge).not.toHaveBeenCalled();
    const apply = screen.getByRole('button', { name: '점수·순위에 반영' });
    expect(apply).toBeDisabled();
    confirmApply();
    fireEvent.click(apply); fireEvent.click(apply);
    expect(api.applyContestRejudge).toHaveBeenCalledTimes(1);
    expect(api.applyContestRejudge).toHaveBeenCalledWith('contest', 'batch', {
      expectedRequestHash: digest, expectedScoreboardRevision: 3, expectedPreviewHash: preview.previewHash,
      publicNote: '정답 자료를 수정하여 모든 제출을 다시 채점했습니다.',
    }, expect.any(AbortSignal));
    await act(async () => pending.resolve({ status: 'applied' }));
    expect(view.onChanged).toHaveBeenCalledTimes(1);
  });

  it('clears confirmation after changing the public note or preview page', async () => {
    api.getContestRejudgePreview.mockResolvedValue({ ...preview, total: 51 });
    mount(); await compare(); confirmApply();
    fireEvent.change(screen.getByLabelText('참가자에게 공개할 정정 사유'), { target: { value: '변경한 공개 사유를 다시 확인해야 합니다.' } });
    expect(screen.getByRole('button', { name: '점수·순위에 반영' })).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: /전체 후보 결과/ }));
    fireEvent.click(screen.getByRole('button', { name: '미리보기 다음' }));
    await screen.findByRole('region', { name: '점수 변경 미리보기' });
    expect(api.getContestRejudgePreview).toHaveBeenLastCalledWith('contest', 'batch', 50, 50, expect.any(AbortSignal));
    expect(screen.getByRole('checkbox', { name: /전체 후보 결과/ })).not.toBeChecked();
    expect(api.applyContestRejudge).not.toHaveBeenCalled();
  });

  it('blocks ambiguous legacy awards and requires a separate discard confirmation', async () => {
    api.getContestRejudgePreview.mockResolvedValue({ ...preview, blockedCount: 1,
      rows: [{ ...preview.rows[0], practicePointDelta: null, blocker: '과거 근거 확인 필요' }] });
    const view = mount(); await compare();
    expect(screen.getByRole('checkbox', { name: /전체 후보 결과/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: '점수·순위에 반영' })).toBeDisabled();
    const discard = screen.getByRole('button', { name: '후보 결과 폐기' });
    expect(discard).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: /이 후보를 반영하지 않고 폐기/ }));
    fireEvent.click(discard);
    await waitFor(() => expect(view.onChanged).toHaveBeenCalledOnce());
    expect(api.discardContestRejudge).toHaveBeenCalledWith('contest', 'batch', { expectedRequestHash: digest }, expect.any(AbortSignal));
    expect(api.applyContestRejudge).not.toHaveBeenCalled();
  });

  it('opens legacy resolution only for a blocked preview and clears that preview after a decision', async () => {
    api.getContestRejudgePreview.mockResolvedValue({ ...preview, blockedCount: 1,
      rows: [{ ...preview.rows[0], practicePointDelta: null, blocker: '과거 근거 확인 필요' }] });
    const view = mount(); await compare();
    expect(await screen.findByRole('region', { name: '과거 점수 출처 검수' })).toBeInTheDocument();
    expect(api.getContestRejudgeLegacyResolutions).toHaveBeenCalledWith('contest', 'batch', expect.any(AbortSignal));
    fireEvent.click(screen.getByRole('button', { name: `검수: ${legacyCandidate.username}` }));
    fireEvent.change(screen.getByLabelText('과거 점수 결정'), { target: { value: 'retain_unattributed' } });
    fireEvent.change(screen.getByLabelText('검수 근거 메모'), { target: { value: '현재 출처를 확인할 수 없어 과거 점수를 명시적으로 유지합니다.' } });
    fireEvent.click(screen.getByRole('button', { name: '과거 점수 결정 기록' }));

    await waitFor(() => expect(api.appendContestRejudgeLegacyResolution).toHaveBeenCalledOnce());
    expect(view.onChanged).toHaveBeenCalledOnce();
    expect(screen.queryByRole('region', { name: '점수 변경 미리보기' })).not.toBeInTheDocument();
  });

  it('shows legacy resolutions as read-only audit history after apply', async () => {
    mount({ ...detail, status: 'applied' });
    expect(await screen.findByRole('region', { name: '과거 점수 출처 검수 이력' })).toBeInTheDocument();
    expect(api.getContestRejudgeLegacyResolutions).toHaveBeenCalledWith('contest', 'batch', expect.any(AbortSignal));
    expect(screen.queryByRole('button', { name: '과거 점수 결정 기록' })).not.toBeInTheDocument();
  });

  it.each([true, undefined])('fails closed when correction review is %s', async reviewBlocked => {
    api.getContestRejudgePreview.mockResolvedValue({ ...preview, reviewBlocked });
    mount(); await compare();
    expect(screen.getByRole('checkbox', { name: /전체 후보 결과/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: '점수·순위에 반영' })).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent('네 출제 검수');
  });

  it('clears a loaded preview and asks the parent to reload after a correction-review decision', async () => {
    const view = mount(); await compare();
    fireEvent.click(screen.getByRole('button', { name: '검수 완료 알림' }));
    expect(view.onChanged).toHaveBeenCalledOnce();
    expect(screen.queryByRole('region', { name: '점수 변경 미리보기' })).not.toBeInTheDocument();
  });

  it.each([new ApiError('미리보기 이후 데이터 변경', 409), new Error('응답 연결 끊김')])('does not retry failed or ambiguous apply automatically', async error => {
    api.applyContestRejudge.mockRejectedValue(error);
    mount(); await compare(); confirmApply();
    fireEvent.click(screen.getByRole('button', { name: '점수·순위에 반영' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('먼저 이력을 새로고침');
    expect(screen.queryByRole('region', { name: '점수 변경 미리보기' })).not.toBeInTheDocument();
    expect(api.applyContestRejudge).toHaveBeenCalledOnce();
  });

  it.each([401, 403])('drops the preview and asks the parent to clear all private data on %i', async status => {
    api.applyContestRejudge.mockRejectedValue(new ApiError('권한 없음', status));
    const view = mount(); await compare(); confirmApply();
    fireEvent.click(screen.getByRole('button', { name: '점수·순위에 반영' }));
    await waitFor(() => expect(view.onAccessLost).toHaveBeenCalledOnce());
    expect(screen.queryByRole('region', { name: '점수 변경 미리보기' })).not.toBeInTheDocument();
    expect(view.onChanged).not.toHaveBeenCalled();
  });

  it('ignores a pending private preview after account change even if the transport ignores abort', async () => {
    const pending = deferred<ContestRejudgePreview>();
    api.getContestRejudgePreview.mockReturnValue(pending.promise);
    mount(); fireEvent.click(screen.getByRole('button', { name: '반영 전 점수 비교' }));
    act(() => setAuthToken('different-admin'));
    await act(async () => pending.resolve(preview));
    expect(screen.queryByText('합성 참가자')).not.toBeInTheDocument();
  });

  it('aborts pending apply on unmount and never calls a stale completion callback', async () => {
    const pending = deferred<unknown>();
    api.applyContestRejudge.mockReturnValue(pending.promise);
    const view = mount(); await compare(); confirmApply();
    fireEvent.click(screen.getByRole('button', { name: '점수·순위에 반영' }));
    const signal = api.applyContestRejudge.mock.calls[0][3] as AbortSignal;
    view.unmount(); expect(signal.aborted).toBe(true);
    await act(async () => pending.resolve({ status: 'applied' }));
    expect(view.onChanged).not.toHaveBeenCalled();
  });
});
