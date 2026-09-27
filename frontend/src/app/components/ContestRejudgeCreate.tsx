import { useEffect, useRef, useState } from 'react';
import { getAuthScope } from '../services/authIdentity';
import { ApiError } from '../services/apiBase';
import { createContestRejudge, getContestRejudgeContext, type ContestRejudgeContext } from '../services/contestRejudgeApi';
import { parseImportedJudgePolicy, type JudgePolicy } from '../services/judgePolicyTypes';
import type { HiddenTestCase, TestCase } from '../services/problemApi';
import { parseAuthoringMetadata, type AuthoringMetadata } from '../services/problemAuthoringApi';
import { JudgePolicyEditor } from './JudgePolicyEditor';
import { HiddenTestFileUpload } from './HiddenTestFileUpload';

type ProblemChoice = { id: string; label: string; title: string };
const field = 'w-full min-w-0 rounded border border-slate-400 bg-white p-2 text-sm text-slate-900 dark:bg-slate-950 dark:text-slate-100';

function baselinePolicy(context: ContestRejudgeContext): JudgePolicy | null {
  try { return parseImportedJudgePolicy(JSON.stringify(context.snapshot.judgePolicy)); } catch { return null; }
}

export function ContestRejudgeCreate({ contestId, problems, onCreated, onAccessLost }: {
  contestId: string; problems: ProblemChoice[]; onCreated: () => void; onAccessLost: () => void;
}) {
  const [problemId, setProblemId] = useState('');
  const [context, setContext] = useState<ContestRejudgeContext | null>(null);
  const [sample, setSample] = useState('[]');
  const [hidden, setHidden] = useState('[]');
  const [policy, setPolicy] = useState<JudgePolicy | null>(null);
  const [reason, setReason] = useState('');
  const [authoring, setAuthoring] = useState('');
  const [authoringEdited, setAuthoringEdited] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const mounted = useRef(false);
  const operation = useRef<AbortController | null>(null);
  const request = useRef<{ body: string; id: string } | null>(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; operation.current?.abort(); }; }, []);
  const clearContext = () => { setContext(null); setPolicy(null); setSample('[]'); setHidden('[]'); setAuthoring(''); setAuthoringEdited(false); setConfirmed(false); request.current = null; };
  const run = async (action: (signal: AbortSignal, active: () => boolean) => Promise<void>) => {
    if (operation.current || getAuthScope() === 'guest') return;
    const controller = new AbortController(); operation.current = controller;
    const scope = getAuthScope();
    const active = () => mounted.current && !controller.signal.aborted && scope === getAuthScope();
    setBusy(true); setError(''); setMessage('');
    try { await action(controller.signal, active); }
    catch (caught) {
      if (active()) {
        if (caught instanceof ApiError && [401, 403].includes(caught.status)) { clearContext(); onAccessLost(); return; }
        setError(caught instanceof Error ? caught.message : '요청 결과를 확인하지 못했습니다.');
      }
    } finally { if (active()) setBusy(false); if (operation.current === controller) operation.current = null; }
  };
  const load = () => void run(async (signal, active) => {
    clearContext();
    const loaded = await getContestRejudgeContext(contestId, problemId, signal);
    if (!active()) return;
    setContext(loaded); setSample(JSON.stringify(loaded.snapshot.sample, null, 2));
    setHidden(JSON.stringify(loaded.snapshot.hidden, null, 2)); setPolicy(baselinePolicy(loaded));
    setAuthoring(loaded.snapshot.authoring === undefined ? '' : JSON.stringify(loaded.snapshot.authoring, null, 2));
    setAuthoringEdited(false);
  });
  const submit = () => void run(async (signal, active) => {
    if (!context || context.contestProblemId !== problemId || !confirmed || !policy || reason.trim().length < 10) throw new Error('문제, 새 정책, 사유와 확인 항목을 작성하세요.');
    const samples: unknown = JSON.parse(sample), hiddenCases: unknown = JSON.parse(hidden);
    if (!Array.isArray(samples) || !Array.isArray(hiddenCases) || samples.length + hiddenCases.length < 1 || samples.length + hiddenCases.length > 200) throw new Error('예제와 숨김 테스트는 총 1~200개의 배열이어야 합니다.');
    const old = baselinePolicy(context);
    if (policy.reviewStatus !== 'verified' || (old && (policy.policyId !== old.policyId || policy.revision <= old.revision))) throw new Error('같은 정책 ID의 검증된 새 버전을 가져오세요. 측정 근거는 서버에서 다시 확인합니다.');
    let authoringMetadata: AuthoringMetadata | undefined;
    if (authoringEdited) {
      if (!authoring.trim()) throw new Error('출처 메타데이터를 비워서 지울 수 없습니다. 기존 값을 유지하려면 편집하지 마세요.');
      authoringMetadata = parseAuthoringMetadata(authoring);
    }
    const payload = { contestProblemId: problemId, expectedSnapshotHash: context.snapshotHash, reason: reason.trim(),
      sample: samples as TestCase[], hidden: hiddenCases as HiddenTestCase[], judgePolicy: policy,
      ...(authoringMetadata === undefined ? {} : { authoring: authoringMetadata }) };
    const canonical = JSON.stringify(payload);
    if (request.current?.body !== canonical) request.current = { body: canonical, id: crypto.randomUUID() };
    await createContestRejudge(contestId, { ...payload, requestId: request.current.id }, signal);
    if (!active()) return;
    clearContext(); setReason(''); request.current = null;
    setMessage('후보 채점을 접수했습니다. 이력에서 진행 상태를 확인하세요. 원래 점수는 그대로입니다.');
    onCreated();
  });
  return <details className="mt-4 min-w-0 rounded-lg border border-amber-400 p-3">
    <summary className="cursor-pointer font-semibold">재채점 후보 만들기</summary>
    <div className="mt-3 grid min-w-0 gap-3">
      <p className="text-sm">새 테스트와 실측 정책으로 후보만 채점합니다. 점수 반영은 결과 비교 후 별도로 확인해야 합니다.</p>
      <label className="grid gap-1 text-sm">재채점 문제<select aria-label="재채점 문제" className={field} value={problemId} disabled={busy || uploading} onChange={event => { setProblemId(event.target.value); clearContext(); setMessage(''); }}>
        <option value="">문제를 선택하세요</option>{problems.map(p => <option key={p.id} value={p.id}>{p.label}. {p.title}</option>)}
      </select></label>
      <button type="button" disabled={!problemId || busy || uploading} onClick={load} className="justify-self-start rounded border px-3 py-2 text-sm disabled:opacity-50">현재 테스트 불러오기</button>
      {context && <fieldset disabled={busy || uploading} className="grid min-w-0 gap-3">
        <label className="grid min-w-0 gap-1 text-sm">수정한 예제 JSON<textarea aria-label="수정한 예제 JSON" className={field+' font-mono'} rows={5} value={sample} onChange={event => { setSample(event.target.value); setConfirmed(false); }} /></label>
        <label className="grid min-w-0 gap-1 text-sm">수정한 숨김 테스트 JSON<textarea aria-label="수정한 숨김 테스트 JSON" className={field+' font-mono'} rows={5} value={hidden} onChange={event => { setHidden(event.target.value); setConfirmed(false); }} /></label>
        <p className="text-xs">저장 참조는 그대로 유지할 수 있습니다. 테스트가 바뀌면 해당 테스트 해시와 측정 근거를 포함하는 새 정책이 필요합니다.</p>
        <JudgePolicyEditor key={context.snapshotHash} policy={policy} onReplace={replacement => { setPolicy(replacement); setConfirmed(false); }} />
        <label className="grid min-w-0 gap-1 text-sm">출처 메타데이터 JSON (선택)<textarea aria-label="정정 출처 메타데이터 JSON" className={field+' font-mono'} rows={8} value={authoring} onChange={event => { setAuthoring(event.target.value); setAuthoringEdited(true); setConfirmed(false); }} placeholder={'{\n  "sources": [...],\n  "adaptationNotes": "...",\n  "requiredLanguages": ["bpp"]\n}'} /></label>
        <p className="text-xs text-slate-600 dark:text-slate-300">처음 불러온 메타데이터는 참고용이며 편집하지 않으면 요청에서 생략되어 기존 고정 기록을 유지합니다. null 또는 빈 값으로 출처 기록을 지울 수 없습니다. 메타데이터가 없는 후보는 네 범주의 정정 검수를 승인할 수 없습니다.</p>
        <label className="grid gap-1 text-sm">관리자 변경 사유<textarea aria-label="관리자 변경 사유" className={field} rows={3} maxLength={2000} value={reason} onChange={event => { setReason(event.target.value); setConfirmed(false); }} /></label>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />원래 점수는 유지하고 후보 채점만 시작합니다.</label>
        <button type="button" onClick={submit} disabled={!confirmed || !policy || reason.trim().length < 10} className="justify-self-start rounded bg-blue-700 px-4 py-2 text-sm text-white disabled:opacity-50">후보 채점 시작</button>
      </fieldset>}
      {context && <HiddenTestFileUpload targetKey={`${contestId}:${context.contestProblemId}:${context.snapshotHash}`} disabled={busy} onBusyChange={setUploading} onUploaded={testCase => {
        try { const cases: unknown = JSON.parse(hidden); if (!Array.isArray(cases)) throw new Error('숨김 테스트 JSON 배열을 먼저 확인하세요.'); setHidden(JSON.stringify([...cases, testCase], null, 2)); setConfirmed(false); }
        catch (caught) { setError(caught instanceof Error ? caught.message : '저장 참조를 추가하지 못했습니다.'); }
      }} />}
      {busy && <p role="status" className="text-sm">요청을 처리하는 중입니다.</p>}
      {error && <p role="alert" className="break-words text-sm text-red-700 dark:text-red-300">{error} 네트워크 오류라면 처리되었을 수도 있습니다. 같은 내용으로 재시도하면 동일 요청 ID를 사용합니다.</p>}
      {message && <p role="status" className="text-sm">{message}</p>}
    </div>
  </details>;
}
