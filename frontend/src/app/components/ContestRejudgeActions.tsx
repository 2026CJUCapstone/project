import { useEffect, useRef, useState } from 'react';
import { getAuthScope } from '../services/authIdentity';
import { ApiError } from '../services/apiBase';
import { ContestRejudgeAudit } from './ContestRejudgeAudit';
import { ContestRejudgeLegacyResolution } from './ContestRejudgeLegacyResolution';
import { ContestRejudgeReview } from './ContestRejudgeReview';
import { applyContestRejudge, discardContestRejudge, getContestRejudgePreview,
  type ContestRejudgeBatchDetail, type ContestRejudgePreview } from '../services/contestRejudgeApi';

export function ContestRejudgeActions({ contestId, detail, onChanged, onAccessLost }: {
  contestId: string; detail: ContestRejudgeBatchDetail; onChanged: () => void; onAccessLost: () => void;
}) {
  const [preview, setPreview] = useState<ContestRejudgePreview | null>(null);
  const [note, setNote] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [discardConfirmed, setDiscardConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const mounted = useRef(false);
  const operation = useRef<AbortController | null>(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; operation.current?.abort(); }; }, []);
  const run = async (action: (signal: AbortSignal, active: () => boolean) => Promise<void>) => {
    if (operation.current || getAuthScope() === 'guest') return;
    const controller = new AbortController(); operation.current = controller;
    const scope = getAuthScope();
    const active = () => mounted.current && !controller.signal.aborted && getAuthScope() === scope;
    setBusy(true); setError('');
    try { await action(controller.signal, active); }
    catch (caught) {
      if (active()) {
        setPreview(null); setConfirmed(false); setDiscardConfirmed(false);
        if (caught instanceof ApiError && [401, 403].includes(caught.status)) { onAccessLost(); return; }
        setError((caught instanceof Error ? caught.message : '처리 결과를 확인하지 못했습니다.')+' 반영 여부가 불명확하면 먼저 이력을 새로고침하세요.');
      }
    } finally { if (active()) setBusy(false); if (operation.current === controller) operation.current = null; }
  };
  const loadPreview = (offset = 0) => void run(async (signal, active) => {
    setPreview(null); setConfirmed(false);
    const result = await getContestRejudgePreview(contestId, detail.id, offset, 50, signal);
    if (active()) setPreview(result);
  });
  const apply = () => void run(async (signal, active) => {
    // Older preview responses cannot demonstrate the correction-review gate.
    if (!preview || preview.blockedCount || preview.reviewBlocked !== false || !confirmed || note.trim().length < 10) return;
    await applyContestRejudge(contestId, detail.id, { expectedRequestHash: preview.requestHash,
      expectedScoreboardRevision: preview.beforeScoreboardRevision, expectedPreviewHash: preview.previewHash,
      publicNote: note.trim() }, signal);
    if (active()) { setPreview(null); setConfirmed(false); onChanged(); }
  });
  const discard = () => void run(async (signal, active) => {
    if (!discardConfirmed) return;
    await discardContestRejudge(contestId, detail.id, { expectedRequestHash: detail.requestHash }, signal);
    if (active()) { setPreview(null); setDiscardConfirmed(false); onChanged(); }
  });
  const reviewed = () => {
    setPreview(null); setConfirmed(false); setDiscardConfirmed(false);
    onChanged();
  };
  const legacyResolved = () => {
    setPreview(null); setConfirmed(false); setNote('');
    onChanged();
  };
  return <section aria-label="재채점 결과 검토" className="mt-4 grid min-w-0 gap-3 rounded border border-slate-400 p-3 text-sm">
    {detail.application && <p>반영 완료 · 점수판 개정 {detail.application.beforeRevision} → {detail.application.afterRevision}<br />공개 사유: {detail.application.publicNote}</p>}
    <ContestRejudgeReview contestId={contestId} batchId={detail.id} onReviewed={reviewed} onAccessLost={onAccessLost} />
    {detail.status === 'applied' && <ContestRejudgeAudit contestId={contestId} batchId={detail.id} onAccessLost={onAccessLost} />}
    {detail.status === 'ready' && <>
      <button type="button" onClick={() => loadPreview()} disabled={busy} className="justify-self-start rounded border px-3 py-2 disabled:opacity-50">반영 전 점수 비교</button>
      {preview && <>
        <p>참가자 {preview.total}명 · 검수가 필요한 해결 기록 {preview.blockedCount}건. 표는 현재 페이지이며 반영은 이 후보 묶음 전체에 적용됩니다.</p>
        <p className="text-xs sm:hidden">표를 좌우로 스크롤하여 변경 내용을 확인하세요.</p>
        <div role="region" aria-label="점수 변경 미리보기" tabIndex={0} className="min-w-0 overflow-x-auto">
          <table className="w-full min-w-[620px] text-left"><thead><tr><th className="p-2">참가자</th><th className="p-2">순위</th><th className="p-2">대회 점수</th><th className="p-2">패널티(초)</th><th className="p-2">일반 점수 변화</th></tr></thead>
            <tbody>{preview.rows.map(row => <tr key={row.userId} className="border-t border-slate-500"><td className="p-2 break-all">{row.username}</td><td className="p-2">{row.beforeRank} → {row.afterRank}</td><td className="p-2">{row.beforePoints} → {row.afterPoints}</td><td className="p-2">{row.beforePenaltySeconds} → {row.afterPenaltySeconds}</td><td className="p-2">{row.blocker || (row.practicePointDelta !== null && row.practicePointDelta > 0 ? '+' : '')+String(row.practicePointDelta ?? '검수 필요')}</td></tr>)}</tbody>
          </table>
        </div>
        {preview.total > preview.limit && <div className="flex flex-wrap justify-between gap-2"><button disabled={busy || preview.offset === 0} onClick={() => loadPreview(Math.max(0, preview.offset - preview.limit))}>미리보기 이전</button><span>{preview.offset + 1}–{Math.min(preview.offset + preview.rows.length, preview.total)} / {preview.total}</span><button disabled={busy || preview.offset + preview.limit >= preview.total} onClick={() => loadPreview(preview.offset + preview.limit)}>미리보기 다음</button></div>}
        {preview.blockedCount > 0 && <p role="alert" className="text-red-700 dark:text-red-300">과거 해결 기록을 검수해야 합니다. 근거 없이 점수를 차감할 수 없어 반영을 막았습니다.</p>}
        {preview.blockedCount > 0 && <ContestRejudgeLegacyResolution contestId={contestId} batchId={detail.id}
          expectedRequestHash={preview.requestHash} onResolved={legacyResolved} onAccessLost={onAccessLost} />}
        {preview.reviewBlocked !== false && <p role="alert" className="text-red-700 dark:text-red-300">이 후보의 네 출제 검수가 모두 승인되기 전에는 점수·순위에 반영할 수 없습니다. 검수 상태를 새로 확인하세요.</p>}
        <label className="grid gap-1">참가자에게 공개할 정정 사유<textarea aria-label="참가자에게 공개할 정정 사유" rows={3} maxLength={1000} disabled={busy} value={note} onChange={event => { setNote(event.target.value); setConfirmed(false); }} className="w-full rounded border bg-white p-2 text-slate-900 dark:bg-slate-950 dark:text-slate-100" /></label>
        <label className="flex items-start gap-2"><input type="checkbox" checked={confirmed} disabled={busy || preview.blockedCount > 0 || preview.reviewBlocked !== false} onChange={event => setConfirmed(event.target.checked)} />전체 후보 결과와 공개 사유를 확인했고 점수·순위 변경에 동의합니다.</label>
        <button type="button" disabled={busy || !confirmed || preview.blockedCount > 0 || preview.reviewBlocked !== false || note.trim().length < 10} onClick={apply} className="justify-self-start rounded bg-blue-700 px-4 py-2 text-white disabled:opacity-50">점수·순위에 반영</button>
      </>}
    </>}
    {detail.status === 'applied' && <ContestRejudgeLegacyResolution contestId={contestId} batchId={detail.id}
      expectedRequestHash={detail.requestHash} readOnly onResolved={() => {}} onAccessLost={onAccessLost} />}
    {['ready', 'failed'].includes(detail.status) && <div className="grid gap-2 border-t border-slate-400 pt-3"><label className="flex items-start gap-2"><input type="checkbox" checked={discardConfirmed} disabled={busy} onChange={event => setDiscardConfirmed(event.target.checked)} />이 후보를 반영하지 않고 폐기합니다. 감사 이력은 남습니다.</label><button type="button" disabled={busy || !discardConfirmed} onClick={discard} className="justify-self-start rounded border border-red-500 px-3 py-2 disabled:opacity-50">후보 결과 폐기</button></div>}
    {busy && <p role="status">요청을 처리하는 중입니다.</p>}
    {error && <p role="alert" className="break-words text-red-700 dark:text-red-300">{error}</p>}
  </section>;
}
