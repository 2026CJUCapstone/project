import { describe, expect, it } from 'vitest';
import { analyzeControlFlow, type ControlFlowBlock, type ControlFlowEdge } from './controlFlowAnalysis';

const blocks = (...ids: string[]): ControlFlowBlock[] => ids.map((id) => ({ id }));

const edges = (...pairs: Array<readonly [string, string]>): ControlFlowEdge[] =>
  pairs.map(([from, to]) => ({ from, to }));

describe('analyzeControlFlow', () => {
  it('computes dominators and immediate dominators for a diamond', () => {
    expect(
      analyzeControlFlow(
        blocks('start', 'left', 'right', 'join'),
        edges(['start', 'left'], ['start', 'right'], ['left', 'join'], ['right', 'join']),
      ),
    ).toEqual({
      roots: ['start'],
      dominators: {
        join: ['join', 'start'],
        left: ['left', 'start'],
        right: ['right', 'start'],
        start: ['start'],
      },
      immediateDominators: { join: 'start', left: 'start', right: 'start', start: null },
      backEdges: [],
      loops: [],
      unreachable: [],
    });
  });

  it('finds a natural loop and treats a self-loop as a back edge', () => {
    const analysis = analyzeControlFlow(
      blocks('entry', 'header', 'body', 'exit', 'self'),
      edges(
        ['entry', 'header'],
        ['header', 'body'],
        ['header', 'exit'],
        ['body', 'header'],
        ['exit', 'self'],
        ['self', 'self'],
      ),
    );

    expect(analysis.dominators).toEqual({
      body: ['body', 'entry', 'header'],
      entry: ['entry'],
      exit: ['entry', 'exit', 'header'],
      header: ['entry', 'header'],
      self: ['entry', 'exit', 'header', 'self'],
    });
    expect(analysis.backEdges).toEqual([
      { from: 'body', to: 'header' },
      { from: 'self', to: 'self' },
    ]);
    expect(analysis.loops).toEqual([
      { header: 'header', nodes: ['body', 'header'], backEdges: [{ from: 'body', to: 'header' }] },
      { header: 'self', nodes: ['self'], backEdges: [{ from: 'self', to: 'self' }] },
    ]);
  });

  it('supports disconnected functions with multiple entries', () => {
    const analysis = analyzeControlFlow(
      blocks('alpha-entry', 'alpha-exit', 'beta-entry', 'beta-middle', 'beta-exit'),
      edges(
        ['alpha-entry', 'alpha-exit'],
        ['beta-entry', 'beta-middle'],
        ['beta-middle', 'beta-exit'],
      ),
    );

    expect(analysis.roots).toEqual(['alpha-entry', 'beta-entry']);
    expect(analysis.immediateDominators).toEqual({
      'alpha-entry': null,
      'alpha-exit': 'alpha-entry',
      'beta-entry': null,
      'beta-exit': 'beta-middle',
      'beta-middle': 'beta-entry',
    });
    expect(analysis.unreachable).toEqual([]);
  });

  it('does not invent dominance or loop evidence for a rootless cycle', () => {
    const analysis = analyzeControlFlow(
      blocks('entry', 'exit', 'orphan-a', 'orphan-b'),
      edges(['entry', 'exit'], ['orphan-a', 'orphan-b'], ['orphan-b', 'orphan-a']),
    );

    expect(analysis.roots).toEqual(['entry']);
    expect(analysis.unreachable).toEqual(['orphan-a', 'orphan-b']);
    expect(analysis.dominators['orphan-a']).toEqual([]);
    expect(analysis.dominators['orphan-b']).toEqual([]);
    expect(analysis.immediateDominators['orphan-a']).toBeNull();
    expect(analysis.backEdges).toEqual([]);
    expect(analysis.loops).toEqual([]);
  });

  it('keeps rootless predecessors out of the reachable loop reverse closure', () => {
    const analysis = analyzeControlFlow(
      blocks('entry', 'header', 'body', 'orphan-a', 'orphan-b'),
      edges(
        ['entry', 'header'],
        ['header', 'body'],
        ['body', 'header'],
        ['orphan-a', 'orphan-b'],
        ['orphan-b', 'orphan-a'],
        ['orphan-b', 'body'],
      ),
    );

    expect(analysis.unreachable).toEqual(['orphan-a', 'orphan-b']);
    expect(analysis.loops).toEqual([
      { header: 'header', nodes: ['body', 'header'], backEdges: [{ from: 'body', to: 'header' }] },
    ]);
  });

  it('honors an explicit entry even when a loop closes back to it', () => {
    const analysis = analyzeControlFlow(
      [{ id: 'entry', isEntry: true }, { id: 'body' }],
      edges(['entry', 'body'], ['body', 'entry']),
    );

    expect(analysis.roots).toEqual(['entry']);
    expect(analysis.dominators).toEqual({ body: ['body', 'entry'], entry: ['entry'] });
    expect(analysis.loops).toEqual([
      { header: 'entry', nodes: ['body', 'entry'], backEdges: [{ from: 'body', to: 'entry' }] },
    ]);
  });

  it('finds nested natural loops and excludes incoming edges to a loop header', () => {
    const analysis = analyzeControlFlow(
      blocks('entry', 'outer', 'inner', 'inner-body', 'outer-body', 'exit'),
      edges(
        ['entry', 'outer'],
        ['outer', 'inner'],
        ['outer', 'exit'],
        ['inner', 'inner-body'],
        ['inner', 'outer-body'],
        ['inner-body', 'inner'],
        ['outer-body', 'outer'],
      ),
    );

    expect(analysis.backEdges).toEqual([
      { from: 'inner-body', to: 'inner' },
      { from: 'outer-body', to: 'outer' },
    ]);
    expect(analysis.loops).toEqual([
      {
        header: 'inner',
        nodes: ['inner', 'inner-body'],
        backEdges: [{ from: 'inner-body', to: 'inner' }],
      },
      {
        header: 'outer',
        nodes: ['inner', 'inner-body', 'outer', 'outer-body'],
        backEdges: [{ from: 'outer-body', to: 'outer' }],
      },
    ]);
  });

  it('merges block adjacency with explicit edges while ignoring duplicate and dangling edges', () => {
    const analysis = analyzeControlFlow(
      [
        { id: 'entry', successors: ['body', 'missing'] },
        { id: 'body', predecessors: ['entry'], successors: ['exit'] },
        { id: 'exit', predecessors: ['body'] },
      ],
      edges(['entry', 'body'], ['entry', 'body'], ['missing', 'body'], ['body', 'missing']),
    );

    expect(analysis).toMatchObject({
      roots: ['entry'],
      dominators: {
        entry: ['entry'],
        body: ['body', 'entry'],
        exit: ['body', 'entry', 'exit'],
      },
      unreachable: [],
    });
  });

  it('does not treat disconnected blocks of a known function as entries', () => {
    const result = analyzeControlFlow([
      { id: 'main-entry', functionId: 'main', isEntry: true },
      { id: 'dead', functionId: 'main' },
      { id: 'helper-entry', functionId: 'helper', isEntry: true },
    ], [{ from: 'main-entry', to: 'main-entry' }]);
    expect(result.roots).toEqual(['helper-entry', 'main-entry']);
    expect(result.unreachable).toEqual(['dead']);
    expect(result.loops[0].header).toBe('main-entry');
  });
});
