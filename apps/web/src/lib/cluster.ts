// Types and pure helpers for the admin cluster view.

export type VerdictState = 'healthy' | 'degraded' | 'critical' | 'unknown';
export type ReasonLevel = 'critical' | 'warning' | 'info' | 'ok';
export type WorkloadStatus = 'healthy' | 'degraded' | 'down' | 'idle' | 'progressing';
export const GROUPS = ['Core', 'Runtime pools', 'Data', 'Apps'] as const;
export type Group = (typeof GROUPS)[number];

export interface Reason { level: ReasonLevel; text: string; target?: string | null; kind?: string }
export interface Verdict { state: VerdictState; label: string; reasons: Reason[] }

export interface NodeCondition { type: string; status: string; reason?: string | null; message?: string }
export interface ClusterNode {
  name: string;
  ready: boolean;
  unschedulable: boolean;
  roles: string[];
  pool?: string | null;
  zone?: string | null;
  instance_type?: string | null;
  kubelet_version?: string | null;
  os_image?: string | null;
  container_runtime?: string | null;
  created?: string | null;
  age_seconds?: number | null;
  cpu_cores: number;
  cpu_allocatable_cores: number;
  mem_bytes: number;
  mem_allocatable_bytes: number;
  pods_capacity: number;
  pods_here: number;
  cpu_requested_cores: number;
  mem_requested_bytes: number;
  cpu_used_cores: number | null;
  mem_used_bytes: number | null;
  cpu_pct: number | null;
  mem_pct: number | null;
  pressure: string[];
  conditions: NodeCondition[];
  taints: { key: string; value?: string | null; effect: string }[];
}

export interface Termination { reason?: string | null; exit_code?: number | null; at?: string | null; container?: string; pod?: string; message?: string }
export interface PodSummary {
  name: string;
  phase: string;
  status: string;
  ready: boolean;
  containers_ready: number;
  containers_total: number;
  restarts: number;
  node?: string | null;
  created?: string | null;
  age_seconds?: number | null;
  waiting?: { reason: string; message?: string; container?: string } | null;
  last_termination?: Termination | null;
  cpu_used_cores?: number | null;
  mem_used_bytes?: number | null;
  terminating?: boolean;
}
export interface ScaleMetric { name: string; label: string; current: string | null; current_value: number | null; target: string | null }
export interface Scaling {
  kind: 'keda' | 'hpa';
  name: string;
  min: number | null;
  max: number | null;
  current: number | null;
  desired: number | null;
  metrics: ScaleMetric[];
  active: boolean | null;
  paused: boolean | null;
  last_active?: string | null;
  triggers: string[];
}
export interface HistoryPoint { t: number; ready: number; desired: number }
export interface Workload {
  kind: 'Deployment' | 'StatefulSet';
  name: string;
  display: string;
  group: Group;
  critical: boolean;
  desired: number;
  ready: number;
  updated: number;
  available: number;
  status: WorkloadStatus;
  status_text: string;
  images: { container: string; image: string; tag: string }[];
  image_tag: string | null;
  created?: string | null;
  age_seconds?: number | null;
  restarts: number;
  last_restart: Termination | null;
  pods: PodSummary[];
  cpu_used_cores: number | null;
  mem_used_bytes: number | null;
  scaling: Scaling | null;
  history: HistoryPoint[];
}
export interface ClusterEvent {
  type: string;
  reason: string;
  message: string;
  kind?: string;
  object?: string;
  workload?: string | null;
  count: number;
  objects?: number;
  at: string;
  first_at?: string;
  age_seconds: number;
}
export interface AccessRow { key: string; label: string; why: string; scope: string; ok: boolean; optional: boolean; state?: string; fix?: string }
export interface Totals {
  nodes?: number;
  nodes_ready?: number;
  cpu_cores?: number;
  cpu_allocatable_cores?: number;
  mem_bytes?: number;
  mem_allocatable_bytes?: number;
  cpu_used_cores?: number | null;
  mem_used_bytes?: number | null;
  pods?: number;
  pod_phases?: Record<string, number>;
  services?: number;
  services_healthy?: number;
  restarts?: number;
  warnings_recent?: number;
}
export interface Overview {
  namespace: string;
  release: string;
  source: 'in-cluster' | 'kubeconfig' | 'outside' | string;
  outside_reason?: string;
  rbac_value: string;
  rbac_setting: string | null;
  generated_at: string;
  ttl_seconds: number;
  cache_age_seconds?: number;
  grafana_url?: string;
  nodes: ClusterNode[];
  workloads: Workload[];
  events: ClusterEvent[];
  pvcs: { pvc: string; requested_bytes: number; capacity_bytes: number; status?: string; storage_class?: string }[];
  access: AccessRow[];
  totals: Totals;
  verdict: Verdict;
}
export interface ContainerDetail {
  name: string;
  init: boolean;
  image: string;
  tag: string;
  ready: boolean;
  restarts: number;
  state: string;
  state_reason?: string | null;
  state_message?: string;
  started_at?: string | null;
  last_termination: Termination | null;
  requests: Record<string, string>;
  limits: Record<string, string>;
}
export interface PodDetail extends PodSummary {
  namespace?: string;
  owner_kind?: string | null;
  owner?: string | null;
  ip?: string | null;
  qos?: string | null;
  started?: string | null;
  conditions: NodeCondition[];
  containers: ContainerDetail[];
  events: { type: string; reason: string; message: string; count: number; at: string | null; age_seconds: number | null }[];
  events_error?: string | null;
}
export interface PodLogs { pod: string; container: string | null; previous: boolean; lines: string[]; truncated: boolean }

