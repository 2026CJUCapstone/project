import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setAuthToken } from '../services/authIdentity';
import { ApiError } from '../services/apiBase';
import type { ContestRejudgeAudit as AuditResponse } from '../services/contestRejudgeApi';
import { ContestRejudgeAudit } from './ContestRejudgeAudit';

const api = vi.hoisted(() => ({ getContestRejudgeAudit: vi.fn() }));
vi.mock('../services/contestRejudgeApi', () => api);

function audit(offset = 0, total = 51): AuditResponse {
  return {
    total,
    offset,
    limit: 50,
    beforeRevision: 7,
    afterRevision: 8,
    rows: [{
      userId: offset ? 'user-51' : 'user-1',
      before: { rank: offset ? 51 : 2, totalPoints: 100, penaltySeconds: 420, problems: [] },
      after: { rank: offset ? 50 : 1, totalPoints: 200, penaltySeconds: 360, problems: [] },
      practicePointDelta: 100,
    }],
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

function mount() {
  const onAccessLost = vi.fn();
  const view = render(<ContestRejudgeAudit contestId="contest-1" batchId="batch-1" onAccessLost={onAccessLost} />);
  return { ...view, onAccessLost };
}

async function load() {
  fireEvent.click(screen.getByRole('button', { name: '반영 전후 기록 보기' }));
  await screen.findByRole('region', { name: '반영 전후 기록 표' });
}

describe('ContestRejudgeAudit', () => {
  beforeEach(() => {
    setAuthToken('isolated-admin');
    api.getContestRejudgeAudit.mockReset();
    api.getContestRejudgeAudit.mockResolvedValue(audit());
  });

  afterEach(() => {
    setAuthToken(null);
    vi.unstubAllGlobals();
  });

  it('loads no audit on mount, then shows bounded read-only rows and requests the next page explicitly', async () => {
    api.getContestRejudgeAudit.mockResolvedValueOnce(audit(0)).mockResolvedValueOnce(audit(50));
    mount();

    expect(api.getContestRejudgeAudit).not.toHaveBeenCalled();
    await load();
    expect(api.getContestRejudgeAudit).toHaveBeenCalledWith('contest-1', 'batch-1', 0, 50, expect.any(AbortSignal));
    expect(screen.getByRole('region', { name: '반영 전후 기록 표' })).toHaveAttribute('tabindex', '0');
    expect(screen.getByText('user-1')).toBeInTheDocument();
    expect(screen.getByText('2 → 1')).toBeInTheDocument();
    expect(screen.getByText('100 → 200')).toBeInTheDocument();
    expect(screen.getByText('420 → 360')).toBeInTheDocument();
    expect(screen.getByText('+100')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '반영 기록 다음' }));
    await waitFor(() => expect(api.getContestRejudgeAudit).toHaveBeenLastCalledWith('contest-1', 'batch-1', 50, 50, expect.any(AbortSignal)));
    expect(screen.getByText('user-51')).toBeInTheDocument();
    expect(screen.getByText('51–51 / 51')).toBeInTheDocument();
  });

  it('shows a read error and never retries the audit request automatically', async () => {
    api.getContestRejudgeAudit.mockRejectedValue(new Error('audit connection failed'));
    mount();

    fireEvent.click(screen.getByRole('button', { name: '반영 전후 기록 보기' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('audit connection failed');
    expect(screen.queryByRole('region', { name: '반영 전후 기록 표' })).not.toBeInTheDocument();
    expect(api.getContestRejudgeAudit).toHaveBeenCalledOnce();
  });

  it.each([401, 403])('clears retained audit rows and delegates stale authorization on %i', async status => {
    api.getContestRejudgeAudit.mockResolvedValueOnce(audit()).mockRejectedValueOnce(new ApiError('권한 없음', status));
    const view = mount();
    await load();

    fireEvent.click(screen.getByRole('button', { name: '반영 전후 기록 새로고침' }));
    await waitFor(() => expect(view.onAccessLost).toHaveBeenCalledOnce());
    expect(screen.queryByText('user-1')).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: '반영 전후 기록 표' })).not.toBeInTheDocument();
  });

  it('ignores an audit response that completes after the authorization scope changes', async () => {
    const pending = deferred<AuditResponse>();
    api.getContestRejudgeAudit.mockReturnValue(pending.promise);
    mount();
    fireEvent.click(screen.getByRole('button', { name: '반영 전후 기록 보기' }));
    const signal = api.getContestRejudgeAudit.mock.calls[0][4] as AbortSignal;

    act(() => setAuthToken('different-admin'));
    await waitFor(() => expect(signal.aborted).toBe(true));
    await act(async () => pending.resolve(audit()));
    expect(screen.queryByText('user-1')).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: '반영 전후 기록 표' })).not.toBeInTheDocument();
  });

  it('removes already-loaded audit facts synchronously when the account changes', async () => {
    mount();
    await load();
    expect(screen.getByText('user-1')).toBeInTheDocument();

    act(() => setAuthToken('different-admin'));
    expect(screen.queryByText('user-1')).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: '반영 전후 기록 표' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '반영 전후 기록 보기' })).toBeInTheDocument();
  });

  it('aborts and replaces pending audit state when contest or batch props change', async () => {
    const pending = deferred<AuditResponse>();
    api.getContestRejudgeAudit.mockReturnValueOnce(pending.promise).mockResolvedValue(audit());
    const view = mount();
    fireEvent.click(screen.getByRole('button', { name: '반영 전후 기록 보기' }));
    const signal = api.getContestRejudgeAudit.mock.calls[0][4] as AbortSignal;

    view.rerender(<ContestRejudgeAudit contestId="contest-2" batchId="batch-2" onAccessLost={view.onAccessLost} />);
    expect(signal.aborted).toBe(true);
    await act(async () => pending.resolve(audit()));
    expect(screen.queryByText('user-1')).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: '반영 전후 기록 표' })).not.toBeInTheDocument();

    await load();
    expect(api.getContestRejudgeAudit).toHaveBeenLastCalledWith('contest-2', 'batch-2', 0, 50, expect.any(AbortSignal));
  });

  it('aborts a pending audit request when unmounted', async () => {
    const pending = deferred<AuditResponse>();
    api.getContestRejudgeAudit.mockReturnValue(pending.promise);
    const view = mount();
    fireEvent.click(screen.getByRole('button', { name: '반영 전후 기록 보기' }));
    const signal = api.getContestRejudgeAudit.mock.calls[0][4] as AbortSignal;

    view.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => pending.resolve(audit()));
  });
});
