import { describe, expect, it } from 'vitest';
import { createSourceMapper, editorSelection, mapCompileSource } from './sourceMapping';
import { getHighlightedCodeLineIndexes } from '../components/CompilerGraphViewer';
import type { SourceRange } from './compilerApi';

const encoder = new TextEncoder();
function byteRange(code: string, text: string): SourceRange {
  const start = code.indexOf(text);
  return { file: 'main.bpp', startLine: 1, startColumn: 1, endLine: 1, endColumn: 1,
    startOffset: encoder.encode(code.slice(0, start)).length, endOffset: encoder.encode(code.slice(0, start + text.length)).length };
}

describe('compiler source mapping', () => {
  it.each(['\n', '\r\n'])('maps UTF-8 Korean and emoji to UTF-16 Monaco coordinates with %j', newline => {
    const code = `// 한글🙂${newline}emitln("한글🙂"); return 0;${newline}`;
    const mapped = createSourceMapper(code, { columnEncoding: 'byte', offsetEncoding: 'byte' })(byteRange(code, 'return 0;'))!;
    expect(mapped.startLine).toBe(2);
    expect(mapped.startColumn).toBe('emitln("한글🙂"); '.length + 1);
    expect(code.slice(mapped.startOffset!, mapped.endOffset!)).toBe('return 0;');
    const selection = editorSelection(code, { startLine: 2, endLine: 2, startColumn: mapped.startColumn, endColumn: mapped.endColumn });
    expect(selection.startOffset).toBe(mapped.startOffset);
  });

  it('converts byte columns even when old compiler JSON has no offsets', () => {
    const text = 'emitln("한🙂"); return 0;';
    const prefix = 'emitln("한🙂"); ';
    const result = createSourceMapper(text, { columnEncoding: 'byte' })({ startLine: 1, endLine: 1, startColumn: encoder.encode(prefix).length + 1, endColumn: encoder.encode(text).length + 1 });
    expect(result?.startColumn).toBe(prefix.length + 1);
    expect(result?.endColumn).toBe(text.length + 1);
  });

  it('rejects imported, inverted, out-of-bounds and split UTF-8 ranges', () => {
    const map = createSourceMapper('한글');
    const range = byteRange('한글', '글');
    expect(map({ ...range, file: '/tmp/src/std/main.bpp' })).toBeNull();
    expect(map({ ...range, startOffset: 1 })).toBeNull();
    expect(map({ ...range, endOffset: 200 })).toBeNull();
    expect(map({ ...range, startOffset: 6, endOffset: 3 })).toBeNull();
  });

  it('does not fall back to an approximate AST location when an explicit range is invalid', () => {
    const result = mapCompileSource({ success: true, executionTime: 1, ast: { nodes: [{ id: 'n', type: 'Call', label: 'x', children: [], sourceRanges: [byteRange('different string', 'string')], sourceLocation: { line: 1, column: 1, endLine: 1, endColumn: 2 } }], edges: [] } }, 'x');
    expect(result?.ast?.nodes[0].sourceRanges).toEqual([]);
  });

  it('marks legacy fallback as approximate and preserves exact provenance otherwise', () => {
    const legacy = { id: 'n', type: 'Call', label: 'x', children: [], sourceLocation: { line: 1, column: 1, endLine: 1, endColumn: 2 } };
    const mapped = mapCompileSource({ success: true, executionTime: 1, ast: { nodes: [legacy, { ...legacy, id: 'exact', sourceRanges: [{ ...byteRange('x', 'x'), astNodeId: 'exact' }] }], edges: [] } }, 'x');
    expect(mapped?.ast?.nodes[0].metadata?.mappingApproximate).toBe(true);
    expect(mapped?.ast?.nodes[1].metadata?.mappingApproximate).toBe(false);
    expect(mapped?.ast?.nodes[1].sourceRanges?.[0].astNodeId).toBe('exact');
  });

  it('retains all fully selected statements, not just a nested literal', () => {
    const lines = [
      { sourceRanges: [{ startLine: 1, startColumn: 1, endLine: 6, endColumn: 2 }] },
      { sourceRanges: [{ startLine: 2, startColumn: 3, endLine: 2, endColumn: 12 }] },
      { sourceRanges: [{ startLine: 2, startColumn: 10, endLine: 2, endColumn: 11 }] },
      { sourceRanges: [{ startLine: 3, startColumn: 3, endLine: 3, endColumn: 12 }] },
    ];
    expect([...getHighlightedCodeLineIndexes(lines, { hasSelection: true, range: { startLine: 2, startColumn: 1, endLine: 4, endColumn: 1 } })]).toEqual([1, 2, 3]);
    expect([...getHighlightedCodeLineIndexes(lines, { hasSelection: true, range: { startLine: 2, startColumn: 10, endLine: 2, endColumn: 11 } })]).toEqual([2]);
  });
});
