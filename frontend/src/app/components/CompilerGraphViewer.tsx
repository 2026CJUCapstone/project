import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowDownUp,
  Binary,
  Braces,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Eye,
  EyeOff,
  FileCode2,
  Focus,
  GitBranch,
  GitMerge,
  Loader2,
  Maximize2,
  Minus,
  Network,
  RotateCcw,
  ScanSearch,
  Search,
  Workflow,
  X,
} from 'lucide-react';
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  SelectionMode,
  useNodesState,
  type Edge,
  type Node,
  type NodeChange,
  type NodeProps,
  type ReactFlowInstance,
  type XYPosition,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './compiler-graph.css';
import dagre from 'dagre';
import { useCompilerStore, type SourceSelectionRange } from '../store/compilerStore';
import type { ASMLine, ASTGraph, IRInstruction, SSAGraph, SSAInstructionDetail, SourceRange } from '../services/compilerApi';
import { editorSelection, mapCompileSource, sameSource } from '../services/sourceMapping';
import { OptimizationCompare, PipelineExplorer } from './CompilerExplorer';
import { ControlFlowExplorer } from './ControlFlowExplorer';
import { CompilerTutorial } from './CompilerTutorial';
import { MappingBadge } from './MappingBadge';
import { ValueFlowExplorer } from './ValueFlowExplorer';
import { traceValueFlow } from '../services/valueFlow';
import { getSelectionNeighborhood } from '../services/selectionFocus';

type GraphTab = 'AST' | 'SSA';
type LayoutDirection = 'TB' | 'LR';

type GraphNodeData = {
  label: string;
  sub?: string;
  lines?: string[];
  highlightedLines?: boolean[];
  tracedLines?: boolean[];
  instructionDetails?: SSAInstructionDetail[];
  onValueClick?: (value: string) => void;
  approximate?: boolean;
  ast?: ASTGraph;
  isRoot?: boolean;
  highlight?: boolean;
  generated?: boolean;
  generatedReason?: string;
  metadata?: Record<string, unknown>;
  sourceRanges?: SourceRange[];
  instructionSourceRanges?: SourceRange[][];
  children?: string[];
  predecessors?: string[];
  successors?: string[];
  searchText?: string;
  searchMatch?: boolean;
  related?: boolean;
  dimmed?: boolean;
  layoutDirection?: LayoutDirection;
  w?: number;
  h?: number;
};

