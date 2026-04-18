import { useMemo } from 'react';
import { Network, GitBranch, GitMerge, FileCode2, Minus } from 'lucide-react';
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
  MarkerType,
  BackgroundVariant,
  type Node,
  type Edge,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import dagre from 'dagre';
import { useCompilerStore } from '../store/compilerStore';
import type { ASTGraph, SSAGraph, IRInstruction, ASMLine } from '../services/compilerApi';

/* ── Dagre 레이아웃 ──────────────────────────────────────────── */

function layoutNodes(nodes: Node[], edges: Edge[], w = 160, h = 56, opts?: { nodesep?: number; ranksep?: number }): Node[] {
  const g = new (dagre as any).graphlib.Graph();
  g.setGraph({ rankdir: 'TB', nodesep: opts?.nodesep ?? 50, ranksep: opts?.ranksep ?? 70, marginx: 30, marginy: 30 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n: Node) => {
    const nw = (n.data?.w as number) || w;
    const nh = (n.data?.h as number) || h;
    g.setNode(n.id, { width: nw, height: nh });
  });
  edges.forEach((e: Edge) => g.setEdge(e.source, e.target));
  (dagre as any).layout(g);
  return nodes.map((n: Node) => {
    const nw = (n.data?.w as number) || w;
    const nh = (n.data?.h as number) || h;
    const p = g.node(n.id);
    return { ...n, position: { x: p.x - nw / 2, y: p.y - nh / 2 }, sourcePosition: Position.Bottom, targetPosition: Position.Top };
  });
}

/* ── 커스텀 노드: AST ────────────────────────────────────────── */

function ASTNode({ data }: NodeProps) {
  const hl = data.highlight as boolean;
  const isRoot = data.isRoot as boolean;
  return (
    <div className={`px-5 py-2.5 rounded-full border-2 text-center shadow-lg min-w-[120px] transition-all
      ${hl
        ? 'bg-amber-50 dark:bg-amber-900/30 border-amber-400 ring-2 ring-amber-300/60 shadow-amber-200/30 dark:shadow-amber-700/20'
        : isRoot
          ? 'bg-orange-100 dark:bg-orange-900/40 border-orange-400 dark:border-orange-500'
          : 'bg-white dark:bg-[#1e150a] border-orange-200 dark:border-orange-700/60'}`}>
      {!isRoot && <Handle type="target" position={Position.Top} className="!bg-orange-400 !w-2 !h-2 !border-0 !-top-1" />}
      <div className={`text-[11px] font-bold leading-tight ${hl ? 'text-amber-700 dark:text-amber-200' : 'text-orange-700 dark:text-orange-200'}`}>
        {data.label as string}
      </div>
      {data.sub ? <div className="text-[9px] mt-0.5 text-orange-400/80 dark:text-orange-400/60 font-medium">{String(data.sub)}</div> : null}
      <Handle type="source" position={Position.Bottom} className="!bg-orange-400 !w-2 !h-2 !border-0 !-bottom-1" />
    </div>
  );
}

/* ── 커스텀 노드: SSA 블록 ───────────────────────────────────── */

function SSANode({ data }: NodeProps) {
  const hl = data.highlight as boolean;
  const lines = (data.lines as string[]) || [];
  return (
    <div className={`rounded-lg border-2 shadow-lg overflow-hidden min-w-[180px] transition-all
      ${hl
        ? 'border-amber-400 ring-2 ring-amber-300/60 shadow-amber-200/20 dark:shadow-amber-700/10'
        : 'border-teal-300 dark:border-teal-600 shadow-teal-100/30 dark:shadow-teal-900/20'}`}>
      <Handle type="target" position={Position.Top} className="!bg-teal-400 !w-2 !h-2 !border-0 !-top-1" />
      <div className={`px-3 py-1.5 text-[11px] font-bold tracking-wide
        ${hl ? 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-200' : 'bg-teal-500 dark:bg-teal-700 text-white'}`}>
        {data.label as string}
      </div>
      <div className="bg-white dark:bg-[#0a1f1c] px-3 py-2 space-y-0.5">
        {lines.map((l: string, i: number) => (
          <div key={i} className="font-mono text-[10px] text-gray-500 dark:text-teal-300/70 leading-relaxed">{l}</div>
        ))}
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-teal-400 !w-2 !h-2 !border-0 !-bottom-1" />
    </div>
  );
}

