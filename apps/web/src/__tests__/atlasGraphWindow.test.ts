import { describe, expect, it } from 'vitest';
import {
  FULL_GRAPH_NODES,
  MAX_WINDOW_NODES,
  isLargeGraph,
  mergeWindow,
  rectQuery,
  renderVisibleOnly,
  viewportRect,
  windowLabel,
} from '@/components/atlas/graphWindow';

const node = (id: number) => ({ id: `n${id}` });
const edge = (a: number, b: number) => ({ id: `e${a}-${b}`, from_node_id: `n${a}`, to_node_id: `n${b}` });

describe('atlas graph window', () => {
  it('only a big graph goes into explore mode', () => {
    expect(isLargeGraph(FULL_GRAPH_NODES)).toBe(false);
    expect(isLargeGraph(FULL_GRAPH_NODES + 1)).toBe(true);
    expect(isLargeGraph(100000)).toBe(true);
    expect(isLargeGraph(null)).toBe(false);
  });

  it('renders only what is on screen once there is a lot of it', () => {
    expect(renderVisibleOnly(false, 50)).toBe(false);
    expect(renderVisibleOnly(false, 500)).toBe(true);
    expect(renderVisibleOnly(true, 10)).toBe(true);
  });

  it('never holds more than the cap however far you pan', () => {
    let state = { nodes: [] as { id: string }[], edges: [] as ReturnType<typeof edge>[] };
    for (let page = 0; page < 200; page += 1) {
      const incoming = Array.from({ length: 300 }, (_, i) => node(page * 300 + i));
      const links = incoming.slice(1).map((_, i) => edge(page * 300 + i, page * 300 + i + 1));
      state = mergeWindow(state.nodes, state.edges, incoming, links);
      expect(state.nodes.length).toBeLessThanOrEqual(MAX_WINDOW_NODES);
    }
    const ids = new Set(state.nodes.map(n => n.id));
    expect(state.edges.every(e => ids.has(e.from_node_id) && ids.has(e.to_node_id))).toBe(true);
  });

  it('keeps the selected node and evicts the oldest first', () => {
    const start = [node(1), node(2), node(3)];
    const out = mergeWindow(start, [], [node(4), node(5)], [], ['n1'], 3);
    expect(out.nodes.map(n => n.id).sort()).toEqual(['n1', 'n4', 'n5']);
    expect(out.evicted).toBe(2);
  });

  it('a fresher copy of a node replaces the old one and drops dangling edges', () => {
    const out = mergeWindow(
      [{ id: 'n1', label: 'old' }, { id: 'n2', label: 'b' }],
      [edge(1, 2), edge(2, 9)],
      [{ id: 'n1', label: 'new' }],
      [],
    );
    expect(out.nodes.find(n => n.id === 'n1')?.label).toBe('new');
    expect(out.edges.map(e => e.id)).toEqual(['e1-2']);
  });

  it('turns the canvas transform into a rectangle in graph coordinates', () => {
    const r = viewportRect({ x: -1000, y: -500, zoom: 0.5 }, 800, 600, 0);
    expect(r).toEqual({ min_x: 2000, min_y: 1000, max_x: 3600, max_y: 2200 });
    expect(rectQuery(r, 10)).toBe('min_x=2000&min_y=1000&max_x=3600&max_y=2200&limit=10');
  });

  it('says plainly what is on screen', () => {
    expect(windowLabel(200, 100000)).toContain('200 of 100,000 nodes');
  });
});
