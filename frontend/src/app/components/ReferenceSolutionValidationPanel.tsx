import { useEffect, useMemo, useRef, useState } from 'react';
import { Loader2, PlayCircle } from 'lucide-react';
import { VERDICTS } from '../services/contestApi';
import type { CompilerLanguage } from '../services/compilerApi';
import type { JudgePolicy, JudgePolicyLanguage } from '../services/judgePolicyTypes';
import type { ProblemAuthoringRecord } from '../services/problemAuthoringApi';
import { ApiError } from '../services/apiBase';
import {
  createAuthoringValidation,
  createProblemAuthoringValidation,
  createRejudgeAuthoringValidation,
  waitForAuthoringValidation,
  waitForProblemAuthoringValidation,
  waitForRejudgeAuthoringValidation,
  type AuthoringValidationReceipt,
} from '../services/authoringValidationApi';
import { SubmissionResourceUsage } from './SubmissionResourceUsage';

const LANGUAGE_LABELS: Record<JudgePolicyLanguage, string> = {
  bpp: 'B++', c: 'C', cpp: 'C++', python: 'Python', java: 'Java', javascript: 'JavaScript',
};

function createRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return `authoring-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14) || 'retry'}`;
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

export interface ReferenceSolutionValidationPanelProps {
  /** Standalone practice problem target. */
  problemId?: string;
  contestId?: string;
  contestProblemId?: string;
  rejudgeBatchId?: string;
  policy?: JudgePolicy | null;
  authoring?: Pick<ProblemAuthoringRecord, 'fingerprint' | 'metadata'>;
  isAdmin: boolean;
}