const nodeTypes = { ast: ASTNode, ssa: SSANode };

/* ── 엣지 헬퍼 ───────────────────────────────────────────────── */

function mkEdge(id: string, src: string, tgt: string, color: string, label?: string, type: string = 'straight'): Edge {
  return {
    id, source: src, target: tgt, type,
    style: { stroke: color, strokeWidth: 1.5 },
    markerEnd: { type: MarkerType.ArrowClosed, color, width: 12, height: 12 },
    ...(label ? { label, labelStyle: { fill: color, fontWeight: 700, fontSize: 10 }, labelBgStyle: { fill: 'transparent' } } : {}),
  };
}

/* ── 그래프 빌더 ──────────────────────────────────────────────── */

function buildAST(code: string, sel: string) {
  const hasIf = code.includes('if');
  const hasFor = code.includes('for') || code.includes('while');
  const hasPrint = code.includes('cout') || code.includes('print');
  const s = sel.trim();
  const ifS = !!(s && (sel.includes('if') || sel.includes('else')));
  const forS = !!(s && (sel.includes('for') || sel.includes('while')));
  const prS = !!(s && (sel.includes('cout') || sel.includes('print')));
  const mainS = !!(s && !ifS && !forS && !prS);
  const c = '#fb923c';

  const W = 150;
  const H = 48;
  const n: Node[] = [
    { id: 'rt', type: 'ast', data: { label: 'Program', highlight: false, isRoot: true, w: W, h: H }, position: { x: 0, y: 0 } },
    { id: 'fn', type: 'ast', data: { label: 'FunctionDecl', sub: 'main()', highlight: mainS, w: W, h: H }, position: { x: 0, y: 0 } },
  ];
  const e: Edge[] = [mkEdge('e1', 'rt', 'fn', c)];

  if (hasIf) {
    n.push(
      { id: 'if', type: 'ast', data: { label: 'IfStatement', highlight: ifS, w: W, h: H }, position: { x: 0, y: 0 } },
      { id: 'cd', type: 'ast', data: { label: 'Condition', highlight: ifS, w: W, h: H }, position: { x: 0, y: 0 } },
      { id: 'tb', type: 'ast', data: { label: 'TrueBody', highlight: ifS, w: W, h: H }, position: { x: 0, y: 0 } },
    );
    e.push(mkEdge('e2', 'fn', 'if', c), mkEdge('e3', 'if', 'cd', c), mkEdge('e4', 'if', 'tb', c));
    if (hasPrint) {
      n.push({ id: 'pr', type: 'ast', data: { label: 'FunctionCall', sub: 'print/cout', highlight: prS, w: W, h: H }, position: { x: 0, y: 0 } });
      e.push(mkEdge('e5', 'tb', 'pr', c));
    }
  } else {
    n.push({ id: 'sl', type: 'ast', data: { label: 'StatementList', highlight: mainS, w: W, h: H }, position: { x: 0, y: 0 } });
    e.push(mkEdge('e2', 'fn', 'sl', c));
    if (hasPrint) {
      n.push({ id: 'pr', type: 'ast', data: { label: 'FunctionCall', sub: 'print/cout', highlight: prS, w: W, h: H }, position: { x: 0, y: 0 } });
      e.push(mkEdge('e3', 'sl', 'pr', c));
    }
  }

  if (hasFor) {
    n.push({ id: 'lp', type: 'ast', data: { label: 'LoopStatement', highlight: forS, w: W, h: H }, position: { x: 0, y: 0 } });
    e.push(mkEdge('elo', 'fn', 'lp', c));
  }

  return { nodes: layoutNodes(n, e, W, H, { nodesep: 60, ranksep: 80 }), edges: e };
}

