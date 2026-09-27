import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { AlertCircle, Loader2, RefreshCw } from 'lucide-react';
import { getAuthScope, subscribeAuthIdentity } from '../services/authIdentity';
import { ApiError } from '../services/apiBase';
import {
  getContestRejudgeBatch,
  getContestRejudgeBatches,
  type ContestRejudgeBatch,
  type ContestRejudgeBatchDetail,
  type ContestRejudgeStatus,
} from '../services/contestRejudgeApi';
import { contestDate, VERDICTS } from '../services/contestApi';
import { ContestRejudgeCreate } from './ContestRejudgeCreate';
import { ContestRejudgeActions } from './ContestRejudgeActions';

const BATCH_PAGE_SIZE = 20;
const PAGE_SIZE = 50;
const statusLabel: Record<ContestRejudgeStatus, string> = {
  pending: '대기', running: '진행 중', ready: '검토 준비', failed: '실패', cancelled: '취소됨', applied: '반영됨',
};

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return '재채점 이력은 이 대회를 관리할 수 있는 관리자만 볼 수 있습니다.';
    if (error.status === 404) return '요청한 재채점 이력을 찾을 수 없습니다.';
  }
  return error instanceof Error ? error.message : '재채점 이력을 불러오지 못했습니다.';
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

function verdict(value: string | null): string {
  return value === null ? '—' : VERDICTS[value] || value;
}

function BatchStatus({ status }: { status: ContestRejudgeStatus }) {
  return <span className="rounded-full border border-slate-300 px-2 py-0.5 text-xs font-semibold dark:border-slate-600">{statusLabel[status]}</span>;
}

export interface ContestRejudgeHistoryProps {
  contestId: string;
  canManage: boolean;
  finished?: boolean;
  problems?: { id: string; label: string; title: string }[];
}

/** Account-scoped private history; finished contests offer explicit review and mutation controls. */
export function ContestRejudgeHistory({ contestId, canManage, finished = false, problems = [] }: ContestRejudgeHistoryProps) {
  const scope = useSyncExternalStore(subscribeAuthIdentity, getAuthScope, () => 'guest');
  if (!canManage || scope === 'guest') return null;
  return <ContestRejudgeHistoryForScope key={`${scope}:${contestId}`} contestId={contestId} scope={scope} finished={finished} problems={problems} />;
}

