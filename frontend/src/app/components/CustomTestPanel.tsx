import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { getAuthOwner, subscribeAuthIdentity } from '../services/authIdentity';
import { executeCode, type ExecuteResponse } from '../services/compilerApi';
import { compareOutput, type OutputComparisonMode, type OutputComparisonResult } from '../services/outputComparison';
import { useCompilerStore } from '../store/compilerStore';

const MAX_STDIN_BYTES = 65_536;

export interface CustomTestSample {
  input: string;
  expectedOutput: string;
}

interface CustomTestPanelProps {
  samples?: CustomTestSample[];
  scopeKey?: string;
}

interface CustomTestResult {
  execution: ExecuteResponse;
  comparison: OutputComparisonResult | null;
  comparisonEnabled: boolean;
  fingerprint: string;
}

function byteLength(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function formatExecutionTime(milliseconds: number): string {
  return milliseconds >= 1000
    ? `${(milliseconds / 1000).toFixed(2)}초`
    : `${Math.round(milliseconds)}ms`;
}

export function CustomTestPanel({ samples = [], scopeKey = 'main' }: CustomTestPanelProps) {
  const identity = useSyncExternalStore(subscribeAuthIdentity,
    () => `${getAuthOwner()}:${localStorage.getItem('authToken') ?? ''}`, () => 'guest:');
  return <OwnedCustomTestPanel key={identity + ':' + scopeKey} samples={samples} scopeKey={scopeKey} owner={getAuthOwner()} />;
}

function OwnedCustomTestPanel({ samples = [], scopeKey = 'main', owner }: CustomTestPanelProps & { owner: string }) {
  const code = useCompilerStore((state) => state.code);
  const language = useCompilerStore((state) => state.language);
  const codeStorageOwner = useCompilerStore((state) => state.codeStorageOwner);
  const isCompiling = useCompilerStore((state) => state.isCompiling);
  const isStoreRunning = useCompilerStore((state) => state.isRunning);
  const isEditorReady = useCompilerStore((state) => state.isEditorReady);

  const [input, setInput] = useState('');
  const [expectedOutput, setExpectedOutput] = useState('');
  const [comparisonEnabled, setComparisonEnabled] = useState(false);
  const [comparisonMode, setComparisonMode] = useState<OutputComparisonMode>('trim-lines');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [result, setResult] = useState<CustomTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const requestControllerRef = useRef<AbortController | null>(null);
  const requestSequenceRef = useRef(0);
  const submittingRef = useRef(false);
  const mountedRef = useRef(true);

  const normalizedScopeKey = scopeKey.trim() || 'main';
  const identityScopeKey = `${codeStorageOwner}\u0000${normalizedScopeKey}`;
  const previousIdentityScopeKeyRef = useRef(identityScopeKey);
  const inputBytes = byteLength(input);
  const inputTooLarge = inputBytes > MAX_STDIN_BYTES;
  const fingerprint = useMemo(() => JSON.stringify({
    code,
    language,
    codeStorageOwner,
    scopeKey: normalizedScopeKey,
    input,
    expectedOutput,
    comparisonEnabled,
    comparisonMode,
  }), [code, codeStorageOwner, comparisonEnabled, comparisonMode, expectedOutput, input, language, normalizedScopeKey]);
  const latestFingerprintRef = useRef(fingerprint);
  latestFingerprintRef.current = fingerprint;

  const clearDisplayedResult = () => {
    setResult(null);
    setError(null);
  };

  useEffect(() => {
    mountedRef.current = true;
    const unsubscribe = subscribeAuthIdentity(() => {
      requestSequenceRef.current += 1;
      requestControllerRef.current?.abort();
    });
    return () => {
      unsubscribe();
      mountedRef.current = false;
      requestSequenceRef.current += 1;
      requestControllerRef.current?.abort();
      requestControllerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const identityOrScopeChanged = previousIdentityScopeKeyRef.current !== identityScopeKey;
    previousIdentityScopeKeyRef.current = identityScopeKey;
    requestSequenceRef.current += 1;
    requestControllerRef.current?.abort();
    requestControllerRef.current = null;
    submittingRef.current = false;
    setIsSubmitting(false);
    clearDisplayedResult();
    if (identityOrScopeChanged) {
      setInput('');
      setExpectedOutput('');
      setComparisonEnabled(false);
    }
  }, [codeStorageOwner, identityScopeKey, language, normalizedScopeKey]);

  useEffect(() => {
    setResult((previous) => previous?.fingerprint === fingerprint ? previous : null);
  }, [fingerprint]);

  const runDisabled = isSubmitting
    || owner !== codeStorageOwner
    || isCompiling
    || isStoreRunning
    || !isEditorReady
    || !code.trim()
    || inputTooLarge;

  const runTest = async () => {
    if (submittingRef.current || runDisabled || getAuthOwner() !== owner) return;

    const requestId = requestSequenceRef.current + 1;
    requestSequenceRef.current = requestId;
    const controller = new AbortController();
    const requestFingerprint = fingerprint;
    requestControllerRef.current = controller;
    submittingRef.current = true;
    setIsSubmitting(true);
    setResult(null);
    setError(null);

    try {
      const execution = await executeCode(
        { code, language, input },
        { signal: controller.signal },
      );

      const requestIsCurrent = requestSequenceRef.current === requestId
        && latestFingerprintRef.current === requestFingerprint
        && !controller.signal.aborted;
      if (!mountedRef.current || !requestIsCurrent) return;

      setResult({
        execution,
        comparison: comparisonEnabled && execution.exitCode === 0
          ? compareOutput(execution.stdout, expectedOutput, comparisonMode)
          : null,
        comparisonEnabled,
        fingerprint: requestFingerprint,
      });
    } catch (runError) {
      const requestIsCurrent = requestSequenceRef.current === requestId
        && latestFingerprintRef.current === requestFingerprint
        && !controller.signal.aborted;
      if (mountedRef.current && requestIsCurrent) {
        setError(runError instanceof Error ? runError.message : '테스트 실행에 실패했습니다.');
      }
    } finally {
      if (requestControllerRef.current === controller) {
        requestControllerRef.current = null;
      }
      if (requestSequenceRef.current === requestId) {
        submittingRef.current = false;
        if (mountedRef.current) setIsSubmitting(false);
      }
    }
  };

  const visibleResult = result?.fingerprint === fingerprint ? result : null;

  return (
    <section aria-labelledby="custom-test-heading" className="space-y-4 rounded-lg border border-slate-700 bg-slate-950 p-4 text-slate-100">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 id="custom-test-heading" className="text-sm font-semibold">사용자 테스트</h2>
          <p className="text-xs text-slate-400">공식 채점과 무관하게 현재 코드의 입출력을 확인합니다.</p>
        </div>
        {samples.length > 0 && (
          <div className="flex flex-wrap gap-2" aria-label="예제 입력 적용">
            {samples.map((sample, index) => (
              <button
                key={`${index}:${sample.input}:${sample.expectedOutput}`}
                type="button"
                onClick={() => {
                  setInput(sample.input);
                  setExpectedOutput(sample.expectedOutput);
                  setComparisonEnabled(true);
                  clearDisplayedResult();
                }}
                className="rounded border border-slate-600 px-2 py-1 text-xs text-slate-200 hover:border-blue-400 hover:text-blue-200"
              >
                예제 {index + 1} 적용
              </button>
            ))}
          </div>
        )}
      </div>

      <div>
        <label htmlFor="custom-test-input" className="mb-1 block text-xs font-medium text-slate-200">표준 입력</label>
        <textarea
          id="custom-test-input"
          value={input}
          onChange={(event) => {
            setInput(event.target.value);
            clearDisplayedResult();
          }}
          rows={5}
          spellCheck={false}
          className="w-full rounded border border-slate-600 bg-slate-900 p-2 font-mono text-xs text-slate-100 outline-none focus:border-blue-400"
          placeholder="프로그램에 전달할 표준 입력을 작성하세요"
        />
        <p className={`mt-1 text-xs ${inputTooLarge ? 'text-red-300' : 'text-slate-400'}`}>
          {inputBytes.toLocaleString()} / {MAX_STDIN_BYTES.toLocaleString()} bytes
        </p>
        {inputTooLarge && <p role="alert" className="mt-1 text-xs text-red-300">표준 입력은 65,536 bytes를 초과할 수 없습니다.</p>}
      </div>

      <div className="space-y-3 rounded border border-slate-800 bg-slate-900/60 p-3">
        <label className="flex items-center gap-2 text-sm text-slate-200">
          <input
            type="checkbox"
            checked={comparisonEnabled}
            onChange={(event) => {
              setComparisonEnabled(event.target.checked);
              clearDisplayedResult();
            }}
          />
          예상 출력 비교
        </label>
        {comparisonEnabled && (
          <>
            <div>
              <label htmlFor="custom-test-expected-output" className="mb-1 block text-xs font-medium text-slate-200">예상 출력</label>
              <textarea
                id="custom-test-expected-output"
                value={expectedOutput}
                onChange={(event) => {
                  setExpectedOutput(event.target.value);
                  clearDisplayedResult();
                }}
                rows={5}
                spellCheck={false}
                className="w-full rounded border border-slate-600 bg-slate-950 p-2 font-mono text-xs text-slate-100 outline-none focus:border-blue-400"
              />
            </div>
            <label className="block text-xs text-slate-300">
              비교 방식
              <select
                value={comparisonMode}
                onChange={(event) => {
                  setComparisonMode(event.target.value as OutputComparisonMode);
                  clearDisplayedResult();
                }}
                className="mt-1 block rounded border border-slate-600 bg-slate-950 px-2 py-1 text-slate-100"
              >
                <option value="trim-lines">줄 끝 공백 무시</option>
                <option value="exact">정확히 비교</option>
              </select>
            </label>
          </>
        )}
      </div>

      <button
        type="button"
        onClick={() => { void runTest(); }}
        disabled={runDisabled}
        className="rounded bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
      >
        {isSubmitting ? '대기 중...' : '테스트 실행'}
      </button>
      {!isEditorReady && <p className="text-xs text-slate-400">에디터 준비가 끝난 뒤 테스트를 실행할 수 있습니다.</p>}
      {isCompiling && <p className="text-xs text-slate-400">컴파일이 끝난 뒤 테스트를 실행할 수 있습니다.</p>}
      {isStoreRunning && <p className="text-xs text-slate-400">다른 실행이 끝난 뒤 테스트를 실행할 수 있습니다.</p>}
      {!code.trim() && <p className="text-xs text-slate-400">실행할 코드가 없습니다.</p>}
      {error && <p role="alert" className="text-sm text-red-300">{error}</p>}

      {visibleResult && (
        <div data-testid="custom-test-result" className="space-y-3 rounded border border-slate-700 bg-slate-900 p-3 text-sm">
          <dl className="grid gap-2 text-xs sm:grid-cols-2">
            <div><dt className="text-slate-400">종료 코드</dt><dd data-testid="custom-test-exit-code" className="font-mono text-slate-100">{visibleResult.execution.exitCode}</dd></div>
            <div><dt className="text-slate-400">실행 시간</dt><dd data-testid="custom-test-execution-time" className="font-mono text-slate-100">{formatExecutionTime(visibleResult.execution.executionTime)}</dd></div>
          </dl>
          <div>
            <p className="mb-1 text-xs text-slate-400">실제 stdout</p>
            <pre data-testid="custom-test-stdout" className="min-h-8 overflow-auto rounded bg-slate-950 p-2 text-xs text-slate-100">{visibleResult.execution.stdout || '(없음)'}</pre>
          </div>
          <div>
            <p className="mb-1 text-xs text-slate-400">stderr</p>
            <pre data-testid="custom-test-stderr" className="min-h-8 overflow-auto rounded bg-slate-950 p-2 text-xs text-red-200">{visibleResult.execution.stderr || '(없음)'}</pre>
          </div>
          {visibleResult.comparisonEnabled && (
            visibleResult.comparison ? (
              <div className={`rounded border p-2 text-xs ${visibleResult.comparison.matches ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200' : 'border-amber-500/40 bg-amber-500/10 text-amber-100'}`}>
                <p className="font-semibold">사용자 테스트 비교: {visibleResult.comparison.matches ? '출력 일치' : '출력 불일치'}</p>
                {!visibleResult.comparison.matches && visibleResult.comparison.firstDifferentLine !== null && (
                  <p className="mt-1 break-words">
                    첫 차이: {visibleResult.comparison.firstDifferentLine}번째 줄 (실제: {visibleResult.comparison.actualLine ?? '(없음)'}, 예상: {visibleResult.comparison.expectedLine ?? '(없음)'})
                  </p>
                )}
              </div>
            ) : (
              <p className="rounded border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-100">사용자 테스트 비교: 실행이 정상 종료되지 않아 출력 비교를 건너뛰었습니다.</p>
            )
          )}
        </div>
      )}
    </section>
  );
}
