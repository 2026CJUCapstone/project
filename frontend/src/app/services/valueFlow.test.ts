import { describe, expect, it } from 'vitest';
import type { SSAGraph } from './compilerApi';
import { buildValueFlow, traceValueFlow, type SSAInstructionDetail } from './valueFlow';

type ValueFlowGraph = SSAGraph & {
  blocks: Array<SSAGraph['blocks'][number] & { instructionDetails?: SSAInstructionDetail[] }>;
};

function graph(blocks: ValueFlowGraph['blocks']): ValueFlowGraph {
  return { blocks, edges: [] };
}

function block(
  id: string,
  instructionDetails?: SSAInstructionDetail[],
  functionId?: string,
): ValueFlowGraph['blocks'][number] {
  return {
    id,
    functionId,
    label: id,
    instructions: [],
    predecessors: [],
    successors: [],
    instructionDetails,
  };
}

describe('value flow', () => {
  it('scopes equal register names to their functions, including inferred function ids', () => {
    const valueGraph = graph([
      block('alpha:entry', [{ id: 'alpha-1', opcode: 'const', result: 'r1', uses: [] }]),
      block('alpha:exit', [{ id: 'alpha-2', opcode: 'return', uses: ['r1'] }]),
      block('beta:entry', [{ id: 'beta-1', opcode: 'const', result: 'r1', uses: [] }], 'beta'),
      block('beta:exit', [{ id: 'beta-2', opcode: 'return', uses: ['r1'] }], 'beta'),
    ]);

    expect(buildValueFlow(valueGraph)).toMatchObject([
      { key: '["alpha","r1"]', label: 'r1', functionId: 'alpha' },
      { key: '["beta","r1"]', label: 'r1', functionId: 'beta' },
    ]);
    expect(traceValueFlow(valueGraph, 'alpha', 'r1')).toMatchObject({
      blockIds: ['alpha:entry', 'alpha:exit'],
      instructionKeys: ['["alpha:entry",0]', '["alpha:exit",0]'],
    });
  });

  it('uses exact structured values rather than rendered instruction text or register substrings', () => {
    const valueGraph = graph([
      {
        ...block('main:entry', [
          { id: 'one', opcode: 'const', result: 'r1', uses: [] },
          { id: 'ten', opcode: 'add', result: 'r10', uses: ['r1'] },
        ]),
        instructions: ['r1 = const 1', 'r10 = add r1, 9'],
      },
      {
        ...block('main:unused', [{ id: 'display-only', opcode: 'nop', uses: [] }]),
        instructions: ['print r10 and r1'],
      },
    ]);

    const r1 = traceValueFlow(valueGraph, 'main', 'r1');
    expect(r1.entry?.uses).toEqual([{ blockId: 'main:entry', instructionId: 'ten', index: 1 }]);
    expect(traceValueFlow(valueGraph, 'main', 'r10').entry?.uses).toEqual([]);
    expect(buildValueFlow(valueGraph).map((entry) => entry.label)).toEqual(['r1', 'r10']);
  });

  it('preserves phi incoming values and treats a constant result as having no use', () => {
    const valueGraph = graph([
      block('main:left', [{ id: 'left', opcode: 'const', result: 'r1', uses: [] }]),
      block('main:right', [{ id: 'right', opcode: 'const', result: 'r2', uses: [] }]),
      block('main:join', [{ id: 'join', opcode: 'phi', result: 'r3', uses: ['r1', 'r2'] }]),
    ]);

    expect(traceValueFlow(valueGraph, 'main', 'r1').entry).toMatchObject({
      definitions: [{ blockId: 'main:left', instructionId: 'left', index: 0 }],
      uses: [{ blockId: 'main:join', instructionId: 'join', index: 0 }],
    });
    expect(traceValueFlow(valueGraph, 'main', 'r3').entry).toMatchObject({
      definitions: [{ blockId: 'main:join', instructionId: 'join', index: 0 }],
      uses: [],
    });
  });

  it('keeps duplicate definitions and undefined external values distinguishable', () => {
    const valueGraph = graph([
      block('main:first', [{ id: 'first', opcode: 'const', result: 'r2', uses: [] }]),
      block('main:second', [{ id: 'second', opcode: 'copy', result: 'r2', uses: ['external'] }]),
      block('main:consumer', [{ id: 'consumer', opcode: 'return', uses: ['r2'] }]),
    ]);

    expect(traceValueFlow(valueGraph, 'main', 'r2').entry).toMatchObject({
      definitions: [
        { blockId: 'main:first', instructionId: 'first', index: 0 },
        { blockId: 'main:second', instructionId: 'second', index: 0 },
      ],
      uses: [{ blockId: 'main:consumer', instructionId: 'consumer', index: 0 }],
    });
    expect(traceValueFlow(valueGraph, 'main', 'external').entry).toMatchObject({
      definitions: [],
      uses: [{ blockId: 'main:second', instructionId: 'second', index: 0 }],
    });
  });

  it('uses authoritative multi-definitions instead of the legacy result field', () => {
    const valueGraph = graph([
      block('main:entry', [{
        id: 'slice',
        opcode: 'slice',
        result: 'legacy-result',
        definitions: ['r4', 'r5'],
        uses: ['r1'],
      }]),
    ]);

    expect(buildValueFlow(valueGraph).map((entry) => entry.label)).toEqual(['r4', 'r5', 'r1']);
    expect(traceValueFlow(valueGraph, 'main', 'r4').entry?.definitions).toEqual([
      { blockId: 'main:entry', instructionId: 'slice', index: 0 },
    ]);
    expect(traceValueFlow(valueGraph, 'main', 'legacy-result').entry).toBeUndefined();
  });

  it('reports no value flow when the structured payload is absent', () => {
    const valueGraph: SSAGraph = {
      blocks: [{
        id: 'main:entry',
        label: 'main:entry',
        instructions: ['r1 = add r2, r3'],
        predecessors: [],
        successors: [],
      }],
      edges: [],
    };

    expect(buildValueFlow(valueGraph)).toEqual([]);
    expect(traceValueFlow(valueGraph, 'main', 'r1')).toEqual({
      entry: undefined,
      blockIds: [],
      instructionKeys: [],
    });
  });
});
