import { create } from 'zustand';
import type { DeviceRow, Health, HistoryPoint, Metric } from './types';
import type { Batch } from './stream';
import { deviceKey, nodeKey, toMs } from './format';

export interface NodeEntry {
  key: string;
  group: string;
  node: string;
  // the node's own row, device ""
  self: DeviceRow | null;
  devices: Record<string, DeviceRow>;
}

// a live window per metric, long enough for the history chart's live tail
export const SAMPLE_WINDOW_MS = 30 * 60_000;
export const SAMPLE_CAP = 4000;

export interface AssetInfo {
  group: string;
  node: string;
  device?: string;
  display_name?: string | null;
  type?: string | null;
  tags?: string[];
  registered?: boolean;
}

export interface TelemetryState {
  nodes: Record<string, NodeEntry>;
  metrics: Record<string, Record<string, Metric>>;
  samples: Record<string, Record<string, HistoryPoint[]>>;
  health: Health | null;
  // msg/s per node from the ingest health, fresher than the device list
  nodeRates: Record<string, number>;
  // the asset registry by group/node, from the assets page
  assets: Record<string, AssetInfo>;
  setAssets: (rows: AssetInfo[]) => void;
  loaded: boolean;
  setNodeRates: (rates: Record<string, number>) => void;
  setRows: (rows: DeviceRow[]) => void;
  setDeviceMetrics: (group: string, node: string, device: string, metrics: Metric[]) => void;
  applyBatch: (b: Batch, now?: number) => void;
  reset: () => void;
}

function blankNode(group: string, node: string): NodeEntry {
  return { key: nodeKey(group, node), group, node, self: null, devices: {} };
}

function withDefaults(r: Partial<DeviceRow> & { group: string; node: string; device: string }, prev?: DeviceRow): DeviceRow {
  return {
    online: false, last_seen: null, birth_at: null, msgs_per_sec: 0, seq_gaps: 0, metric_count: 0,
    ...(prev ?? {}),
    ...r,
  } as DeviceRow;
}

// marks when it went offline if the server did not say
function merged(prev: DeviceRow | undefined, r: Partial<DeviceRow> & { group: string; node: string; device: string }, now: number): DeviceRow {
  const next = withDefaults(r, prev);
  if (prev?.online && next.online === false && !r.offline_at) next.offline_at = now;
  if (next.online) next.offline_at = null;
  return next;
}

export function buildNodes(rows: DeviceRow[], prev: Record<string, NodeEntry> = {}, now = Date.now()): Record<string, NodeEntry> {
  const out: Record<string, NodeEntry> = {};
  for (const r of rows) {
    const k = nodeKey(r.group, r.node);
    const entry = out[k] ?? (out[k] = blankNode(r.group, r.node));
    const old = r.device ? prev[k]?.devices[r.device] : prev[k]?.self ?? undefined;
    const row = merged(old, r, now);
    if (!r.offline_at && !row.online && !old) row.offline_at = toMs(r.last_seen);
    if (r.device) entry.devices[r.device] = row;
    else entry.self = row;
  }
  return out;
}

function trim(arr: HistoryPoint[], now: number): HistoryPoint[] {
  const cut = now - SAMPLE_WINDOW_MS;
  let i = 0;
  while (i < arr.length && arr[i].t < cut) i++;
  if (arr.length - i > SAMPLE_CAP) i = arr.length - SAMPLE_CAP;
  return i ? arr.slice(i) : arr;
}

