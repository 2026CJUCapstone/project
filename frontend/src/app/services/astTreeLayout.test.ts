import { describe, expect, it } from 'vitest';
import { layoutAstForest, type AstTreeLayoutEdge, type AstTreeLayoutNode } from './astTreeLayout';

const tb = { direction: 'TB' as const, nodesep: 10, ranksep: 20 };
const lr = { direction: 'LR' as const, nodesep: 10, ranksep: 20 };
const node = (id: string, width = 20, height = 10): AstTreeLayoutNode => ({ id, width, height });

const at = (positions: ReturnType<typeof layoutAstForest>, id: string) => {
  expect(positions).not.toBeNull();
  return positions!.get(id)!;
};

describe('layoutAstForest', () => {
  it('lays out a 250-node tree with every node retained and same-depth boxes separated', () => {
    const nodes = Array.from({ length: 250 }, (_, index) => node(String(index), 20 + index % 3, 12 + index % 5));
    const edges = nodes.slice(1).map((child, index): AstTreeLayoutEdge => ({ source: String(Math.floor(index / 2)), target: child.id }));
    const positions = layoutAstForest(nodes, edges, tb);

    expect(positions?.size).toBe(nodes.length);
    for (const item of nodes) {
      const position = at(positions, item.id);
      expect(Number.isFinite(position.x) && Number.isFinite(position.y)).toBe(true);
    }
    for (const edge of edges) expect(at(positions, edge.target).y).toBeGreaterThan(at(positions, edge.source).y);

    const byDepth = new Map<number, AstTreeLayoutNode[]>();
    for (const item of nodes) {
      const mainCoordinate = at(positions, item.id).y;
      byDepth.set(mainCoordinate, [...(byDepth.get(mainCoordinate) ?? []), item]);
    }
    for (const items of byDepth.values()) {
      const ordered = [...items].sort((left, right) => at(positions, left.id).x - at(positions, right.id).x);
      for (let index = 1; index < ordered.length; index += 1) {
        const previous = ordered[index - 1], current = ordered[index];
        expect(at(positions, current.id).x).toBeGreaterThanOrEqual(at(positions, previous.id).x + previous.width);
      }
    }
  });

  it('centers an unequal parent over its child subtree and uses the largest prior depth extent', () => {
    const nodes = [node('root', 100, 30), node('left', 20, 100), node('right', 30, 20), node('leaf', 10, 10)];
    const edges = [{ source: 'root', target: 'left' }, { source: 'root', target: 'right' }, { source: 'left', target: 'leaf' }];
    const positions = layoutAstForest(nodes, edges, tb);

    const root = at(positions, 'root'), left = at(positions, 'left'), right = at(positions, 'right'), leaf = at(positions, 'leaf');
    expect(root.x + 50).toBe((left.x + right.x + 30) / 2);
    expect(left.y).toBe(30 + tb.ranksep);
    expect(leaf.y).toBe(30 + tb.ranksep + 100 + tb.ranksep);
  });

  it('keeps multiple roots and their ordered subtrees separate', () => {
    const nodes = [node('first', 40), node('first-child', 30), node('second', 50), node('second-child', 20), node('third', 25)];
    const edges = [{ source: 'first', target: 'first-child' }, { source: 'second', target: 'second-child' }];
    const positions = layoutAstForest(nodes, edges, tb);

    expect(at(positions, 'first').x).toBeLessThan(at(positions, 'second').x);
    expect(at(positions, 'second').x).toBeLessThan(at(positions, 'third').x);
    expect(at(positions, 'first-child').y).toBeGreaterThan(at(positions, 'first').y);
    expect(at(positions, 'second-child').y).toBeGreaterThan(at(positions, 'second').y);
  });

  it('uses the requested main axis for TB and LR layouts', () => {
    const nodes = [node('root', 30, 20), node('left', 20, 40), node('right', 40, 10)];
    const edges = [{ source: 'root', target: 'left' }, { source: 'root', target: 'right' }];
    const topToBottom = layoutAstForest(nodes, edges, tb);
    const leftToRight = layoutAstForest(nodes, edges, lr);

    expect(at(topToBottom, 'left').y).toBeGreaterThan(at(topToBottom, 'root').y);
    expect(at(leftToRight, 'left').x).toBeGreaterThan(at(leftToRight, 'root').x);
    expect(at(topToBottom, 'left').x).toBeLessThan(at(topToBottom, 'right').x);
    expect(at(leftToRight, 'left').y).toBeLessThan(at(leftToRight, 'right').y);
  });

  it('rejects duplicate IDs, unknown endpoints, cycles, and shared children', () => {
    expect(layoutAstForest([node('a'), node('a')], [], tb)).toBeNull();
    expect(layoutAstForest([node('a')], [{ source: 'a', target: 'missing' }], tb)).toBeNull();
    expect(layoutAstForest([node('a'), node('b')], [{ source: 'a', target: 'b' }, { source: 'b', target: 'a' }], tb)).toBeNull();
    expect(layoutAstForest([node('a'), node('b'), node('child')], [{ source: 'a', target: 'child' }, { source: 'b', target: 'child' }], tb)).toBeNull();
  });

  it('handles a long chain iteratively without losing nodes', () => {
    const nodes = Array.from({ length: 2_500 }, (_, index) => node(String(index), 10, 10));
    const edges = nodes.slice(1).map((child, index): AstTreeLayoutEdge => ({ source: String(index), target: child.id }));
    const positions = layoutAstForest(nodes, edges, tb);

    expect(positions?.size).toBe(nodes.length);
    expect(at(positions, '2499').y).toBe(2_499 * (10 + tb.ranksep));
  });
});
