import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { ApiError } from '../services/apiBase';
import { getAuthScope, subscribeAuthIdentity } from '../services/authIdentity';
import {
  appendContestRejudgeLegacyResolution,
  getContestRejudgeLegacyResolutions,
  type ContestRejudgeLegacyResolutionDecision,
  type ContestRejudgeLegacyResolutionWrite,
  type ContestRejudgeLegacyResolutions,
  type ContestRejudgeLegacySourceKind,
} from '../services/contestRejudgeApi';

function requestId(): string {
  return `legacy-resolution-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14) || 'retry'}`;
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

function decisionLabel(decision: ContestRejudgeLegacyResolutionDecision): string {
  return decision === 'retain_unattributed' ? '출처 미상으로 명시적 유지' : '검증 영수증에 연결';
}

export interface ContestRejudgeLegacyResolutionProps {
  contestId: string;
  batchId: string;
  expectedRequestHash: string;
  readOnly?: boolean;
  onResolved: () => void;
  onAccessLost: () => void;
}

/** Admin-only UI for explicitly resolving legacy score evidence blocked by a preview. */
export function ContestRejudgeLegacyResolution(props: ContestRejudgeLegacyResolutionProps) {
  const scope = useSyncExternalStore(subscribeAuthIdentity, getAuthScope, () => 'guest');
  if (scope === 'guest') return null;
  return <ContestRejudgeLegacyResolutionForScope key={`${scope}:${props.contestId}:${props.batchId}:${props.expectedRequestHash}:${props.readOnly ? 'history' : 'review'}`}
    {...props} scope={scope} />;
}

function ContestRejudgeLegacyResolutionForScope({ contestId, batchId, expectedRequestHash, readOnly = false, onResolved, onAccessLost, scope }: ContestRejudgeLegacyResolutionProps & { scope: string }) {
  const [record, setRecord] = useState<ContestRejudgeLegacyResolutions | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [reload, setReload] = useState(0);
  const [selectedUserId, setSelectedUserId] = useState('');
  const [decision, setDecision] = useState<ContestRejudgeLegacyResolutionDecision | ''>('');
  const [sourceKind, setSourceKind] = useState<ContestRejudgeLegacySourceKind | ''>('');
  const [sourceId, setSourceId] = useState('');
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
    setRecord(null); setLoading(true); setError(''); setSelectedUserId('');
    setDecision(''); setSourceKind(''); setSourceId(''); setNote(''); attempted.current = null;
    void getContestRejudgeLegacyResolutions(contestId, batchId, controller.signal).then(next => {
      if (!active()) return;
      if (next.requestHash !== expectedRequestHash) {
        setRecord(null);
        setError('재채점 후보가 변경되었습니다. 이력을 새로고침한 뒤 다시 미리보기를 여세요.');
        return;
      }
      setRecord(next);
    }).catch(caught => {
      if (!active() || isAbort(caught)) return;
      setRecord(null);
      if (caught instanceof ApiError && [401, 403].includes(caught.status)) { onAccessLost(); return; }
      setError(caught instanceof Error ? caught.message : '과거 점수 출처 검수 대상을 불러오지 못했습니다.');
    }).finally(() => { if (active()) setLoading(false); });
    return () => controller.abort();
  }, [batchId, contestId, expectedRequestHash, onAccessLost, reload, scope]);

  const selectedCandidate = record?.candidates.find(candidate => candidate.userId === selectedUserId && !candidate.resolution) ?? null;
  const busy = loading || submitting;
  const needsSource = decision === 'link_verified_receipt';
  const canSubmit = !!record && record.requestHash === expectedRequestHash && !!selectedCandidate && !!decision
    && note.trim().length >= 10 && (!needsSource || (!!sourceKind && !!sourceId.trim())) && !busy;

  const submit = () => {
    if (!record || record.requestHash !== expectedRequestHash || !selectedCandidate || !decision
      || note.trim().length < 10 || submitting) return;
    if (decision === 'link_verified_receipt' && (!sourceKind || !sourceId.trim())) return;

    const trimmedNote = note.trim();
    const trimmedSourceId = sourceId.trim();
    const key = [record.requestHash, selectedCandidate.userId, selectedCandidate.legacyFingerprint,
      decision, sourceKind, trimmedSourceId, trimmedNote].join('\u0000');
    const id = attempted.current?.key === key ? attempted.current.id : requestId();
    attempted.current = { key, id };
    const request: ContestRejudgeLegacyResolutionWrite = {
      requestId: id,
      expectedRequestHash: record.requestHash,
      userId: selectedCandidate.userId,
      expectedLegacyFingerprint: selectedCandidate.legacyFingerprint,
      decision,
      note: trimmedNote,
    };
    if (decision === 'link_verified_receipt') {
      request.sourceKind = sourceKind as ContestRejudgeLegacySourceKind;
      request.sourceId = trimmedSourceId;
    }

    const controller = new AbortController();
    writeController.current?.abort(); writeController.current = controller;
    const active = () => mounted.current && writeController.current === controller
      && !controller.signal.aborted && scope === getAuthScope();
    setSubmitting(true); setError('');
    void appendContestRejudgeLegacyResolution(contestId, batchId, request, controller.signal).then(next => {
      if (!active()) return;
      setRecord(next); attempted.current = null;
      onResolved();
    }).catch(caught => {
      if (!active() || isAbort(caught)) return;
      if (caught instanceof ApiError && [401, 403].includes(caught.status)) {
        setRecord(null); setSelectedUserId(''); onAccessLost(); return;
      }
      setError((caught instanceof Error ? caught.message : '과거 점수 출처 검수 결정을 저장하지 못했습니다.')
        + ' 반영 여부가 불명확하면 이력을 새로고침한 뒤 다시 확인하세요.');
    }).finally(() => {
      if (active()) setSubmitting(false);
      if (writeController.current === controller) writeController.current = null;
    });
  };

  const unresolved = record?.candidates.filter(candidate => !candidate.resolution) ?? [];
  const resolved = record?.candidates.filter(candidate => candidate.resolution) ?? [];

  return <section aria-label={readOnly ? '과거 점수 출처 검수 이력' : '과거 점수 출처 검수'} className="grid min-w-0 gap-3 rounded border border-amber-500 p-3 text-sm">
    <div>
      <h3 className="font-semibold">{readOnly ? '과거 점수 출처 검수 이력' : '과거 점수 출처 검수'}</h3>
      <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">{readOnly
        ? '저장된 결정과 검수 메모를 표시합니다. 제출 코드와 테스트 내용은 포함하지 않습니다.'
        : '재채점으로 영향받는 참가자의 출처 미상 점수를 하나씩 확인하고 명시적으로 결정합니다. 제출 코드와 테스트 내용은 표시하지 않습니다.'}</p>
    </div>
    {loading && <p role="status">과거 점수 검수 대상을 불러오는 중입니다.</p>}
    {error && <div role="alert" className="break-words text-red-700 dark:text-red-300"><p>{error}</p>{!loading && <button type="button" className="mt-2 underline" disabled={submitting} onClick={() => setReload(value => value + 1)}>다시 불러오기</button>}</div>}
    {record && (readOnly ? <>
      {record.resolutions.length ? <ul className="grid min-w-0 gap-2" aria-label="과거 점수 출처 검수 결정">
        {record.resolutions.map(resolution => <li key={resolution.id} className="grid min-w-0 gap-1 rounded border border-slate-300 p-2 dark:border-slate-700">
          <div className="flex min-w-0 flex-wrap items-center justify-between gap-2"><strong className="break-words">참가자 {resolution.userId} · {decisionLabel(resolution.decision)}</strong><time className="text-xs">{resolution.createdAt}</time></div>
          {resolution.sourceKind && resolution.sourceId && <p>연결 영수증: {resolution.sourceKind === 'practice' ? '일반 문제 제출' : '대회 제출'} · {resolution.sourceId}</p>}
          <p className="whitespace-pre-wrap break-words">검수 메모: {resolution.note}</p>
          <p className="break-words text-xs text-slate-600 dark:text-slate-300">검수자: {resolution.actorId}</p>
        </li>)}
      </ul> : <p>저장된 과거 점수 출처 결정이 없습니다.</p>}
    </> : <>
      <p>미결 {unresolved.length}명 · 결정 완료 {resolved.length}명</p>
      {record.candidates.length > 0 && <ul className="grid min-w-0 gap-2" aria-label="과거 점수 후보">
        {record.candidates.map(candidate => <li key={candidate.userId} className="flex min-w-0 flex-wrap items-center justify-between gap-2 rounded border border-slate-300 p-2 dark:border-slate-700">
          <span className="min-w-0 break-words"><strong>{candidate.username}</strong> · {candidate.points}점 · {candidate.solvedAt}</span>
          {candidate.resolution
            ? <span role="status">{decisionLabel(candidate.resolution.decision)}</span>
            : <button type="button" disabled={busy} aria-label={`검수: ${candidate.username}`} onClick={() => {
              setSelectedUserId(candidate.userId); setDecision(''); setSourceKind(''); setSourceId(''); setNote('');
            }} className="rounded border px-3 py-1.5 disabled:opacity-50">검수</button>}
        </li>)}
      </ul>}
      {!record.candidates.length && <p>검수할 과거 점수 후보가 없습니다.</p>}
      {selectedCandidate && <div className="grid min-w-0 gap-3 rounded border border-slate-300 p-3 dark:border-slate-700">
        <h4 className="font-semibold">{selectedCandidate.username} · {selectedCandidate.points}점</h4>
        <label className="grid min-w-0 gap-1">과거 점수 결정
          <select aria-label="과거 점수 결정" value={decision} disabled={busy} onChange={event => {
            setDecision(event.target.value as ContestRejudgeLegacyResolutionDecision | '');
            setSourceKind(''); setSourceId('');
          }} className="w-full min-w-0 rounded border bg-white p-2 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
            <option value="">결정을 선택하세요</option>
            <option value="retain_unattributed">출처 미상으로 이번 정정에서도 유지</option>
            <option value="link_verified_receipt">검증된 해결 영수증과 연결</option>
          </select>
        </label>
        {needsSource && <>
          <label className="grid min-w-0 gap-1">영수증 종류
            <select aria-label="영수증 종류" value={sourceKind} disabled={busy} onChange={event => setSourceKind(event.target.value as ContestRejudgeLegacySourceKind | '')}
              className="w-full min-w-0 rounded border bg-white p-2 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
              <option value="">종류를 선택하세요</option>
              <option value="practice">일반 문제 제출</option>
              <option value="contest">대회 제출</option>
            </select>
          </label>
          <label className="grid min-w-0 gap-1">검증된 영수증 ID
            <input aria-label="검증된 영수증 ID" value={sourceId} maxLength={80} disabled={busy} onChange={event => setSourceId(event.target.value)}
              className="w-full min-w-0 rounded border bg-white p-2 text-slate-900 dark:bg-slate-950 dark:text-slate-100" />
          </label>
        </>}
        <label className="grid min-w-0 gap-1">검수 근거 메모
          <textarea aria-label="검수 근거 메모" rows={3} maxLength={2000} value={note} disabled={busy} onChange={event => setNote(event.target.value)}
            placeholder="확인한 근거와 결정 이유를 10자 이상 기록하세요."
            className="w-full min-w-0 rounded border bg-white p-2 text-slate-900 dark:bg-slate-950 dark:text-slate-100" />
        </label>
        <p className="text-xs text-slate-600 dark:text-slate-300">영수증 연결은 같은 사용자·문제·배점의 정답 완료 기록만 서버에서 검증합니다. 출처를 확인하지 못하면 출처 미상으로 유지하는 결정을 남기세요.</p>
        <button type="button" disabled={!canSubmit} onClick={submit} className="justify-self-start rounded bg-amber-700 px-4 py-2 text-white disabled:opacity-50">과거 점수 결정 기록</button>
      </div>}
    </>)}
    {busy && !loading && <p role="status">결정을 저장하는 중입니다.</p>}
  </section>;
}
