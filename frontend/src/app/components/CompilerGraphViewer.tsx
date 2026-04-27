import { useMemo } from 'react';
import {
  Binary,
  Braces,
  CircleAlert,
  FileCode2,
  GitBranch,
  GitMerge,
  Loader2,
  Minus,
  Network,
  ScanSearch,
  Workflow,
} from 'lucide-react';
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Panel,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import dagre from 'dagre';
import { useCompilerStore } from '../store/compilerStore';
import type { ASMLine, ASTGraph, IRInstruction, SSAGraph } from '../services/compilerApi';

function layoutNodes(nodes: Node[], edges: Edge[], w = 160, h = 56, opts?: { nodesep?: number; ranksep?: number }): Node[] {
  const g = new (dagre as any).graphlib.Graph();
  g.setGraph({
    rankdir: 'TB',
    nodesep: opts?.nodesep ?? 56,
    ranksep: opts?.ranksep ?? 80,
    marginx: 36,
    marginy: 36,
  });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((node: Node) => {
    const width = (node.data?.w as number) || w;
    const height = (node.data?.h as number) || h;
    g.setNode(node.id, { width, height });
  });
  edges.forEach((edge: Edge) => g.setEdge(edge.source, edge.target));
  (dagre as any).layout(g);
  return nodes.map((node: Node) => {
    const width = (node.data?.w as number) || w;
    const height = (node.data?.h as number) || h;
    const position = g.node(node.id);
    return {
      ...node,
      position: { x: position.x - width / 2, y: position.y - height / 2 },
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
    };
  });
}

function ASTNode({ data }: NodeProps) {
  const highlight = data.highlight as boolean;
  const isRoot = data.isRoot as boolean;
  return (
    <div
      className={`min-w-[150px] rounded-lg border px-4 py-3 shadow-[0_10px_24px_-20px_rgba(15,23,42,0.8)] transition-all ${
        highlight
          ? 'border-amber-300 bg-amber-50 text-amber-950 ring-1 ring-amber-200/80 dark:border-amber-400/60 dark:bg-[#22170d] dark:text-amber-50 dark:ring-amber-400/20'
          : isRoot
            ? 'border-orange-300 bg-orange-100 text-orange-950 dark:border-orange-500/60 dark:bg-[#1c1510] dark:text-orange-50'
            : 'border-orange-100 bg-white text-slate-900 dark:border-[#4a3321] dark:bg-[#151312] dark:text-slate-100'
      }`}
    >
      {!isRoot && <Handle type="target" position={Position.Top} className="!h-2.5 !w-2.5 !border-0 !bg-orange-400 !-top-1.5" />}
      <div className="flex items-center gap-2">
        <span className="rounded-md bg-orange-500/12 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-orange-600 dark:bg-orange-400/12 dark:text-orange-300">
          AST
        </span>
        <span className="text-[12px] font-semibold leading-tight">{data.label as string}</span>
      </div>
      {data.sub ? <div className="mt-1 text-[11px] leading-snug text-slate-500 dark:text-slate-400">{String(data.sub)}</div> : null}
      <Handle type="source" position={Position.Bottom} className="!h-2.5 !w-2.5 !border-0 !bg-orange-400 !-bottom-1.5" />
    </div>
  );
}

function SSANode({ data }: NodeProps) {
  const highlight = data.highlight as boolean;
  const lines = (data.lines as string[]) || [];
  return (
    <div
      className={`min-w-[220px] overflow-hidden rounded-lg border shadow-[0_10px_24px_-20px_rgba(15,23,42,0.85)] transition-all ${
        highlight
          ? 'border-cyan-300 bg-cyan-50 ring-1 ring-cyan-200/70 dark:border-cyan-400/60 dark:bg-[#121d1d] dark:ring-cyan-400/20'
          : 'border-teal-200 bg-white dark:border-[#254240] dark:bg-[#141616]'
      }`}
    >
      <Handle type="target" position={Position.Top} className="!h-2.5 !w-2.5 !border-0 !bg-teal-400 !-top-1.5" />
      <div
        className={`border-b px-3.5 py-2 ${
          highlight
            ? 'border-cyan-200 bg-cyan-100/90 text-cyan-900 dark:border-cyan-500/20 dark:bg-cyan-500/10 dark:text-cyan-50'
            : 'border-teal-100 bg-teal-500/90 text-white dark:border-teal-500/20 dark:bg-[#1d5f5a]'
        }`}
      >
        <div className="text-[11px] font-semibold uppercase tracking-[0.16em]">SSA Block</div>
        <div className="mt-0.5 text-[12px] font-semibold leading-tight">{data.label as string}</div>
      </div>
      <div className="space-y-1 bg-white/95 px-3.5 py-3 dark:bg-[#101313]">
        {lines.map((line: string, index: number) => (
          <div key={index} className="font-mono text-[10.5px] leading-relaxed text-slate-600 dark:text-teal-100/80">
            {line}
          </div>
        ))}
      </div>
      <Handle type="source" position={Position.Bottom} className="!h-2.5 !w-2.5 !border-0 !bg-teal-400 !-bottom-1.5" />
    </div>
  );
}