function layoutNodes(
  nodes: Node[],
  edges: Edge[],
  w = 160,
  h = 56,
  opts?: { nodesep?: number; ranksep?: number; direction?: LayoutDirection },
): Node[] {
  const direction = opts?.direction ?? 'TB';
  const g = new (dagre as any).graphlib.Graph();
  g.setGraph({
    rankdir: direction,
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
  const knownIds = new Set(nodes.map(node => node.id));
  edges.filter(edge => knownIds.has(edge.source) && knownIds.has(edge.target))
    .forEach((edge: Edge) => g.setEdge(edge.source, edge.target));
  (dagre as any).layout(g);
  return nodes.map((node: Node) => {
    const width = (node.data?.w as number) || w;
    const height = (node.data?.h as number) || h;
    const position = g.node(node.id);
    return {
      ...node,
      position: { x: position.x - width / 2, y: position.y - height / 2 },
      sourcePosition: direction === 'LR' ? Position.Right : Position.Bottom,
      targetPosition: direction === 'LR' ? Position.Left : Position.Top,
      data: { ...node.data, layoutDirection: direction },
    };
  });
}

function ASTNode({ data, selected }: NodeProps) {
  const nodeData = data as GraphNodeData;
  const highlight = data.highlight as boolean;
  const isRoot = data.isRoot as boolean;
  const horizontal = nodeData.layoutDirection === 'LR';
  return (
    <div
      data-graph-node="ast"
      data-node-selected={Boolean(selected)}
      data-search-match={Boolean(nodeData.searchMatch)}
      data-related={Boolean(nodeData.related)}
      data-source-highlight={Boolean(highlight)}
      className={`min-w-[150px] rounded-lg border px-4 py-3 shadow-[0_10px_24px_-20px_rgba(15,23,42,0.8)] transition-all ${
        nodeData.dimmed ? 'opacity-30' : 'opacity-100'
      } ${
        selected
          ? 'border-blue-400 bg-blue-50 text-blue-950 ring-2 ring-blue-400/35 dark:border-blue-400 dark:bg-[#111b2c] dark:text-blue-50'
          : nodeData.searchMatch
            ? 'border-fuchsia-400 bg-fuchsia-50 text-fuchsia-950 ring-2 ring-fuchsia-300/40 dark:border-fuchsia-400 dark:bg-[#251226] dark:text-fuchsia-50'
            : highlight
          ? 'border-amber-300 bg-amber-50 text-amber-950 ring-1 ring-amber-200/80 dark:border-amber-400/60 dark:bg-[#22170d] dark:text-amber-50 dark:ring-amber-400/20'
          : nodeData.related
            ? 'border-sky-300 bg-sky-50 text-sky-950 dark:border-sky-500/60 dark:bg-[#101a22] dark:text-sky-50'
          : isRoot
            ? 'border-orange-300 bg-orange-100 text-orange-950 dark:border-orange-500/60 dark:bg-[#1c1510] dark:text-orange-50'
            : 'border-orange-100 bg-white text-slate-900 dark:border-[#4a3321] dark:bg-[#151312] dark:text-slate-100'
      }`}
    >
      {!isRoot && <Handle type="target" position={horizontal ? Position.Left : Position.Top} className="!h-2 !w-2 !border-0 !bg-[#8aa4e6]" />}
      <div className="flex items-center gap-2">
        <span className="rounded-md bg-orange-500/12 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-orange-600 dark:bg-orange-400/12 dark:text-orange-300">
          AST
        </span>
        <span className="text-[12px] font-semibold leading-tight">{data.label as string}</span>
      </div>
      {data.sub ? <div className="mt-1 text-[11px] leading-snug text-slate-500 dark:text-slate-400">{String(data.sub)}</div> : null}
      <Handle type="source" position={horizontal ? Position.Right : Position.Bottom} className="!h-2 !w-2 !border-0 !bg-[#8aa4e6]" />
    </div>
  );
}

function SSANode({ data, selected }: NodeProps) {
  const nodeData = data as GraphNodeData;
  const highlight = data.highlight as boolean;
  const lines = (data.lines as string[]) || [];
  const highlightedLines = (data.highlightedLines as boolean[]) || [];
  const horizontal = nodeData.layoutDirection === 'LR';
  return (
    <div
      data-graph-node="ssa"
      data-node-selected={Boolean(selected)}
      data-search-match={Boolean(nodeData.searchMatch)}
      data-related={Boolean(nodeData.related)}
      data-source-highlight={Boolean(highlight)}
      style={{ width: nodeData.w ?? 330 }}
      className={`min-w-[220px] overflow-hidden rounded-lg border shadow-[0_10px_24px_-20px_rgba(15,23,42,0.85)] transition-all ${
        nodeData.dimmed ? 'opacity-30' : 'opacity-100'
      } ${
        selected
          ? 'border-blue-400 bg-blue-50 ring-2 ring-blue-400/35 dark:border-blue-400 dark:bg-[#111b2c]'
          : nodeData.searchMatch
            ? 'border-fuchsia-400 bg-fuchsia-50 ring-2 ring-fuchsia-300/40 dark:border-fuchsia-400 dark:bg-[#251226]'
            : highlight
          ? 'border-cyan-300 bg-cyan-50 ring-1 ring-cyan-200/70 dark:border-cyan-400/60 dark:bg-[#121d1d] dark:ring-cyan-400/20'
          : nodeData.related
            ? 'border-sky-300 bg-sky-50 dark:border-sky-500/60 dark:bg-[#101a22]'
          : 'border-teal-200 bg-white dark:border-[#254240] dark:bg-[#141616]'
      }`}
    >
      <Handle type="target" position={horizontal ? Position.Left : Position.Top} className="!h-2 !w-2 !border-0 !bg-[#5ea6b0]" />
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
          <div
            key={index}
            data-value-highlight={Boolean(nodeData.tracedLines?.[index])}
            className={`break-all rounded px-1 font-mono text-[10.5px] leading-relaxed ${
              nodeData.tracedLines?.[index] ? 'bg-violet-100 text-violet-950 ring-1 ring-violet-400 dark:bg-violet-900 dark:text-violet-50' : highlightedLines[index]
                ? 'bg-cyan-100 text-cyan-950 dark:bg-cyan-500/15 dark:text-cyan-50'
                : 'text-slate-600 dark:text-teal-100/80'
            }`}
          >
            {line}
            {nodeData.instructionDetails?.[index] && <span className="ml-1 inline-flex flex-wrap gap-1">
              {[...new Set([...(nodeData.instructionDetails[index].definitions ?? []), ...nodeData.instructionDetails[index].uses])].map(value => <button type="button" key={value} className="nodrag nopan rounded border border-violet-400/50 px-1 text-violet-600 dark:text-violet-300" title={`${value} 정의·사용 추적`} onClick={event => { event.stopPropagation(); nodeData.onValueClick?.(value); }}>{value}</button>)}
            </span>}
            <div><MappingBadge ranges={nodeData.instructionSourceRanges?.[index]} ast={nodeData.ast} generated={nodeData.instructionDetails?.[index]?.generated} generatedReason={nodeData.instructionDetails?.[index]?.generatedReason} /></div>
          </div>
        ))}
      </div>
      <Handle type="source" position={horizontal ? Position.Right : Position.Bottom} className="!h-2 !w-2 !border-0 !bg-[#5ea6b0]" />
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

export type SelectionContext = {
  range: SourceSelectionRange | null;
  hasSelection: boolean;
};

type SourceRangeLike = {
  line?: number;
  column?: number;
  startLine?: number;
  startColumn?: number;
  endLine?: number;
  endColumn?: number;
  startOffset?: number | null;
  endOffset?: number | null;
};

type NormalizedSourceRange = {
  startLine: number;
  startColumn: number;
  endLine: number;
  endColumn: number;
  startOffset?: number;
  endOffset?: number;
};

type RenderedCodeLine = {
  text: string;
  sourceRanges: SourceRange[];
  generated?: boolean;
  generatedReason?: string;
};

function extractSelectedTextFromRange(code: string, range: SourceSelectionRange | null): string {
  if (!range) return '';
  const lines = code.split(/\r?\n/);
  const start = Math.max(0, range.startLine - 1);
  const end = Math.min(lines.length - 1, range.endLine - 1);
  if (start > end) return '';

  return lines
    .slice(start, end + 1)
    .map((line, index, selectedLines) => {
      if (selectedLines.length === 1) {
        return line.slice(Math.max(0, range.startColumn - 1), Math.max(0, range.endColumn - 1));
      }
      if (index === 0) return line.slice(Math.max(0, range.startColumn - 1));
      if (index === selectedLines.length - 1) return line.slice(0, Math.max(0, range.endColumn - 1));
      return line;
    })
    .join('\n');
}

function buildSelectionContext(code: string, selectedText: string, range: SourceSelectionRange | null): SelectionContext {
  const rangeText = extractSelectedTextFromRange(code, range);
  const text = selectedText.trim() ? selectedText : rangeText;
  const trimmed = text.trim();

  if (!trimmed) {
    return {
      range: null,
      hasSelection: false,
    };
  }

  return {
    range,
    hasSelection: true,
  };
}

function normalizeSourceRange(range: SourceRangeLike | SourceSelectionRange | undefined | null): NormalizedSourceRange | null {
  if (!range) return null;
  const sourceRange = range as SourceRangeLike;
  const startLine = sourceRange.startLine ?? sourceRange.line;
  const startColumn = sourceRange.startColumn ?? sourceRange.column ?? 1;
  const endLine = sourceRange.endLine ?? startLine;
  const endColumn = sourceRange.endColumn ?? startColumn;
  const startOffset = typeof sourceRange.startOffset === 'number' && Number.isFinite(sourceRange.startOffset)
    ? sourceRange.startOffset
    : undefined;
  const endOffset = typeof sourceRange.endOffset === 'number' && Number.isFinite(sourceRange.endOffset)
    ? sourceRange.endOffset
    : undefined;

  if (
    typeof startLine !== 'number' ||
    typeof startColumn !== 'number' ||
    typeof endLine !== 'number' ||
    typeof endColumn !== 'number' ||
    !Number.isFinite(startLine) ||
    !Number.isFinite(startColumn) ||
    !Number.isFinite(endLine) ||
    !Number.isFinite(endColumn)
  ) {
    return null;
  }

  const normalized: NormalizedSourceRange = {
    startLine: Math.max(1, startLine),
    startColumn: Math.max(1, startColumn),
    endLine: Math.max(1, endLine),
    endColumn: Math.max(1, endColumn),
  };
  if (startOffset !== undefined && endOffset !== undefined) {
    normalized.startOffset = Math.max(0, Math.min(startOffset, endOffset));
    normalized.endOffset = Math.max(0, Math.max(startOffset, endOffset));
  }
  return normalized;
}

function isBeforeOrEqual(lineA: number, columnA: number, lineB: number, columnB: number): boolean {
  return lineA < lineB || (lineA === lineB && columnA <= columnB);
}

function isBefore(lineA: number, columnA: number, lineB: number, columnB: number): boolean {
  return lineA < lineB || (lineA === lineB && columnA < columnB);
}

function hasOffsets(range: NormalizedSourceRange): range is NormalizedSourceRange & { startOffset: number; endOffset: number } {
  return typeof range.startOffset === 'number' && typeof range.endOffset === 'number';
}

function rangesOverlap(a: SourceRangeLike | SourceSelectionRange | undefined, b: SourceRangeLike | SourceSelectionRange | undefined): boolean {
  const left = normalizeSourceRange(a);
  const right = normalizeSourceRange(b);
  if (!left || !right) return false;

  if (hasOffsets(left) && hasOffsets(right)) {
    return left.startOffset < right.endOffset && right.startOffset < left.endOffset;
  }

  return (
    isBefore(left.startLine, left.startColumn, right.endLine, right.endColumn) &&
    isBefore(right.startLine, right.startColumn, left.endLine, left.endColumn)
  );
}

function rangesEqual(a: NormalizedSourceRange, b: NormalizedSourceRange): boolean {
  if (hasOffsets(a) && hasOffsets(b)) {
    return a.startOffset === b.startOffset && a.endOffset === b.endOffset;
  }
  return (
    a.startLine === b.startLine &&
    a.startColumn === b.startColumn &&
    a.endLine === b.endLine &&
    a.endColumn === b.endColumn
  );
}

function rangeContains(outer: NormalizedSourceRange, inner: NormalizedSourceRange): boolean {
  if (hasOffsets(outer) && hasOffsets(inner)) {
    return outer.startOffset <= inner.startOffset && inner.endOffset <= outer.endOffset;
  }
  return (
    isBeforeOrEqual(outer.startLine, outer.startColumn, inner.startLine, inner.startColumn) &&
    isBeforeOrEqual(inner.endLine, inner.endColumn, outer.endLine, outer.endColumn)
  );
}

function rangeStrictlyContains(outer: NormalizedSourceRange, inner: NormalizedSourceRange): boolean {
  return rangeContains(outer, inner) && !rangesEqual(outer, inner);
}

function sourceRangeToSelection(range: SourceRange | undefined): SourceSelectionRange | null {
  const normalized = normalizeSourceRange(range);
  if (!normalized) return null;
  return {
    startLine: normalized.startLine,
    startColumn: normalized.startColumn,
    endLine: normalized.endLine,
    endColumn: normalized.endColumn,
    ...(normalized.startOffset !== undefined ? { startOffset: normalized.startOffset } : {}),
    ...(normalized.endOffset !== undefined ? { endOffset: normalized.endOffset } : {}),
  };
}

export function getConnectedNodeIds(edges: Edge[], nodeId: string): Set<string> {
  const connected = new Set<string>([nodeId]);
  edges.forEach((edge) => {
    if (edge.source === nodeId) connected.add(edge.target);
    if (edge.target === nodeId) connected.add(edge.source);
  });
  return connected;
}

export function getDescendantNodeIds(edges: Edge[], nodeId: string): Set<string> {
  const descendants = new Set<string>();
  const queue = [nodeId];
  while (queue.length) {
    const current = queue.shift()!;
    edges.forEach((edge) => {
      if (edge.source !== current || descendants.has(edge.target) || edge.target === nodeId) return;
      descendants.add(edge.target);
      queue.push(edge.target);
    });
  }
  return descendants;
}

function getAncestorNodeIds(edges: Edge[], nodeId: string): Set<string> {
  const ancestors = new Set<string>();
  const queue = [nodeId];
  while (queue.length) {
    const current = queue.shift()!;
    edges.forEach((edge) => {
      if (edge.target !== current || ancestors.has(edge.source) || edge.source === nodeId) return;
      ancestors.add(edge.source);
      queue.push(edge.source);
    });
  }
  return ancestors;
}

export function getHighlightedCodeLineIndexes(
  lines: Array<{ sourceRanges?: SourceRange[] }>,
  selection: SelectionContext,
): Set<number> {
  if (!selection.hasSelection || !selection.range) return new Set();

  const candidates: { lineIndex: number; range: NormalizedSourceRange }[] = [];
  lines.forEach((line, lineIndex) => {
    line.sourceRanges?.forEach((sourceRange) => {
      if (!rangesOverlap(sourceRange, selection.range ?? undefined)) return;
      const normalized = normalizeSourceRange(sourceRange);
      if (!normalized) return;
      candidates.push({ lineIndex, range: normalized });
    });
  });

  if (!candidates.length) return new Set();

  const specificCandidates = candidates.filter(
    (candidate) => rangeContains(normalizeSourceRange(selection.range)!, candidate.range)
      || !candidates.some((other) => rangeStrictlyContains(candidate.range, other.range)),
  );

  return new Set(specificCandidates.map((candidate) => candidate.lineIndex));
}

function convertASTGraph(astGraph: ASTGraph, selection: SelectionContext): { nodes: Node[]; edges: Edge[] } {
  const highlighted = getHighlightedCodeLineIndexes(astGraph.nodes, selection);
  const targets = new Set(astGraph.edges.map(edge => edge.to));
  const nodes: Node[] = astGraph.nodes.map((node, index) => ({
    id: node.id,
    type: 'ast',
    data: {
      label: node.type,
      sub: node.label !== node.type ? node.label : undefined,
      highlight: highlighted.has(index),
      isRoot: !targets.has(node.id),
      generated: node.generated,
      generatedReason: node.generatedReason,
      metadata: node.metadata,
      approximate: node.metadata?.mappingApproximate === true,
      sourceRanges: node.sourceRanges ?? (node.sourceLocation ? [node.sourceLocation] : []),
      children: node.children,
      searchText: `${node.type} ${node.label} ${node.id}`.toLowerCase(),
      w: 170,
      h: 62,
    },
    position: { x: 0, y: 0 },
  }));

  const edges: Edge[] = astGraph.edges.map((edge, index) => mkEdge(`ast-edge-${index}`, edge.from, edge.to, '#7c95c9', edge.label));
  return { nodes, edges };
}

function convertSSAGraph(ssaGraph: SSAGraph, selection: SelectionContext): { nodes: Node[]; edges: Edge[] } {
  const lines = ssaGraph.blocks.flatMap(block => block.instructions.map((_, i) => ({ sourceRanges: block.instructionSourceRanges?.[i] ?? [] })));
  const matchedLines = getHighlightedCodeLineIndexes(lines, selection);
  let lineOffset = 0;
  const nodes: Node[] = ssaGraph.blocks.map((block) => {
    const highlightedLines = block.instructions.map((_, index) => matchedLines.has(lineOffset + index));
    lineOffset += block.instructions.length;
    const highlight =
      highlightedLines.some(Boolean) ||
      (!block.instructionSourceRanges?.some(ranges => ranges.length) && selection.hasSelection && (block.sourceRanges ?? []).some((sourceRange) => rangesOverlap(sourceRange, selection.range ?? undefined)));

    return {
      id: block.id,
      type: 'ssa',
      data: {
        label: block.label,
        highlight,
        highlightedLines,
        lines: block.instructions,
        sourceRanges: block.sourceRanges ?? [],
        instructionSourceRanges: block.instructionSourceRanges ?? [],
        instructionDetails: block.instructionDetails,
        predecessors: block.predecessors,
        successors: block.successors,
        generated: block.generated,
        generatedReason: block.generatedReason,
        metadata: block.metadata,
        searchText: `${block.label} ${block.id} ${block.instructions.join(' ')}`.toLowerCase(),
        w: 330,
        h: 72 + block.instructions.reduce((height, text, index) => height + 56 + Math.floor(text.length / 48) * 16 + Math.floor((block.instructionDetails?.[index]?.uses.length ?? 0) / 6) * 20, 0),
      },
      position: { x: 0, y: 0 },
    };
  });

  const edges: Edge[] = ssaGraph.edges.map((edge, index) => {
    const color = edge.type === 'true' ? '#4fb99a' : edge.type === 'false' ? '#d27e89' : '#5ea6b0';
    return mkEdge(`ssa-edge-${index}`, edge.from, edge.to, color, edge.label);
  });

  return { nodes, edges };
}

function convertIRLines(instructions: IRInstruction[]): RenderedCodeLine[] {
  return instructions.map((instruction) => {
    const parts: string[] = [];
    if (instruction.result) parts.push(`${instruction.result} = `);
    parts.push(instruction.opcode);
    if (instruction.operands.length) parts.push(` ${instruction.operands.join(', ')}`);
    if (instruction.comment) parts.push(`  ; ${instruction.comment}`);
    return {
      generated: instruction.generated,
      generatedReason: instruction.generatedReason,
      text: parts.join(''),
      sourceRanges: instruction.sourceRanges ?? [],
    };
  });
}

function convertASMLines(lines: ASMLine[]): RenderedCodeLine[] {
  return lines.map((line) => {
    const parts: string[] = [];
    if (line.text !== undefined) {
      return {
        generated: line.generated,
        generatedReason: line.generatedReason,
        text: line.text,
        sourceRanges: line.sourceRanges ?? [],
      };
    }
    if (line.label) {
      return {
        generated: line.generated,
        generatedReason: line.generatedReason,
        text: `${line.label}:`,
        sourceRanges: line.sourceRanges ?? [],
      };
    }
    if (line.instruction) parts.push(`  ${line.instruction}`);
    if (line.operands.length) parts.push(`  ${line.operands.join(', ')}`);
    if (line.comment) parts.push(`  ; ${line.comment}`);
    return {
      text: parts.join(''),
      sourceRanges: line.sourceRanges ?? [],
    };
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

function firstSourceRange(data: GraphNodeData): SourceRange | undefined {
  return data.sourceRanges?.[0] ?? data.instructionSourceRanges?.flat().find(Boolean);
}

function formatSourceRange(range: SourceRange | undefined): string {
  const normalized = normalizeSourceRange(range);
  if (!normalized) return '연결된 소스 위치 없음';
  if (normalized.startLine === normalized.endLine) {
    return `${normalized.startLine}행 ${normalized.startColumn}–${normalized.endColumn}열`;
  }
  return `${normalized.startLine}:${normalized.startColumn} – ${normalized.endLine}:${normalized.endColumn}`;
}

function InteractiveGraph({
  kind,
  baseNodes,
  baseEdges,
  theme,
  navigateToSource,
  overlayIds,
  canNavigate,
  positionCache,
  ast,
}: {
  kind: GraphTab;
  baseNodes: Node[];
  baseEdges: Edge[];
  theme: 'dark' | 'light';
  navigateToSource: (range: SourceSelectionRange, revealEditor?: boolean) => void;
  overlayIds: string[];
  canNavigate: boolean;
  positionCache: Map<string, Record<string, XYPosition>>;
  ast?: ASTGraph;
}) {
  const [direction, setDirection] = useState<LayoutDirection>('TB');
  const [flowNodes, setFlowNodes, applyNodeChanges] = useNodesState<Node>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null);
  const [collapsedNodeIds, setCollapsedNodeIds] = useState<Set<string>>(() => new Set());
  const [searchQuery, setSearchQuery] = useState('');
  const [searchCursor, setSearchCursor] = useState(-1);
  const [showMiniMap, setShowMiniMap] = useState(false);
  const [selectionFocus, setSelectionFocus] = useState(false);
  const [neighborDepth, setNeighborDepth] = useState(0);
  const [instance, setInstance] = useState<ReactFlowInstance | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const [canvasSize, setCanvasSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    if (!canvasRef.current) return;
    let frame = 0;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setCanvasSize({ width, height });
      cancelAnimationFrame(frame);
      if (width > 0 && height > 0) frame = requestAnimationFrame(() => {
        void instance?.fitView({ padding: 0.25, maxZoom: 1.15 });
      });
    });
    observer.observe(canvasRef.current);
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, [instance]);
  const layoutScopeRef = useRef('');

  const topologySignature = useMemo(
    () => `${baseNodes.map((node) => node.id).join(',')}|${baseEdges.map((edge) => `${edge.source}>${edge.target}`).join(',')}`,
    [baseEdges, baseNodes],
  );
  const selectionSeedIds = useMemo(() => baseNodes.filter(node => node.data.highlight).map(node => node.id), [baseNodes]);
  const selectionKey = selectionSeedIds.join('|');
  useEffect(() => { setNeighborDepth(0); }, [selectionKey]);
  useEffect(() => { if (!canNavigate) setSelectionFocus(false); }, [canNavigate]);
  const focusedSelectionIds = useMemo(() => getSelectionNeighborhood(selectionSeedIds, baseEdges, neighborDepth), [selectionSeedIds, neighborDepth, baseEdges]);
  const hiddenNodeIds = useMemo(() => {
    const hidden = new Set<string>();
    if (selectionFocus) baseNodes.forEach(node => { if (!focusedSelectionIds.has(node.id)) hidden.add(node.id); });
    else collapsedNodeIds.forEach((nodeId) => getDescendantNodeIds(baseEdges, nodeId).forEach((id) => hidden.add(id)));
    return hidden;
  }, [baseEdges, baseNodes, collapsedNodeIds, selectionFocus, focusedSelectionIds]);
  const hiddenSignature = useMemo(() => [...hiddenNodeIds].sort().join(','), [hiddenNodeIds]);
  const visibleBaseNodes = useMemo(() => baseNodes.filter((node) => !hiddenNodeIds.has(node.id)), [baseNodes, hiddenNodeIds]);
  const visibleEdges = useMemo(
    () => {
      const ids = new Set(visibleBaseNodes.map(node => node.id));
      return baseEdges.filter(edge => ids.has(edge.source) && ids.has(edge.target));
    },
    [baseEdges, visibleBaseNodes],
  );
  const scopeKey = `${kind}:${direction}:${topologySignature}:${hiddenSignature}`;

  const rebuildLayout = useCallback((force = false) => {
    const currentPositions = new Map(flowNodes.map((node) => [node.id, node.position]));
    const cached = !force ? positionCache.get(scopeKey) : undefined;
    const canReuseCurrent = !force && layoutScopeRef.current === scopeKey;
    const laidOut = layoutNodes(visibleBaseNodes, visibleEdges, kind === 'AST' ? 170 : 230, kind === 'AST' ? 62 : 90, {
      direction,
      nodesep: kind === 'AST' ? 64 : 76,
      ranksep: kind === 'AST' ? 88 : 96,
    });
    setFlowNodes(
      laidOut.map((node) => ({
        ...node,
        position: cached?.[node.id] ?? (canReuseCurrent ? currentPositions.get(node.id) : undefined) ?? node.position,
        selected: node.id === selectedNodeId,
      })),
    );
    layoutScopeRef.current = scopeKey;
    if (force) positionCache.delete(scopeKey);
  }, [direction, flowNodes, kind, scopeKey, selectedNodeId, setFlowNodes, visibleBaseNodes, visibleEdges, positionCache]);

  useEffect(() => {
    const cached = positionCache.get(scopeKey);
    const canReuseCurrent = layoutScopeRef.current === scopeKey;
    // Selection changes only paint nodes; don't rerun Dagre while dragging code.
    const laidOut = canReuseCurrent ? visibleBaseNodes : layoutNodes(visibleBaseNodes, visibleEdges, kind === 'AST' ? 170 : 230, kind === 'AST' ? 62 : 90, {
      direction,
      nodesep: kind === 'AST' ? 64 : 76,
      ranksep: kind === 'AST' ? 88 : 96,
    });
    setFlowNodes(current => {
      const existing = new Map(current.map(node => [node.id, node]));
      return laidOut.map(node => ({ ...node,
        ...(canReuseCurrent ? existing.get(node.id) : {}),
        data: { ...node.data, layoutDirection: direction },
        position: (canReuseCurrent ? existing.get(node.id)?.position : undefined) ?? cached?.[node.id] ?? node.position,
      }));
    });
    layoutScopeRef.current = scopeKey;
  }, [direction, kind, scopeKey, setFlowNodes, visibleBaseNodes, visibleEdges, positionCache]);

  useEffect(() => {
    if (selectedNodeId && hiddenNodeIds.has(selectedNodeId)) setSelectedNodeId(null);
    if (focusedNodeId && hiddenNodeIds.has(focusedNodeId)) setFocusedNodeId(null);
  }, [focusedNodeId, hiddenNodeIds, selectedNodeId]);

  const normalizedQuery = searchQuery.trim().toLowerCase();
  const searchMatches = useMemo(
    () => normalizedQuery
      ? visibleBaseNodes.filter((node) => String((node.data as GraphNodeData).searchText ?? node.data.label ?? '').includes(normalizedQuery))
      : [],
    [normalizedQuery, visibleBaseNodes],
  );
  const searchMatchIds = useMemo(() => new Set(searchMatches.map((node) => node.id)), [searchMatches]);
  const relatedNodeIds = useMemo(
    () => (selectedNodeId ? getConnectedNodeIds(visibleEdges, selectedNodeId) : new Set<string>()),
    [selectedNodeId, visibleEdges],
  );
  const focusNodeIds = useMemo(() => {
    if (!focusedNodeId) return new Set<string>();
    if (kind === 'AST') {
      return new Set([
        focusedNodeId,
        ...getAncestorNodeIds(visibleEdges, focusedNodeId),
        ...getDescendantNodeIds(visibleEdges, focusedNodeId),
      ]);
    }
    return getConnectedNodeIds(visibleEdges, focusedNodeId);
  }, [focusedNodeId, kind, visibleEdges]);

  const renderedNodes = useMemo(
    () => flowNodes.map((node) => ({
      ...node,
      selected: node.selected || node.id === selectedNodeId,
      data: {
        ...node.data,
        searchMatch: searchMatchIds.has(node.id),
        related: overlayIds.includes(node.id) || Boolean(selectedNodeId && node.id !== selectedNodeId && relatedNodeIds.has(node.id)),
        dimmed: Boolean(overlayIds.length ? !overlayIds.includes(node.id) : focusedNodeId && !focusNodeIds.has(node.id)),
      },
    })),
    [flowNodes, focusNodeIds, focusedNodeId, relatedNodeIds, searchMatchIds, selectedNodeId, overlayIds],
  );
  const renderedEdges = useMemo(
    () => visibleEdges.map((edge) => {
      const related = Boolean(selectedNodeId && (edge.source === selectedNodeId || edge.target === selectedNodeId));
      const dimmed = Boolean(focusedNodeId && (!focusNodeIds.has(edge.source) || !focusNodeIds.has(edge.target)));
      return {
        ...edge,
        animated: related,
        style: {
          ...edge.style,
          opacity: dimmed ? 0.12 : selectedNodeId && !related ? 0.28 : 1,
          strokeWidth: related ? 2.8 : edge.style?.strokeWidth,
        },
      };
    }),
    [focusNodeIds, focusedNodeId, selectedNodeId, visibleEdges],
  );
  const selectedNode = useMemo(
    () => baseNodes.find((node) => node.id === selectedNodeId) ?? null,
    [baseNodes, selectedNodeId],
  );
  const selectedData = selectedNode?.data as GraphNodeData | undefined;
  const selectedRange = firstSourceRange(selectedData ?? { label: '' });

  const selectAndRevealNode = useCallback((nodeId: string, reveal = false) => {
    setSelectedNodeId(nodeId);
    const node = baseNodes.find((candidate) => candidate.id === nodeId);
    const sourceRange = firstSourceRange((node?.data ?? { label: '' }) as GraphNodeData);
    const navigationRange = sourceRangeToSelection(sourceRange);
    if (navigationRange) navigateToSource(navigationRange, false);
    if (reveal) {
      window.requestAnimationFrame(() => {
        instance?.fitView({ nodes: [{ id: nodeId }], duration: 280, padding: 0.8, maxZoom: 1.45 });
      });
    }
  }, [baseNodes, instance, navigateToSource]);

  const moveToSearchMatch = useCallback((step: number) => {
    if (!searchMatches.length) return;
    const next = searchCursor < 0 ? (step < 0 ? searchMatches.length - 1 : 0) : (searchCursor + step + searchMatches.length) % searchMatches.length;
    setSearchCursor(next);
    selectAndRevealNode(searchMatches[next].id, true);
  }, [searchCursor, searchMatches, selectAndRevealNode]);

  const toggleCollapse = useCallback((nodeId: string) => {
    setCollapsedNodeIds((current) => {
      const next = new Set(current);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });
  }, []);

  const handleNodesChange = useCallback((changes: NodeChange<Node>[]) => {
    applyNodeChanges(changes);
    const selected = changes.find(change => change.type === 'select' && change.selected);
    if (selected && 'id' in selected) setSelectedNodeId(selected.id);
    const positions = changes.filter(change => change.type === 'position' && change.position);
    if (positions.length) {
      const saved = { ...positionCache.get(scopeKey) };
      positions.forEach(change => { if (change.type === 'position' && change.position) saved[change.id] = change.position; });
      positionCache.set(scopeKey, saved);
      if (positionCache.size > 16) positionCache.delete(positionCache.keys().next().value!);
    }
  }, [applyNodeChanges, positionCache, scopeKey]);

  const persistPosition = useCallback((_event: React.MouseEvent, node: Node) => {
    const positions = Object.fromEntries(
      flowNodes.map((candidate) => [candidate.id, candidate.id === node.id ? node.position : candidate.position]),
    );
    positionCache.set(scopeKey, positions);
  }, [flowNodes, scopeKey, positionCache]);

  return (
    <div className="graph-interactive absolute inset-0 flex flex-col">
        <div className="graph-toolbar shrink-0 p-2">
          <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-slate-200 bg-white/95 p-2 shadow-sm backdrop-blur dark:border-[#333] dark:bg-[#171717]/95">
            <label className="flex h-8 min-w-[170px] flex-1 items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-2 dark:border-[#3a3a3a] dark:bg-[#0d0d0d]">
              <Search size={13} className="shrink-0 text-slate-400" />
              <input
                value={searchQuery}
                onChange={(event) => {
                  setSearchQuery(event.target.value);
                  setSearchCursor(-1);
                }}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') moveToSearchMatch(event.shiftKey ? -1 : 1);
                }}
                placeholder={`${kind} 노드 검색`}
                className="min-w-0 flex-1 bg-transparent text-xs text-slate-800 outline-none placeholder:text-slate-400 dark:text-gray-100"
              />
              {searchQuery ? (
                <button type="button" onClick={() => setSearchQuery('')} className="text-slate-400 hover:text-slate-700 dark:hover:text-white" title="검색 지우기">
                  <X size={13} />
                </button>
              ) : null}
            </label>
            {normalizedQuery ? (
              <span className="px-1 text-[10px] tabular-nums text-slate-500 dark:text-gray-400">
                {searchMatches.length ? `${searchCursor + 1}/${searchMatches.length}` : '0개'}
              </span>
            ) : null}
            <button type="button" onClick={() => moveToSearchMatch(-1)} disabled={!searchMatches.length} className="rounded-md p-2 text-slate-500 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-[#292929]" title="이전 검색 결과">
              <ChevronLeft size={14} />
            </button>
            <button type="button" onClick={() => moveToSearchMatch(1)} disabled={!searchMatches.length} className="rounded-md p-2 text-slate-500 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-[#292929]" title="다음 검색 결과">
              <ChevronRight size={14} />
            </button>
            <span className="mx-0.5 h-5 w-px bg-slate-200 dark:bg-[#3a3a3a]" />
            <button type="button" onClick={() => setDirection((current) => (current === 'TB' ? 'LR' : 'TB'))} className="rounded-md p-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-[#292929]" title={direction === 'TB' ? '좌우 레이아웃으로 전환' : '상하 레이아웃으로 전환'}>
              <ArrowDownUp size={14} className={direction === 'LR' ? 'rotate-90' : ''} />
            </button>
            <button type="button" onClick={() => rebuildLayout(true)} className="rounded-md p-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-[#292929]" title="자동 배치로 초기화">
              <RotateCcw size={14} />
            </button>
            <button type="button" onClick={() => instance?.fitView({ duration: 280, padding: 0.25, maxZoom: 1.2 })} className="rounded-md p-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-[#292929]" title="전체 그래프 맞추기">
              <Maximize2 size={14} />
            </button>
            <button type="button" onClick={() => setShowMiniMap((current) => !current)} className="rounded-md p-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-[#292929]" title={showMiniMap ? '미니맵 숨기기' : '미니맵 보기'}>
              {showMiniMap ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
            {collapsedNodeIds.size > 0 && <button onClick={() => setCollapsedNodeIds(new Set())} className="p-1 text-xs text-blue-500">모두 펼치기</button>}
            {focusedNodeId && <button onClick={() => setFocusedNodeId(null)} className="p-1 text-xs text-blue-500">관계 집중 해제</button>}
            <button aria-pressed={selectionFocus} disabled={!selectionFocus && (!selectionSeedIds.length || !canNavigate)} onClick={() => { setSelectionFocus(value => !value); setNeighborDepth(0); }} className="rounded border border-slate-300 px-2 py-1 text-xs disabled:opacity-40 dark:border-neutral-600">{selectionFocus ? '선택 집중 해제' : '선택 영역만 보기'}</button>
            {selectionFocus && <><button disabled={focusedSelectionIds.size >= baseNodes.length} onClick={() => setNeighborDepth(depth => depth + 1)} className="rounded px-2 py-1 text-xs text-blue-500 disabled:opacity-40">주변 연결 펼치기</button><span className="text-[10px] text-slate-500">{visibleBaseNodes.length}/{baseNodes.length}개 · 주변 {neighborDepth}단계</span></>}
          </div>
        </div>
      <div ref={canvasRef} data-testid="graph-canvas" className="graph-canvas relative min-h-0 flex-1">
      <ReactFlow
        nodes={renderedNodes}
        edges={renderedEdges}
        nodeTypes={nodeTypes}
        onNodesChange={handleNodesChange}
        onInit={setInstance}
        onNodeClick={(_event, node) => selectAndRevealNode(node.id)}
        onNodeDoubleClick={(_event, node) => setFocusedNodeId((current) => (current === node.id ? null : node.id))}
        onNodeDragStop={persistPosition}
        onPaneClick={() => setSelectedNodeId(null)}
        fitView
        fitViewOptions={{ padding: 0.28, maxZoom: 1.15 }}
        minZoom={0.2}
        maxZoom={2.2}
        nodesDraggable
        nodesConnectable={false}
        nodesFocusable
        edgesFocusable
        elementsSelectable
        deleteKeyCode={null}
        selectionMode={SelectionMode.Partial}
        colorMode={theme}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={24} size={1} color={theme === 'dark' ? '#283449' : '#cbd5e1'} />
        {showMiniMap && !selectedNode ? (
          <MiniMap pannable zoomable style={{ width: Math.min(140, canvasSize.width * 0.3), height: Math.min(90, canvasSize.height * 0.3) }}
            className="!rounded-md !border !border-slate-200 !bg-white/95 dark:!border-[#333] dark:!bg-[#1e1e1e]/95"
            nodeColor={(node) => (node.type === 'ast' ? '#f97316' : '#14b8a6')}
            maskColor={theme === 'dark' ? 'rgba(13, 13, 13, 0.82)' : 'rgba(255,255,255,0.76)'}
          />
        ) : null}
        <Controls showInteractive={false} className="!rounded-md !border !border-slate-200 dark:!border-[#333] dark:!bg-[#1e1e1e]" />
      </ReactFlow>
      </div>
        {selectedNode && selectedData ? (
          <aside aria-label="선택한 노드 상세" className="graph-inspector shrink-0 overflow-auto">
            <div className="rounded-lg border border-slate-200 bg-white/95 p-3 text-xs shadow-lg backdrop-blur dark:border-[#3a3a3a] dark:bg-[#171717]/95">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate font-semibold text-slate-900 dark:text-white">{selectedData.label}</div>
                  <div className="mt-1 font-mono text-[10px] text-slate-400">{selectedNode.id}</div>
                </div>
                <button type="button" onClick={() => setSelectedNodeId(null)} className="shrink-0 text-slate-400 hover:text-slate-700 dark:hover:text-white" title="상세 닫기"><X size={14} /></button>
              </div>
              {selectedData.sub ? <p className="mt-2 text-slate-600 dark:text-gray-300">{selectedData.sub}</p> : null}
              <div className="mt-2 rounded-md bg-slate-50 px-2 py-1.5 text-[11px] text-slate-500 dark:bg-[#0d0d0d] dark:text-gray-400">
                {formatSourceRange(selectedRange)}
              </div>
              <MappingBadge ranges={selectedData.sourceRanges?.length ? selectedData.sourceRanges : selectedData.instructionSourceRanges?.flat()} ast={ast} generated={selectedData.generated} generatedReason={selectedData.generatedReason} approximate={selectedData.approximate} />
              {selectedData.generated ? (
                <p className="mt-2 text-[11px] text-amber-600 dark:text-amber-300">컴파일러 생성 노드{selectedData.generatedReason ? ` · ${selectedData.generatedReason}` : ''}</p>
              ) : null}
              {kind === 'SSA' ? (
                <div className="mt-2 flex gap-3 text-[10px] text-slate-500 dark:text-gray-400">
                  <span>이전 {selectedData.predecessors?.length ?? 0}</span>
                  <span>다음 {selectedData.successors?.length ?? 0}</span>
                  <span>명령 {selectedData.lines?.length ?? 0}</span>
                </div>
              ) : null}
              <div className="mt-3 flex flex-wrap gap-1.5">
                <button type="button" disabled={!selectedRange || !canNavigate} onClick={() => {
                  const range = sourceRangeToSelection(selectedRange);
                  if (range) navigateToSource(range);
                }} className="inline-flex items-center gap-1 rounded-md bg-blue-600 px-2.5 py-1.5 font-medium text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40">
                  <FileCode2 size={12} /> 소스로 이동
                </button>
                <button type="button" onClick={() => setFocusedNodeId((current) => (current === selectedNode.id ? null : selectedNode.id))} className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-2.5 py-1.5 font-medium text-slate-600 hover:bg-slate-50 dark:border-[#3a3a3a] dark:text-gray-300 dark:hover:bg-[#292929]">
                  <Focus size={12} /> {focusedNodeId === selectedNode.id ? '집중 해제' : '관계 집중'}
                </button>
                {kind === 'AST' && getDescendantNodeIds(baseEdges, selectedNode.id).size ? (
                  <button type="button" onClick={() => toggleCollapse(selectedNode.id)} className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-2.5 py-1.5 font-medium text-slate-600 hover:bg-slate-50 dark:border-[#3a3a3a] dark:text-gray-300 dark:hover:bg-[#292929]">
                    <ChevronDown size={12} className={collapsedNodeIds.has(selectedNode.id) ? '-rotate-90' : ''} />
                    {collapsedNodeIds.has(selectedNode.id) ? '하위 펼치기' : '하위 접기'}
                  </button>
                ) : null}
              </div>
            </div>
          </aside>
        ) : null}
    </div>
  );
}

function CodeView({
  lines,
  selection,
  colorize,
  onLineClick,
  canNavigate,
  ast,
}: {
  lines: RenderedCodeLine[];
  selection: SelectionContext;
  colorize: (text: string) => JSX.Element;
  onLineClick: (range: SourceRange) => void;
  canNavigate: boolean;
  ast?: ASTGraph;
}) {
  const highlightedLineIndexes = useMemo(() => getHighlightedCodeLineIndexes(lines, selection), [lines, selection]);

  return (
    <div className="overflow-hidden border-y border-slate-200 bg-white dark:border-[#333] dark:bg-[#0d0d0d]">
      {lines.map((line, index) => {
        const highlighted = highlightedLineIndexes.has(index);
        return (
          <button
            type="button"
            key={index}
            disabled={!line.sourceRanges.length || !canNavigate}
            onClick={() => line.sourceRanges[0] && onLineClick(line.sourceRanges[0])}
            className={`flex font-mono text-[12px] leading-7 ${
              highlighted
                ? 'bg-amber-50 dark:bg-[#1d1710]'
                : index % 2 === 0
                  ? 'bg-white dark:bg-[#0d0d0d]'
                  : 'bg-slate-50/80 dark:bg-[#121212]'
            } w-full text-left transition-colors enabled:cursor-pointer enabled:hover:bg-blue-50 dark:enabled:hover:bg-[#111b2c]`}
            title={line.sourceRanges.length ? '이 명령을 만든 소스 코드로 이동' : '연결된 소스가 없습니다'}
          >
            <span className="w-11 shrink-0 border-r border-slate-200 px-3 text-right text-[11px] text-slate-400 dark:border-[#252525] dark:text-gray-500">
              {index + 1}
            </span>
            <span className="min-w-0 whitespace-pre px-3 text-slate-700 dark:text-gray-200">{colorize(line.text)}</span>
            <span className="ml-auto shrink-0 px-2"><MappingBadge ranges={line.sourceRanges} ast={ast} generated={line.generated} generatedReason={line.generatedReason} /></span>
          </button>
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
  const [explorer, setExplorer] = useState<'none' | 'lineage' | 'optimization' | 'cfg' | 'values'>('none');
  const [pair, setPair] = useState<'none' | 'AST-SSA' | 'IR-ASM'>('none');
  const [expanded, setExpanded] = useState(false);
  const [selectedValue, setSelectedValue] = useState<{ functionId: string; value: string } | null>(null);
  const [overlayIds, setOverlayIds] = useState<string[]>([]);
  const {
    activeGraphTab,
    isCompiling,
    language,
    lastCompile: rawCompile,
    lastCompiledCode,
    selectedSourceRange,
    selectedText,
    navigateToSource,
    setActiveGraphTab,
    setGraphViewerOpen,
    theme,
    codeStorageScope,
    codeStorageOwner,
    compile,
    setCode,
  } = useCompilerStore();

  const lastCompile = useMemo(() => mapCompileSource(rawCompile, lastCompiledCode ?? ''), [rawCompile, lastCompiledCode]);
  const isCurrentCodeCompiled = sameSource(lastCompiledCode, code);
  const positionCache = useMemo(() => new Map<string, Record<string, XYPosition>>(), [rawCompile, codeStorageScope, codeStorageOwner]);
  useEffect(() => { setOverlayIds([]); }, [lastCompiledCode, explorer, activeGraphTab]);
  useEffect(() => { setSelectedValue(null); }, [rawCompile, codeStorageScope, codeStorageOwner]);
  useEffect(() => {
    if (!expanded) return;
    const handle = (event: KeyboardEvent) => { if (event.key === 'Escape') setExpanded(false); };
    window.addEventListener('keydown', handle);
    return () => window.removeEventListener('keydown', handle);
  }, [expanded]);

  const selection = useMemo(
    () => isCurrentCodeCompiled && selectedSourceRange
      ? buildSelectionContext(code, selectedText, editorSelection(lastCompiledCode ?? code, selectedSourceRange))
      : { range: null, hasSelection: false },
    [code, lastCompiledCode, isCurrentCodeCompiled, selectedSourceRange, selectedText],
  );
  const astData = useMemo(() => (lastCompile?.ast ? convertASTGraph(lastCompile.ast, selection) : null), [lastCompile?.ast, selection]);
  const ssaData = useMemo(() => (lastCompile?.ssa ? convertSSAGraph(lastCompile.ssa, selection) : null), [lastCompile?.ssa, selection]);
  const valueTrace = useMemo(() => selectedValue && lastCompile?.ssa ? traceValueFlow(lastCompile.ssa, selectedValue.functionId, selectedValue.value) : null, [selectedValue, lastCompile?.ssa]);
  const selectValue = useCallback((functionId: string, value: string) => { setSelectedValue({ functionId, value }); setExplorer('values'); setActiveGraphTab('SSA'); }, [setActiveGraphTab]);
  const tracedSSA = useMemo(() => {
    if (!ssaData || !lastCompile?.ssa) return ssaData;
    const trace = explorer === 'values' ? valueTrace : null;
    const instructionKeys = new Set(trace?.instructionKeys ?? []);
    const edges: Edge[] = [...ssaData.edges];
    const seen = new Set<string>();
    trace?.entry?.definitions.forEach(definition => trace.entry!.uses.forEach(use => {
      if (definition.blockId === use.blockId) return;
      const key = JSON.stringify([definition.blockId, use.blockId]);
      if (seen.has(key) || seen.size >= 300) return;
      seen.add(key);
      edges.push({ ...mkEdge(`value:${key}`, definition.blockId, use.blockId, '#a855f7', trace.entry!.label), style: { stroke: '#a855f7', strokeWidth: 3, strokeDasharray: '6 4' }, animated: true });
    }));
    return { edges, nodes: ssaData.nodes.map((node, index) => ({ ...node, data: { ...node.data, ast: lastCompile.ast,
      tracedLines: lastCompile.ssa!.blocks[index].instructions.map((_, i) => instructionKeys.has(JSON.stringify([node.id, i]))),
      onValueClick: (value: string) => selectValue(lastCompile.ssa!.blocks[index].functionId ?? node.id.slice(0, node.id.lastIndexOf(':')), value),
    } })) };
  }, [ssaData, lastCompile?.ssa, lastCompile?.ast, explorer, valueTrace, selectValue]);
  const irLines = useMemo(() => (lastCompile?.ir?.instructions?.length ? convertIRLines(lastCompile.ir.instructions) : []), [lastCompile?.ir]);
  const asmLines = useMemo(() => (lastCompile?.asm?.lines?.length ? convertASMLines(lastCompile.asm.lines) : []), [lastCompile?.asm]);

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

  const renderStage = (stage: 'AST' | 'SSA' | 'IR' | 'ASM') => {
    const graph = stage === 'AST' ? astData : tracedSSA;
    const lines = stage === 'IR' ? irLines : asmLines;
    if (language !== 'bpp' || (stage === 'AST' || stage === 'SSA' ? !graph?.nodes.length : !lines.length)) return <EmptyState {...emptyState} title={canRender ? `${stage} 결과가 없습니다` : emptyState.title} />;
    if (stage === 'AST' || stage === 'SSA') return <InteractiveGraph
      key={`${stage}:${codeStorageScope}:${codeStorageOwner}:${lastCompiledCode}`}
      kind={stage} baseNodes={graph?.nodes ?? []} baseEdges={graph?.edges ?? []} theme={theme}
      ast={lastCompile?.ast} canNavigate={isCurrentCodeCompiled} positionCache={positionCache}
      overlayIds={stage === 'SSA' ? explorer === 'values' ? valueTrace?.blockIds ?? [] : overlayIds : []}
      navigateToSource={(range, revealEditor) => { if (isCurrentCodeCompiled) navigateToSource(range, revealEditor); }} />;
    return <div className="h-full overflow-auto"><CodeView ast={lastCompile?.ast} canNavigate={isCurrentCodeCompiled} lines={lines} selection={selection} colorize={stage === 'IR' ? colorIR : colorASM} onLineClick={range => {
      const navigation = sourceRangeToSelection(range);
      if (navigation && isCurrentCodeCompiled) navigateToSource(navigation, false);
    }} /></div>;
  };

  return (
    <div data-graph-workspace data-expanded={expanded} className={`${expanded ? 'fixed inset-2 z-50 shadow-2xl' : 'h-full'} flex min-w-0 flex-col overflow-y-auto border border-slate-200 bg-white dark:border-[#333] dark:bg-[#0d0d0d]`}>
      <div className="graph-header min-w-0 shrink-0">
        <div className="graph-heading"><span className="graph-heading-icon"><Workflow size={16} /></span><span>컴파일 탐색</span><span className={`graph-status ${compileState}`}><i />{isCompiling ? '컴파일 중' : compileState === 'ready' ? '최신 결과' : compileState === 'stale' ? '이전 결과' : compileState === 'error' ? '컴파일 오류' : 'B++'}</span>
          <div className="ml-auto flex gap-1">
            <button onClick={() => setExpanded(value => !value)} title={expanded ? '원래 크기로 (Esc)' : '탐색 크게 보기'} className="graph-icon-button"><Maximize2 size={15} /></button>
            <button onClick={() => setGraphViewerOpen(false)} title="그래프 패널 닫기" className="graph-icon-button"><Minus size={16} /></button>
          </div>
        </div>
        <div className="flex min-w-0 items-center gap-2">
          <div className="graph-stage-tabs flex min-w-0 flex-1 items-center gap-1">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                aria-pressed={activeGraphTab === tab.id && pair === 'none'}
                onClick={() => { setActiveGraphTab(tab.id); setPair('none'); }}
                className={`flex shrink-0 items-center gap-2 border-b-2 px-3 py-2 text-xs font-semibold uppercase tracking-[0.14em] transition-all ${
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
        </div>
        <div className="graph-metrics flex flex-wrap items-center gap-2">
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

      {language === 'bpp' && <CompilerTutorial currentSource={code} disabled={isCompiling} onCompile={() => compile()} onLoad={source => {
        if (code.trim() && !sameSource(code, source) && !window.confirm('현재 코드를 예제로 바꿀까요? 저장하지 않은 편집 내용은 대체됩니다.')) return;
        setCode(source); setActiveGraphTab('AST'); setPair('none');
      }} onSelect={range => navigateToSource(range, false)} />}

      {lastCompile?.success && language === 'bpp' && <>
        {!isCurrentCodeCompiled && <div role="status" className="border-b border-amber-300 bg-amber-50 p-2 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-100">
          코드가 변경되어 이전 결과와의 위치 연결을 멈췄습니다.
          <button onClick={() => compile()} disabled={isCompiling} className="ml-2 underline">다시 컴파일</button>
        </div>}
        <div className="graph-analysis-tools flex shrink-0 flex-wrap gap-1 text-xs">
          {([['lineage', '단계 연결'], ['optimization', '최적화 비교'], ['cfg', '제어 흐름'], ['values', '변수 흐름']] as const).map(([id, label]) => <button key={id} aria-pressed={explorer === id} onClick={() => { setExplorer(explorer === id ? 'none' : id); if (id === 'cfg' || id === 'values') { setActiveGraphTab('SSA'); if (pair === 'IR-ASM') setPair('none'); } }} className={`rounded px-2 py-1 ${explorer === id ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-700 dark:bg-neutral-800 dark:text-neutral-300'}`}>{label}</button>)}
          <label className="graph-pair-select flex items-center gap-1">나란히 보기<select aria-label="단계 나란히 보기" value={pair} onChange={event => { setPair(event.target.value as typeof pair); setExplorer('none'); }} className="min-w-0 rounded border border-slate-300 bg-white p-1 dark:border-neutral-600 dark:bg-neutral-900"><option value="none">한 단계</option><option value="AST-SSA">AST · SSA</option><option value="IR-ASM">IR · ASM</option></select></label>
        </div>
        {explorer === 'lineage' && <PipelineExplorer result={lastCompile} selection={selection.range} navigate={range => { if (isCurrentCodeCompiled) navigateToSource(range, false); }} setTab={stage => { setActiveGraphTab(stage); if (pair !== 'none' && !pair.split('-').includes(stage)) setPair('none'); }} />}
        {explorer === 'optimization' && rawCompile && <OptimizationCompare source={lastCompiledCode ?? ''} baseline={rawCompile} current={isCurrentCodeCompiled} scope={codeStorageScope} owner={codeStorageOwner} />}
        {explorer === 'cfg' && activeGraphTab === 'SSA' && lastCompile.ssa && <ControlFlowExplorer graph={lastCompile.ssa} onHighlight={setOverlayIds} />}
        {explorer === 'values' && lastCompile.ssa && <ValueFlowExplorer graph={lastCompile.ssa} canNavigate={isCurrentCodeCompiled} selected={valueTrace?.entry} onSelect={selectValue} navigate={range => { const target = sourceRangeToSelection(range); if (target && isCurrentCodeCompiled) navigateToSource(target, false); }} />}
      </>}

      {pair === 'none' ? <div className="relative min-h-[360px] flex-1 overflow-hidden bg-slate-50 dark:bg-[#0d0d0d]">{renderStage(activeGraphTab)}</div> :
        <div data-testid="stage-comparison" className="grid min-h-min flex-1 gap-px bg-slate-200 dark:bg-neutral-700" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 320px), 1fr))', gridAutoRows: 'minmax(430px, 1fr)', flexShrink: 0 }}>
          {(pair === 'AST-SSA' ? ['AST', 'SSA'] as const : ['IR', 'ASM'] as const).map(stage => <section key={stage} aria-label={`${stage} 비교 패널`} className="flex min-h-[430px] min-w-0 flex-col bg-slate-50 dark:bg-[#0d0d0d]">
            <h3 className="shrink-0 border-b border-slate-200 px-3 py-2 text-xs font-semibold dark:border-neutral-700">{stage} · 같은 소스 선택으로 연결</h3>
            <div className="relative min-h-[390px] flex-1 overflow-hidden">{renderStage(stage)}</div>
          </section>)}
        </div>}

      <div data-testid="compiler-stage-footer" className="shrink-0 border-t border-slate-200 bg-slate-50 px-4 py-2.5 text-xs text-slate-500 dark:border-[#333] dark:bg-[#121212] dark:text-gray-400">
        {pair === 'none' ? footerDescriptions[activeGraphTab] : `${pair.replace('-', ' · ')} — 같은 소스 선택으로 두 단계를 연결합니다.`}
      </div>
    </div>
  );
}
