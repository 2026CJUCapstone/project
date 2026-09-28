import { useMemo, useState } from 'react';
import type { SSAGraph, SourceRange } from '../services/compilerApi';
import { buildValueFlow, type ValueFlowEntry } from '../services/valueFlow';

export function ValueFlowExplorer({ graph, selected, onSelect, navigate, canNavigate = true }: {
  graph: SSAGraph;
  selected: ValueFlowEntry | undefined;
  onSelect: (functionId: string, value: string) => void;
  navigate: (range: SourceRange) => void;
  canNavigate?: boolean;
}) {
  const [query, setQuery] = useState('');
  const entries = useMemo(() => buildValueFlow(graph), [graph]);
  const matches = entries.filter(entry => `${entry.functionId} ${entry.label}`.toLowerCase().includes(query.trim().toLowerCase()));
  const incomplete = graph.blocks.some(block => block.instructionDetails?.some(detail => detail.complete === false));
  return <section aria-label="변수 흐름 추적" className="shrink-0 space-y-2 border-b border-slate-200 p-3 text-xs dark:border-neutral-700">
    <p>SSA 값을 선택하면 정의와 사용을 강조합니다. 보라색 점선은 값의 전달 관계이며 실행 순서가 아닙니다. 같은 블록 안의 연결은 명령 강조로 표시합니다. 연결선은 최대 300개입니다.</p>
    {!entries.length ? <p role="status">이 결과에는 구조화된 값 정보가 없습니다. 새 컴파일러로 다시 컴파일해야 합니다.</p> : <>
      <input aria-label="SSA 값 검색" placeholder="함수 또는 값 검색 (예: r1)" value={query} onChange={event => setQuery(event.target.value)} className="w-full rounded border border-slate-300 bg-transparent p-2 dark:border-neutral-600" />
      <div className="flex max-h-20 flex-wrap gap-1 overflow-auto">
        {matches.slice(0, 100).map(entry => <button key={entry.key} aria-pressed={selected?.key === entry.key} onClick={() => onSelect(entry.functionId, entry.label)} className={`rounded border px-2 py-1 ${selected?.key === entry.key ? 'border-violet-500 bg-violet-600 text-white' : 'border-slate-300 dark:border-neutral-600'}`}>{entry.functionId} · {entry.label}</button>)}
        {matches.length > 100 && <span>앞 100개 표시 · 검색으로 범위를 좁혀주세요.</span>}
      </div>
    </>}
    {incomplete && <p className="text-amber-600 dark:text-amber-300">일부 명령의 사용 정보가 불완전합니다. 표시된 연결만 확인할 수 있습니다.</p>}
    {selected && <div className="max-h-36 space-y-2 overflow-auto">
      <p className="font-semibold">{selected.functionId} · {selected.label} — 정의 {selected.definitions.length}곳 / 사용 {selected.uses.length}곳</p>
      {!selected.definitions.length && <p>이 출력 안에는 정의가 없습니다. 함수 인자 등 외부에서 들어온 값일 수 있습니다.</p>}
      {selected.definitions.length > 1 && <p>정의가 여러 곳입니다. 하나의 정의로 단정하지 않습니다.</p>}
      {([['정의', selected.definitions], ['사용', selected.uses]] as const).map(([label, locations]) => <div key={label} className="flex flex-wrap gap-1">
        {locations.map((location, index) => {
          const block = graph.blocks.find(item => item.id === location.blockId);
          const range = block?.instructionSourceRanges?.[location.index]?.[0];
          return <button key={`${location.instructionId}:${index}`} disabled={!range || !canNavigate} onClick={() => range && canNavigate && navigate(range)} title={block?.instructions[location.index]} className="max-w-full truncate rounded bg-slate-100 px-2 py-1 text-left disabled:opacity-50 dark:bg-neutral-800">{label} · {block?.label ?? location.blockId} · {location.index + 1}번 명령</button>;
        })}
      </div>)}
    </div>}
  </section>;
}