const nodeTypes = { ast: ASTNode, ssa: SSANode };

function mkEdge(id: string, source: string, target: string, color: string, label?: string): Edge {
  return {
    id,
    source,
    target,
    type: 'smoothstep',
    style: { stroke: color, strokeWidth: 1.8 },
    markerEnd: { type: MarkerType.ArrowClosed, color, width: 14, height: 14 },
    label,
    labelStyle: {
      fill: color,
      fontWeight: 700,
      fontSize: 10,
    },
    labelBgPadding: [7, 4],
    labelBgBorderRadius: 999,
    labelBgStyle: {
      fill: 'rgba(255,255,255,0.9)',
      stroke: 'transparent',
    },
  };
}

function convertASTGraph(astGraph: ASTGraph, selectedText: string): { nodes: Node[]; edges: Edge[] } {
  const search = selectedText.trim().toLowerCase();
  const nodes: Node[] = astGraph.nodes.map((node, index) => ({
    id: node.id,
    type: 'ast',
    data: {
      label: node.type,
      sub: node.label !== node.type ? node.label : undefined,
      highlight: search ? node.label.toLowerCase().includes(search) || node.type.toLowerCase().includes(search) : false,
      isRoot: index === 0,
      w: 170,
      h: 62,
    },
    position: { x: 0, y: 0 },
  }));

  const edges: Edge[] = astGraph.edges.map((edge, index) => mkEdge(`ast-edge-${index}`, edge.from, edge.to, '#f97316', edge.label));
  return { nodes: layoutNodes(nodes, edges, 170, 62, { nodesep: 64, ranksep: 88 }), edges };
}

function convertSSAGraph(ssaGraph: SSAGraph, selectedText: string): { nodes: Node[]; edges: Edge[] } {
  const search = selectedText.trim().toLowerCase();
  const nodes: Node[] = ssaGraph.blocks.map((block) => ({
    id: block.id,
    type: 'ssa',
    data: {
      label: block.label,
      highlight: search ? block.label.toLowerCase().includes(search) || block.instructions.some((line) => line.toLowerCase().includes(search)) : false,
      lines: block.instructions,
      w: 230,
      h: 72 + block.instructions.length * 18,
    },
    position: { x: 0, y: 0 },
  }));

  const edges: Edge[] = ssaGraph.edges.map((edge, index) => {
    const color = edge.type === 'true' ? '#22c55e' : edge.type === 'false' ? '#ef4444' : '#14b8a6';
    return mkEdge(`ssa-edge-${index}`, edge.from, edge.to, color, edge.label);
  });

  return { nodes: layoutNodes(nodes, edges, 230, 90, { nodesep: 76, ranksep: 96 }), edges };
}

function convertIRLines(instructions: IRInstruction[]): string[] {
  return instructions.map((instruction) => {
    const parts: string[] = [];
    if (instruction.result) parts.push(`${instruction.result} = `);
    parts.push(instruction.opcode);
    if (instruction.operands.length) parts.push(` ${instruction.operands.join(', ')}`);
    if (instruction.comment) parts.push(`  ; ${instruction.comment}`);
    return parts.join('');
  });
}

function convertASMLines(lines: ASMLine[]): string[] {
  return lines.map((line) => {
    const parts: string[] = [];
    if (line.label) return `${line.label}:`;
    if (line.instruction) parts.push(`  ${line.instruction}`);
    if (line.operands.length) parts.push(`  ${line.operands.join(', ')}`);
    if (line.comment) parts.push(`  ; ${line.comment}`);
    return parts.join('');
  });
}

