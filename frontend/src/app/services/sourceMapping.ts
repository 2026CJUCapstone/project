import type { CompileResponse, SourceRange } from './compilerApi';
import type { SourceSelectionRange } from '../store/compilerStore';

export type RangeSemantics = { columnEncoding?: unknown; offsetEncoding?: unknown; endColumn?: unknown };
export const sameSource = (a: string | null, b: string) => a !== null && a.replace(/\r\n/g, '\n') === b.replace(/\r\n/g, '\n');

/** Compiler byte positions and Monaco UTF-16 columns use different units. */
export function createSourceMapper(source: string, semantics: RangeSemantics = {}) {
  const encoder = new TextEncoder();
  const bytes = new Map<number, number>([[0, 0]]);
  let byteOffset = 0;
  let offset = 0;
  for (const character of source) {
    byteOffset += encoder.encode(character).length;
    offset += character.length;
    bytes.set(byteOffset, offset);
  }
  const starts = [0];
  for (let i = 0; i < source.length; i++) if (source[i] === '\n') starts.push(i + 1);
  const position = (index: number) => {
    let low = 0, high = starts.length - 1;
    while (low < high) {
      const middle = Math.ceil((low + high) / 2);
      if (starts[middle] <= index) low = middle; else high = middle - 1;
    }
    return { line: low + 1, column: index - starts[low] + 1 };
  };
  const fromColumn = (line: number, column: number): number | undefined => {
    if (!Number.isInteger(line) || !Number.isInteger(column) || line < 1 || line > starts.length || column < 1) return;
    const start = starts[line - 1];
    const text = source.slice(start, starts[line] ?? source.length).replace(/\r?\n$/, '');
    const encoding = semantics.columnEncoding ?? 'utf16';
    if (encoding === 'byte' || encoding === 'utf8') {
      let consumed = 0, index = 0;
      for (const char of text) {
        if (consumed === column - 1) return start + index;
        consumed += encoder.encode(char).length;
        index += char.length;
      }
      return consumed === column - 1 ? start + text.length : undefined;
    }
    if (encoding === 'codepoint' || encoding === 'unicode') {
      const chars = [...text];
      return column <= chars.length + 1 ? start + chars.slice(0, column - 1).join('').length : undefined;
    }
    return column <= text.length + 1 ? start + column - 1 : undefined;
  };
  return (range: SourceRange): SourceRange | null => {
    if (range.file && (/(?:^|\/)std\//.test(range.file.replace(/\\/g, '/')) || !/^main\.(bpp|b)$/.test(range.file.replace(/\\/g, '/').split('/').pop() ?? ''))) return null;
    let start: number | undefined, end: number | undefined;
    const hasOffsets = typeof range.startOffset === 'number' && typeof range.endOffset === 'number';
    if (hasOffsets) {
      if (semantics.offsetEncoding === 'utf16') {
        start = range.startOffset!; end = range.endOffset!;
      } else {
        start = bytes.get(range.startOffset!); end = bytes.get(range.endOffset!);
      }
      // Invalid byte boundaries must not silently point at unrelated columns.
      if (start === undefined || end === undefined) return null;
    } else {
      start = fromColumn(range.startLine, range.startColumn);
      end = fromColumn(range.endLine, range.endColumn + (semantics.endColumn === 'inclusive' ? 1 : 0));
    }
    if (start === undefined || end === undefined || !Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start || end > source.length) return null;
    const first = position(start), last = position(end);
    return { ...range, startLine: first.line, startColumn: first.column, endLine: last.line, endColumn: last.column,
      startOffset: start, endOffset: end };
  };
}

/** Normalize once per result. All rendered ranges then use Monaco coordinates. */
export function mapCompileSource(result: CompileResponse | null, source: string): CompileResponse | null {
  if (!result) return null;
  const map = createSourceMapper(source, result.metadata?.sourceRangeSemantics);
  const ranges = (values: SourceRange[] | undefined) => (values ?? []).map(map).filter((r): r is SourceRange => r !== null);
  const legacy = createSourceMapper(source, { columnEncoding: 'codepoint' });
  return { ...result,
    ast: result.ast && { ...result.ast, nodes: result.ast.nodes.map(node => ({ ...node,
      metadata: { ...node.metadata, mappingApproximate: !node.sourceRanges && Boolean(node.sourceLocation) },
      sourceRanges: node.sourceRanges ? ranges(node.sourceRanges) : node.sourceLocation ? [legacy({ startLine: node.sourceLocation.line, startColumn: node.sourceLocation.column, endLine: node.sourceLocation.endLine, endColumn: node.sourceLocation.endColumn })].filter((r): r is SourceRange => r !== null) : [],
      sourceLocation: undefined,
    })) },
    ssa: result.ssa && { ...result.ssa, blocks: result.ssa.blocks.map(block => ({ ...block, sourceRanges: ranges(block.sourceRanges), instructionSourceRanges: block.instructionSourceRanges?.map(ranges) })) },
    ir: result.ir && { ...result.ir, instructions: result.ir.instructions.map(line => ({ ...line, sourceRanges: ranges(line.sourceRanges) })) },
    asm: result.asm && { ...result.asm, lines: result.asm.lines.map(line => ({ ...line, sourceRanges: ranges(line.sourceRanges) })) },
  };
}

export function editorSelection(source: string, range: SourceSelectionRange): SourceSelectionRange {
  const lines = source.split('\n');
  const at = (line: number, column: number) => lines.slice(0, line - 1).reduce((n, s) => n + s.length + 1, 0) + column - 1;
  return { ...range, startOffset: at(range.startLine, range.startColumn), endOffset: at(range.endLine, range.endColumn) };
}
