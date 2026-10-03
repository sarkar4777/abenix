// Types and helpers shared by the Source Watch screens. Mirrors app/routers/sources.py.
import { API_URL } from '@/lib/api-client';

export type SourceKind = 'html' | 'pdf' | 'xlsx' | 'csv' | 'json' | 'rss';
export type Health = 'ok' | 'new' | 'failing' | 'paused' | 'stopped';
export type Hint = 'low' | 'medium' | 'high';
export type Tier = 'low' | 'medium' | 'high' | 'critical';

export interface ChangeSummary {
  id: string;
  source_id: string;
  from_snapshot_id: string | null;
  to_snapshot_id: string;
  detected_at: string | null;
  summary: string;
  stats: Record<string, any>;
  materiality_hint: Hint;
  source_name?: string;
}

export interface Source {
  id: string;
  name: string;
  description: string;
  url: string;
  host: string;
  kind: SourceKind;
  cadence_minutes: number;
  active: boolean;
  paused_reason: string | null;
  credentials_key: string | null;
  headers: Record<string, string>;
  selector: string | null;
  jurisdiction: string | null;
  tags: string[];
  risk_tier: Tier;
  ingest_to_kb: string | null;
  kb_document_id: string | null;
  kb_name?: string | null;
  created_at: string | null;
  updated_at: string | null;
  next_check_at: string | null;
  last_checked_at: string | null;
  last_changed_at: string | null;
  last_status: string | null;
  last_error: string | null;
  consecutive_failures: number;
  etag: string | null;
  last_modified: string | null;
  current_snapshot_id: string | null;
  check_count: number;
  health: Health;
  snapshot_count?: number;
  change_count?: number;
  latest_change?: ChangeSummary | null;
}

export interface Snapshot {
  id: string;
  source_id: string;
  url: string;
  kind: SourceKind;
  content_sha256: string;
  text_sha256: string;
  content_type: string;
  bytes: number;
  http_status: number;
  http_headers: Record<string, string>;
  fetched_at: string | null;
  parser_version: string;
  title: string | null;
  text_truncated: boolean;
  notes: string[];
  text_chars?: number;
  current?: boolean;
  change?: ChangeSummary | null;
  text?: string;
  tables?: Record<string, string[][]> | null;
  source?: { id: string; name: string } | null;
}

export interface DiffLine { op: ' ' | '+' | '-'; text: string; old: number | null; new: number | null }
export interface Hunk { old_start: number; old_len: number; new_start: number; new_len: number; lines: DiffLine[] }
export interface SheetDiff {
  name: string;
  header: string[];
  header_changed: boolean;
  key_column: string | null;
  added: string[][];
  removed: string[][];
  changed: { key: string; before: string[]; after: string[]; columns: string[]; indexes: number[] }[];
  rows_old: number;
  rows_new: number;
  truncated: boolean;
  added_total?: number;
  removed_total?: number;
  changed_total?: number;
}
export interface Diff {
  kind: 'text' | 'table';
  hunks?: Hunk[];
  added?: string[];
  removed?: string[];
  sheets?: SheetDiff[];
  truncated?: boolean;
  stats?: Record<string, any>;
}
export interface ChangeDetail extends ChangeSummary {
  diff: Diff;
  source: { id: string; name: string; url: string; kind: SourceKind } | null;
  from_snapshot: Snapshot | null;
  to_snapshot: Snapshot | null;
}

export interface SourceSettings {
  host_allowlist: string[];
  pause_after_failures: number;
  credential_keys: { key: string; set: boolean }[];
  private_targets_allowed: boolean;
  limits: { max_bytes: number; timeout_seconds: number; host_interval_seconds: number; min_cadence_minutes: number; max_cadence_minutes: number };
  kinds: SourceKind[];
}

export interface Preview {
  ok: boolean;
  error?: string;
  blocked?: boolean;
  kind?: SourceKind;
  detected_kind?: SourceKind;
  status?: number | null;
  final_url?: string;
  elapsed_ms?: number;
  content_type?: string;
  bytes?: number;
  sha256?: string;
  title?: string;
  text?: string;
  text_chars?: number;
  lines?: number;
  notes?: string[];
  table?: { name: string; rows: string[][]; total_rows: number; sheets: string[] } | null;
  etag?: string | null;
  last_modified?: string | null;
}

export const KIND_LABEL: Record<SourceKind, string> = {
  html: 'Web page',
  pdf: 'PDF',
  xlsx: 'Excel',
  csv: 'CSV',
  json: 'JSON',
  rss: 'RSS / Atom',
};

export const SELECTOR_HELP: Record<SourceKind, { label: string; placeholder: string; help: string } | null> = {
  html: { label: 'Only watch part of the page', placeholder: 'main #content, article.guidance', help: 'A CSS selector: tag, #id, .class or [attr=value], with spaces for nesting and commas for several parts.' },
  json: { label: 'Only watch part of the document', placeholder: '/data/items', help: 'A JSON pointer that starts with /.' },
  xlsx: { label: 'Only watch one sheet', placeholder: 'Sheet1', help: 'The sheet name exactly as it appears in the workbook.' },
  pdf: null,
  csv: null,
  rss: null,
};