function tokenHighlight(text: string, re: RegExp, classify: (match: string) => string | null) {
  const parts: JSX.Element[] = [];
  let lastIndex = 0;
  let key = 0;
  let match: RegExpExecArray | null;
  re.lastIndex = 0;

  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(<span key={key++}>{text.slice(lastIndex, match.index)}</span>);
    }
    const className = classify(match[0]);
    parts.push(
      <span key={key++} className={className || undefined}>
        {match[0]}
      </span>,
    );
    lastIndex = re.lastIndex;
  }

  if (lastIndex < text.length) {
    parts.push(<span key={key++}>{text.slice(lastIndex)}</span>);
  }

  return <>{parts}</>;
}

function colorIR(text: string): JSX.Element {
  if (text.trim().endsWith(':')) return <span className="font-semibold text-amber-400">{text}</span>;
  if (!text.trim()) return <>{text}</>;
  return tokenHighlight(
    text,
    /(%[\w.]+|\b(?:func|alloca|store|load|add|sub|mul|icmp|br|ret|call|phi|sgt|ugt|slt|eq|ne|ult|udiv)\b|\b(?:i32|i64|i1|i8|void|label)\b|@[\w.]+|\b\d+\b)/g,
    (match) => {
      if (match.startsWith('%') || /^r\d+$/.test(match)) return 'text-sky-400';
      if (/^(func|alloca|store|load|add|sub|mul|icmp|br|ret|call|phi|sgt|ugt|slt|eq|ne|ult|udiv)$/.test(match)) return 'font-medium text-violet-400';
      if (/^(i32|i64|i1|i8|void|label)$/.test(match)) return 'text-emerald-400';
      if (match.startsWith('@')) return 'text-yellow-400';
      if (/^\d+$/.test(match)) return 'text-orange-300';
      return null;
    },
  );
}

function colorASM(text: string): JSX.Element {
  if (/^\.\w+.*:$/.test(text.trim()) || /^[A-Za-z_][\w.]*:$/.test(text.trim())) {
    return <span className="font-semibold text-green-400">{text}</span>;
  }
  if (!text.trim()) return <>{text}</>;
  return tokenHighlight(
    text,
    /(\b(?:push|pop|mov|add|sub|cmp|jle|jmp|jge|je|jne|ret|xor|call|lea|nop|test|sete|setne|setb|setg|movzx)\b|\b(?:rbp|rsp|rax|rbx|rcx|rdx|rdi|rsi|eax|ebx|ecx|edx|r8|r9|r10|r11)\b|\.[\w]+:?|\b(?:dword|qword|ptr)\b|\b\d+\b)/g,
    (match) => {
      if (/^(push|pop|mov|add|sub|cmp|jle|jmp|jge|je|jne|ret|xor|call|lea|nop|test|sete|setne|setb|setg|movzx)$/.test(match)) {
        return 'font-semibold text-sky-400';
      }
      if (/^(rbp|rsp|rax|rbx|rcx|rdx|rdi|rsi|eax|ebx|ecx|edx|r8|r9|r10|r11)$/.test(match)) return 'text-amber-300';
      if (match.startsWith('.')) return 'font-semibold text-green-400';
      if (/^(dword|qword|ptr)$/.test(match)) return 'text-rose-300';
      if (/^\d+$/.test(match)) return 'text-orange-300';
      return null;
    },
  );
}

function CodeView({ lines, selectedText, colorize }: { lines: string[]; selectedText: string; colorize: (text: string) => JSX.Element }) {
  const search = selectedText.trim().toLowerCase();
  return (
    <div className="overflow-hidden border-y border-slate-200 bg-white dark:border-[#333] dark:bg-[#0d0d0d]">
      {lines.map((line, index) => {
        const highlighted = search.length > 0 && line.toLowerCase().includes(search);
        return (
          <div
            key={index}
            className={`flex font-mono text-[12px] leading-7 ${
              highlighted
                ? 'bg-amber-50 dark:bg-[#1d1710]'
                : index % 2 === 0
                  ? 'bg-white dark:bg-[#0d0d0d]'
                  : 'bg-slate-50/80 dark:bg-[#121212]'
            }`}
          >
            <span className="w-11 shrink-0 border-r border-slate-200 px-3 text-right text-[11px] text-slate-400 dark:border-[#252525] dark:text-gray-500">
              {index + 1}
            </span>
            <span className="min-w-0 whitespace-pre px-3 text-slate-700 dark:text-gray-200">{colorize(line)}</span>
          </div>
        );
      })}
    </div>
  );
}

