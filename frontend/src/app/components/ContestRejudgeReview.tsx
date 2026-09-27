import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { ApiError } from '../services/apiBase';
import { getAuthScope, subscribeAuthIdentity } from '../services/authIdentity';
import {
  appendContestRejudgeReview,
  getContestRejudgeReviews,
  type ContestRejudgeReviews,
} from '../services/contestRejudgeApi';
import { AUTHORING_CATEGORIES, type AuthoringCategory, type AuthoringDecision } from '../services/problemAuthoringApi';
import type { JudgePolicy } from '../services/judgePolicyTypes';
import { ReferenceSolutionValidationPanel } from './ReferenceSolutionValidationPanel';

const categoryLabel: Record<AuthoringCategory, string> = {
  sources: '출처·이용 조건', statement: '문제 본문', tests: '테스트 자산', resources: '실행 자원',
};
const statusLabel: Record<AuthoringDecision, string> = {
  pending: '대기', approved: '승인', rejected: '반려',
};

function requestId(): string {
  return `rejudge-review-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14) || 'retry'}`;
}

function json(value: unknown): string {
  try { return JSON.stringify(value, null, 2) ?? ''; } catch { return '표시할 수 없는 구조입니다.'; }
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

/**
 * A review targets one immutable candidate fingerprint, rather than the mutable
 * source problem. This panel is mounted only inside the administrator history.
 */
export interface ContestRejudgeReviewProps {
  contestId: string; batchId: string; onReviewed: () => void; onAccessLost: () => void;
}

/** The keyed boundary immediately drops another contest, batch, or account's private candidate. */
export function ContestRejudgeReview({ contestId, batchId, onReviewed, onAccessLost }: ContestRejudgeReviewProps) {
  const scope = useSyncExternalStore(subscribeAuthIdentity, getAuthScope, () => 'guest');
  if (scope === 'guest') return null;
  return <ContestRejudgeReviewForScope key={`${scope}:${contestId}:${batchId}`} scope={scope}
    contestId={contestId} batchId={batchId} onReviewed={onReviewed} onAccessLost={onAccessLost} />;
}

function ContestRejudgeReviewForScope({ contestId, batchId, onReviewed, onAccessLost, scope }: ContestRejudgeReviewProps & { scope: string }) {
  const [record, setRecord] = useState<ContestRejudgeReviews | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [reload, setReload] = useState(0);
  const [category, setCategory] = useState<AuthoringCategory>('sources');
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const mounted = useRef(false);
  const writeController = useRef<AbortController | null>(null);
  const attempted = useRef<{ key: string; id: string } | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; writeController.current?.abort(); };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const active = () => mounted.current && !controller.signal.aborted && scope === getAuthScope();
    // Clear synchronously before fetching the next identity's private candidate.
    setRecord(null); setLoading(true); setError(''); setNote(''); setCategory('sources'); attempted.current = null;
    void getContestRejudgeReviews(contestId, batchId, controller.signal).then(next => {
      if (active()) setRecord(next);
    }).catch(caught => {
      if (!active() || isAbort(caught)) return;
      setRecord(null);
      if (caught instanceof ApiError && [401, 403].includes(caught.status)) { onAccessLost(); return; }
      setError(caught instanceof Error ? caught.message : '정정 검수 기록을 불러오지 못했습니다.');
    }).finally(() => { if (active()) setLoading(false); });
    return () => controller.abort();
  }, [batchId, contestId, onAccessLost, reload, scope]);

  const submit = (decision: Exclude<AuthoringDecision, 'pending'>) => {
    if (!record || !record.canReview || record.metadata === null || !note.trim() || submitting) return;
    const trimmed = note.trim();
    const key = `${record.requestHash}:${record.fingerprint}:${category}:${decision}:${trimmed}`;
    const id = attempted.current?.key === key ? attempted.current.id : requestId();
    attempted.current = { key, id };
    const controller = new AbortController();
    writeController.current?.abort(); writeController.current = controller;
    const active = () => mounted.current && writeController.current === controller && !controller.signal.aborted && scope === getAuthScope();
    setSubmitting(true); setError('');
    void appendContestRejudgeReview(contestId, batchId, {
      requestId: id, expectedRequestHash: record.requestHash, expectedFingerprint: record.fingerprint,
      category, decision, note: trimmed,
    }, controller.signal).then(next => {
      if (!active()) return;
      setRecord(next); attempted.current = null;
      onReviewed();
    }).catch(caught => {
      if (!active() || isAbort(caught)) return;
      if (caught instanceof ApiError && [401, 403].includes(caught.status)) {
        setRecord(null); onAccessLost(); return;
      }
      setError((caught instanceof Error ? caught.message : '정정 검수 기록을 저장하지 못했습니다.')+' 네트워크 오류라면 먼저 이력을 새로고침하세요.');
    }).finally(() => {
      if (active()) setSubmitting(false);
      if (writeController.current === controller) writeController.current = null;
    });
  };

  const busy = loading || submitting;
  const canDecide = !!record && record.canReview && record.metadata !== null;
  return <section aria-label="정정 출제 검수" className="grid min-w-0 gap-3 rounded border border-indigo-400 p-3 text-sm">
    <div><h3 className="font-semibold">정정 출제 검수</h3><p className="mt-1 text-xs text-slate-600 dark:text-slate-300">네 범주는 이 후보의 고정된 콘텐츠 지문에 각각 직접 승인해야 합니다. 이전 문제의 승인은 출처 기록으로만 남고 자동 승계되지 않습니다.</p></div>
    {loading && <p role="status">정정 검수 기록을 불러오는 중입니다.</p>}
    {error && <div role="status" className="break-words text-red-700 dark:text-red-300"><p>{error}</p>{!loading && <button type="button" className="mt-2 underline" disabled={submitting} onClick={() => setReload(value => value + 1)}>다시 불러오기</button>}</div>}
    {record && <>
      <p className="break-all text-xs font-mono">후보 지문: {record.fingerprint}</p>
      <div className="min-w-0 overflow-x-auto" role="region" aria-label="정정 검수 상태" tabIndex={0}><table className="w-full min-w-[480px] text-left"><thead><tr><th className="p-2">범주</th><th className="p-2">상태</th><th className="p-2">후보 지문</th></tr></thead><tbody>{AUTHORING_CATEGORIES.map(item => <tr key={item} className="border-t border-slate-300 dark:border-slate-700"><th className="p-2">{categoryLabel[item]}</th><td className="p-2">{statusLabel[record.categories[item]]}</td><td className="p-2 font-mono text-xs">{record.fingerprint}</td></tr>)}</tbody></table></div>
      <p role={record.ready ? 'status' : 'alert'} className={record.ready ? 'text-emerald-700 dark:text-emerald-300' : 'text-amber-800 dark:text-amber-200'}>{record.ready ? '네 범주의 후보 검수가 모두 승인되었습니다.' : '네 범주의 후보 검수가 모두 승인되기 전에는 점수 반영이 차단됩니다.'}</p>
      <ReferenceSolutionValidationPanel contestId={contestId} rejudgeBatchId={batchId}
        policy={record.snapshot.judgePolicy as JudgePolicy}
        authoring={{ fingerprint: record.fingerprint, metadata: record.metadata }} isAdmin />
      {record.metadata === null && <p role="alert" className="rounded border border-amber-400 p-2 text-amber-900 dark:text-amber-100">이 후보에는 출처 메타데이터가 없습니다. 메타데이터를 포함한 새 후보를 만들기 전에는 검수를 승인할 수 없습니다.</p>}
      {!record.canReview && <p className="rounded border border-slate-400 p-2">이미 반영했거나 폐기한 후보는 검수할 수 없습니다. 이전 형식의 미반영 후보는 폐기 후 다시 생성하세요.</p>}
      <details className="min-w-0 rounded border border-slate-300 p-2 dark:border-slate-700"><summary className="cursor-pointer font-semibold">고정된 정정 후보 전체 보기</summary><p className="mt-2 text-xs text-slate-600 dark:text-slate-300">예제·숨김 테스트·정책을 포함한 관리자 전용 고정 스냅샷입니다.</p><pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950 p-2 text-xs text-slate-100">{json(record.snapshot)}</pre></details>
      <details className="min-w-0 rounded border border-slate-300 p-2 dark:border-slate-700"><summary className="cursor-pointer font-semibold">출처 메타데이터와 이전 근거 보기</summary><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950 p-2 text-xs text-slate-100">{json({ metadata: record.metadata, basis: record.basis, applicationProvenance: record.applicationProvenance })}</pre></details>
      <section className="grid min-w-0 gap-3 rounded border border-slate-300 p-3 dark:border-slate-700"><h4 className="font-semibold">명시적 검수 결정</h4><label className="grid min-w-0 gap-1">검수 범주<select aria-label="정정 검수 범주" value={category} disabled={busy || !canDecide} onChange={event => setCategory(event.target.value as AuthoringCategory)} className="w-full min-w-0 rounded border bg-white p-2 text-slate-900 dark:bg-slate-950 dark:text-slate-100">{AUTHORING_CATEGORIES.map(item => <option key={item} value={item}>{categoryLabel[item]} · {statusLabel[record.categories[item]]}</option>)}</select></label><label className="grid min-w-0 gap-1">검수 메모<textarea aria-label="정정 검수 메모" rows={3} maxLength={4000} value={note} disabled={busy || !canDecide} onChange={event => setNote(event.target.value)} className="w-full min-w-0 rounded border bg-white p-2 text-slate-900 dark:bg-slate-950 dark:text-slate-100" placeholder="확인한 후보 근거와 판단을 기록하세요. 메모는 필수입니다." /></label><div className="flex min-w-0 flex-wrap justify-end gap-2"><button type="button" disabled={busy || !canDecide || !note.trim()} onClick={() => submit('rejected')} className="max-w-full break-words rounded border border-red-500 px-3 py-2 text-red-700 disabled:opacity-50 dark:text-red-300">반려 기록</button><button type="button" disabled={busy || !canDecide || !note.trim()} onClick={() => submit('approved')} className="max-w-full break-words rounded bg-emerald-700 px-3 py-2 text-white disabled:opacity-50">승인 기록</button></div></section>
      <details className="min-w-0 rounded border border-slate-300 p-2 dark:border-slate-700"><summary className="cursor-pointer font-semibold">검수 이력 ({record.events.length.toLocaleString('ko-KR')})</summary>{record.events.length ? <ol className="mt-2 grid gap-2">{record.events.map(event => <li key={event.id} className="rounded border border-slate-300 p-2 text-xs dark:border-slate-700"><div className="flex flex-wrap gap-x-2"><strong>{categoryLabel[event.category]} · {statusLabel[event.decision]}</strong><span>{event.createdAt}</span><span className="font-mono break-all">{event.actorId}</span></div><p className="mt-1 whitespace-pre-wrap break-words">{event.note}</p></li>)}</ol> : <p className="mt-2 text-xs text-slate-600 dark:text-slate-300">이 후보의 검수 이력이 없습니다.</p>}</details>
    </>}
  </section>;
}