function buildSSA(code: string, sel: string) {
  const hasIf = code.includes('if');
  const s = sel.trim();
  const ifS = !!(s && (sel.includes('if') || sel.includes('else')));
  const mainS = !!(s && !ifS);

  const n: Node[] = [];
  const e: Edge[] = [];

  if (hasIf) {
    n.push(
      { id: 'e0', type: 'ssa', data: { label: 'Block 0 — Entry', highlight: mainS, lines: ['var_1 = init', 'branch B1, B2'], w: 210, h: 90 }, position: { x: 0, y: 0 } },
      { id: 'b1', type: 'ssa', data: { label: 'Block 1 — True', highlight: ifS, lines: ['var_2 = expr', 'jump B3'], w: 210, h: 80 }, position: { x: 0, y: 0 } },
      { id: 'b2', type: 'ssa', data: { label: 'Block 2 — False', highlight: ifS, lines: ['var_3 = expr', 'jump B3'], w: 210, h: 80 }, position: { x: 0, y: 0 } },
      { id: 'b3', type: 'ssa', data: { label: 'Block 3 — Merge', highlight: mainS, lines: ['var_4 = Φ(var_2, var_3)', 'return 0'], w: 210, h: 80 }, position: { x: 0, y: 0 } },
    );
    e.push(
      mkEdge('et', 'e0', 'b1', '#4ade80', 'True'),
      mkEdge('ef', 'e0', 'b2', '#f87171', 'False'),
      mkEdge('em1', 'b1', 'b3', '#2dd4bf'),
      mkEdge('em2', 'b2', 'b3', '#2dd4bf'),
    );
  } else {
    n.push(
      { id: 'e0', type: 'ssa', data: { label: 'Block 0 — Entry', highlight: mainS, lines: ['var_1 = init', 'jump B1'], w: 210, h: 80 }, position: { x: 0, y: 0 } },
      { id: 'b1', type: 'ssa', data: { label: 'Block 1 — Body', highlight: mainS, lines: ['var_2 = expr', 'return 0'], w: 210, h: 80 }, position: { x: 0, y: 0 } },
    );
    e.push(mkEdge('em', 'e0', 'b1', '#2dd4bf'));
  }

  return { nodes: layoutNodes(n, e, 210, 85, { nodesep: 60, ranksep: 80 }), edges: e };
}

/* ── 코드 라인 생성 (IR / ASM) ────────────────────────────────── */

function irLines(code: string): string[] {
  const hasIf = code.includes('if');
  if (hasIf) {
    return [
      '  %1 = alloca i32, align 4',
      '  store i32 0, i32* %1, align 4',
      '  %2 = load i32, i32* %1, align 4',
      '  %3 = icmp sgt i32 %2, 0',
      '  br i1 %3, label %true_blk, label %false_blk',
      '',
      'true_blk:',
      '  %4 = add i32 %2, 1',
      '  br label %merge',
      '',
      'false_blk:',
      '  %5 = sub i32 %2, 1',
      '  br label %merge',
      '',
      'merge:',
      '  %6 = phi i32 [ %4, %true_blk ], [ %5, %false_blk ]',
      '  ret i32 %6',
    ];
  }
  return [
    '  %1 = alloca i32, align 4',
    '  store i32 0, i32* %1, align 4',
    '  %2 = load i32, i32* %1, align 4',
    '  %3 = add i32 %2, 1',
    '  ret i32 0',
  ];
}

function asmLines(code: string): string[] {
  const hasIf = code.includes('if');
  if (hasIf) {
    return [
      '  push    rbp',
      '  mov     rbp, rsp',
      '  sub     rsp, 16',
      '  cmp     dword ptr [rbp-4], 0',
      '  jle     .LBB0_2',
      '.LBB0_1:',
      '  mov     eax, 1',
      '  jmp     .LBB0_3',
      '.LBB0_2:',
      '  mov     eax, 0',
      '.LBB0_3:',
      '  add     rsp, 16',
      '  pop     rbp',
      '  ret',
    ];
  }
  return [
    '  push    rbp',
    '  mov     rbp, rsp',
    '  sub     rsp, 16',
    '  mov     dword ptr [rbp-4], 0',
    '  xor     eax, eax',
    '  add     rsp, 16',
    '  pop     rbp',
    '  ret',
  ];
}

/* ── 실제 컴파일 데이터 → ReactFlow 변환 ─────────────────────── */

