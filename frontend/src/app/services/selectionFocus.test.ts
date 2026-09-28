import { describe, expect, it } from 'vitest';
import { getSelectionNeighborhood } from './selectionFocus';

const values = (result: Set<string>): string[] => [...result];

describe('getSelectionNeighborhood', () => {
  it('traverses cycles once and stops at the requested depth', () => {
    const edges = [
      { source: 'a', target: 'b' },
      { source: 'b', target: 'c' },
      { source: 'c', target: 'a' },
      { source: 'c', target: 'd' },
    ];

    expect(values(getSelectionNeighborhood(['a'], edges, 1))).toEqual(['a', 'b', 'c']);
    expect(values(getSelectionNeighborhood(['a'], edges, 2))).toEqual(['a', 'b', 'c', 'd']);
  });

  it('does not include disconnected components', () => {
    const edges = [
      { source: 'a', target: 'b' },
      { source: 'x', target: 'y' },
    ];

    expect(values(getSelectionNeighborhood(['a'], edges, 10))).toEqual(['a', 'b']);
  });

  it('treats each directed graph edge as an undirected relationship', () => {
    const edges = [{ source: 'downstream', target: 'selected' }];

    expect(values(getSelectionNeighborhood(['selected'], edges, 1))).toEqual(['selected', 'downstream']);
    expect(values(getSelectionNeighborhood(['downstream'], edges, 1))).toEqual(['downstream', 'selected']);
  });

  it('preserves absent seed ids and treats invalid depths as zero', () => {
    const edges = [{ source: 'a', target: 'b' }];

    expect(values(getSelectionNeighborhood(['missing', 'missing'], edges, -1))).toEqual(['missing']);
    expect(values(getSelectionNeighborhood(['a'], edges, Number.NaN))).toEqual(['a']);
    expect(values(getSelectionNeighborhood(['a'], edges, 0))).toEqual(['a']);
  });
});
