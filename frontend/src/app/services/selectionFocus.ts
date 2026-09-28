export interface SelectionEdge {
  source: string;
  target: string;
}

/**
 * Expands selected graph nodes through undirected neighbors up to `depth`.
 * The result always contains every seed, including ids absent from the graph.
 */
export function getSelectionNeighborhood(
  seedIds: string[],
  edges: SelectionEdge[],
  depth: number,
): Set<string> {
  const maximumDepth = Number.isFinite(depth) && depth > 0 ? Math.floor(depth) : 0;
  const visited = new Set(seedIds);
  if (maximumDepth === 0 || visited.size === 0) {
    return visited;
  }

  const neighbors = new Map<string, Set<string>>();
  const addNeighbor = (from: string, to: string): void => {
    const adjacent = neighbors.get(from) ?? new Set<string>();
    adjacent.add(to);
    neighbors.set(from, adjacent);
  };

  edges.forEach(({ source, target }) => {
    addNeighbor(source, target);
    addNeighbor(target, source);
  });

  let frontier = [...visited];
  for (let currentDepth = 0; currentDepth < maximumDepth && frontier.length > 0; currentDepth += 1) {
    const next: string[] = [];
    frontier.forEach((nodeId) => {
      neighbors.get(nodeId)?.forEach((neighbor) => {
        if (!visited.has(neighbor)) {
          visited.add(neighbor);
          next.push(neighbor);
        }
      });
    });
    frontier = next;
  }

  return visited;
}
