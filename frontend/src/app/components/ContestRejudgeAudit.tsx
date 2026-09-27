import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { getAuthScope, subscribeAuthIdentity } from '../services/authIdentity';
import { ApiError } from '../services/apiBase';
import { getContestRejudgeAudit, type ContestRejudgeAudit } from '../services/contestRejudgeApi';

const PAGE_SIZE = 50;

function numberChange(value: number): string {
  return value > 0 ? `+${value}` : String(value);
}

export interface ContestRejudgeAuditProps {
  contestId: string;
  batchId: string;
  onAccessLost: () => void;
}

/** The keyed boundary prevents a prior administrator, contest, or batch from painting stale audit facts. */
export function ContestRejudgeAudit({ contestId, batchId, onAccessLost }: ContestRejudgeAuditProps) {
  const scope = useSyncExternalStore(subscribeAuthIdentity, getAuthScope, () => 'guest');
  if (scope === 'guest') return null;
  return <ContestRejudgeAuditForScope key={`${scope}:${contestId}:${batchId}`} scope={scope}
    contestId={contestId} batchId={batchId} onAccessLost={onAccessLost} />;
}

function ContestRejudgeAuditForScope({ contestId, batchId, onAccessLost, scope }: ContestRejudgeAuditProps & { scope: string }) {
  const [audit, setAudit] = useState<ContestRejudgeAudit | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const mounted = useRef(false);
  const operation = useRef<AbortController | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; operation.current?.abort(); };
  }, []);

  const load = (offset = 0) => {
    if (operation.current || scope === 'guest') return;
    const controller = new AbortController();
    operation.current = controller;
    const requestScope = scope;
    const active = () => mounted.current && !controller.signal.aborted && requestScope === getAuthScope();
    setBusy(true);
    setError('');
    void getContestRejudgeAudit(contestId, batchId, offset, PAGE_SIZE, controller.signal).then(result => {
      if (active()) setAudit(result);
    }).catch((caught: unknown) => {
      if (!active()) return;
      setAudit(null);
      if (caught instanceof ApiError && [401, 403].includes(caught.status)) {
        onAccessLost();
        return;
      }
      setError(caught instanceof Error ? caught.message : '반영 기록을 불러오지 못했습니다.');
    }).finally(() => {
      if (active()) setBusy(false);
      if (operation.current === controller) operation.current = null;
    });
  };

  const first = audit && audit.rows.length ? audit.offset + 1 : 0;
  return <section aria-label="재채점 반영 기록" className="mt-3 grid min-w-0 gap-3 rounded border border-slate-400 p-3 text-sm">
    <button type="button" disabled={busy || scope === 'guest'} onClick={() => load()} className="justify-self-start rounded border px-3 py-2 disabled:opacity-50">
      {audit ? '반영 전후 기록 새로고침' : '반영 전후 기록 보기'}
    </button>
    {busy && <p role="status">반영 기록을 불러오는 중입니다.</p>}
    {error && <p role="alert" className="break-words text-red-700 dark:text-red-300">{error}</p>}
    {audit && <>
      <p>점수판 개정 {audit.beforeRevision} → {audit.afterRevision} · 참가자 {audit.total}명</p>
      {!audit.rows.length && <p>표시할 반영 기록이 없습니다.</p>}
      {!!audit.rows.length && <>
        <p className="text-xs sm:hidden">표를 좌우로 스크롤하여 반영 전후 기록을 확인하세요.</p>
        <div role="region" aria-label="반영 전후 기록 표" tabIndex={0} className="min-w-0 overflow-x-auto">
          <table className="w-full min-w-[720px] text-left">
            <thead><tr className="border-b border-slate-500"><th className="p-2">사용자 ID</th><th className="p-2">순위 (전 → 후)</th><th className="p-2">대회 점수 (전 → 후)</th><th className="p-2">패널티(초) (전 → 후)</th><th className="p-2">일반 점수 변화</th></tr></thead>
            <tbody>{audit.rows.map(row => <tr key={row.userId} className="border-t border-slate-500"><td className="p-2 break-all font-mono text-xs">{row.userId}</td><td className="p-2">{row.before.rank} → {row.after?.rank ?? '—'}</td><td className="p-2">{row.before.totalPoints} → {row.after?.totalPoints ?? '—'}</td><td className="p-2">{row.before.penaltySeconds} → {row.after?.penaltySeconds ?? '—'}</td><td className="p-2">{numberChange(row.practicePointDelta)}</td></tr>)}</tbody>
          </table>
        </div>
      </>}
      {audit.total > audit.limit && <div className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" disabled={busy || audit.offset === 0} onClick={() => load(Math.max(0, audit.offset - audit.limit))}>반영 기록 이전</button>
        <span>{first}–{Math.min(audit.offset + audit.rows.length, audit.total)} / {audit.total}</span>
        <button type="button" disabled={busy || audit.offset + audit.limit >= audit.total} onClick={() => load(audit.offset + audit.limit)}>반영 기록 다음</button>
      </div>}
    </>}
  </section>;
}
