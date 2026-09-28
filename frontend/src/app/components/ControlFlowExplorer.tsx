import { useEffect, useMemo, useState } from 'react';
import type { SSAGraph } from '../services/compilerApi';
import { analyzeControlFlow } from '../services/controlFlowAnalysis';

export function ControlFlowExplorer({ graph, onHighlight }: { graph: SSAGraph; onHighlight: (ids: string[]) => void }) {
  const analysis = useMemo(() => graph.blocks.length <= 500 ? analyzeControlFlow(graph.blocks, graph.edges) : null, [graph]);
  const [path, setPath] = useState<string[]>([]);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(900);
  const current = path[path.length - 1];
  const outgoing = useMemo(() => graph.edges.filter(edge => edge.from === current), [graph, current]);
  const [mode, setMode] = useState('path');
  useEffect(() => { setPath([]); setPlaying(false); onHighlight([]); }, [graph, onHighlight]);
  useEffect(() => {
    if (!analysis || !current) { onHighlight([]); return; }
    onHighlight(mode === 'dominators' ? analysis.dominators[current] : mode === 'loop' ? [...new Set(analysis.loops.filter(loop => loop.nodes.includes(current)).flatMap(loop => loop.nodes))] : [current]);
  }, [analysis, current, mode, onHighlight]);
  useEffect(() => {
    if (!playing) return;
    // Branches pause for a user choice. A CFG cannot tell which runtime branch was taken.
    if (outgoing.length !== 1 || path.length >= 200 || path.includes(outgoing[0].to)) { setPlaying(false); return; }
    const timer = window.setTimeout(() => setPath(history => [...history, outgoing[0].to]), speed);
    return () => window.clearTimeout(timer);
  }, [playing, outgoing, path, speed]);
  if (!analysis) return <p className="p-2 text-xs">블록 500개를 넘는 그래프는 전체 분석 대신 검색과 노드 탐색을 사용해 주세요.</p>;
  const button = 'rounded border border-slate-300 px-2 py-1 disabled:opacity-40 dark:border-neutral-600';
  const names = new Map(graph.blocks.map(block => [block.id, block.label]));
  return <section aria-label="제어 흐름 탐색" className="max-h-60 shrink-0 overflow-auto border-b border-slate-200 p-3 text-xs dark:border-neutral-700">
    <p className="mb-2 text-slate-500">정적 경로 탐색 · 실제 실행 기록이 아닙니다. 분기와 반복 지점에서는 재생이 멈춥니다.</p>
    <div className="flex flex-wrap gap-2">
      <select aria-label="탐색 시작 블록" className="min-w-0 max-w-full rounded bg-slate-100 p-1 dark:bg-neutral-800" value={path[0] ?? ''} onChange={event => { setPlaying(false); setPath(event.target.value ? [event.target.value] : []); }}>
        <option value="">진입 블록 선택</option>{analysis.roots.map(id => <option key={id} value={id}>{names.get(id)}</option>)}
      </select>
      <select aria-label="그래프 강조 방식" value={mode} onChange={event => setMode(event.target.value)} className="rounded bg-slate-100 p-1 dark:bg-neutral-800"><option value="path">현재 블록</option><option value="dominators">지배 블록</option><option value="loop">자연 루프</option></select>
      <button className={button} disabled={!current || !outgoing.length || path.length >= 200} onClick={() => setPlaying(!playing)}>{playing ? '일시정지' : '경로 재생'}</button>
      <button className={button} disabled={path.length < 2} onClick={() => { setPlaying(false); setPath(history => history.slice(0, -1)); }}>이전 단계</button>
      <button className={button} onClick={() => { setPlaying(false); setPath([]); }}>초기화</button>
      <select aria-label="재생 속도" value={speed} onChange={event => setSpeed(Number(event.target.value))} className="rounded bg-slate-100 p-1 dark:bg-neutral-800"><option value={1400}>느리게</option><option value={900}>보통</option><option value={400}>빠르게</option></select>
    </div>
    <p className="mt-2">자연 루프 {analysis.loops.length}개 · 진입점에서 도달할 수 없는 블록 {analysis.unreachable.length}개</p>
    {current && <>
      <p className="mt-2 break-all">{names.get(current)} · {path.length}단계</p>
      <p className="text-slate-500">직접 지배 블록: {names.get(analysis.immediateDominators[current] ?? '') ?? '없음'} · 지배 블록은 현재 블록에 도달할 때 반드시 거치는 블록입니다.</p>
      <div className="mt-2 flex flex-wrap gap-2">{outgoing.map((edge, index) => <button key={`${edge.to}:${index}`} className={button} disabled={path.length >= 200} onClick={() => { setPlaying(false); setPath(history => [...history, edge.to]); }}>{edge.label || (edge.type === 'true' ? '참' : edge.type === 'false' ? '거짓' : '다음')} → {names.get(edge.to) ?? edge.to}</button>)}</div>
      {!outgoing.length && <p>경로 끝</p>}
      {path.length >= 200 && <p>200단계에 도달했습니다. 초기화해서 다시 탐색하세요.</p>}
    </>}
  </section>;
}
