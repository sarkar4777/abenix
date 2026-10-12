import { apiFetch } from '@/lib/api-client';

export type FieldKind = 'string' | 'int' | 'number' | 'bool' | 'select' | 'text' | 'file' | 'secret' | 'url';

export interface FieldDecl {
  key: string;
  label: string;
  kind: FieldKind;
  required?: boolean;
  default?: string | number | boolean | null;
  options?: { value: string; label: string }[];
  help?: string;
  example?: string;
  show_if?: Record<string, string | string[]>;
  required_if?: Record<string, string>;
  min?: number;
  max?: number;
  rows?: number;
  pattern?: string;
  accept?: string;
}

export interface CollectorType {
  type: string;
  label: string;
  short: string;
  description: string;
  category: 'vehicle' | 'plc' | 'sensor' | 'software';
  default_interval_s: number;
  asset_hint: { group: string; node: string; device: string };
  asset_templates?: boolean;
  device_from_bus?: boolean;
  fields: FieldDecl[];
}

export interface Catalog {
  types: CollectorType[];
  settings: FieldDecl[];
  asset_help: string;
}

export interface CollectorSpec {
  id?: string;
  type: string;
  name: string;
  enabled?: boolean;
  asset: { group?: string; node?: string; device?: string };
  interval_s?: number | string;
  dbc_bytes?: number;
  [key: string]: unknown;
}

export interface CollectorHealth {
  id: string;
  type: string;
  name: string;
  status: string;
  error: string | null;
  readings: number;
  readings_per_s?: number;
  last_reading_at?: number | null;
  subject?: string;
  bus_load_pct?: number;
  frames_per_s?: number;
  last_poll_ms?: number;
}

export interface BufferHealth {
  depth?: number;
  chunks?: number;
  bytes?: number;
  oldest_age_s?: number;
  max_bytes?: number;
  max_age_s?: number;
  sent?: number;
  written?: number;
  dropped_age?: number;
  dropped_size?: number;
  rejected?: number;
}

export interface UplinkHealth {
  status?: string;
  error?: string | null;
  last_ok_at?: number | null;
  batches?: number;
  retries?: number;
  gzip?: boolean;
}

export interface DeployedAgent {
  slug: string;
  agent_id: string;
  digest: string;
  deployed_at: string;
}

export interface Gateway {
  id: string;
  gateway_id: string;
  name: string;
  description?: string;
  endpoint_url: string | null;
  status: 'waiting' | 'expired' | 'online' | 'offline' | 'revoked' | string;
  roles: string[];
  deployed_agents: DeployedAgent[];
  registered_at: string | null;
  last_seen_at: string | null;
  enrolled_at: string | null;
  enroll_expires_at: string | null;
  revoked_at: string | null;
  first_data_at: string | null;
  version: string | null;
  platform: string | null;
  hostname: string | null;
  config_version: number;
  applied_version: number;
  config_pending: boolean;
  telemetry_connection_id: string | null;
  collector_count: number;
  buffer: BufferHealth;
  uplink: UplinkHealth;
  collector_health: CollectorHealth[];
  uptime_s?: number | null;
  problem?: string | null;
  collectors?: CollectorSpec[];
  settings?: Record<string, number | boolean>;
  assets?: AssetRow[];
  can_manage?: boolean;
}

export interface AssetRow {
  group: string;
  node: string;
  device: string;
  online: boolean;
  last_seen: number | null;
  metric_count?: number;
}

export interface InstallOut {
  gateway: Gateway;
  enroll_token: string;
  expires_at: string;
  platform_urls: { label: string; url: string }[];
  platform_url: string;
  image: string;
  docker_run: string;
  compose: string;
  kubernetes: string;
  systemd: string;
  can_setup: string;
  needs: { host_network: boolean; devices: string[]; folders: string[] };
  arm64_note: string;
}

export const MASK = '********';

export function isCollecting(g: Gateway): boolean {
  return (g.roles || []).includes('collect');
}

export function timeAgo(iso: string | number | null | undefined): string {
  if (iso === null || iso === undefined || iso === '') return 'never';
  const t = typeof iso === 'number' ? iso : Date.parse(iso);
  if (Number.isNaN(t)) return 'never';
  const diff = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (diff < 5) return 'just now';
  if (diff < 60) return `${diff} s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return `${Math.floor(diff / 86400)} d ago`;
}

export function duration(s: number | null | undefined): string {
  if (!s || s < 1) return 'none';
  if (s < 60) return `${Math.round(s)} s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  if (s < 86400) return `${(s / 3600).toFixed(1)} h`;
  return `${(s / 86400).toFixed(1)} days`;
}

