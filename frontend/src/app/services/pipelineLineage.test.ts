import { expect, it } from 'vitest';
import { compareLines, tracePipeline, type PipelineItem } from './pipelineLineage';

it('distinguishes compiler IDs from source overlap without inventing unmapped connections', () => {
  const range = { startLine: 1, startColumn: 1, endLine: 1, endColumn: 8 };
  const items: PipelineItem[] = [
    { stage: 'SSA', id: 's1', label: 'load', ranges: [range], ssaIds: ['s1'], astIds: [] },
    { stage: 'IR', id: 'ir1', label: 'load', ranges: [], ssaIds: ['s1'], astIds: [] },
    { stage: 'ASM', id: 'a1', label: 'mov', ranges: [range], ssaIds: [], astIds: [] },
    { stage: 'ASM', id: 'a2', label: 'prologue', ranges: [], ssaIds: [], astIds: [] },
  ];
  expect(tracePipeline(items, range, items[0]).map(item => [item.id, item.relation])).toEqual([['s1', 'id'], ['ir1', 'id'], ['a1', 'source']]);
});

it('compares additions and removals while retaining surrounding unchanged instructions', () => {
  expect(compareLines(['label:', 'add 1, 2', 'mov x', 'ret'], ['label:', 'mov 3', 'mov x', 'ret'])).toEqual([
    { kind: 'same', text: 'label:' }, { kind: 'removed', text: 'add 1, 2' }, { kind: 'added', text: 'mov 3' },
    { kind: 'same', text: 'mov x' }, { kind: 'same', text: 'ret' },
  ]);
});
