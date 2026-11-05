// How the canvas holds a piece of a graph too big to load whole.

export const FULL_GRAPH_NODES = 1000;
export const MAX_WINDOW_NODES = 1200;
export const OVERVIEW_NODES = 200;
export const VIEWPORT_NODES = 300;
export const NEIGHBOURS_PER_EXPAND = 100;
export const VISIBLE_ONLY_FROM = 200;

export interface HasId {
  id: string;
}

export interface EdgeEnds extends HasId {
  from_node_id: string;
  to_node_id: string;
}

export function isLargeGraph(nodeCount: number | null | undefined): boolean {
  return (nodeCount || 0) > FULL_GRAPH_NODES;
}

export function renderVisibleOnly(explore: boolean, loaded: number): boolean {
  return explore || loaded > VISIBLE_ONLY_FROM;
}

// Newest wins and the oldest fall out first, except what the user is looking at.
export function mergeWindow<N extends HasId, E extends EdgeEnds>(
  nodes: N[],
  edges: E[],
  incomingNodes: N[],
  incomingEdges: E[],
  keep: string[] = [],
  maxNodes: number = MAX_WINDOW_NODES,
): { nodes: N[]; edges: E[]; evicted: number } {
  const byId = new Map<string, N>();
  for (const n of nodes) byId.set(n.id, n);
  for (const n of incomingNodes) {
    byId.delete(n.id);
    byId.set(n.id, n);
  }
  const keepSet = new Set(keep);
  for (const n of incomingNodes) keepSet.add(n.id);
  let evicted = 0;
  if (byId.size > maxNodes) {
    for (const id of Array.from(byId.keys())) {
      if (byId.size <= maxNodes) break;
      if (keepSet.has(id)) continue;
      byId.delete(id);
      evicted += 1;
    }
  }
  const edgeById = new Map<string, E>();
  for (const e of [...edges, ...incomingEdges]) {
    if (byId.has(e.from_node_id) && byId.has(e.to_node_id)) edgeById.set(e.id, e);
  }
  return { nodes: Array.from(byId.values()), edges: Array.from(edgeById.values()), evicted };
}

export interface Rect {
  min_x: number;
  min_y: number;
  max_x: number;
  max_y: number;
}

export function viewportRect(
  transform: { x: number; y: number; zoom: number },
  width: number,
  height: number,
  margin = 0.25,
): Rect {
  const zoom = transform.zoom || 1;
  const w = width / zoom;
  const h = height / zoom;
  const minX = -transform.x / zoom;
  const minY = -transform.y / zoom;
  return {
    min_x: Math.round(minX - w * margin),
    min_y: Math.round(minY - h * margin),
    max_x: Math.round(minX + w * (1 + margin)),
    max_y: Math.round(minY + h * (1 + margin)),
  };
}

export function rectQuery(rect: Rect, limit: number = VIEWPORT_NODES): string {
  const q = new URLSearchParams({
    min_x: String(rect.min_x),
    min_y: String(rect.min_y),
    max_x: String(rect.max_x),
    max_y: String(rect.max_y),
    limit: String(limit),
  });
  return q.toString();
}

export function windowLabel(shown: number, total: number): string {
  return `Showing ${shown.toLocaleString()} of ${total.toLocaleString()} nodes. Search, pan or double-click a node to open its neighbours.`;
}
