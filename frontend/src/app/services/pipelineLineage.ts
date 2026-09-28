import type { CompileResponse, SourceRange } from './compilerApi';
import type { SourceSelectionRange } from '../store/compilerStore';

export type PipelineStage = 'AST' | 'SSA' | 'IR' | 'ASM';
export type PipelineItem = { stage: PipelineStage; id: string; label: string; ranges: SourceRange[]; ssaIds: string[]; astIds: string[] };
export function pipelineItems(result: CompileResponse): PipelineItem[] {
  const items: PipelineItem[] = [];
  result.ast?.nodes.forEach(node => items.push({ stage: 'AST', id: node.id, label: `${node.type}: ${node.label}`, ranges: node.sourceRanges ?? [], ssaIds: [],
    astIds: [node.id, ...[node.metadata?.astNodeId, node.metadata?.originNodeId].filter((v): v is string => typeof v === 'string')] }));
  result.ssa?.blocks.forEach(block => block.instructions.forEach((label, index) => items.push({ stage: 'SSA', id: block.instructionIds?.[index] ?? `${block.id}:${index}`, label,
    ranges: block.instructionSourceRanges?.[index] ?? [], ssaIds: block.instructionIds?.[index] ? [block.instructionIds[index]] : [], astIds: [] })));
  result.ir?.instructions.forEach(line => items.push({ stage: 'IR', id: line.id, label: [line.result && `${line.result} =`, line.opcode, ...line.operands].filter(Boolean).join(' '), ranges: line.sourceRanges ?? [], ssaIds: line.ssaInstructionIds ?? [], astIds: [] }));
  result.asm?.lines.forEach((line, i) => items.push({ stage: 'ASM', id: `asm:${i}`, label: line.text || [line.label, line.instruction, ...line.operands].filter(Boolean).join(' '), ranges: line.sourceRanges ?? [], ssaIds: line.ssaInstructionIds ?? [], astIds: [] }));
  return items.map(item => ({ ...item, astIds: [...new Set([...item.astIds, ...item.ranges.flatMap(range => [range.astNodeId, range.originNodeId].filter((v): v is string => typeof v === 'string'))])] }));
}

export function overlaps(a: SourceRange | SourceSelectionRange, b: SourceRange | SourceSelectionRange): boolean {
  if (typeof a.startOffset === 'number' && typeof a.endOffset === 'number' && typeof b.startOffset === 'number' && typeof b.endOffset === 'number') return a.startOffset < b.endOffset && b.startOffset < a.endOffset;
  const before = (l: number, c: number, r: number, d: number) => l < r || l === r && c < d;
  return before(a.startLine, a.startColumn, b.endLine, b.endColumn) && before(b.startLine, b.startColumn, a.endLine, a.endColumn);
}

export function tracePipeline(items: PipelineItem[], range: SourceSelectionRange | null, seed?: PipelineItem | null) {
  // A source overlap is evidence of shared source, not evidence of a compiler transform.
  const ssaIds = new Set(seed?.ssaIds ?? []), astIds = new Set(seed?.astIds ?? []);
  return items.flatMap(item => {
    const exact = Boolean(seed && (seed === item || item.ssaIds.some(id => ssaIds.has(id)) || item.astIds.some(id => astIds.has(id))));
    const source = Boolean(range && item.ranges.some(r => overlaps(r, range)));
    return exact || source ? [{ ...item, relation: exact ? 'id' as const : 'source' as const }] : [];
  });
}

/** Bounded line alignment; avoids quadratic memory for large compiler dumps. */
export function compareLines(before: string[], after: string[]) {
  const rows: { kind: 'same' | 'removed' | 'added'; text: string }[] = [];
  let left = 0, right = 0;
  while (left < before.length || right < after.length) {
    if (left < before.length && right < after.length && before[left] === after[right]) {
      rows.push({ kind: 'same', text: before[left++] }); right++; continue;
    }
    const added = left < before.length ? after.indexOf(before[left], right + 1) : -1;
    const removed = right < after.length ? before.indexOf(after[right], left + 1) : -1;
    if (added >= 0 && added - right <= 40 && (removed < 0 || added - right <= removed - left)) {
      while (right < added) rows.push({ kind: 'added', text: after[right++] });
    } else if (removed >= 0 && removed - left <= 40) {
      while (left < removed) rows.push({ kind: 'removed', text: before[left++] });
    } else {
      if (left < before.length) rows.push({ kind: 'removed', text: before[left++] });
      if (right < after.length) rows.push({ kind: 'added', text: after[right++] });
    }
  }
  return rows;
}
