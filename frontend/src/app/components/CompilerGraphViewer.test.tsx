import { describe, expect, it } from 'vitest';
import { getHighlightedCodeLineIndexes, type SelectionContext } from './CompilerGraphViewer';
import type { SourceRange } from '../services/compilerApi';

const broadWhileRange: SourceRange = {
  file: 'main.bpp',
  startLine: 37,
  startColumn: 5,
  endLine: 45,
  endColumn: 6,
};

const exactAssignmentRange: SourceRange = {
  file: 'main.bpp',
  startLine: 43,
  startColumn: 9,
  endLine: 43,
  endColumn: 19,
};

describe('getHighlightedCodeLineIndexes', () => {
  it('prefers exact statement ranges over enclosing control-flow ranges', () => {
    const selection: SelectionContext = {
      hasSelection: true,
      range: {
        startLine: 43,
        startColumn: 9,
        endLine: 43,
        endColumn: 19,
      },
    };

    const highlighted = getHighlightedCodeLineIndexes(
      [
        { sourceRanges: [broadWhileRange] },
        { sourceRanges: [broadWhileRange] },
        { sourceRanges: [exactAssignmentRange] },
        { sourceRanges: [exactAssignmentRange] },
        { sourceRanges: [broadWhileRange] },
      ],
      selection,
    );

    expect([...highlighted]).toEqual([2, 3]);
  });

  it('keeps the enclosing range when no more specific range overlaps the selection', () => {
    const selection: SelectionContext = {
      hasSelection: true,
      range: {
        startLine: 37,
        startColumn: 5,
        endLine: 37,
        endColumn: 26,
      },
    };

    const highlighted = getHighlightedCodeLineIndexes(
      [
        { sourceRanges: [broadWhileRange] },
        { sourceRanges: [broadWhileRange] },
        { sourceRanges: [exactAssignmentRange] },
      ],
      selection,
    );

    expect([...highlighted]).toEqual([0, 1]);
  });
});