export const HEALTH_STYLE: Record<Health, { label: string; chip: string; dot: string }> = {
  ok: { label: 'Watching', chip: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300', dot: 'bg-emerald-400' },
  new: { label: 'First check pending', chip: 'border-sky-500/30 bg-sky-500/10 text-sky-300', dot: 'bg-sky-400' },
  failing: { label: 'Failing', chip: 'border-amber-500/30 bg-amber-500/10 text-amber-300', dot: 'bg-amber-400' },
  paused: { label: 'Paused', chip: 'border-slate-600 bg-slate-800/60 text-slate-300', dot: 'bg-slate-400' },
  stopped: { label: 'Stopped by kill switch', chip: 'border-rose-500/30 bg-rose-500/10 text-rose-300', dot: 'bg-rose-400' },
};

export const HINT_STYLE: Record<Hint, { label: string; chip: string }> = {
  high: { label: 'Likely material', chip: 'border-rose-500/30 bg-rose-500/10 text-rose-300' },
  medium: { label: 'Worth a look', chip: 'border-amber-500/30 bg-amber-500/10 text-amber-300' },
  low: { label: 'Minor', chip: 'border-slate-600 bg-slate-800/60 text-slate-300' },
};

export const STATUS_TEXT: Record<string, string> = {
  changed: 'Changed',
  unchanged: 'No change',
  not_modified: 'No change (site said not modified)',
  baseline: 'Baseline captured',
  error: 'Check failed',
  stopped: 'Stopped by a kill switch',
};

export const CADENCES: { minutes: number; label: string }[] = [
  { minutes: 15, label: 'Every 15 minutes' },
  { minutes: 60, label: 'Hourly' },
  { minutes: 360, label: 'Every 6 hours' },
  { minutes: 1440, label: 'Daily' },
  { minutes: 10080, label: 'Weekly' },
];

export function cadenceLabel(m: number): string {
  const hit = CADENCES.find((c) => c.minutes === m);
  if (hit) return hit.label;
  if (m % 1440 === 0) return `Every ${m / 1440} days`;
  if (m % 60 === 0) return `Every ${m / 60} hours`;
  return `Every ${m} minutes`;
}

export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return 'never';
  const s = Math.round((now - new Date(iso).getTime()) / 1000);
  const future = s < 0;
  const a = Math.abs(s);
  if (a < 45) return future ? 'in a moment' : 'just now';
  if (a >= 86400 * 45) return new Date(iso).toLocaleDateString(undefined, { dateStyle: 'medium' });
  const txt = a < 3600 ? `${Math.round(a / 60)} min` : a < 86400 ? `${Math.round(a / 3600)} h` : `${Math.round(a / 86400)} d`;
  return future ? `in ${txt}` : `${txt} ago`;
}

export function when(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '';
}

export function bytes(n: number | undefined | null): string {
  if (!n) return '0 B';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function isHttpUrl(s: string): boolean {
  try {
    const u = new URL(s.trim());
    return (u.protocol === 'http:' || u.protocol === 'https:') && !!u.hostname;
  } catch {
    return false;
  }
}

export interface CheckOutcome {
  status: string;
  error?: string;
  note?: string;
  summary?: string;
  change_id?: string;
  snapshot_id?: string;
  materiality_hint?: Hint;
  consecutive_failures?: number;
  paused?: boolean;
  kb_document_id?: string;
  kb_error?: string;
}

export function describeOutcome(o: CheckOutcome): { tone: 'ok' | 'change' | 'bad'; text: string } {
  switch (o.status) {
    case 'changed':
      return { tone: 'change', text: `Changed. ${o.summary || ''}`.trim() };
    case 'baseline':
      return { tone: 'ok', text: o.note || 'Baseline captured. Later checks are compared with it.' };
    case 'unchanged':
      return { tone: 'ok', text: o.note || 'No change since the last snapshot.' };
    case 'not_modified':
      return { tone: 'ok', text: 'No change. The site confirmed nothing was modified.' };
    case 'error':
      return { tone: 'bad', text: `The check failed: ${o.error || 'unknown error'}${o.paused ? ' The source is now paused.' : ''}` };
    case 'stopped':
      return { tone: 'bad', text: o.error || 'A kill switch stops this source.' };
    default:
      return { tone: 'ok', text: STATUS_TEXT[o.status] || o.status };
  }
}

// The raw route needs the bearer token, so it is fetched and handed to the browser as a file.
export async function downloadRaw(snapshotId: string): Promise<string | null> {
  let token: string | null = null;
  try {
    token = localStorage.getItem('access_token');
  } catch {
    token = null;
  }
  const res = await fetch(`${API_URL}/api/sources/snapshots/${snapshotId}/raw`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    try {
      const j = await res.json();
      return j?.error?.message || `Download failed (${res.status})`;
    } catch {
      return `Download failed (${res.status})`;
    }
  }
  const blob = await res.blob();
  const name = /filename="([^"]+)"/.exec(res.headers.get('content-disposition') || '')?.[1] || `snapshot-${snapshotId}`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return null;
}
