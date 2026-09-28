import { useId, useState } from 'react';
import { JUDGE_POLICY_LANGUAGES, parseImportedJudgePolicy, type JudgePolicy, type JudgePolicyLanguage, type JudgePolicyStageLimits } from '../services/judgePolicyTypes';

const LANGUAGE_LABELS: Record<JudgePolicyLanguage, string> = {
  bpp: 'B++',
  c: 'C',
  cpp: 'C++',
  python: 'Python',
  java: 'Java',
  javascript: 'JavaScript',
};

export interface JudgePolicyEditorProps {
  /** Existing policy remains intact unless a valid imported replacement is accepted. */
  policy?: JudgePolicy | null;
  onReplace: (policy: JudgePolicy) => void;
}

function seconds(milliseconds: number): string {
  return `${(milliseconds / 1000).toLocaleString('ko-KR', { maximumFractionDigits: 3 })}초`;
}

function bytes(value: number): string {
  if (value % 1024 ** 3 === 0) return `${value / 1024 ** 3} GiB`;
  if (value % 1024 ** 2 === 0) return `${value / 1024 ** 2} MiB`;
  if (value % 1024 === 0) return `${value / 1024} KiB`;
  return `${value.toLocaleString('ko-KR')} B`;
}

function StageSummary({ stage }: { stage: JudgePolicyStageLimits }) {
  return <span className="text-xs text-slate-600 dark:text-slate-300">CPU {seconds(stage.cpuMs)} · Wall {seconds(stage.wallMs)} · 메모리 {bytes(stage.memoryBytes)}</span>;
}

export function JudgePolicyEditor({ policy = null, onReplace }: JudgePolicyEditorProps) {
  const inputId = useId();
  const headingId = useId();
  const [rawJson, setRawJson] = useState('');
  const [validationError, setValidationError] = useState('');

  const importReplacement = () => {
    try {
      const parsed = parseImportedJudgePolicy(rawJson);
      onReplace(parsed);
      setValidationError('');
      setRawJson('');
    } catch (error) {
      setValidationError(error instanceof Error ? error.message : '정책을 확인하지 못했습니다.');
    }
  };

  const profileLanguages = JUDGE_POLICY_LANGUAGES.filter((language) => policy?.profiles[language]);
  const evidenceCount = policy ? Object.keys(policy.evidence ?? {}).length : 0;

  return (
    <section aria-labelledby={headingId} className="min-w-0 space-y-3 rounded-lg border border-slate-300 bg-slate-50 p-4 text-slate-900 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100">
      <div>
        <h3 id={headingId} className="font-semibold">채점 정책 가져오기·검토</h3>
        <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">오프라인 측정 결과의 원본 JSON만 가져올 수 있습니다. 이 화면은 제한값이나 측정 증거를 만들거나 검증 상태를 변경하지 않습니다.</p>
      </div>

      <label className="block text-sm font-medium" htmlFor={inputId}>정책 JSON 가져오기</label>
      <textarea
        id={inputId}
        aria-label="정책 JSON 가져오기"
        value={rawJson}
        onChange={(event) => setRawJson(event.target.value)}
        placeholder="오프라인 측정 워크플로에서 생성한 JudgePolicy JSON"
        rows={7}
        spellCheck={false}
        className="w-full rounded border border-slate-300 bg-white p-3 font-mono text-xs text-slate-900 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
      />
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={importReplacement} className="rounded bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700">정책 JSON 확인 후 교체</button>
        <p className="text-xs text-slate-600 dark:text-slate-300">가져오기가 성공할 때만 현재 정책을 교체합니다. 비워 둔 상태나 null은 기존 정책을 지우지 않습니다.</p>
      </div>
      {validationError && <p role="alert" className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-200">{validationError}</p>}

      {!policy ? (
        <p role="status" className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200">가져온 정책이 없습니다. 대회 초안은 정책 없이 저장할 수 있지만, 새 문제의 공개·일반 문제 등록에는 측정 증거가 있는 검증 정책이 필요합니다.</p>
      ) : (
        <div className="space-y-3 rounded border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-900">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h4 className="font-semibold">정책 {policy.policyId} · 개정 {policy.revision.toLocaleString('ko-KR')}</h4>
              <p className="mt-0.5 break-all text-xs text-slate-600 dark:text-slate-300">테스트 fingerprint {policy.testSuiteHash} · 측정 증거 {evidenceCount}/{profileLanguages.length}개</p>
            </div>
            <span className={`rounded-full border px-2 py-1 text-xs font-semibold ${policy.reviewStatus === 'verified' ? 'border-emerald-400 bg-emerald-50 text-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-200' : 'border-amber-400 bg-amber-50 text-amber-900 dark:bg-amber-950/30 dark:text-amber-200'}`}>
              {policy.reviewStatus === 'verified' ? '검증됨' : '초안'}
            </span>
          </div>
          {policy.reviewStatus === 'draft' && <p role="status" className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200">초안 정책은 대회 초안에만 저장할 수 있으며, 공개 또는 새 일반 문제 등록 기준으로 사용할 수 없습니다.</p>}

          <div className="max-w-full overflow-x-auto rounded border border-slate-200 dark:border-slate-700">
            <table className="min-w-[650px] w-full text-left text-sm" aria-label="가져온 언어별 채점 정책">
              <thead className="bg-slate-100 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300"><tr><th className="px-3 py-2">언어</th><th className="px-3 py-2">런타임</th><th className="px-3 py-2">실행 제한</th><th className="px-3 py-2">컴파일 제한</th><th className="px-3 py-2">측정 증거</th></tr></thead>
              <tbody>
                {profileLanguages.map((language) => {
                  const profile = policy.profiles[language]!;
                  const evidence = policy.evidence?.[language];
                  return <tr key={language} className="border-t border-slate-200 align-top dark:border-slate-700">
                    <th scope="row" className="whitespace-nowrap px-3 py-2 font-medium">{LANGUAGE_LABELS[language]}</th>
                    <td className="px-3 py-2"><div>{profile.runtimeVersion}</div><div className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{profile.runtimeId} · {profile.workerClass}</div></td>
                    <td className="px-3 py-2"><StageSummary stage={profile.run} /></td>
                    <td className="px-3 py-2"><StageSummary stage={profile.compile} /></td>
                    <td className="px-3 py-2 text-xs">{evidence ? <span>{evidence.repetitions.toLocaleString('ko-KR')}회 · {evidence.caseCount.toLocaleString('ko-KR')}케이스</span> : <span className="text-amber-700 dark:text-amber-300">없음</span>}</td>
                  </tr>;
                })}
              </tbody>
            </table>
          </div>
          <details className="rounded border border-slate-200 p-3 text-xs dark:border-slate-700">
            <summary className="cursor-pointer font-semibold">가져온 원본 JSON 검토</summary>
            <pre className="mt-3 max-w-full overflow-x-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(policy, null, 2)}</pre>
          </details>
        </div>
      )}
    </section>
  );
}
