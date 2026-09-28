/** A CFG block as exposed by the compiler graph API. */
export interface ControlFlowBlock {
  id: string;
  /** Declares a CFG entry when the entry has an incoming loop-back edge. */
  isEntry?: boolean;
  functionId?: string;
  predecessors?: string[];
  successors?: string[];
}

/** A directed relationship between two CFG blocks. */
export interface ControlFlowEdge {
  from: string;
  to: string;
}

export interface NaturalLoop {
  /** The dominator targeted by each loop-closing edge. */
  header: string;
  /** Blocks in the reverse-predecessor closure of the loop latches. */
  nodes: string[];
  backEdges: ControlFlowEdge[];
}

export interface ControlFlowAnalysis {
  /** CFG entries: declared entries and known blocks with no valid predecessor. */
  roots: string[];
  /**
   * Dominators for reachable blocks, including the block itself. Rootless
   * components have an empty list because there is no entry-based evidence.
   */
  dominators: Record<string, string[]>;
  /** The closest strict dominator, or null for entries and unanalyzed blocks. */
  immediateDominators: Record<string, string | null>;
  /** Reachable edges whose target dominates their source. */
  backEdges: ControlFlowEdge[];
  /** Natural loops, grouped by header. */
  loops: NaturalLoop[];
  /** Blocks that cannot be reached from any CFG entry. */
  unreachable: string[];
}

interface NormalizedControlFlowGraph {
  ids: string[];
  declaredEntries: Set<string>;
  incoming: Map<string, string[]>;
  outgoing: Map<string, string[]>;
  edges: ControlFlowEdge[];
}

const compareIds = (left: string, right: string): number => left.localeCompare(right);

const compareEdges = (left: ControlFlowEdge, right: ControlFlowEdge): number =>
  compareIds(left.from, right.from) || compareIds(left.to, right.to);

function intersectSets(sets: ReadonlySet<string>[]): Set<string> {
  if (sets.length === 0) {
    return new Set();
  }

  const [first, ...rest] = sets;
  return new Set([...first].filter((id) => rest.every((set) => set.has(id))));
}

function normalizeGraph(
  blocks: readonly ControlFlowBlock[],
  explicitEdges: readonly ControlFlowEdge[],
): NormalizedControlFlowGraph {
  const knownIds = new Set(blocks.map((block) => block.id));
  const ids = [...knownIds].sort(compareIds);
  const declaredEntries = new Set(blocks.filter((block) => block.isEntry).map((block) => block.id));
  const uniqueEdges = new Map<string, ControlFlowEdge>();

  const addEdge = (from: string, to: string): void => {
    if (!knownIds.has(from) || !knownIds.has(to)) {
      return;
    }

    // JSON CFG identifiers can contain any character, so avoid delimiter-based
    // edge keys that could accidentally collide.
    const key = JSON.stringify([from, to]);
    uniqueEdges.set(key, { from, to });
  };

  explicitEdges.forEach((edge) => addEdge(edge.from, edge.to));
  blocks.forEach((block) => {
    block.successors?.forEach((successor) => addEdge(block.id, successor));
    block.predecessors?.forEach((predecessor) => addEdge(predecessor, block.id));
  });

  const edges = [...uniqueEdges.values()].sort(compareEdges);
  const incoming = new Map<string, string[]>(ids.map((id): [string, string[]] => [id, []]));
  const outgoing = new Map<string, string[]>(ids.map((id): [string, string[]] => [id, []]));

  edges.forEach(({ from, to }) => {
    incoming.get(to)?.push(from);
    outgoing.get(from)?.push(to);
  });

  incoming.forEach((neighbors) => neighbors.sort(compareIds));
  outgoing.forEach((neighbors) => neighbors.sort(compareIds));

  return { ids, declaredEntries, incoming, outgoing, edges };
}

function collectReachable(roots: readonly string[], outgoing: ReadonlyMap<string, readonly string[]>): Set<string> {
  const reachable = new Set<string>();
  const pending = [...roots].reverse();

  while (pending.length > 0) {
    const id = pending.pop();
    if (id === undefined || reachable.has(id)) {
      continue;
    }

    reachable.add(id);
    const successors = outgoing.get(id) ?? [];
    for (let index = successors.length - 1; index >= 0; index -= 1) {
      const successor = successors[index];
      if (!reachable.has(successor)) {
        pending.push(successor);
      }
    }
  }

  return reachable;
}

