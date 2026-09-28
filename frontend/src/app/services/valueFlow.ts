import type { SSAGraph, SSAInstructionDetail } from './compilerApi';

export type { SSAInstructionDetail } from './compilerApi';

export interface ValueFlowLocation {
  blockId: string;
  instructionId: string;
  index: number;
}

export interface ValueFlowEntry {
  /** Collision-safe identifier for the function/value pair. */
  key: string;
  /** The SSA value as supplied by the structured instruction payload. */
  label: string;
  functionId: string;
  definitions: ValueFlowLocation[];
  uses: ValueFlowLocation[];
}

export interface ValueFlowTrace {
  entry: ValueFlowEntry | undefined;
  blockIds: string[];
  instructionKeys: string[];
}

function functionIdFor(block: SSAGraph['blocks'][number]): string {
  if (block.functionId !== undefined) {
    return block.functionId;
  }

  const separator = block.id.lastIndexOf(':');
  return separator === -1 ? block.id : block.id.slice(0, separator);
}

function valueKey(functionId: string, value: string): string {
  return JSON.stringify([functionId, value]);
}

function locationFor(blockId: string, detail: SSAInstructionDetail, index: number): ValueFlowLocation {
  return { blockId, instructionId: detail.id, index };
}

function definitionsFor(detail: SSAInstructionDetail): readonly string[] {
  return detail.definitions ?? (typeof detail.result === 'string' ? [detail.result] : []);
}

/**
 * Builds a definition/use index from structured SSA instruction details.
 * Rendered instruction strings are intentionally not inspected: a graph with
 * no details has no value-flow evidence.
 */
export function buildValueFlow(graph: SSAGraph): ValueFlowEntry[] {
  const entries = new Map<string, ValueFlowEntry>();

  const entryFor = (functionId: string, value: string): ValueFlowEntry => {
    const key = valueKey(functionId, value);
    const existing = entries.get(key);
    if (existing) {
      return existing;
    }

    const entry: ValueFlowEntry = {
      key,
      label: value,
      functionId,
      definitions: [],
      uses: [],
    };
    entries.set(key, entry);
    return entry;
  };

  graph.blocks.forEach((block) => {
    const details = block.instructionDetails;
    if (!details) {
      return;
    }

    const functionId = functionIdFor(block);
    details.forEach((detail, index) => {
      const location = locationFor(block.id, detail, index);

      definitionsFor(detail).forEach((value) => entryFor(functionId, value).definitions.push(location));

      detail.uses.forEach((value) => {
        entryFor(functionId, value).uses.push(location);
      });
    });
  });

  return [...entries.values()];
}

/**
 * Returns all instructions and blocks that define or consume one SSA value.
 * Multiple definitions and empty definition lists are preserved as evidence of
 * ambiguous and externally-defined values respectively.
 */
export function traceValueFlow(graph: SSAGraph, functionId: string, value: string): ValueFlowTrace {
  const entry = buildValueFlow(graph).find(
    (candidate) => candidate.functionId === functionId && candidate.label === value,
  );
  if (!entry) {
    return { entry: undefined, blockIds: [], instructionKeys: [] };
  }

  const blockIds = new Set<string>();
  const instructionKeys = new Set<string>();
  [...entry.definitions, ...entry.uses].forEach((location) => {
    blockIds.add(location.blockId);
    instructionKeys.add(JSON.stringify([location.blockId, location.index]));
  });

  return {
    entry,
    blockIds: [...blockIds],
    instructionKeys: [...instructionKeys],
  };
}
