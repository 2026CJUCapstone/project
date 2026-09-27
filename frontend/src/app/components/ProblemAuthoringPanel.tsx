import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { ChevronDown, FileWarning, Loader2, RefreshCw, Save, ShieldCheck, XCircle } from 'lucide-react';
import { ApiError } from '../services/apiBase';
import { getAuthOwner, subscribeAuthIdentity } from '../services/authIdentity';
import {
  AUTHORING_CATEGORIES,
  appendProblemAuthoringReview,
  getProblemAuthoring,
  parseAuthoringMetadata,
  safeHttpUrl,
  updateProblemAuthoring,
  type AuthoringCategory,
  type AuthoringDecision,
  type ProblemAuthoringRecord,
} from '../services/problemAuthoringApi';

const categoryLabels: Record<AuthoringCategory, string> = {
  sources: '출처·이용 조건',
  statement: '문제 서술',
  tests: '테스트·자산',
  resources: '실행 자원',
};

const statusLabels: Record<AuthoringDecision, string> = {
  pending: '대기',
  approved: '승인',
  rejected: '반려',
};

function getAuthScope(): string {
  if (typeof window === 'undefined') return 'guest';
  const token = window.localStorage.getItem('authToken');
  return token && token !== 'undefined' && token !== 'null' ? `${getAuthOwner()}:${token}` : 'guest';
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString('ko-KR', { hour12: false }) : value;
}

function createRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return `review-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14) || 'retry'}`;
}

function errorMessage(error: unknown, action: string): string {
  if (error instanceof ApiError && error.status === 404) {
    return `문제를 찾을 수 없습니다. 작성 중인 내용은 보존했습니다. ${action} 전에 대회 문제 구성을 다시 확인해 주세요.`;
  }
  if (error instanceof ApiError && error.status === 409) {
    return `서버의 문제 버전이 바뀌었거나 현재 상태에서 처리할 수 없습니다. 작성 중인 내용은 보존했습니다. 최신 내용을 확인한 뒤 다시 시도해 주세요.`;
  }
  return error instanceof Error ? error.message : `${action}하지 못했습니다.`;
}

export interface ProblemAuthoringPanelProps {
  problemId: string;
  /** The surrounding admin-only page has already checked the current role. */
  isAdmin: boolean;
  /** Manage endpoint data is shown immediately, then refreshed from the authoritative endpoint. */
  initialRecord?: ProblemAuthoringRecord;
  /** Keep sibling admin tools on the same freshly loaded or saved snapshot. */
  onRecordChange?: (record: ProblemAuthoringRecord) => void;
}

/**
 * Admin provenance UI.  It is intentionally raw-JSON based so optional server
 * fields are not silently manufactured, dropped, or converted by a form.
 */
export function ProblemAuthoringPanel({ problemId, isAdmin, initialRecord, onRecordChange }: ProblemAuthoringPanelProps) {
  const scope = useSyncExternalStore(subscribeAuthIdentity, getAuthScope, () => 'guest');
  if (!isAdmin || scope === 'guest') {
    return <details className="rounded-lg border border-slate-300 bg-slate-50 p-3 text-sm dark:border-slate-700 dark:bg-slate-950"><summary className="cursor-pointer font-semibold">출처·검수 기록</summary><p className="mt-2 text-slate-600 dark:text-slate-300">출처와 검수 기록은 관리자 계정에서만 확인·편집할 수 있습니다.</p></details>;
  }
  return <ProblemAuthoringPanelForScope key={`${scope}:${problemId}`} problemId={problemId} scope={scope} initialRecord={initialRecord} onRecordChange={onRecordChange} />;
}