/** Admin-only saved-draft check. It never creates a participant submission or score. */
export function ReferenceSolutionValidationPanel({
  problemId,
  contestId,
  contestProblemId,
  rejudgeBatchId,
  policy,
  authoring,
  isAdmin,
}: ReferenceSolutionValidationPanelProps) {
  const references = useMemo(() => {
    const byLanguage = new Map<JudgePolicyLanguage, string>();
    for (const asset of authoring?.metadata?.assets ?? []) {
      if (asset.role === 'reference' && asset.language && policy?.profiles[asset.language]) {
        byLanguage.set(asset.language, asset.digest);
      }
    }
    return [...byLanguage.entries()];
  }, [authoring, policy]);
  const [language, setLanguage] = useState<JudgePolicyLanguage | ''>('');
  const [source, setSource] = useState('');
  const [receipt, setReceipt] = useState<AuthoringValidationReceipt | null>(null);
  const [error, setError] = useState('');
  const [running, setRunning] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);
  const attemptRef = useRef<{ key: string; requestId: string } | null>(null);
  const scopeRef = useRef('');
  const referenceKey = references.map(([item, digest]) => `${item}:${digest}`).join('|');
  const scope = [problemId, contestId, contestProblemId, rejudgeBatchId, authoring?.fingerprint, JSON.stringify(policy ?? null), referenceKey].join('\u0000');

  useEffect(() => {
    scopeRef.current = scope;
    controllerRef.current?.abort();
    setLanguage(references[0]?.[0] ?? '');
    setSource('');
    setReceipt(null);
    setError('');
    setRunning(false);
    attemptRef.current = null;
    return () => controllerRef.current?.abort();
  }, [scope, referenceKey]);

  if (!isAdmin) return null;

  const verified = policy?.reviewStatus === 'verified';
  const digest = references.find(([candidate]) => candidate === language)?.[1];
  const targetAvailable = Boolean(problemId || (contestId && (rejudgeBatchId || contestProblemId)));
  const available = Boolean(targetAvailable && authoring?.fingerprint && verified && language && digest);

  const run = async () => {
    if (!available || !authoring || !language || !digest || !source.trim()) return;
    const attemptKey = [scope, language, digest, source].join('\u0000');
    const requestId = attemptRef.current?.key === attemptKey ? attemptRef.current.requestId : createRequestId();
    attemptRef.current = { key: attemptKey, requestId };
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const requestedScope = scope;
    setRunning(true);
    setError('');
    setReceipt(null);
    try {
      const request = {
        code: source,
        language: language as CompilerLanguage,
        requestId,
        expectedFingerprint: authoring.fingerprint,
        referenceAssetDigest: digest,
      };
      const queued = rejudgeBatchId && contestId
        ? await createRejudgeAuthoringValidation(contestId, rejudgeBatchId, request, controller.signal)
        : problemId
          ? await createProblemAuthoringValidation(problemId, request, controller.signal)
          : await createAuthoringValidation(contestId!, contestProblemId!, request, controller.signal);
      if (scopeRef.current !== requestedScope || controllerRef.current !== controller) return;
      setReceipt(queued);
      const finished = rejudgeBatchId && contestId
        ? await waitForRejudgeAuthoringValidation(contestId, rejudgeBatchId, queued, controller.signal)
        : problemId
          ? await waitForProblemAuthoringValidation(problemId, queued, controller.signal)
          : await waitForAuthoringValidation(contestId!, contestProblemId!, queued, controller.signal);
      if (scopeRef.current !== requestedScope || controllerRef.current !== controller) return;
      setReceipt(finished);
      attemptRef.current = null;
    } catch (caught) {
      if (scopeRef.current !== requestedScope || controllerRef.current !== controller || isAbort(caught)) return;
      if (caught instanceof ApiError && caught.status === 410) {
        attemptRef.current = null;
        setError('이전 검증 결과가 만료되었습니다. 다시 실행하여 새 검증을 시작하세요.');
        return;
      }
      setError(caught instanceof Error ? caught.message : '기준 풀이 검증을 완료하지 못했습니다.');
    } finally {
      if (scopeRef.current === requestedScope && controllerRef.current === controller) setRunning(false);
    }
  };

  return <details className="min-w-0 rounded-lg border border-slate-300 bg-slate-50 p-3 text-sm dark:border-slate-700 dark:bg-slate-950">
    <summary className="cursor-pointer font-semibold">기준 풀이 검증 <span className="ml-1 text-xs font-normal text-slate-500 dark:text-slate-400">관리자 전용</span></summary>
    <div className="mt-3 space-y-3">
      <p className="text-xs leading-5 text-slate-600 dark:text-slate-300">저장된 문제 스냅샷과 숨겨진 테스트 전체에 실행합니다. 참가자 제출 기록·점수·순위에는 반영되지 않으며 테스트 내용은 결과에 표시하지 않습니다.</p>
      <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">{problemId ? '출처 파일 지문이나 채점 정책을 바꿨다면 문제를 먼저 저장한 뒤 검증하세요.' : '출처 파일 지문이나 채점 정책을 바꿨다면 대회를 저장하고 편집 화면을 다시 연 뒤 검증하세요.'}</p>
      {!targetAvailable ? <p role="status" className="rounded border border-dashed border-slate-300 px-3 py-2 text-xs dark:border-slate-600">문제를 먼저 저장한 뒤 기준 풀이를 검증할 수 있습니다.</p>
        : !authoring?.metadata ? <p role="status" className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100">출처·검수 기록에 언어별 기준 풀이 파일 지문을 먼저 저장하세요.</p>
          : !verified ? <p role="status" className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100">검증된 언어별 채점 제한을 먼저 저장하세요.</p>
            : references.length === 0 ? <p role="status" className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100">채점 정책과 일치하는 기준 풀이 파일 지문이 없습니다.</p>
              : <>
                <label className="block">검증 언어<select aria-label="기준 풀이 검증 언어" value={language} disabled={running} onChange={event => { setLanguage(event.target.value as JudgePolicyLanguage); setSource(''); setReceipt(null); setError(''); attemptRef.current = null; }} className="mt-1 w-full rounded border border-slate-300 bg-white px-3 py-2 dark:border-slate-600 dark:bg-slate-900">{references.map(([item]) => <option key={item} value={item}>{LANGUAGE_LABELS[item]}</option>)}</select></label>
                <label className="block">기준 풀이 코드<textarea aria-label="기준 풀이 코드" value={source} disabled={running} onChange={event => { setSource(event.target.value); setReceipt(null); setError(''); }} rows={10} spellCheck={false} className="mt-1 w-full rounded border border-slate-300 bg-white p-3 font-mono text-xs dark:border-slate-600 dark:bg-slate-900" placeholder="등록한 기준 풀이 파일과 바이트 단위로 같은 코드를 붙여 넣으세요." /></label>
                <p className="break-all text-[11px] text-slate-500 dark:text-slate-400">등록 지문: {digest}</p>
                <button type="button" onClick={() => void run()} disabled={!available || !source.trim() || running} className="inline-flex items-center gap-2 rounded bg-blue-600 px-3 py-2 font-semibold text-white disabled:opacity-50">{running ? <Loader2 aria-hidden="true" size={16} className="animate-spin" /> : <PlayCircle aria-hidden="true" size={16} />}{running ? '검증 중…' : '기준 풀이 실행'}</button>
              </>}
      {error && <p role="alert" className="rounded border border-red-300 bg-red-50 px-3 py-2 text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-100">{error}</p>}
      {receipt && <section aria-label="기준 풀이 검증 결과" className="space-y-2 rounded border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-900">
        <div className="flex flex-wrap items-center justify-between gap-2"><strong>{receipt.status === 'queued' ? '대기 중' : receipt.status === 'running' ? '실행 중' : receipt.result ? (VERDICTS[receipt.result.verdict] ?? receipt.result.verdict) : '검증 실패'}</strong><span className="font-mono text-[11px] text-slate-500">{receipt.id}</span></div>
        {receipt.result?.error && <p role="alert" className="text-xs text-red-700 dark:text-red-300">{receipt.result.error}</p>}
        {receipt.result && <SubmissionResourceUsage resourceUsage={receipt.result.resourceUsage} />}
      </section>}
    </div>
  </details>;
}
