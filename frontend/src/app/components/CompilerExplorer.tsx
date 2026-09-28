import { useEffect, useMemo, useRef, useState } from 'react';
import { compileCode, type CompileResponse } from '../services/compilerApi';
import { compareLines, pipelineItems, tracePipeline, type PipelineItem, type PipelineStage } from '../services/pipelineLineage';
import type { SourceSelectionRange } from '../store/compilerStore';
import { useCompilerStore } from '../store/compilerStore';
import { sameSource } from '../services/sourceMapping';

const stages: PipelineStage[] = ['AST', 'SSA', 'IR', 'ASM'];
const button = 'rounded border border-slate-300 px-2 py-1 text-xs disabled:opacity-40 dark:border-neutral-600';
const optimizationReasons: Record<string, string> = {
  constantOperands: '상수로 확정된 피연산자 대체',
  constantBranches: '상수 조건 분기 단순화',
  commonExpressions: '중복 계산 재사용',
  unusedCopies: '불필요한 복사 제거',
  deadStores: '불필요한 저장 제거',
  unreachableBlocks: '도달할 수 없는 블록 제거',
  simplifiedPhi: 'φ 노드 단순화',
  algebraicSimplifications: '대수식 단순화',
};

export function PipelineExplorer({ result, selection, navigate, setTab }: {
  result: CompileResponse; selection: SourceSelectionRange | null;
  navigate: (range: SourceSelectionRange) => void; setTab: (stage: PipelineStage) => void;
}) {
  const items = useMemo(() => pipelineItems(result), [result]);
  const [seedState, setSeedState] = useState<{ id: string; range: string } | null>(null);
  const rangeKey = (range: SourceSelectionRange | null) => range ? `${range.startLine}:${range.startColumn}:${range.endLine}:${range.endColumn}` : '';
  const seed = seedState?.range === rangeKey(selection) ? items.find(item => `${item.stage}:${item.id}` === seedState.id) : undefined;
  const matches = useMemo(() => tracePipeline(items, selection, seed), [items, selection, seed]);
  const choose = (item: PipelineItem) => {
    if (item.ranges[0]) navigate(item.ranges[0] as SourceSelectionRange);
    setSeedState({ id: `${item.stage}:${item.id}`, range: rangeKey(item.ranges[0] as SourceSelectionRange ?? selection) });
    setTab(item.stage);
  };
  return <section aria-label="단계별 변환 연결" className="max-h-64 overflow-auto border-b border-slate-200 p-3 text-xs dark:border-neutral-700">
    <p className="mb-2 text-slate-500">코드 범위를 선택하면 각 단계의 관련 항목이 표시됩니다. 항목을 누르면 해당 단계로 이동합니다.</p>
    {stages.map(stage => {
      const related = matches.filter(item => item.stage === stage);
      return <div key={stage} className="mb-2"><strong>{stage} · {related.length}</strong>
        {!related.length ? <span className="ml-2 text-slate-500">연결 정보 없음</span> : related.slice(0, 40).map(item => <button key={item.id} onClick={() => choose(item)} className="mt-1 block w-full rounded bg-slate-100 p-2 text-left dark:bg-neutral-800">
          <span className="mr-2 text-[10px] text-slate-500">{item.relation === 'id' ? '컴파일러 ID 연결' : '같은 소스 범위'}</span><code className="break-all">{item.label}</code>
        </button>)}
        {related.length > 40 && <p className="text-slate-500">처음 40개 표시 · 범위를 좁혀 주세요.</p>}
      </div>;
    })}
  </section>;
}