function EmptyState({
  title,
  description,
  icon,
  loading = false,
}: {
  title: string;
  description: string;
  icon: JSX.Element;
  loading?: boolean;
}) {
  return (
    <div className="flex h-full items-center justify-center px-8">
      <div className="max-w-sm text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-slate-500 dark:border-[#333] dark:bg-[#1e1e1e] dark:text-gray-300">
          {loading ? <Loader2 size={22} className="animate-spin" /> : icon}
        </div>
        <h3 className="mt-4 text-sm font-semibold text-slate-800 dark:text-gray-100">{title}</h3>
        <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-gray-400">{description}</p>
      </div>
    </div>
  );
}

function uniqueFunctionCountFromSSA(ssa: SSAGraph | undefined): number {
  if (!ssa?.blocks?.length) return 0;
  return new Set(ssa.blocks.map((block) => block.label.split(' · ')[0])).size;
}

function functionCountFromAST(ast: ASTGraph | undefined): number {
  if (!ast?.nodes?.length) return 0;
  return ast.nodes.filter((node) => node.type === 'FunctionDecl').length;
}

export function CompilerGraphViewer({ code }: { code: string }) {
  const {
    activeGraphTab,
    isCompiling,
    language,
    lastCompile,
    lastCompiledCode,
    selectedText,
    setActiveGraphTab,
    setGraphViewerOpen,
    theme,
  } = useCompilerStore();

  const astData = useMemo(() => (lastCompile?.ast ? convertASTGraph(lastCompile.ast, selectedText) : null), [lastCompile?.ast, selectedText]);
  const ssaData = useMemo(() => (lastCompile?.ssa ? convertSSAGraph(lastCompile.ssa, selectedText) : null), [lastCompile?.ssa, selectedText]);
  const irLines = useMemo(() => (lastCompile?.ir?.instructions?.length ? convertIRLines(lastCompile.ir.instructions) : []), [lastCompile?.ir]);
  const asmLines = useMemo(() => (lastCompile?.asm?.lines?.length ? convertASMLines(lastCompile.asm.lines) : []), [lastCompile?.asm]);

  const isCurrentCodeCompiled = lastCompiledCode === code;
  const compileState = !lastCompile
    ? 'idle'
    : lastCompile.success
      ? isCurrentCodeCompiled
        ? 'ready'
        : 'stale'
      : 'error';

  const tabs = [
    { id: 'AST', label: 'AST', icon: <Network size={13} />, accent: 'text-orange-500 border-orange-500 dark:bg-[#252525] dark:text-orange-400', count: lastCompile?.ast?.nodes?.length ?? 0 },
    { id: 'SSA', label: 'SSA', icon: <GitMerge size={13} />, accent: 'text-teal-500 border-teal-500 dark:bg-[#252525] dark:text-teal-300', count: lastCompile?.ssa?.blocks?.length ?? 0 },
    { id: 'IR', label: 'IR', icon: <GitBranch size={13} />, accent: 'text-violet-500 border-violet-500 dark:bg-[#252525] dark:text-violet-300', count: lastCompile?.ir?.instructions?.length ?? 0 },
    { id: 'ASM', label: 'ASM', icon: <FileCode2 size={13} />, accent: 'text-rose-500 border-rose-500 dark:bg-[#252525] dark:text-rose-300', count: lastCompile?.asm?.lines?.length ?? 0 },
  ] as const;

  const footerDescriptions = {
    AST: 'AST - 소스 구조를 기반으로 정리한 트리 뷰',
    SSA: 'SSA - 실제 B++ dump에서 파싱한 제어 흐름 그래프',
    IR: 'IR - 실제 B++ dump-ir 출력',
    ASM: 'ASM - 실제 B++ asm 출력',
  } as const;

  const metricBadges = useMemo(() => {
    if (activeGraphTab === 'AST') {
      return [
        { icon: <Braces size={12} />, label: `${lastCompile?.ast?.nodes?.length ?? 0} nodes` },
        { icon: <Workflow size={12} />, label: `${lastCompile?.ast?.edges?.length ?? 0} edges` },
        { icon: <Network size={12} />, label: `${functionCountFromAST(lastCompile?.ast)} funcs` },
      ];
    }
    if (activeGraphTab === 'SSA') {
      return [
        { icon: <Binary size={12} />, label: `${lastCompile?.ssa?.blocks?.length ?? 0} blocks` },
        { icon: <Workflow size={12} />, label: `${lastCompile?.ssa?.edges?.length ?? 0} edges` },
        { icon: <Network size={12} />, label: `${uniqueFunctionCountFromSSA(lastCompile?.ssa)} funcs` },
      ];
    }
    if (activeGraphTab === 'IR') {
      return [{ icon: <GitBranch size={12} />, label: `${irLines.length} lines` }];
    }
    return [{ icon: <FileCode2 size={12} />, label: `${asmLines.length} lines` }];
  }, [activeGraphTab, asmLines.length, irLines.length, lastCompile?.ast, lastCompile?.ssa]);

  const activeGraphData = activeGraphTab === 'AST' ? astData : ssaData;
  const graphHasData = activeGraphTab === 'AST' ? Boolean(astData?.nodes.length) : Boolean(ssaData?.nodes.length);
  const textLines = activeGraphTab === 'IR' ? irLines : asmLines;
  const textHasData = textLines.length > 0;
  const canRender = activeGraphTab === 'AST' || activeGraphTab === 'SSA' ? graphHasData : textHasData;

  const emptyState = useMemo(() => {
    if (language !== 'bpp') {
      return {
        title: 'B++ 전용 파이프라인 뷰',
        description: '지금 연결된 그래프, IR, ASM 뷰는 B++ 컴파일 결과를 기준으로 동작합니다.',
        icon: <CircleAlert size={22} />,
        loading: false,
      };
    }
    if (isCompiling && !canRender) {
      return {
        title: '컴파일 결과를 가져오는 중',
        description: '실제 B++ dump를 읽어서 그래프와 텍스트 뷰를 갱신하고 있습니다.',
        icon: <Loader2 size={22} />,
        loading: true,
      };
    }
    if (compileState === 'idle') {
      return {
        title: '컴파일하면 파이프라인이 열립니다',
        description: 'Ctrl+Shift+B로 컴파일하면 AST, SSA, IR, ASM이 이 패널에 실제 결과 기준으로 나타납니다.',
        icon: <ScanSearch size={22} />,
        loading: false,
      };
    }
    if (compileState === 'error') {
      return {
        title: '최근 컴파일이 실패했습니다',
        description: '오른쪽 패널은 성공한 컴파일 결과가 있어야 채워집니다. 먼저 오류를 해결한 뒤 다시 컴파일해 주세요.',
        icon: <CircleAlert size={22} />,
        loading: false,
      };
    }
    return {
      title: `${activeGraphTab} 결과가 아직 없습니다`,
      description: '이 탭에 필요한 출력이 비어 있습니다. 코드를 다시 컴파일하면 최신 결과로 채워집니다.',
      icon: <ScanSearch size={22} />,
      loading: false,
    };
  }, [activeGraphTab, canRender, compileState, isCompiling, language]);

  return (
    <div className="flex h-full flex-col border-l border-slate-200 bg-white dark:border-[#333] dark:bg-[#0d0d0d]">
      <div className="shrink-0 border-b border-slate-200 bg-white px-3 pt-2 dark:border-[#333] dark:bg-[#1e1e1e]">
        <div className="flex items-center justify-between gap-2 border-b border-slate-200 dark:border-[#333]">
          <div className="flex items-center gap-1">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveGraphTab(tab.id)}
                className={`flex items-center gap-2 border-b-2 px-3 py-2 text-xs font-semibold uppercase tracking-[0.14em] transition-all ${
                  activeGraphTab === tab.id
                    ? `${tab.accent}`
                    : 'border-transparent text-slate-400 hover:text-slate-600 dark:text-gray-400 dark:hover:bg-[#252525] dark:hover:text-gray-200'
                }`}
              >
                {tab.icon}
                {tab.label}
                <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500 dark:bg-[#2a2a2a] dark:text-gray-400">{tab.count}</span>
              </button>
            ))}
          </div>
          <button
            onClick={() => setGraphViewerOpen(false)}
            className="rounded-md p-1.5 text-slate-500 transition-colors hover:bg-slate-200 hover:text-slate-900 dark:text-gray-400 dark:hover:bg-[#252525] dark:hover:text-white"
            title="최소화"
          >
            <Minus size={16} />
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-2 py-2.5">
          {metricBadges.map((metric) => (
            <span
              key={metric.label}
              className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-medium text-slate-600 dark:border-[#333] dark:bg-[#161616] dark:text-gray-300"
            >
              {metric.icon}
              {metric.label}
            </span>
          ))}
        </div>
      </div>

      <div className="relative flex-1 overflow-hidden bg-slate-50 dark:bg-[#0d0d0d]">
        {!canRender ? (
          <EmptyState {...emptyState} />
        ) : activeGraphTab === 'AST' || activeGraphTab === 'SSA' ? (
          <div className="absolute inset-0">
            <ReactFlow
              key={activeGraphTab}
              nodes={activeGraphData?.nodes ?? []}
              edges={activeGraphData?.edges ?? []}
              nodeTypes={nodeTypes}
              fitView
              fitViewOptions={{ padding: 0.28, maxZoom: 1.15 }}
              minZoom={0.2}
              maxZoom={2.2}
              nodesDraggable
              nodesConnectable={false}
              elementsSelectable={false}
              colorMode={theme}
              proOptions={{ hideAttribution: true }}
            >
              <Background
                variant={BackgroundVariant.Dots}
                gap={20}
                size={0.8}
                color={theme === 'dark' ? '#242424' : '#dbe4f0'}
              />
              <MiniMap
                pannable
                zoomable
                className="!rounded-md !border !border-slate-200 !bg-white/95 dark:!border-[#333] dark:!bg-[#1e1e1e]/95"
                nodeColor={(node) => (node.type === 'ast' ? '#f97316' : '#14b8a6')}
                maskColor={theme === 'dark' ? 'rgba(13, 13, 13, 0.82)' : 'rgba(255,255,255,0.76)'}
              />
              <Panel position="top-left">
                <div className="flex flex-wrap items-center gap-2 rounded-md border border-slate-200 bg-white/95 px-3 py-2 text-[11px] font-medium text-slate-600 backdrop-blur dark:border-[#333] dark:bg-[#1e1e1e]/95 dark:text-gray-300">
                  {activeGraphTab === 'AST' ? (
                    <>
                      <span className="inline-flex items-center gap-1.5 text-orange-500"><Braces size={12} /> syntax nodes</span>
                      <span className="inline-flex items-center gap-1.5 text-amber-500"><ScanSearch size={12} /> selection highlight</span>
                    </>
                  ) : (
                    <>
                      <span className="inline-flex items-center gap-1.5 text-teal-500"><Binary size={12} /> blocks</span>
                      <span className="inline-flex items-center gap-1.5 text-emerald-500"><Workflow size={12} /> branch edges</span>
                    </>
                  )}
                </div>
              </Panel>
              <Controls showInteractive={false} className="!rounded-md !border !border-slate-200 dark:!border-[#333] dark:!bg-[#1e1e1e]" />
            </ReactFlow>
          </div>
        ) : (
          <div className="h-full overflow-auto">
            <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:border-[#333] dark:bg-[#1e1e1e] dark:text-gray-400">
              {activeGraphTab === 'IR' ? <GitBranch size={14} className="text-violet-400" /> : <FileCode2 size={14} className="text-rose-400" />}
              {activeGraphTab === 'IR' ? 'Intermediate Representation' : 'Assembly Output'}
            </div>
            <CodeView lines={textLines} selectedText={selectedText} colorize={activeGraphTab === 'IR' ? colorIR : colorASM} />
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-slate-200 bg-slate-50 px-4 py-2.5 text-xs text-slate-500 dark:border-[#333] dark:bg-[#121212] dark:text-gray-400">
        {footerDescriptions[activeGraphTab]}
      </div>
    </div>
  );
}