function calculateDominators(
  ids: readonly string[],
  roots: ReadonlySet<string>,
  incoming: ReadonlyMap<string, readonly string[]>,
): Map<string, Set<string>> {
  const reachable = new Set(ids);
  const dominators = new Map<string, Set<string>>();

  ids.forEach((id) => {
    dominators.set(id, roots.has(id) ? new Set([id]) : new Set(reachable));
  });

  // Each change removes at least one member of a dominator set. This bound is
  // therefore sufficient while preventing malformed input from causing an
  // unbounded fixed-point calculation.
  const maximumIterations = Math.max(1, ids.length * ids.length + 1);
  for (let iteration = 0; iteration < maximumIterations; iteration += 1) {
    let changed = false;

    ids.forEach((id) => {
      if (roots.has(id)) {
        return;
      }

      const predecessorSets = (incoming.get(id) ?? [])
        .filter((predecessor) => reachable.has(predecessor))
        .map((predecessor) => dominators.get(predecessor) as ReadonlySet<string>);
      const next = intersectSets(predecessorSets);
      next.add(id);
      const current = dominators.get(id) as Set<string>;

      if (next.size !== current.size || [...next].some((member) => !current.has(member))) {
        dominators.set(id, next);
        changed = true;
      }
    });

    if (!changed) {
      break;
    }
  }

  return dominators;
}

function calculateImmediateDominators(
  ids: readonly string[],
  dominators: ReadonlyMap<string, ReadonlySet<string>>,
): Record<string, string | null> {
  return Object.fromEntries(
    ids.map((id) => {
      const strictDominators = [...(dominators.get(id) ?? new Set())]
        .filter((candidate) => candidate !== id)
        .sort(compareIds);
      const immediate = strictDominators.find((candidate) =>
        strictDominators.every(
          (other) => other === candidate || (dominators.get(candidate)?.has(other) ?? false),
        ),
      );

      return [id, immediate ?? null];
    }),
  );
}

function calculateNaturalLoops(
  backEdges: readonly ControlFlowEdge[],
  incoming: ReadonlyMap<string, readonly string[]>,
  reachable: ReadonlySet<string>,
): NaturalLoop[] {
  const byHeader = new Map<string, ControlFlowEdge[]>();
  backEdges.forEach((edge) => {
    const edges = byHeader.get(edge.to) ?? [];
    edges.push(edge);
    byHeader.set(edge.to, edges);
  });

  return [...byHeader.entries()]
    .sort(([left], [right]) => compareIds(left, right))
    .map(([header, headerBackEdges]) => {
      const nodes = new Set<string>([header]);
      const pending = headerBackEdges.map((edge) => edge.from).sort(compareIds).reverse();

      while (pending.length > 0) {
        const id = pending.pop();
        if (id === undefined || !reachable.has(id) || nodes.has(id)) {
          continue;
        }

        nodes.add(id);
        // Do not cross the loop header: its predecessors may be outside the loop.
        (incoming.get(id) ?? []).forEach((predecessor) => {
          if (reachable.has(predecessor) && !nodes.has(predecessor) && predecessor !== header) {
            pending.push(predecessor);
          }
        });
      }

      return {
        header,
        nodes: [...nodes].sort(compareIds),
        backEdges: [...headerBackEdges].sort(compareEdges),
      };
    });
}

/**
 * Analyzes a static control-flow graph. This describes possible graph paths;
 * it does not represent or predict a program's runtime execution path.
 */
export function analyzeControlFlow(
  blocks: readonly ControlFlowBlock[],
  edges: readonly ControlFlowEdge[],
): ControlFlowAnalysis {
  const graph = normalizeGraph(blocks, edges);
  const declaredFunctions = new Set(blocks.filter(block => block.isEntry && block.functionId).map(block => block.functionId));
  const functionById = new Map(blocks.map(block => [block.id, block.functionId]));
  const roots = graph.ids.filter(
    (id) => graph.declaredEntries.has(id) || (!declaredFunctions.has(functionById.get(id)) && (graph.incoming.get(id)?.length ?? 0) === 0),
  );
  const reachable = collectReachable(roots, graph.outgoing);
  const reachableIds = graph.ids.filter((id) => reachable.has(id));
  const unreachable = graph.ids.filter((id) => !reachable.has(id));
  const dominatorSets = calculateDominators(reachableIds, new Set(roots), graph.incoming);
  const immediateDominators = calculateImmediateDominators(reachableIds, dominatorSets);

  unreachable.forEach((id) => {
    immediateDominators[id] = null;
  });

  const dominators = Object.fromEntries(
    graph.ids.map((id) => [id, [...(dominatorSets.get(id) ?? [])].sort(compareIds)]),
  );
  const backEdges = graph.edges.filter(
    (edge) => reachable.has(edge.from) && reachable.has(edge.to) && (dominatorSets.get(edge.from)?.has(edge.to) ?? false),
  );

  return {
    roots,
    dominators,
    immediateDominators,
    backEdges,
    loops: calculateNaturalLoops(backEdges, graph.incoming, reachable),
    unreachable,
  };
}
