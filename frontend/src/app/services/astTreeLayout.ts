export type AstTreeLayoutNode = {
  id: string;
  width: number;
  height: number;
};

export type AstTreeLayoutEdge = {
  source: string;
  target: string;
};

export type AstTreeLayoutDirection = 'TB' | 'LR';

export type AstTreeLayoutOptions = {
  direction: AstTreeLayoutDirection;
  nodesep: number;
  ranksep: number;
};

export type AstTreePosition = {
  x: number;
  y: number;
};

type NodeRecord = {
  node: AstTreeLayoutNode;
  children: string[];
};

type Placement = {
  id: string;
  crossOrigin: number;
};

const finiteNonNegative = (value: number) => Number.isFinite(value) && value >= 0;

/**
 * Positions a verified directed AST forest without changing its nodes or edges.
 * Positions are top-left coordinates, ordered by the supplied node and edge order.
 * Returns null for any graph that needs the general Dagre fallback.
 */
export function layoutAstForest(
  nodes: readonly AstTreeLayoutNode[],
  edges: readonly AstTreeLayoutEdge[],
  options: AstTreeLayoutOptions,
): Map<string, AstTreePosition> | null {
  if ((options.direction !== 'TB' && options.direction !== 'LR') || !finiteNonNegative(options.nodesep) || !finiteNonNegative(options.ranksep)) return null;

  const records = new Map<string, NodeRecord>();
  for (const node of nodes) {
    if (records.has(node.id) || !finiteNonNegative(node.width) || !finiteNonNegative(node.height)) return null;
    records.set(node.id, { node, children: [] });
  }

  const parents = new Set<string>();
  for (const edge of edges) {
    const source = records.get(edge.source);
    if (!source || !records.has(edge.target) || parents.has(edge.target)) return null;
    parents.add(edge.target);
    source.children.push(edge.target);
  }

  const roots = nodes.filter(node => !parents.has(node.id)).map(node => node.id);
  const postorder: string[] = [];
  for (const root of roots) {
    const stack: Array<{ id: string; expanded: boolean }> = [{ id: root, expanded: false }];
    while (stack.length) {
      const current = stack.pop()!;
      if (current.expanded) {
        postorder.push(current.id);
        continue;
      }
      stack.push({ id: current.id, expanded: true });
      const children = records.get(current.id)!.children;
      for (let index = children.length - 1; index >= 0; index -= 1) stack.push({ id: children[index], expanded: false });
    }
  }
  // With at most one parent, every unvisited node belongs to a directed cycle.
  if (postorder.length !== nodes.length) return null;

  const crossSize = (node: AstTreeLayoutNode) => options.direction === 'TB' ? node.width : node.height;
  const mainSize = (node: AstTreeLayoutNode) => options.direction === 'TB' ? node.height : node.width;
  const breadth = new Map<string, number>();
  for (const id of postorder) {
    const record = records.get(id)!;
    const childrenBreadth = record.children.reduce((sum, childId) => sum + breadth.get(childId)!, 0)
      + Math.max(0, record.children.length - 1) * options.nodesep;
    breadth.set(id, Math.max(crossSize(record.node), childrenBreadth));
  }

  const depths = new Map<string, number>();
  const maxMainAtDepth: number[] = [];
  const depthStack = roots.map(id => ({ id, depth: 0 }));
  while (depthStack.length) {
    const current = depthStack.pop()!;
    const record = records.get(current.id)!;
    depths.set(current.id, current.depth);
    maxMainAtDepth[current.depth] = Math.max(maxMainAtDepth[current.depth] ?? 0, mainSize(record.node));
    for (let index = record.children.length - 1; index >= 0; index -= 1) {
      depthStack.push({ id: record.children[index], depth: current.depth + 1 });
    }
  }
  const mainStart: number[] = [];
  for (let depth = 0; depth < maxMainAtDepth.length; depth += 1) {
    mainStart[depth] = depth === 0 ? 0 : mainStart[depth - 1] + maxMainAtDepth[depth - 1] + options.ranksep;
  }

  const positions = new Map<string, AstTreePosition>();
  const placements: Placement[] = [];
  let rootCross = 0;
  for (const root of roots) {
    placements.push({ id: root, crossOrigin: rootCross });
    rootCross += breadth.get(root)! + options.nodesep;
  }
  while (placements.length) {
    const current = placements.pop()!;
    const record = records.get(current.id)!;
    const nodeBreadth = breadth.get(current.id)!;
    const nodeCross = current.crossOrigin + (nodeBreadth - crossSize(record.node)) / 2;
    const main = mainStart[depths.get(current.id)!];
    positions.set(current.id, options.direction === 'TB' ? { x: nodeCross, y: main } : { x: main, y: nodeCross });

    const childrenBreadth = record.children.reduce((sum, childId) => sum + breadth.get(childId)!, 0)
      + Math.max(0, record.children.length - 1) * options.nodesep;
    let childCross = current.crossOrigin + (nodeBreadth - childrenBreadth) / 2;
    const children: Placement[] = [];
    for (const childId of record.children) {
      children.push({ id: childId, crossOrigin: childCross });
      childCross += breadth.get(childId)! + options.nodesep;
    }
    for (let index = children.length - 1; index >= 0; index -= 1) placements.push(children[index]);
  }

  return positions.size === nodes.length ? positions : null;
}