function ContestRejudgeHistoryForScope({ contestId, scope, finished, problems }: { contestId: string; scope: string; finished: boolean; problems: { id: string; label: string; title: string }[] }) {
  const [batches, setBatches] = useState<ContestRejudgeBatch[]>([]);
  const [total, setTotal] = useState(0);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ContestRejudgeBatchDetail | null>(null);
  const [batchOffset, setBatchOffset] = useState(0);
  const [offset, setOffset] = useState(0);
  const [listLoading, setListLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [listError, setListError] = useState('');
  const [detailError, setDetailError] = useState('');
  const [listRevision, setListRevision] = useState(0);
  const [detailRevision, setDetailRevision] = useState(0);
  const [privateRevision, setPrivateRevision] = useState(0);
  const mountedRef = useRef(false);
  const listRequestRef = useRef(0);
  const detailRequestRef = useRef(0);

  const current = () => mountedRef.current && getAuthScope() === scope;
  const clearPrivateHistory = () => {
    listRequestRef.current += 1;
    detailRequestRef.current += 1;
    setBatches([]); setTotal(0); setSelectedBatchId(null); setDetail(null); setOffset(0);
    setListLoading(false); setDetailLoading(false);
    setPrivateRevision(value => value + 1);
  };

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const request = listRequestRef.current + 1;
    listRequestRef.current = request;
    const active = () => current() && listRequestRef.current === request;
    setListLoading(true); setListError('');
    void getContestRejudgeBatches(contestId, batchOffset, BATCH_PAGE_SIZE, controller.signal).then(response => {
      if (!active()) return;
      setBatches(response.batches); setTotal(response.total);
      setSelectedBatchId(currentSelection => response.batches.some(batch => batch.id === currentSelection) ? currentSelection : null);
    }).catch(error => {
      if (active() && !isAbort(error)) {
        clearPrivateHistory();
        setListError(errorMessage(error));
      }
    }).finally(() => {
      if (active()) setListLoading(false);
    });
    return () => {
      controller.abort();
      if (listRequestRef.current === request) listRequestRef.current = request + 1;
    };
  }, [batchOffset, contestId, listRevision]);

  useEffect(() => {
    if (!selectedBatchId) { setDetail(null); setDetailError(''); setDetailLoading(false); return; }
    const controller = new AbortController();
    const request = detailRequestRef.current + 1;
    detailRequestRef.current = request;
    const active = () => current() && detailRequestRef.current === request;
    setDetailLoading(true); setDetailError('');
    void getContestRejudgeBatch(contestId, selectedBatchId, offset, PAGE_SIZE, controller.signal).then(response => {
      if (active()) setDetail(response);
    }).catch(error => {
      if (active() && !isAbort(error)) {
        clearPrivateHistory();
        setListError(errorMessage(error));
      }
    }).finally(() => {
      if (active()) setDetailLoading(false);
    });
    return () => {
      controller.abort();
      if (detailRequestRef.current === request) detailRequestRef.current = request + 1;
    };
  }, [contestId, selectedBatchId, offset, detailRevision]);

  const selectBatch = (batchId: string) => {
    setSelectedBatchId(batchId); setOffset(0); setDetail(null); setDetailError('');
  };
  const changeBatchPage = (nextOffset: number) => {
    setBatchOffset(Math.max(0, nextOffset)); setSelectedBatchId(null); setOffset(0); setDetail(null); setDetailError('');
  };
  const batchStart = batches.length ? batchOffset + 1 : 0;

  return <section aria-label="재채점 이력" className="min-w-0 rounded-xl border border-amber-300 bg-amber-50 p-4 text-slate-900 dark:border-amber-800 dark:bg-amber-950/20 dark:text-slate-100">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h2 className="text-lg font-bold">재채점 이력</h2><p className="mt-1 max-w-3xl text-sm text-amber-950 dark:text-amber-100">검토 준비까지는 원래 점수와 순위를 유지합니다. 후보 결과를 비교한 뒤 별도로 반영해야 최종 결과가 바뀝니다. 반영됨 상태는 이미 정정된 기록입니다.</p></div>
      <button type="button" onClick={() => { setListRevision(value => value + 1); if (selectedBatchId) setDetailRevision(value => value + 1); }} disabled={listLoading || detailLoading} className="inline-flex shrink-0 items-center gap-1 rounded border border-amber-600 px-3 py-2 text-sm font-semibold hover:bg-amber-100 disabled:opacity-50 dark:hover:bg-amber-900/30"><RefreshCw size={15} className={listLoading || detailLoading ? 'animate-spin' : ''} />새로고침</button>
    </div>
    {finished && !listError && <ContestRejudgeCreate key={privateRevision} contestId={contestId} problems={problems}
      onAccessLost={() => { clearPrivateHistory(); setListError('관리자 권한을 다시 확인하세요.'); }}
      onCreated={() => { setBatchOffset(0); setListRevision(value => value + 1); }} />}
    {listError && <div role="alert" className="mt-3 flex gap-2 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-900 dark:bg-red-950/30 dark:text-red-100"><AlertCircle size={17} className="shrink-0" /><div><p>{listError}</p><button type="button" onClick={() => setListRevision(value => value + 1)} className="mt-2 underline">다시 시도</button></div></div>}
    {listLoading && <p role="status" className="mt-3 inline-flex items-center gap-2 text-sm"><Loader2 size={16} className="animate-spin" />재채점 이력을 불러오는 중입니다.</p>}
    {!listLoading && !listError && !batches.length && <p className="mt-3 rounded border border-dashed border-amber-300 p-3 text-sm dark:border-amber-800">아직 기록된 재채점 캠페인이 없습니다.</p>}
    {!!batches.length && <div className="mt-3 grid min-w-0 gap-2">
      <p className="text-xs text-slate-600 dark:text-slate-300">총 {total}개 캠페인</p>
      {batches.map(batch => <button type="button" key={batch.id} aria-pressed={selectedBatchId === batch.id} onClick={() => selectBatch(batch.id)} className="min-w-0 rounded-lg border border-amber-300 bg-white p-3 text-left hover:border-amber-600 aria-[pressed=true]:ring-2 aria-[pressed=true]:ring-amber-500 dark:border-amber-800 dark:bg-slate-950">
        <span className="flex min-w-0 flex-wrap items-center justify-between gap-2"><span className="min-w-0 break-words font-semibold">문제 {batch.contestProblemId} · 개정 {batch.revision}</span><BatchStatus status={batch.status} /></span>
        <span className="mt-2 grid min-w-0 gap-1 text-xs text-slate-700 dark:text-slate-300 sm:grid-cols-2"><span className="min-w-0 break-words">요청자: {batch.actorId}</span><span>생성: {contestDate(batch.createdAt)}</span><span className="sm:col-span-2 break-words">사유: {batch.reason}</span><span>완료 {batch.completed}/{batch.total} · 변경 {batch.changed} · 실패 {batch.failed}</span><span>분할 처리 {batch.completedShards ?? (['ready', 'failed', 'cancelled', 'applied'].includes(batch.status) ? 1 : 0)}/{batch.shardCount ?? 1}</span>{batch.finishedAt && <span>종료: {contestDate(batch.finishedAt)}</span>}</span>
      </button>)}
      {total > BATCH_PAGE_SIZE && <div className="flex flex-wrap items-center justify-between gap-2 text-sm"><button type="button" disabled={listLoading || batchOffset === 0} onClick={() => changeBatchPage(batchOffset - BATCH_PAGE_SIZE)} className="rounded border px-3 py-1.5 disabled:opacity-50">이전</button><span>{batchStart}–{Math.min(batchOffset + batches.length, total)} / {total}</span><button type="button" disabled={listLoading || batchOffset + BATCH_PAGE_SIZE >= total} onClick={() => changeBatchPage(batchOffset + BATCH_PAGE_SIZE)} className="rounded border px-3 py-1.5 disabled:opacity-50">다음</button></div>}
    </div>}
    {selectedBatchId && <section aria-label="선택한 재채점 캠페인" className="mt-4 min-w-0 rounded-lg border border-amber-300 bg-white p-3 dark:border-amber-800 dark:bg-slate-950">
      {detail && !detailLoading && finished && <ContestRejudgeActions key={`${detail.id}:${detail.status}:${detailRevision}:${listRevision}`} contestId={contestId} detail={detail}
        onChanged={() => { setDetail(null); setSelectedBatchId(null); setListRevision(value => value + 1); }}
        onAccessLost={() => { clearPrivateHistory(); setListError('관리자 권한을 다시 확인하세요.'); }} />}
      <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">제출별 단계 결과</h3><button type="button" className="inline-flex items-center gap-1 text-sm underline disabled:opacity-50" disabled={detailLoading} onClick={() => setDetailRevision(value => value + 1)}><RefreshCw size={14} />선택한 캠페인 새로고침</button></div>
      {detailLoading && <p role="status" className="mt-3 inline-flex items-center gap-2 text-sm"><Loader2 size={16} className="animate-spin" />제출 결과를 불러오는 중입니다.</p>}
      {detailError && <div role="alert" className="mt-3 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-900 dark:bg-red-950/30 dark:text-red-100"><p>{detailError}</p><button type="button" onClick={() => setDetailRevision(value => value + 1)} className="mt-2 underline">다시 시도</button></div>}
      {detail && !detailLoading && !detailError && <><p className="mt-3 text-xs text-slate-600 dark:text-slate-300 sm:hidden">표를 좌우로 스크롤하여 모든 결과를 확인하세요.</p><div className="mt-3 overflow-x-auto" role="region" aria-label="제출별 단계 결과 표" tabIndex={0}><table className="w-full min-w-[700px] text-left text-sm"><thead><tr className="border-b border-slate-300 dark:border-slate-700"><th className="p-2">분할</th><th className="p-2">제출</th><th className="p-2">언어</th><th className="p-2">기존 결과</th><th className="p-2">단계 결과</th><th className="p-2">상태</th><th className="p-2">제출 시각</th></tr></thead><tbody>{detail.items.map(item => <tr key={item.id} className="border-b border-slate-200 last:border-0 dark:border-slate-800"><td className="p-2">#{(item.shardSequence ?? 0) + 1}</td><td className="p-2 font-mono text-xs">{item.submissionId}</td><td className="p-2">{item.language}</td><td className="p-2">{verdict(item.beforeVerdict)}</td><td className="p-2">{verdict(item.afterVerdict)}</td><td className="p-2">{item.status}</td><td className="p-2 whitespace-nowrap text-xs">{contestDate(item.receivedAt)}</td></tr>)}</tbody></table></div>
        {!detail.items.length && <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">이 캠페인에 표시할 제출 결과가 없습니다.</p>}
        {detail.totalItems > detail.limit && <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm"><button type="button" disabled={detail.offset === 0} onClick={() => setOffset(value => Math.max(0, value - PAGE_SIZE))} className="rounded border px-3 py-1.5 disabled:opacity-50">이전</button><span>{detail.offset + 1}–{Math.min(detail.offset + detail.items.length, detail.totalItems)} / {detail.totalItems}</span><button type="button" disabled={detail.offset + detail.limit >= detail.totalItems} onClick={() => setOffset(value => value + PAGE_SIZE)} className="rounded border px-3 py-1.5 disabled:opacity-50">다음</button></div>}
      </>}
    </section>}
  </section>;
}
