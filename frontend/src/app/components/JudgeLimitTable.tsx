import { JUDGE_POLICY_LANGUAGES, type JudgePolicyLanguage, type JudgePolicyStageLimits, type PublicJudgeLimits } from '../services/judgePolicyTypes';

const LANGUAGE_LABELS: Record<JudgePolicyLanguage, string> = {
  bpp: 'B++',
  c: 'C',
  cpp: 'C++',
  python: 'Python',
  java: 'Java',
  javascript: 'JavaScript',
};

export interface JudgeLimitTableProps {
  policy: PublicJudgeLimits | null;
  selectedLanguage: string;
  legacy?: boolean;
  compatibility?: boolean;
}

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function safeNonNegativeInteger(value: unknown): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null;
}

function safeText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function profileFor(policy: PublicJudgeLimits, language: string): UnknownRecord | null {
  if (!isRecord(policy.languages) || !Object.prototype.hasOwnProperty.call(policy.languages, language)) return null;
  const profile = (policy.languages as UnknownRecord)[language];
  return isRecord(profile) ? profile : null;
}

function stageFor(profile: UnknownRecord | null, stage: 'compile' | 'run'): UnknownRecord | null {
  if (!profile) return null;
  const value = profile[stage];
  return isRecord(value) ? value : null;
}

function millisecondsAsSeconds(value: unknown): string {
  const milliseconds = safeNonNegativeInteger(value);
  if (milliseconds === null) return '—';
  return `${(milliseconds / 1000).toLocaleString('ko-KR', { maximumFractionDigits: 3 })}초`;
}

function bytesAsBinaryUnit(value: unknown): string {
  const bytes = safeNonNegativeInteger(value);
  if (bytes === null) return '—';
  if (bytes === 0) return '0 B';

  const units = [
    { size: 1024 ** 3, label: 'GiB' },
    { size: 1024 ** 2, label: 'MiB' },
    { size: 1024, label: 'KiB' },
  ];
  const exactUnit = units.find(({ size }) => bytes % size === 0);
  return exactUnit
    ? `${(bytes / exactUnit.size).toLocaleString('ko-KR')} ${exactUnit.label}`
    : `${bytes.toLocaleString('ko-KR')} B`;
}

function runtimeVersion(profile: UnknownRecord | null): string {
  return safeText(profile?.runtimeVersion) ?? '—';
}

function stageValue(stage: UnknownRecord | null, key: keyof JudgePolicyStageLimits): unknown {
  return stage?.[key];
}

function languageLabel(language: string): string {
  return LANGUAGE_LABELS[language as JudgePolicyLanguage] ?? language;
}

function LimitCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-900">
      <dt className="text-xs font-medium text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="mt-1 font-mono text-sm font-semibold text-slate-900 dark:text-slate-100">{value}</dd>
    </div>
  );
}

function StageDetails({ title, stage }: { title: string; stage: UnknownRecord | null }) {
  return (
    <section aria-label={`${title} 제한`} className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
      <h4 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{title}</h4>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
        <div><dt className="text-slate-500 dark:text-slate-400">CPU 시간</dt><dd>{millisecondsAsSeconds(stageValue(stage, 'cpuMs'))}</dd></div>
        <div><dt className="text-slate-500 dark:text-slate-400">Wall 시간</dt><dd>{millisecondsAsSeconds(stageValue(stage, 'wallMs'))}</dd></div>
        <div><dt className="text-slate-500 dark:text-slate-400">메모리</dt><dd>{bytesAsBinaryUnit(stageValue(stage, 'memoryBytes'))}</dd></div>
        <div><dt className="text-slate-500 dark:text-slate-400">출력</dt><dd>{bytesAsBinaryUnit(stageValue(stage, 'outputBytes'))}</dd></div>
        <div><dt className="text-slate-500 dark:text-slate-400">PID</dt><dd>{safeNonNegativeInteger(stageValue(stage, 'pids'))?.toLocaleString('ko-KR') ?? '—'}</dd></div>
        <div><dt className="text-slate-500 dark:text-slate-400">임시 저장소</dt><dd>{bytesAsBinaryUnit(stageValue(stage, 'tmpBytes'))}</dd></div>
      </dl>
    </section>
  );
}