function ProblemAuthoringPanelForScope({ problemId, scope, initialRecord, onRecordChange }: Omit<ProblemAuthoringPanelProps, 'isAdmin'> & { scope: string }) {
  const [record, setRecord] = useState<ProblemAuthoringRecord | null>(initialRecord ?? null);
  const [rawMetadata, setRawMetadata] = useState(() => initialRecord?.metadata ? JSON.stringify(initialRecord.metadata, null, 2) : '');
  const [metadataEdited, setMetadataEdited] = useState(false);
  const [loading, setLoading] = useState(true);
  const [savingMetadata, setSavingMetadata] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  const [conflict, setConflict] = useState(false);
  const [category, setCategory] = useState<AuthoringCategory>('sources');
  const [reviewNote, setReviewNote] = useState('');
  const mountedRef = useRef(false);
  const loadControllerRef = useRef<AbortController | null>(null);
  const metadataControllerRef = useRef<AbortController | null>(null);
  const reviewControllerRef = useRef<AbortController | null>(null);
  const reviewAttemptRef = useRef<{ key: string; requestId: string } | null>(null);

  const currentScope = () => mountedRef.current && getAuthScope() === scope;
  const busy = loading || savingMetadata || reviewing;
  const hasUnsavedMetadata = (() => {
    if (!record || !metadataEdited) return false;
    try {
      // Compare parsed values only after a user edit.  This avoids treating
      // server-provided optional defaults as a client-side change on load.
      return JSON.stringify(parseAuthoringMetadata(rawMetadata)) !== JSON.stringify(record.metadata);
    } catch {
      // Invalid edited JSON is also unsaved and must not be approved against
      // the older server content.
      return true;
    }
  })();

  const applyRecord = (nextRecord: ProblemAuthoringRecord, preserveDraft: boolean) => {
    setRecord(nextRecord);
    onRecordChange?.(nextRecord);
    if (!preserveDraft) {
      setRawMetadata(nextRecord.metadata ? JSON.stringify(nextRecord.metadata, null, 2) : '');
      setMetadataEdited(false);
    }
  };

  const load = async (preserveDraft: boolean) => {
    loadControllerRef.current?.abort();
    const controller = new AbortController();
    loadControllerRef.current = controller;
    setLoading(true);
    setLoadError('');
    try {
      const nextRecord = await getProblemAuthoring(problemId, controller.signal);
      if (!currentScope() || loadControllerRef.current !== controller) return;
      applyRecord(nextRecord, preserveDraft);
      setConflict(false);
      if (preserveDraft) setNotice('서버의 최신 검수 기록을 확인했습니다. 작성 중인 출처 JSON은 바꾸지 않았습니다.');
    } catch (error) {
      if (!currentScope() || loadControllerRef.current !== controller || isAbort(error)) return;
      setLoadError(errorMessage(error, '출처·검수 정보를 불러오기'));
    } finally {
      if (currentScope() && loadControllerRef.current === controller) setLoading(false);
    }
  };

  useEffect(() => {
    mountedRef.current = true;
    void load(false);
    return () => {
      mountedRef.current = false;
      loadControllerRef.current?.abort();
      metadataControllerRef.current?.abort();
      reviewControllerRef.current?.abort();
    };
    // The keyed scope owns each private request and unsaved draft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [problemId, scope]);

  const saveMetadata = async () => {
    if (!record || busy || !currentScope()) return;
    let metadata;
    try {
      metadata = parseAuthoringMetadata(rawMetadata);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '출처 메타데이터를 확인하지 못했습니다.');
      return;
    }
    metadataControllerRef.current?.abort();
    const controller = new AbortController();
    metadataControllerRef.current = controller;
    setSavingMetadata(true);
    setActionError('');
    setNotice('');
    try {
      const saved = await updateProblemAuthoring(problemId, { expectedFingerprint: record.fingerprint, metadata }, controller.signal);
      if (!currentScope() || metadataControllerRef.current !== controller) return;
      applyRecord(saved, false);
      reviewAttemptRef.current = null;
      setConflict(false);
      setNotice('출처 메타데이터를 저장했습니다. 내용이 바뀌면 현재 버전의 검수 상태가 다시 평가됩니다.');
    } catch (error) {
      if (!currentScope() || metadataControllerRef.current !== controller || isAbort(error)) return;
      const status = error instanceof ApiError ? error.status : null;
      setConflict(status === 409);
      setActionError(errorMessage(error, '출처 메타데이터를 저장'));
    } finally {
      if (currentScope() && metadataControllerRef.current === controller) setSavingMetadata(false);
    }
  };

  const submitReview = async (decision: Exclude<AuthoringDecision, 'pending'>) => {
    if (!record || busy || !currentScope()) return;
    if (hasUnsavedMetadata) {
      setActionError('저장되지 않은 출처 메타데이터 변경이 있습니다. 서버에 저장한 콘텐츠에만 검수 승인을 기록할 수 있으니 먼저 저장해 주세요.');
      return;
    }
    const note = reviewNote.trim();
    if (!note) {
      setActionError('검수 메모를 입력한 뒤 명시적으로 승인 또는 반려를 기록해 주세요.');
      return;
    }
    const attemptKey = [record.fingerprint, category, decision, note].join('\u0000');
    const requestId = reviewAttemptRef.current?.key === attemptKey ? reviewAttemptRef.current.requestId : createRequestId();
    reviewAttemptRef.current = { key: attemptKey, requestId };
    reviewControllerRef.current?.abort();
    const controller = new AbortController();
    reviewControllerRef.current = controller;
    setReviewing(true);
    setActionError('');
    setNotice('');
    try {
      const saved = await appendProblemAuthoringReview(problemId, {
        requestId,
        expectedFingerprint: record.fingerprint,
        category,
        decision,
        note,
      }, controller.signal);
      if (!currentScope() || reviewControllerRef.current !== controller) return;
      applyRecord(saved, true);
      reviewAttemptRef.current = null;
      setConflict(false);
      setNotice(`${categoryLabels[category]} ${decision === 'approved' ? '승인' : '반려'} 기록을 저장했습니다.`);
    } catch (error) {
      if (!currentScope() || reviewControllerRef.current !== controller || isAbort(error)) return;
      const status = error instanceof ApiError ? error.status : null;
      setConflict(status === 409);
      setActionError(errorMessage(error, '검수 기록을 저장'));
    } finally {
      if (currentScope() && reviewControllerRef.current === controller) setReviewing(false);
    }
  };

  return (
    <details className="min-w-0 rounded-lg border border-slate-300 bg-slate-50 p-3 text-sm dark:border-slate-700 dark:bg-slate-950" data-testid={`problem-authoring-${problemId}`}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 font-semibold text-slate-900 dark:text-slate-100">
        <span>출처·검수 기록 <span className="ml-1 text-xs font-normal text-slate-500 dark:text-slate-400">관리자 전용</span></span>
        <ChevronDown aria-hidden="true" size={18} className="shrink-0" />
      </summary>
      <div className="mt-4 min-w-0 space-y-4">
        <p className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100">이 패널은 출처와 검수 증거를 기록합니다. 외부 난이도는 내부 난이도로 환산하지 않는 미확인 참고 정보입니다. 승인은 자동으로 수행되지 않으며, 메모와 버튼 클릭이 모두 필요합니다.</p>
        {loading && !record && <p role="status" className="flex items-center gap-2 text-slate-500"><Loader2 size={16} className="animate-spin" /> 출처·검수 기록을 불러오는 중...</p>}
        {loadError && <div role="alert" className="rounded border border-red-300 bg-red-50 px-3 py-2 text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-100"><p>{loadError}</p><button type="button" onClick={() => void load(true)} className="mt-2 inline-flex items-center gap-1 font-semibold underline"><RefreshCw size={14} /> 다시 시도</button></div>}
        {record && <>
          <section aria-label="현재 검수 상태" className="overflow-x-auto rounded border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
            <table className="w-full min-w-[480px] text-left text-xs"><thead className="bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"><tr><th className="px-3 py-2">검수 범주</th><th className="px-3 py-2">상태</th><th className="px-3 py-2">현재 콘텐츠 지문</th></tr></thead><tbody>
              {AUTHORING_CATEGORIES.map(item => <tr key={item} className="border-t border-slate-200 dark:border-slate-700"><th scope="row" className="px-3 py-2 font-medium">{categoryLabels[item]}</th><td className="px-3 py-2"><span className={`rounded-full border px-2 py-0.5 font-semibold ${record.categories[item] === 'approved' ? 'border-emerald-400 text-emerald-700 dark:text-emerald-300' : record.categories[item] === 'rejected' ? 'border-red-400 text-red-700 dark:text-red-300' : 'border-amber-400 text-amber-800 dark:text-amber-200'}`}>{statusLabels[record.categories[item]]}</span></td><td className="max-w-[280px] truncate px-3 py-2 font-mono" title={record.fingerprint}>{record.fingerprint}</td></tr>)}
            </tbody></table>
          </section>

          {record.metadata?.sources.length ? <section aria-label="등록된 출처" className="rounded border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-900"><h4 className="font-semibold">등록된 출처</h4><ul className="mt-2 space-y-2">{record.metadata.sources.map((source, index) => {
            const url = safeHttpUrl(source.url);
            return <li key={`${source.url}:${index}`} className="min-w-0 rounded border border-slate-200 p-2 dark:border-slate-700"><div className="break-words font-medium">{url ? <a href={url} target="_blank" rel="noreferrer" className="text-blue-600 underline dark:text-blue-300">{source.title}</a> : source.title}</div><p className="mt-1 break-words text-xs text-slate-600 dark:text-slate-300">이용 근거: {source.reuseBasis ?? '(기록 없음)'}{source.reuseEvidence ? ` · ${source.reuseEvidence}` : ''}</p>{source.externalTier && <p className="mt-1 text-xs text-amber-800 dark:text-amber-200">외부 난이도 “{source.externalTier}”는 출처의 미확인 참고 정보이며 내부 난이도와 대응하지 않습니다.</p>}</li>;
          })}</ul></section> : <p className="rounded border border-dashed border-slate-300 px-3 py-2 text-xs text-slate-600 dark:border-slate-600 dark:text-slate-300">아직 출처 메타데이터가 없습니다. 완전한 JSON을 입력해 저장한 뒤 검수를 기록할 수 있습니다.</p>}

          <section className="space-y-2"><label htmlFor={`authoring-json-${problemId}`} className="block font-semibold">출처 메타데이터 JSON</label><textarea id={`authoring-json-${problemId}`} aria-label="출처 메타데이터 JSON" value={rawMetadata} onChange={event => { setRawMetadata(event.target.value); setMetadataEdited(true); setActionError(''); setNotice(''); }} disabled={busy} rows={12} spellCheck={false} placeholder={'{\n  "sources": [...],\n  "adaptationNotes": "...",\n  "requiredLanguages": ["bpp"]\n}'} className="w-full min-w-0 rounded border border-slate-300 bg-white p-3 font-mono text-xs text-slate-900 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100" /><p className="text-xs text-slate-600 dark:text-slate-300">원본 JSON의 선택 필드는 생략한 그대로 서버에 보냅니다. URL은 http 또는 https만 허용하며, 저장 전에 구조와 형식을 확인합니다.</p><div className="flex flex-wrap justify-end gap-2"><button type="button" disabled={busy} onClick={() => void saveMetadata()} className="inline-flex items-center gap-1 rounded bg-blue-600 px-3 py-2 font-semibold text-white hover:bg-blue-700 disabled:opacity-50"><Save size={15} /> {savingMetadata ? '저장 중...' : '출처 메타데이터 저장'}</button></div></section>

          <section className="rounded border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-900"><h4 className="font-semibold">검수 기록</h4><p className="mt-1 text-xs text-slate-600 dark:text-slate-300">승인은 별도의 불변 기록이며 서버에 저장된 콘텐츠 지문에만 적용됩니다. 승인할 범주와 메모를 검토한 뒤 아래 승인 버튼을 직접 눌러야 합니다.</p>{hasUnsavedMetadata && <p role="status" className="mt-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100">저장되지 않은 출처 메타데이터 변경이 있습니다. 먼저 출처 메타데이터를 저장한 뒤 승인할 수 있습니다.</p>}<div className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,220px)_1fr]"><label>검수 범주<select aria-label="검수 범주" value={category} disabled={busy || !record.metadata} onChange={event => { setCategory(event.target.value as AuthoringCategory); setActionError(''); }} className="mt-1 w-full rounded border border-slate-300 bg-white px-3 py-2 dark:border-slate-600 dark:bg-slate-950">{AUTHORING_CATEGORIES.map(item => <option key={item} value={item}>{categoryLabels[item]} · {statusLabels[record.categories[item]]}</option>)}</select></label><label>검수 메모<textarea aria-label="검수 메모" value={reviewNote} disabled={busy || !record.metadata} onChange={event => { setReviewNote(event.target.value); setActionError(''); }} maxLength={4000} rows={3} className="mt-1 w-full rounded border border-slate-300 bg-white px-3 py-2 dark:border-slate-600 dark:bg-slate-950" placeholder="확인한 근거와 판단을 기록하세요. 메모는 필수입니다." /></label></div><div className="mt-3 flex flex-wrap justify-end gap-2"><button type="button" disabled={busy || !record.metadata || !reviewNote.trim() || hasUnsavedMetadata} onClick={() => void submitReview('rejected')} className="inline-flex items-center gap-1 rounded border border-red-400 px-3 py-2 font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50 dark:text-red-300"><XCircle size={15} /> {reviewing ? '기록 중...' : '반려 기록'}</button><button type="button" disabled={busy || !record.metadata || !reviewNote.trim() || hasUnsavedMetadata} onClick={() => void submitReview('approved')} className="inline-flex items-center gap-1 rounded bg-emerald-600 px-3 py-2 font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"><ShieldCheck size={15} /> {reviewing ? '기록 중...' : '승인 기록'}</button></div></section>

          {(actionError || notice) && <p role={actionError ? 'alert' : 'status'} className={`rounded border px-3 py-2 text-sm ${actionError ? (conflict ? 'border-amber-400 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100' : 'border-red-300 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-100') : 'border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-100'}`}>{actionError || notice}</p>}
          {conflict && <button type="button" disabled={busy} onClick={() => void load(true)} className="inline-flex items-center gap-1 text-sm font-semibold text-blue-700 underline disabled:opacity-50 dark:text-blue-300"><RefreshCw size={14} /> 최신 내용 확인</button>}

          <details className="rounded border border-slate-200 p-3 dark:border-slate-700"><summary className="cursor-pointer font-semibold">검수 이력 ({record.events.length.toLocaleString('ko-KR')})</summary>{record.events.length ? <ol className="mt-3 space-y-2">{record.events.map(event => <li key={event.id} className="rounded border border-slate-200 p-2 text-xs dark:border-slate-700"><div className="flex flex-wrap gap-x-2"><strong>{categoryLabels[event.category]} · {statusLabels[event.decision]}</strong><span>{formatDate(event.createdAt)}</span><span className="font-mono">{event.actorId}</span></div><p className="mt-1 whitespace-pre-wrap break-words">{event.note}</p></li>)}</ol> : <p className="mt-2 text-xs text-slate-600 dark:text-slate-300">현재 콘텐츠 지문의 검수 이력이 없습니다.</p>}</details>
        </>}
        {!loading && !record && !loadError && <p role="alert" className="flex items-center gap-2 text-red-700 dark:text-red-300"><FileWarning size={16} /> 출처·검수 기록을 표시할 수 없습니다.</p>}
      </div>
    </details>
  );
}