export function fmtBytes(n: number | null | undefined): string {
  if (n == null || !isFinite(n) || n <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}

export function fmtCores(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return '—';
  if (n === 0) return '0';
  if (n < 1) return `${Math.round(n * 1000)}m`;
  return n % 1 === 0 ? `${n}` : n.toFixed(n >= 10 ? 1 : 2);
}

export function fmtAge(seconds: number | null | undefined): string {
  if (seconds == null || !isFinite(seconds)) return '—';
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return m && h < 10 ? `${h}h ${m}m` : `${h}h`;
  }
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  return h && d < 10 ? `${d}d ${h}h` : `${d}d`;
}

export function agoText(seconds: number | null | undefined): string {
  if (seconds == null || !isFinite(seconds)) return '';
  if (seconds < 5) return 'just now';
  return `${fmtAge(seconds)} ago`;
}

export function secondsSince(iso: string | null | undefined, now = Date.now()): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return isNaN(t) ? null : Math.max(0, (now - t) / 1000);
}

export function pct(part: number | null | undefined, whole: number | null | undefined): number | null {
  if (part == null || !whole) return null;
  return Math.max(0, Math.min(100, (100 * part) / whole));
}

export function usageTone(p: number | null | undefined): 'ok' | 'warn' | 'bad' | 'none' {
  if (p == null) return 'none';
  if (p >= 90) return 'bad';
  if (p >= 75) return 'warn';
  return 'ok';
}

export const VERDICT_STYLE: Record<VerdictState, { ring: string; bg: string; text: string; dot: string }> = {
  healthy: { ring: 'border-emerald-500/40', bg: 'bg-emerald-500/10', text: 'text-emerald-300', dot: 'bg-emerald-400' },
  degraded: { ring: 'border-amber-500/40', bg: 'bg-amber-500/10', text: 'text-amber-300', dot: 'bg-amber-400' },
  critical: { ring: 'border-red-500/50', bg: 'bg-red-500/10', text: 'text-red-300', dot: 'bg-red-400' },
  unknown: { ring: 'border-slate-600/60', bg: 'bg-slate-800/40', text: 'text-slate-300', dot: 'bg-slate-400' },
};