export function JudgeLimitTable({ policy, selectedLanguage, legacy = false, compatibility = false }: JudgeLimitTableProps) {
  const selectedProfile = policy ? profileFor(policy, selectedLanguage) : null;
  const selectedRun = stageFor(selectedProfile, 'run');
  const selectedCompile = stageFor(selectedProfile, 'compile');
  const selectedSupported = selectedProfile !== null;

  return (
    <section aria-labelledby="judge-limits-heading" className="max-w-full rounded-lg border border-slate-200 bg-slate-50 p-4 text-slate-800 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 id="judge-limits-heading" className="text-base font-bold">채점 제한</h3>
          {policy && (
            <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
              정책 {safeText(policy.policyId) ?? '—'} · 개정 {safeNonNegativeInteger(policy.revision)?.toLocaleString('ko-KR') ?? '—'}
            </p>
          )}
        </div>
        {legacy && <span className="rounded-full border border-amber-400/50 bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-900 dark:bg-amber-950/50 dark:text-amber-200">기존 문제 정책</span>}
        {compatibility && <span className="rounded-full border border-blue-400/50 bg-blue-100 px-2 py-1 text-xs font-semibold text-blue-900 dark:bg-blue-950/50 dark:text-blue-200">기존 문제 호환 정책</span>}
      </div>

      {legacy && !policy && (
        <p role="status" className="mt-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200">
          기존 문제에는 확정 제한이 저장되지 않았습니다. 현재 공통 제한을 추정해 표시하지 않습니다.
        </p>
      )}

      {!policy && !legacy && (
        <p role="status" className="mt-3 rounded-md border border-slate-300 bg-white p-3 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
          이 문제에는 확정된 언어별 제한이 아직 없습니다.
        </p>
      )}

      {policy && (
        <div className="mt-3 space-y-3">
          {policy.reviewStatus === 'draft' && (
            <p role="alert" className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200">
              초안 정책입니다. 실제 측정과 검증이 끝나기 전에는 제출 기준으로 사용하면 안 됩니다.
            </p>
          )}
          {policy.reviewStatus === 'compatibility' && (
            <p role="status" className="rounded-md border border-blue-300 bg-blue-50 p-3 text-sm text-blue-900 dark:border-blue-800 dark:bg-blue-950/30 dark:text-blue-200">
              기존 문제에 적용되는 고정 호환 제한입니다. 언어별 시간·메모리 차이를 실제 채점에도 동일하게 적용합니다.
            </p>
          )}

          {!selectedSupported ? (
            <p role="status" className="rounded-md border border-slate-300 bg-white p-3 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
              선택한 언어({languageLabel(selectedLanguage)})는 이 정책에서 지원하지 않습니다.
            </p>
          ) : (
            <>
              <div>
                <h4 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{languageLabel(selectedLanguage)} 실행 기준</h4>
                <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">런타임 {runtimeVersion(selectedProfile)}</p>
              </div>
              <dl className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                <LimitCard label="CPU 시간" value={millisecondsAsSeconds(stageValue(selectedRun, 'cpuMs'))} />
                <LimitCard label="Wall 시간" value={millisecondsAsSeconds(stageValue(selectedRun, 'wallMs'))} />
                <LimitCard label="메모리" value={bytesAsBinaryUnit(stageValue(selectedRun, 'memoryBytes'))} />
              </dl>
              <details className="rounded-md border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-900">
                <summary className="cursor-pointer text-sm font-semibold text-slate-700 dark:text-slate-200">컴파일·출력·PID·임시 저장소 제한 자세히 보기</summary>
                <div className="mt-3 grid gap-3 lg:grid-cols-2">
                  <StageDetails title="실행" stage={selectedRun} />
                  <StageDetails title="컴파일" stage={selectedCompile} />
                </div>
              </details>
            </>
          )}

          <div className="max-w-full overflow-x-auto rounded-md border border-slate-200 dark:border-slate-700">
            <table className="min-w-[620px] w-full text-left text-sm" aria-label="언어별 채점 제한">
              <caption className="sr-only">정책에 포함된 언어별 런타임과 실행 제한</caption>
              <thead className="bg-slate-100 text-xs text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                <tr>
                  <th scope="col" className="px-3 py-2 font-semibold">언어</th>
                  <th scope="col" className="px-3 py-2 font-semibold">런타임</th>
                  <th scope="col" className="px-3 py-2 font-semibold">실행 CPU</th>
                  <th scope="col" className="px-3 py-2 font-semibold">Wall</th>
                  <th scope="col" className="px-3 py-2 font-semibold">메모리</th>
                </tr>
              </thead>
              <tbody>
                {JUDGE_POLICY_LANGUAGES.map((language) => {
                  const profile = profileFor(policy, language);
                  const run = stageFor(profile, 'run');
                  const supported = profile !== null;
                  return (
                    <tr key={language} className="border-t border-slate-200 dark:border-slate-700">
                      <th scope="row" className="whitespace-nowrap px-3 py-2 font-medium">{LANGUAGE_LABELS[language]}</th>
                      <td className="max-w-56 truncate px-3 py-2" title={runtimeVersion(profile)}>{supported ? runtimeVersion(profile) : '미지원'}</td>
                      <td className="whitespace-nowrap px-3 py-2">{supported ? millisecondsAsSeconds(stageValue(run, 'cpuMs')) : '—'}</td>
                      <td className="whitespace-nowrap px-3 py-2">{supported ? millisecondsAsSeconds(stageValue(run, 'wallMs')) : '—'}</td>
                      <td className="whitespace-nowrap px-3 py-2">{supported ? bytesAsBinaryUnit(stageValue(run, 'memoryBytes')) : '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