function convertASTGraph(astGraph: ASTGraph, sel: string): { nodes: Node[]; edges: Edge[] } {
  const c = '#fb923c';
  const W = 150;
  const H = 48;
  const s = sel.trim().toLowerCase();

  const nodes: Node[] = astGraph.nodes.map((n, i) => ({
    id: n.id,
    type: 'ast',
    data: {
      label: n.type,
      sub: n.label !== n.type ? n.label : undefined,
      highlight: s ? n.label.toLowerCase().includes(s) || n.type.toLowerCase().includes(s) : false,
      isRoot: i === 0,
      w: W,
      h: H,
    },
    position: { x: 0, y: 0 },
  }));

  const edges: Edge[] = astGraph.edges.map((e, i) =>
    mkEdge(`ae${i}`, e.from, e.to, c, e.label),
  );

  return { nodes: layoutNodes(nodes, edges, W, H, { nodesep: 60, ranksep: 80 }), edges };
}

function convertSSAGraph(ssaGraph: SSAGraph, sel: string): { nodes: Node[]; edges: Edge[] } {
  const s = sel.trim().toLowerCase();

  const nodes: Node[] = ssaGraph.blocks.map((b) => ({
    id: b.id,
    type: 'ssa',
    data: {
      label: b.label,
      highlight: s ? b.label.toLowerCase().includes(s) || b.instructions.some((l) => l.toLowerCase().includes(s)) : false,
      lines: b.instructions,
      w: 210,
      h: 50 + b.instructions.length * 18,
    },
    position: { x: 0, y: 0 },
  }));

  const edges: Edge[] = ssaGraph.edges.map((e, i) => {
    const color = e.type === 'true' ? '#4ade80' : e.type === 'false' ? '#f87171' : '#2dd4bf';
    return mkEdge(`se${i}`, e.from, e.to, color, e.label);
  });

  return { nodes: layoutNodes(nodes, edges, 210, 85, { nodesep: 60, ranksep: 80 }), edges };
}

function convertIRLines(instructions: IRInstruction[]): string[] {
  return instructions.map((inst) => {
    const parts: string[] = [];
    if (inst.result) parts.push(`${inst.result} = `);
    parts.push(inst.opcode);
    if (inst.operands.length) parts.push(' ' + inst.operands.join(', '));
    if (inst.comment) parts.push(`  ; ${inst.comment}`);
    return parts.join('');
  });
}

function convertASMLines(lines: ASMLine[]): string[] {
  return lines.map((l) => {
    const parts: string[] = [];
    if (l.label) return `${l.label}:`;
    parts.push('  ' + l.instruction);
    if (l.operands.length) parts.push('  ' + l.operands.join(', '));
    if (l.comment) parts.push(`  ; ${l.comment}`);
    return parts.join('');
  });
}

/* ── 구문 하이라이팅 ─────────────────────────────────────────── */

function tokenHighlight(text: string, re: RegExp, classify: (m: string) => string | null) {
  const parts: JSX.Element[] = [];
  let last = 0, k = 0, m: RegExpExecArray | null;
  re.lastIndex = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(<span key={k++}>{text.slice(last, m.index)}</span>);
    const cls = classify(m[0]);
    parts.push(<span key={k++} className={cls || undefined}>{m[0]}</span>);
    last = re.lastIndex;
  }
  if (last < text.length) parts.push(<span key={k++}>{text.slice(last)}</span>);
  return <>{parts}</>;
}

function colorIR(t: string): JSX.Element {
  if (t.trim().endsWith(':')) return <span className="text-yellow-400 font-bold">{t}</span>;
  if (!t.trim()) return <>{t}</>;
  return tokenHighlight(
    t,
    /(%[\w.]+|\b(?:alloca|store|load|add|sub|mul|icmp|br|ret|call|phi|sgt|slt|eq|ne)\b|\b(?:i32|i64|i1|i8|void|label)\b|@[\w.]+|\b\d+\b)/g,
    (m) => {
      if (m.startsWith('%')) return 'text-sky-400';
      if (/^(alloca|store|load|add|sub|mul|icmp|br|ret|call|phi|sgt|slt|eq|ne)$/.test(m)) return 'text-violet-400 font-medium';
      if (/^(i32|i64|i1|i8|void|label)$/.test(m)) return 'text-emerald-400';
      if (m.startsWith('@')) return 'text-yellow-400';
      if (/^\d+$/.test(m)) return 'text-orange-300';
      return null;
    },
  );
}