export function bytes(n: number | null | undefined): string {
  if (!n) return '0 MB';
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export function count(n: number | null | undefined): string {
  return (n || 0).toLocaleString('en-GB');
}

export const STATUS: Record<string, { label: string; dot: string; chip: string; help: string }> = {
  online: { label: 'Online', dot: 'bg-emerald-400', chip: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200', help: 'Heard from in the last minute.' },
  offline: { label: 'Offline', dot: 'bg-amber-400', chip: 'border-amber-500/40 bg-amber-500/10 text-amber-200', help: 'No heartbeat for over a minute. Readings wait in its buffer until it is back.' },
  waiting: { label: 'Waiting for first start', dot: 'bg-sky-400', chip: 'border-sky-500/40 bg-sky-500/10 text-sky-200', help: 'Run its install command on the box. It shows up here within seconds.' },
  expired: { label: 'Install command expired', dot: 'bg-slate-400', chip: 'border-slate-500/40 bg-slate-700/30 text-slate-200', help: 'Install commands work for 24 hours. Make a new one.' },
  revoked: { label: 'Revoked', dot: 'bg-rose-400', chip: 'border-rose-500/40 bg-rose-500/10 text-rose-200', help: 'Abenix refuses its key. Re-enrol it to bring it back.' },
};

export function statusOf(s: string) {
  return STATUS[s] || STATUS.offline;
}

export const COLLECTOR_STATUS: Record<string, { label: string; tone: string }> = {
  running: { label: 'Running', tone: 'text-emerald-300' },
  starting: { label: 'Starting', tone: 'text-sky-300' },
  error: { label: 'Needs attention', tone: 'text-rose-300' },
  stopped: { label: 'Stopped', tone: 'text-slate-400' },
};

export async function edgeCall<T>(path: string, method = 'GET', body?: unknown): Promise<{ data: T | null; error: string | null; details?: Record<string, unknown> }> {
  const r = await apiFetch<T>(path, {
    method,
    silent: true,
    throwOnError: false,
    ...(body !== undefined ? { body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } } : {}),
  });
  if (r.error || r.data === null) {
    const msg = r.errorDetail?.message || r.error || 'Abenix did not answer. Check your connection and try again.';
    return { data: null, error: friendly(msg), details: r.errorDetail?.details };
  }
  return { data: r.data, error: null };
}

function friendly(msg: string): string {
  if (/failed to fetch|networkerror|load failed/i.test(msg)) return 'Could not reach Abenix. Check your connection and try again.';
  if (/^gateway not found$/i.test(msg)) return 'That gateway is gone. It may have been removed by someone else.';
  return msg;
}

export function defaultsFor(t: CollectorType, gatewayName: string, n: number): CollectorSpec {
  const spec: CollectorSpec = {
    type: t.type,
    name: n ? `${t.label} ${n + 1}` : t.label,
    asset: { ...t.asset_hint },
    interval_s: t.default_interval_s,
  };
  const node = gatewayName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  if (node && !t.asset_templates) spec.asset.node = node.slice(0, 64);
  for (const f of t.fields) {
    if (f.default !== undefined && f.default !== null) spec[f.key] = f.default;
  }
  return spec;
}

export function shown(f: FieldDecl, c: CollectorSpec, t: CollectorType): boolean {
  if (!f.show_if) return true;
  return Object.entries(f.show_if).every(([k, want]) => {
    const def = t.fields.find((x) => x.key === k)?.default;
    const have = String(c[k] ?? def ?? '');
    return Array.isArray(want) ? want.map(String).includes(have) : have === String(want);
  });
}

export function requiredNow(f: FieldDecl, c: CollectorSpec, t: CollectorType): boolean {
  if (f.required) return true;
  if (!f.required_if) return false;
  return Object.entries(f.required_if).every(([k, v]) => String(c[k] ?? t.fields.find((x) => x.key === k)?.default ?? '') === String(v));
}

const SLUG = /^[A-Za-z0-9_-]{1,64}$/;
const TEMPLATE = /^([A-Za-z0-9_-]|\{topic\.\d+\}){1,64}$/;

// the same checks the server makes, so problems show while typing
export function checkCollector(c: CollectorSpec, t: CollectorType): Record<string, string> {
  const p: Record<string, string> = {};
  if (!String(c.name || '').trim()) p.name = 'Give it a name people will recognise, such as Truck 12 engine bus';
  else if (String(c.name).length > 80) p.name = 'Keep the name under 80 characters';
  const pat = t.asset_templates ? TEMPLATE : SLUG;
  for (const [part, label, need] of [['group', 'Group', true], ['node', 'Asset', true], ['device', 'Part', false]] as const) {
    const v = String(c.asset?.[part] || '').trim();
    const hint = t.asset_hint[part] || 'engine';
    if (!v) {
      if (need) p[`asset.${part}`] = `${label} is needed, such as ${hint}`;
    } else if (!pat.test(v)) {
      p[`asset.${part}`] = `${label} may use letters, digits, - and _ only, such as ${hint}`;
    }
  }
  const iv = Number(c.interval_s);
  if (c.interval_s !== undefined && c.interval_s !== '' && (Number.isNaN(iv) || iv < 0.1 || iv > 3600)) {
    p.interval_s = 'Send every must be a number of seconds from 0.1 to 3600, such as 1';
  }
  for (const f of t.fields) {
    if (!shown(f, c, t)) continue;
    const v = c[f.key];
    const empty = v === undefined || v === null || (typeof v === 'string' && !v.trim());
    if (empty) {
      if (requiredNow(f, c, t) && f.kind !== 'bool' && !(f.kind === 'secret' && v === MASK)) {
        const ex = f.example || (f.default !== undefined && f.default !== null ? String(f.default) : '');
        p[f.key] = `${f.label} is needed${ex ? `, such as ${ex.split('\n')[0]}` : ''}`;
      }
      continue;
    }
    if (f.kind === 'int' || f.kind === 'number') {
      const n = Number(v);
      if (Number.isNaN(n) || (f.kind === 'int' && !Number.isInteger(n))) {
        p[f.key] = `${f.label} must be a ${f.kind === 'int' ? 'whole ' : ''}number`;
      } else if ((f.min !== undefined && n < f.min) || (f.max !== undefined && n > f.max)) {
        p[f.key] = `${f.label} must be from ${f.min} to ${f.max}`;
      }
    } else if (f.key === 'registers' && typeof v === 'string' && registerLinesProblem(v)) {
      p[f.key] = registerLinesProblem(v) as string;
    } else if (f.pattern && typeof v === 'string' && !new RegExp(f.pattern).test(v)) {
      p[f.key] = `${f.label} should look like ${f.example}`;
    }
  }
  return p;
}

export function telemetryHref(g: Gateway, a?: AssetRow): string {
  if (a) return `/telemetry?group=${encodeURIComponent(a.group)}&node=${encodeURIComponent(a.node)}`;
  const grp = g.collectors?.[0]?.asset?.group;
  return grp ? `/telemetry?grp=${encodeURIComponent(String(grp))}` : '/telemetry';
}

// after a field loses focus its problem shows, the rest wait for their own blur or for save
export function blurCheck(all: Record<string, string>, shownNow: Record<string, string> | undefined, key: string): Record<string, string> {
  const next = { ...(shownNow || {}) };
  if (all[key]) next[key] = all[key];
  else delete next[key];
  return next;
}

// while typing, only the problems already on screen update
export function keepShown(all: Record<string, string>, shownNow: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(all).filter(([k]) => k in shownNow));
}