export function OptimizationCompare({ source, baseline, current, scope, owner }: {
  source: string; baseline: CompileResponse; current: boolean; scope: string; owner: string;
}) {
  const [pair, setPair] = useState<{ before: CompileResponse; after: CompileResponse } | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [stage, setStage] = useState<PipelineStage>('IR');
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => { controller.current?.abort(); setPair(null); setError(''); setPending(false); }, [source, scope, owner, current, baseline]);
  const start = async () => {
    if (pending || !current || !source.trim()) return;
    const abort = new AbortController(); controller.current = abort;
    setPending(true); setError(''); setPair(null);
    const unchanged = () => {
      const now = useCompilerStore.getState();
      return !abort.signal.aborted && sameSource(source, now.code) && now.codeStorageOwner === owner && now.codeStorageScope === scope;
    };
    try {
      const problemId = scope.startsWith('problem:') ? scope.slice(8) : undefined;
      const before = baseline.metadata?.optimizationLevel === 0 ? baseline : await compileCode({ code: source, language: 'bpp', problemId, options: { optimize: false, target: 'all' } }, { signal: abort.signal });
      if (!unchanged()) return;
      if (!before.success) throw new Error('최적화 전 컴파일이 실패했습니다.');
      const after = await compileCode({ code: source, language: 'bpp', problemId, options: { optimize: true, target: 'all' } }, { signal: abort.signal });
      if (!unchanged()) return;
      if (!after.success) throw new Error('최적화 후 컴파일이 실패했습니다.');
      setPair({ before, after });
    } catch (reason) {
      if (!abort.signal.aborted) setError(reason instanceof Error ? reason.message : '비교를 가져오지 못했습니다.');
    } finally { if (controller.current === abort) setPending(false); }
  };
  const comparison = useMemo(() => {
    if (!pair) return null;
    const before = pipelineItems(pair.before).filter(item => item.stage === stage).map(item => item.label);
    const after = pipelineItems(pair.after).filter(item => item.stage === stage).map(item => item.label);
    return { before, after, rows: compareLines(before.slice(0, 3000), after.slice(0, 3000)) };
  }, [pair, stage]);
  const optimizationReports = useMemo(() => {
    if (!pair) return null;
    const summaries = pair.after.ssa?.optimizationSummaries;
    if (!summaries?.length) return [];
    return summaries
      .filter(summary => summary.scope === 'function' && summary.evidence === 'compiler-counters-v1')
      .map(summary => ({
        ...summary,
        reasons: Object.entries(optimizationReasons)
          .map(([name, label]) => ({ label, count: summary.counters[name] }))
          .filter((reason): reason is { label: string; count: number } => typeof reason.count === 'number' && Number.isFinite(reason.count) && reason.count > 0),
      }));
  }, [pair]);
  return <section aria-label="최적화 전후 비교" className="max-h-80 overflow-auto border-b border-slate-200 p-3 text-xs dark:border-neutral-700">
    <div className="flex flex-wrap items-center gap-2">
      <button className={button} disabled={pending || !current} onClick={start}>{pending ? '최적화 결과 생성 중…' : '최적화 전후 비교하기'}</button>
      {pending && <button className={button} onClick={() => { controller.current?.abort(); setPending(false); }}>대기 취소</button>}
      <select aria-label="비교 단계" value={stage} onChange={event => setStage(event.target.value as PipelineStage)} className="rounded bg-slate-100 p-1 dark:bg-neutral-800">{stages.map(value => <option key={value}>{value}</option>)}</select>
    </div>
    <p className="mt-2 text-slate-500">같은 코드를 최적화 켜기·끄기로 컴파일합니다. − 제거, + 추가. 실행 속도 비교는 아닙니다.</p>
    {error && <p role="alert" className="mt-2 text-red-500">{error}</p>}
    {comparison && <>
      <p className="my-2">{comparison.before.length}개 → {comparison.after.length}개 {comparison.rows.every(row => row.kind === 'same') && '· 출력 변화 없음'}</p>
      <section aria-label="함수 단위 최적화 보고" className="mb-3 rounded border border-slate-200 p-2 dark:border-neutral-700">
        <p className="font-medium">SSA 함수 단위 컴파일러 최적화 보고</p>
        <p className="mt-1 text-slate-500">컴파일러가 SSA 변환에서 함수별로 집계한 카운터입니다. 아래 이유는 개별 diff 줄에 귀속되지 않으며, IR·ASM의 줄별 변환 이유도 아닙니다.</p>
        {optimizationReports === null ? null : optimizationReports.length === 0 ? <p className="mt-2 text-slate-500">함수 단위 최적화 근거를 제공하지 않아 이유를 추정할 수 없습니다.</p> : <ul className="mt-2 space-y-2">
          {optimizationReports.map(summary => <li key={summary.functionId} className="rounded bg-slate-50 p-2 dark:bg-neutral-800">
            <p className="font-medium">{summary.functionName} <span className="font-normal text-slate-500">· 최적화 수준 {summary.level}</span></p>
            {summary.reasons.length ? <ul className="mt-1 list-disc pl-4">{summary.reasons.map(reason => <li key={reason.label}>{reason.label} · {reason.count}회</li>)}</ul> : <p className="mt-1 text-slate-500">보고된 최적화 카운터가 없습니다.</p>}
          </li>)}
        </ul>}
      </section>
      {(!comparison.before.length || !comparison.after.length) && <p>이 단계의 출력이 없어 비교할 수 없습니다.</p>}
      {Math.max(comparison.before.length, comparison.after.length) > 3000 && <p>처음 3,000개 항목을 비교합니다.</p>}
      <pre className="overflow-auto text-[11px]">{comparison.rows.map((row, index) => <div key={index} className={row.kind === 'added' ? 'bg-green-500/10 text-green-600 dark:text-green-300' : row.kind === 'removed' ? 'bg-red-500/10 text-red-600 dark:text-red-300' : ''}>{row.kind === 'added' ? '+ ' : row.kind === 'removed' ? '− ' : '  '}{row.text}</div>)}</pre>
    </>}
  </section>;
}