export const STATUS_STYLE: Record<WorkloadStatus, { label: string; dot: string; text: string; chip: string }> = {
  healthy: { label: 'Healthy', dot: 'bg-emerald-400', text: 'text-emerald-300', chip: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' },
  idle: { label: 'Idle', dot: 'bg-slate-500', text: 'text-slate-400', chip: 'border-slate-600/50 bg-slate-800/60 text-slate-300' },
  progressing: { label: 'Rolling out', dot: 'bg-cyan-400', text: 'text-cyan-300', chip: 'border-cyan-500/30 bg-cyan-500/10 text-cyan-300' },
  degraded: { label: 'Degraded', dot: 'bg-amber-400', text: 'text-amber-300', chip: 'border-amber-500/30 bg-amber-500/10 text-amber-300' },
  down: { label: 'Down', dot: 'bg-red-500', text: 'text-red-300', chip: 'border-red-500/40 bg-red-500/10 text-red-300' },
};

export function isProblem(w: Workload): boolean {
  return w.status === 'down' || w.status === 'degraded' || (w.status === 'progressing' && w.pods.some((p) => !!p.waiting));
}

export type StatusFilter = 'all' | 'problems' | 'idle';

export function filterWorkloads(ws: Workload[], q: string, group: Group | 'all', status: StatusFilter): Workload[] {
  const needle = q.trim().toLowerCase();
  return ws.filter((w) => {
    if (group !== 'all' && w.group !== group) return false;
    if (status === 'problems' && !isProblem(w)) return false;
    if (status === 'idle' && w.status !== 'idle') return false;
    if (!needle) return true;
    const hay = [w.name, w.display, w.image_tag || '', w.status, ...w.pods.map((p) => p.name), ...w.images.map((i) => i.image)]
      .join(' ')
      .toLowerCase();
    return hay.includes(needle);
  });
}

export function groupWorkloads(ws: Workload[]): { group: Group; items: Workload[] }[] {
  return GROUPS.map((g) => ({ group: g, items: ws.filter((w) => w.group === g) })).filter((x) => x.items.length > 0);
}

export function groupSummary(items: Workload[]): { text: string; tone: 'ok' | 'warn' | 'bad' } {
  const down = items.filter((w) => w.status === 'down');
  const problems = items.filter(isProblem);
  const n = items.length;
  const noun = n === 1 ? 'service' : 'services';
  if (down.some((w) => w.critical)) return { text: `${n} ${noun}, ${down.length} down`, tone: 'bad' };
  if (problems.length) return { text: `${n} ${noun}, ${problems.length} need attention`, tone: 'warn' };
  return { text: `${n} ${noun}, all healthy`, tone: 'ok' };
}

export function scalingText(s: Scaling | null): string {
  if (!s) return 'Fixed size';
  const kind = s.kind === 'keda' ? 'KEDA' : 'HPA';
  const range = s.min != null && s.max != null ? `${s.min}–${s.max}` : '';
  if (s.paused) return `${kind} ${range}, paused`.trim();
  return `${kind} ${range}`.trim();
}

export function metricText(m: ScaleMetric): string {
  if (m.current == null) return m.target ? `${m.label}, target ${m.target}` : m.label;
  return m.target ? `${m.label}: ${m.current} / ${m.target}` : `${m.label}: ${m.current}`;
}

// SVG path points for a ready-replica sparkline, y grows downward.
export function sparkPoints(history: HistoryPoint[], width: number, height: number, pad = 2): { ready: string; desired: string; max: number } {
  if (history.length < 2) return { ready: '', desired: '', max: 0 };
  const max = Math.max(1, ...history.map((h) => Math.max(h.ready, h.desired)));
  const step = (width - pad * 2) / (history.length - 1);
  const y = (v: number) => (height - pad - (v / max) * (height - pad * 2)).toFixed(1);
  const line = (key: 'ready' | 'desired') => history.map((h, i) => `${(pad + i * step).toFixed(1)},${y(h[key])}`).join(' ');
  return { ready: line('ready'), desired: line('desired'), max };
}

export function hiddenAccess(access: AccessRow[]): { blocking: AccessRow[]; optional: AccessRow[] } {
  const missing = access.filter((a) => !a.ok);
  return {
    blocking: missing.filter((a) => a.state === 'forbidden' || (!a.optional && a.state !== 'not_installed')),
    optional: missing.filter((a) => a.state === 'not_installed' || (a.optional && a.state !== 'forbidden')),
  };
}

export function logFilter(lines: string[], q: string): string[] {
  const needle = q.trim().toLowerCase();
  if (!needle) return lines;
  return lines.filter((l) => l.toLowerCase().includes(needle));
}

// k8s timestamps prefix each log line, split them so the time can be dimmed
export function splitLogLine(line: string): { time: string; text: string } {
  const m = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\s?(.*)$/.exec(line);
  if (!m) return { time: '', text: line };
  return { time: m[1].slice(11, 19), text: m[2] };
}