// the field key behind an input in a collector form
export function fieldKeyOf(testId: string, prefix: string): string | null {
  if (!testId.startsWith(`${prefix}-`)) return null;
  const rest = testId.slice(prefix.length + 1);
  if (rest.startsWith('asset-')) return `asset.${rest.slice(6)}`;
  if (rest === 'interval') return 'interval_s';
  if (rest === 'drop' || rest.endsWith('-paste')) return null;
  return rest;
}

const REG_TABLES = ['holding', 'input', 'coil', 'discrete'];
const REG_TYPES = ['int16', 'uint16', 'int32', 'uint32', 'float32', 'int64', 'uint64', 'float64', 'bool'];

// the first Modbus register line that will not work, said in plain words
export function registerLinesProblem(text: string): string | null {
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i].trim();
    if (!raw || raw.startsWith('#')) continue;
    const parts = raw.split(',').map((x) => x.trim());
    const n = i + 1;
    if (parts.length < 3) return `Line ${n} needs at least a name, a table and an address, such as voltage_v, holding, 0`;
    const [name, table, address, type, scale] = parts;
    if (!name) return `Line ${n} has no name`;
    if (!REG_TABLES.includes(table.toLowerCase())) return `Line ${n}: the table "${table}" is not one of holding, input, coil or discrete`;
    if (!/^\d+$/.test(address)) return `Line ${n}: the address "${address}" must be a whole number, such as 0`;
    if (type && !REG_TYPES.includes(type.toLowerCase())) return `Line ${n}: the type "${type}" is not one of ${REG_TYPES.slice(0, 8).join(', ')}`;
    if (scale && Number.isNaN(Number(scale))) return `Line ${n}: the scale "${scale}" must be a number, such as 0.1`;
  }
  return null;
}