export const useTelemetry = create<TelemetryState>((set) => ({
  nodes: {},
  metrics: {},
  samples: {},
  health: null,
  nodeRates: {},
  assets: {},
  setAssets: (rows) => set(() => {
    const assets: Record<string, AssetInfo> = {};
    for (const r of rows) if (!r.device) assets[nodeKey(r.group, r.node)] = r;
    return { assets };
  }),
  loaded: false,
  setNodeRates: (nodeRates) => set({ nodeRates }),
  setRows: (rows) => set((s) => ({ nodes: buildNodes(rows, s.nodes), loaded: true })),
  setDeviceMetrics: (group, node, device, list) =>
    set((s) => {
      const k = deviceKey(group, node, device);
      const map: Record<string, Metric> = {};
      for (const m of list) map[m.name] = m;
      return { metrics: { ...s.metrics, [k]: { ...(s.metrics[k] ?? {}), ...map } } };
    }),
  applyBatch: (b, now = Date.now()) =>
    set((s) => {
      const patch: Partial<TelemetryState> = {};
      if (b.snapshot) {
        patch.nodes = buildNodes(b.snapshot, s.nodes, now);
        patch.loaded = true;
      }
      if (b.devices.size) {
        const nodes = { ...(patch.nodes ?? s.nodes) };
        const touched = new Set<string>();
        b.devices.forEach((r) => {
          const k = nodeKey(r.group, r.node);
          if (!touched.has(k)) {
            const old = nodes[k];
            nodes[k] = old ? { ...old, devices: { ...old.devices } } : blankNode(r.group, r.node);
            touched.add(k);
          }
          const entry = nodes[k];
          if (r.device) entry.devices[r.device] = merged(entry.devices[r.device], r, now);
          else entry.self = merged(entry.self ?? undefined, r, now);
        });
        patch.nodes = nodes;
      }
      if (b.metrics.size) {
        const metrics = { ...s.metrics };
        const samples = { ...s.samples };
        b.metrics.forEach((slot, k) => {
          const cur = { ...(metrics[k] ?? {}) };
          slot.metrics.forEach((m, name) => {
            cur[name] = m;
          });
          metrics[k] = cur;
          if (slot.samples.size) {
            const sc = { ...(samples[k] ?? {}) };
            slot.samples.forEach((pts, name) => {
              sc[name] = trim([...(sc[name] ?? []), ...pts], now);
            });
            samples[k] = sc;
          }
        });
        patch.metrics = metrics;
        patch.samples = samples;
      }
      if (b.health) patch.health = { ...(s.health ?? {}), ...b.health };
      return patch;
    }),
  reset: () => set({ nodes: {}, metrics: {}, samples: {}, health: null, nodeRates: {}, assets: {}, loaded: false }),
}));

export type NodeStatus = 'online' | 'offline' | 'partial';

export function nodeStatus(n: NodeEntry): NodeStatus {
  const devs = Object.values(n.devices);
  if (n.self) {
    if (!n.self.online) return 'offline';
    return devs.some((d) => !d.online) ? 'partial' : 'online';
  }
  if (!devs.length) return 'offline';
  const up = devs.filter((d) => d.online).length;
  return up === 0 ? 'offline' : up === devs.length ? 'online' : 'partial';
}

export function nodeRate(n: NodeEntry): number {
  if (n.self && n.self.msgs_per_sec) return n.self.msgs_per_sec;
  return Object.values(n.devices).reduce((a, d) => a + (Number(d.msgs_per_sec) || 0), 0);
}

export function nodeGaps(n: NodeEntry): number {
  return (n.self?.seq_gaps ?? 0) + Object.values(n.devices).reduce((a, d) => a + (Number(d.seq_gaps) || 0), 0);
}

export function nodeLastSeen(n: NodeEntry): number | null {
  let best: number | null = toMs(n.self?.last_seen);
  for (const d of Object.values(n.devices)) {
    const t = toMs(d.last_seen);
    if (t !== null && (best === null || t > best)) best = t;
  }
  return best;
}

export interface NodeFilter { q: string; group: string; status: '' | 'online' | 'offline'; team: string; type?: string; tag?: string }

export function matchesNode(n: NodeEntry, f: NodeFilter, assets: Record<string, AssetInfo> = {}): boolean {
  if (f.group && n.group !== f.group) return false;
  const a = assets[n.key];
  if (f.type && (a?.type ?? '') !== f.type) return false;
  if (f.tag && !(a?.tags ?? []).includes(f.tag)) return false;
  const st = nodeStatus(n);
  if (f.status === 'online' && st === 'offline') return false;
  if (f.status === 'offline' && st === 'online') return false;
  if (f.team) {
    const teams = [n.self?.team_name, ...Object.values(n.devices).map((d) => d.team_name)];
    if (!teams.some((t) => (t ?? '') === f.team)) return false;
  }
  const q = f.q.trim().toLowerCase();
  if (!q) return true;
  if (n.node.toLowerCase().includes(q) || n.group.toLowerCase().includes(q) || (a?.display_name ?? '').toLowerCase().includes(q)) return true;
  return Object.keys(n.devices).some((d) => d.toLowerCase().includes(q));
}

// stable name order, so a node going offline never makes the cards jump
export function sortedNodes(nodes: Record<string, NodeEntry>, f: NodeFilter, assets: Record<string, AssetInfo> = {}): NodeEntry[] {
  return Object.values(nodes)
    .filter((n) => matchesNode(n, f, assets))
    .sort((a, b) => a.group.localeCompare(b.group) || a.node.localeCompare(b.node, undefined, { numeric: true }));
}