function colorASM(t: string): JSX.Element {
  if (/^\.\w+.*:$/.test(t.trim())) return <span className="text-green-400 font-bold">{t}</span>;
  if (!t.trim()) return <>{t}</>;
  return tokenHighlight(
    t,
    /(\b(?:push|pop|mov|add|sub|cmp|jle|jmp|jge|je|jne|ret|xor|call|lea|nop)\b|\b(?:rbp|rsp|rax|rbx|rcx|rdx|rdi|rsi|eax|ebx|ecx|edx|r8|r9|r10|r11)\b|\.[\w]+:?|\b(?:dword|qword|ptr)\b|\b\d+\b)/g,
    (m) => {
      if (/^(push|pop|mov|add|sub|cmp|jle|jmp|jge|je|jne|ret|xor|call|lea|nop)$/.test(m)) return 'text-sky-400 font-semibold';
      if (/^(rbp|rsp|rax|rbx|rcx|rdx|rdi|rsi|eax|ebx|ecx|edx|r8|r9|r10|r11)$/.test(m)) return 'text-amber-300';
      if (m.startsWith('.')) return 'text-green-400 font-bold';
      if (/^(dword|qword|ptr)$/.test(m)) return 'text-rose-300';
      if (/^\d+$/.test(m)) return 'text-orange-300';
      return null;
    },
  );
}

/* ── 코드 뷰 컴포넌트 ────────────────────────────────────────── */

function CodeView({ lines, sel, colorize }: { lines: string[]; sel: string; colorize: (t: string) => JSX.Element }) {
  return (
    <div className="rounded-lg border border-gray-200 dark:border-[#333] overflow-hidden shadow-lg font-mono text-[12px] leading-[1.8]">
      {lines.map((line, i) => {
        const isHl = sel.trim().length > 0 && line.toLowerCase().includes(sel.toLowerCase());
        return (
          <div key={i} className={`flex ${isHl ? 'bg-amber-50 dark:bg-amber-900/20' : i % 2 === 0 ? 'bg-white dark:bg-[#141414]' : 'bg-gray-50/50 dark:bg-[#1a1a1a]'}`}>
            <span className="select-none w-10 text-right pr-3 py-1 text-gray-400 dark:text-gray-600 border-r border-gray-200 dark:border-[#333] shrink-0 text-[11px]">
              {i + 1}
            </span>
            <span className="px-3 py-1 whitespace-pre text-gray-800 dark:text-gray-200">{colorize(line)}</span>
          </div>
        );
      })}
    </div>
  );
}

/* ── 메인 컴포넌트 ────────────────────────────────────────────── */

export function CompilerGraphViewer({ code }: { code: string }) {
  const { setGraphViewerOpen, activeGraphTab, setActiveGraphTab, selectedText, theme, lastCompile } = useCompilerStore();

  // 실제 컴파일 결과가 있으면 사용, 없으면 mock fallback
  const astData = useMemo(() => {
    if (lastCompile?.ast) return convertASTGraph(lastCompile.ast, selectedText);
    return buildAST(code, selectedText);
  }, [lastCompile?.ast, code, selectedText]);

  const ssaData = useMemo(() => {
    if (lastCompile?.ssa) return convertSSAGraph(lastCompile.ssa, selectedText);
    return buildSSA(code, selectedText);
  }, [lastCompile?.ssa, code, selectedText]);

  const irData = useMemo(() => {
    if (lastCompile?.ir?.instructions?.length) return convertIRLines(lastCompile.ir.instructions);
    return irLines(code);
  }, [lastCompile?.ir, code]);

  const asmData = useMemo(() => {
    if (lastCompile?.asm?.lines?.length) return convertASMLines(lastCompile.asm.lines);
    return asmLines(code);
  }, [lastCompile?.asm, code]);

  const isGraph = activeGraphTab === 'AST' || activeGraphTab === 'SSA';

  const tabs = ['AST', 'SSA', 'IR', 'ASM'] as const;
  const tabIcon: Record<string, JSX.Element> = {
    AST: <Network size={13} />, SSA: <GitMerge size={13} />, IR: <GitBranch size={13} />, ASM: <FileCode2 size={13} />,
  };
  const tabColor: Record<string, string> = {
    AST: 'text-orange-500 border-orange-500', SSA: 'text-teal-500 border-teal-500', IR: 'text-violet-500 border-violet-500', ASM: 'text-rose-500 border-rose-500',
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-[#121212] border-l border-gray-200 dark:border-[#333]">
      {/* 헤더 */}
      <div className="flex items-center justify-between px-4 py-3 bg-gray-50 dark:bg-[#1e1e1e] border-b border-gray-200 dark:border-[#333] shrink-0">
        <div className="flex items-center gap-2">
          <Network size={18} className="text-purple-500 dark:text-purple-400" />
          <h2 className="text-sm font-bold text-gray-800 dark:text-gray-200 uppercase tracking-wider">Pipeline Viewer</h2>
        </div>
        <button onClick={() => setGraphViewerOpen(false)} className="p-1 hover:bg-gray-200 dark:hover:bg-[#333] text-gray-500 hover:text-gray-900 dark:hover:text-white rounded transition-colors" title="최소화">
          <Minus size={18} />
        </button>
      </div>

      {/* 탭 */}
      <div className="flex items-center border-b border-gray-200 dark:border-[#333] bg-gray-50 dark:bg-[#1a1a1a] px-1 pt-1 shrink-0">
        {tabs.map((tab) => (
          <button key={tab} onClick={() => setActiveGraphTab(tab)}
            className={`flex items-center gap-1.5 px-3 py-2 text-xs font-semibold uppercase tracking-wider border-b-2 transition-all mx-0.5 rounded-t
              ${activeGraphTab === tab ? `${tabColor[tab]} bg-white dark:bg-[#121212]` : 'border-transparent text-gray-400 hover:text-gray-600 dark:hover:text-gray-300'}`}>
            {tabIcon[tab]}{tab}
          </button>
        ))}
      </div>

      {/* 콘텐츠 */}
      <div className="flex-1 relative overflow-hidden">
        {isGraph ? (
          <div className="absolute inset-0">
            <ReactFlow
              key={activeGraphTab}
              nodes={activeGraphTab === 'AST' ? astData.nodes : ssaData.nodes}
              edges={activeGraphTab === 'AST' ? astData.edges : ssaData.edges}
              nodeTypes={nodeTypes}
              fitView
              fitViewOptions={{ padding: 0.35, maxZoom: 1.2 }}
              nodesDraggable
              nodesConnectable={false}
              elementsSelectable={false}
              colorMode={theme}
              minZoom={0.2}
              maxZoom={2.5}
              defaultEdgeOptions={{ animated: false }}
              proOptions={{ hideAttribution: true }}
            >
              <Background variant={BackgroundVariant.Dots} gap={20} size={0.8} color={theme === 'dark' ? '#2a2a2a' : '#e5e5e5'} />
              <Controls showInteractive={false} className="!shadow-lg !border !border-gray-200 dark:!border-gray-700 !rounded-lg" />
            </ReactFlow>
          </div>
        ) : (
          <div className="h-full overflow-auto p-4">
            <div className="flex items-center gap-2 mb-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-widest">
              <FileCode2 size={14} className={activeGraphTab === 'IR' ? 'text-violet-400' : 'text-rose-400'} />
              {activeGraphTab === 'IR' ? 'Intermediate Representation' : 'Assembly Output'}
            </div>
            <CodeView lines={activeGraphTab === 'IR' ? irData : asmData} sel={selectedText} colorize={activeGraphTab === 'IR' ? colorIR : colorASM} />
          </div>
        )}
      </div>

      {/* 설명 */}
      <div className="shrink-0 px-4 py-2.5 border-t border-gray-200 dark:border-[#333] bg-gray-50 dark:bg-[#1a1a1a] text-xs text-gray-500 dark:text-gray-500">
        {activeGraphTab === 'AST' && <p><strong className="text-orange-500">AST</strong> — 소스 코드의 구문 분석 결과 트리</p>}
        {activeGraphTab === 'SSA' && <p><strong className="text-teal-500">SSA</strong> — 제어 흐름 그래프 (CFG)</p>}
        {activeGraphTab === 'IR' && <p><strong className="text-violet-500">IR</strong> — 기계어에 가까운 중간 표현</p>}
        {activeGraphTab === 'ASM' && <p><strong className="text-rose-500">ASM</strong> — 대상 아키텍처 어셈블리 코드</p>}
      </div>
    </div>
  );
}
