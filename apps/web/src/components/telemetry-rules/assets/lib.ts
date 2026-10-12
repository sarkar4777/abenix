import { errLike, explainTelemetryError, isPlain } from '@/lib/telemetry/errors';

export const ASSET_TYPES = ['vehicle', 'machine', 'sensor', 'device', 'system'] as const;
export type AssetType = (typeof ASSET_TYPES)[number];

export const TYPE_INFO: Record<AssetType, { label: string; hint: string }> = {
  vehicle: { label: 'Vehicle', hint: 'Trucks, vans, cars and plant that moves' },
  machine: { label: 'Machine', hint: 'Fixed equipment like a press, pump or compressor' },
  sensor: { label: 'Sensor', hint: 'One measuring point, such as a temperature probe' },
  device: { label: 'Device', hint: 'A gateway, PLC, PC or other box that sends data' },
  system: { label: 'System', hint: 'Software, or a whole line that reports as one' },
};

export const FIXED_FIELDS = ['vin', 'plate', 'serial', 'model'] as const;
export type FixedField = (typeof FIXED_FIELDS)[number];
export const FIXED_LABEL: Record<FixedField, string> = { vin: 'VIN', plate: 'Plate', serial: 'Serial number', model: 'Model' };

export const LIMITS = { name: 120, tags: 20, tag: 40, fields: 30, fieldKey: 40, fieldValue: 200, importRows: 5000, importBytes: 2 * 1024 * 1024 };

export type AssetLocation = { lat: number; lon: number; label?: string } | { x: number; y: number; label?: string };

export interface AssetRow {
  id: string | null;
  key: string;
  group: string;
  node: string;
  device: string;
  registered: boolean;
  display_name: string | null;
  type: string | null;
  tags: string[];
  team_id: string | null;
  team_name: string | null;
  location: AssetLocation | null;
  fields: Record<string, string>;
  live: boolean;
  online: boolean | null;
  last_seen: number | null;
  connection_id: string | null;
  parts?: string[];
  updated_at: string | null;
  can_edit: boolean;
}

export interface AssetsMeta {
  total?: number;
  limit?: number;
  offset?: number;
  registered?: number;
  unregistered?: number;
  types?: Record<string, number>;
  tags?: Array<{ tag: string; count: number }>;
}

export type AssetStatus = '' | 'registered' | 'unregistered';

export interface AssetFilter {
  q: string;
  type: string;
  tag: string;
  status: AssetStatus;
  parts: boolean;
}

export const NO_FILTER: AssetFilter = { q: '', type: '', tag: '', status: '', parts: false };

export function filterFromParams(get: (k: string) => string | null): AssetFilter {
  const status = get('status') || '';
  return {
    q: get('q') || '',
    type: get('type') || '',
    tag: get('tag') || '',
    status: status === 'registered' || status === 'unregistered' ? status : '',
    parts: get('parts') === '1',
  };
}

export function isFiltered(f: AssetFilter): boolean {
  return !!(f.q.trim() || f.type || f.tag || f.status);
}

export function assetKey(group: string, node: string, device = ''): string {
  return `${group}/${node}/${device}`;
}

export function rowKey(r: Pick<AssetRow, 'group' | 'node' | 'device'>): string {
  return assetKey(r.group, r.node, r.device || '');
}

// "g/n/d", "g/n/" and "g/n" all work, the part keeps any slashes after the second one
export function parseAssetKey(raw: string | null | undefined): { group: string; node: string; device: string } | null {
  if (!raw) return null;
  const a = raw.indexOf('/');
  if (a <= 0) return null;
  const b = raw.indexOf('/', a + 1);
  const node = b < 0 ? raw.slice(a + 1) : raw.slice(a + 1, b);
  if (!node) return null;
  return { group: raw.slice(0, a), node, device: b < 0 ? '' : raw.slice(b + 1) };
}

export function assetPath(group: string, node: string, device: string): string {
  return `/api/telemetry/assets/${encodeURIComponent(group)}/${encodeURIComponent(node)}?device=${encodeURIComponent(device)}`;
}

export function listUrl(f: AssetFilter, server = false, limit = 5000): string {
  const p = new URLSearchParams({ limit: String(limit) });
  if (f.parts) p.set('parts', '1');
  if (server) {
    if (f.q.trim()) p.set('q', f.q.trim());
    if (f.type) p.set('type', f.type);
    if (f.tag) p.set('tag', f.tag);
    if (f.status) p.set('status', f.status);
  }
  return `/api/telemetry/assets?${p.toString()}`;
}

export function matchAsset(r: AssetRow, f: AssetFilter): boolean {
  if (!f.parts && r.device) return false;
  if (f.status === 'registered' && !r.registered) return false;
  if (f.status === 'unregistered' && r.registered) return false;
  if (f.type && r.type !== f.type) return false;
  if (f.tag && !(r.tags || []).includes(f.tag.toLowerCase())) return false;
  const q = f.q.trim().toLowerCase();
  if (!q) return true;
  const hay = [
    r.display_name, r.key, rowKey(r), r.type, r.team_name,
    ...(r.tags || []),
    ...Object.values(r.fields || {}),
    r.location?.label,
  ].filter(Boolean).join(' ').toLowerCase();
  return q.split(/\s+/).every((w) => hay.includes(w));
}

// assets by name, each part right under its asset
export function sortAssets(rows: AssetRow[]): AssetRow[] {
  const label = new Map<string, string>();
  for (const r of rows) if (!r.device) label.set(`${r.group}/${r.node}`, (r.display_name || r.node).toLowerCase());
  const keyed = rows.map((r) => ({ r, k: label.get(`${r.group}/${r.node}`) ?? r.node.toLowerCase() }));
  keyed.sort((a, b) =>
    a.k.localeCompare(b.k, undefined, { numeric: true })
    || a.r.group.localeCompare(b.r.group)
    || a.r.node.localeCompare(b.r.node, undefined, { numeric: true })
    || (a.r.device ? 1 : 0) - (b.r.device ? 1 : 0)
    || (a.r.display_name || a.r.device).localeCompare(b.r.display_name || b.r.device, undefined, { numeric: true }));
  return keyed.map((x) => x.r);
}

export function facetsOf(rows: AssetRow[]): { types: Array<{ value: string; count: number }>; tags: Array<{ value: string; count: number }> } {
  const types = new Map<string, number>();
  const tags = new Map<string, number>();
  for (const r of rows) {
    if (r.type) types.set(r.type, (types.get(r.type) ?? 0) + 1);
    for (const t of r.tags || []) tags.set(t, (tags.get(t) ?? 0) + 1);
  }
  const out = (m: Map<string, number>) => Array.from(m.entries()).map(([value, count]) => ({ value, count })).sort((a, b) => a.value.localeCompare(b.value));
  return { types: out(types), tags: out(tags) };
}

export function nextUnregistered(rows: AssetRow[], after: string | null): string | null {
  const open = rows.filter((r) => !r.registered && rowKey(r) !== after);
  if (!open.length) return null;
  if (after) {
    const i = rows.findIndex((r) => rowKey(r) === after);
    const later = rows.slice(i + 1).find((r) => !r.registered);
    if (later) return rowKey(later);
  }
  return rowKey(open[0]);
}

export function replaceRow(rows: AssetRow[], row: AssetRow): AssetRow[] {
  const k = rowKey(row);
  let hit = false;
  const out = rows.map((r) => {
    if (rowKey(r) !== k) return r;
    hit = true;
    return { ...r, ...row, parts: row.parts ?? r.parts };
  });
  return hit ? out : rows;
}

export function pageSlice(total: number, page: number, size = 100, plainMax = 200): { from: number; to: number; pages: number; page: number } {
  if (total <= plainMax) return { from: 0, to: total, pages: 1, page: 0 };
  const pages = Math.ceil(total / size);
  const p = Math.min(Math.max(0, page), pages - 1);
  return { from: p * size, to: Math.min(total, (p + 1) * size), pages, page: p };
}

function num(v: number): string {
  return Number.isInteger(v) ? String(v) : String(Number(v.toFixed(5)));
}

export function locationText(loc: AssetLocation | null | undefined): string {
  if (!loc) return '';
  const label = loc.label?.trim();
  const where = 'lat' in loc ? `${num(loc.lat)}, ${num(loc.lon)}` : `x ${num(loc.x)}, y ${num(loc.y)}`;
  return label ? `${label} (${where})` : where;
}

export function keyFieldsText(fields: Record<string, string> | null | undefined): string {
  if (!fields) return '';
  return FIXED_FIELDS.filter((k) => fields[k]).map((k) => `${FIXED_LABEL[k]} ${fields[k]}`).join(', ');
}

export function typeLabel(t: string | null | undefined): string {
  if (!t) return '';
  return (TYPE_INFO as Record<string, { label: string }>)[t]?.label ?? t.charAt(0).toUpperCase() + t.slice(1);
}

export function statusOf(r: Pick<AssetRow, 'live' | 'online'>): { tone: 'online' | 'offline' | 'unknown'; label: string } {
  if (r.online === true) return { tone: 'online', label: 'Online' };
  if (r.online === false) return { tone: 'offline', label: 'Offline' };
  return { tone: 'unknown', label: r.live ? 'Status unknown' : 'No data yet' };
}

// tags

const TAG_RE = /^[\p{L}\p{N} _.\-:/]+$/u;

export function tagProblem(raw: string): string | null {
  const t = raw.trim();
  if (!t) return 'A tag cannot be empty.';
  if (t.length > LIMITS.tag) return `Keep each tag to ${LIMITS.tag} characters or fewer.`;
  if (!TAG_RE.test(t)) return `"${t}" has a character tags cannot use. Use letters, digits, spaces and _ . - : /`;
  return null;
}

export function addTags(existing: string[], raw: string): { tags: string[]; problem: string | null } {
  const tags = [...existing];
  let problem: string | null = null;
  for (const part of raw.split(',')) {
    const t = part.trim().toLowerCase();
    if (!t) continue;
    const p = tagProblem(t);
    if (p) { problem = problem ?? p; continue; }
    if (tags.includes(t)) continue;
    if (tags.length >= LIMITS.tags) { problem = problem ?? `An asset can have up to ${LIMITS.tags} tags. Remove one to add another.`; continue; }
    tags.push(t);
  }
  return { tags, problem };
}

// the editor's working copy

export type LocKind = 'none' | 'gps' | 'site';
export interface FieldRow { id: string; key: string; value: string }

export interface AssetDraft {
  display_name: string;
  type: AssetType | '';
  tags: string[];
  team_id: string;
  loc: LocKind;
  lat: string;
  lon: string;
  x: string;
  y: string;
  label: string;
  fixed: Record<FixedField, string>;
  custom: FieldRow[];
}

let rid = 0;
export function newFieldRow(key = '', value = ''): FieldRow {
  rid += 1;
  return { id: `f${rid}`, key, value };
}

export function draftFromRow(r: Partial<AssetRow> | null | undefined): AssetDraft {
  const fields = r?.fields || {};
  const loc = r?.location ?? null;
  const fixed = { vin: '', plate: '', serial: '', model: '' } as Record<FixedField, string>;
  const custom: FieldRow[] = [];
  for (const [k, v] of Object.entries(fields)) {
    if ((FIXED_FIELDS as readonly string[]).includes(k)) fixed[k as FixedField] = String(v ?? '');
    else custom.push(newFieldRow(k, String(v ?? '')));
  }
  const isGps = !!loc && 'lat' in loc;
  const isSite = !!loc && 'x' in loc;
  return {
    display_name: r?.display_name ?? '',
    type: (ASSET_TYPES as readonly string[]).includes(r?.type ?? '') ? (r!.type as AssetType) : '',
    tags: [...(r?.tags || [])],
    team_id: r?.team_id ?? '',
    loc: isGps ? 'gps' : isSite ? 'site' : 'none',
    lat: isGps ? String((loc as { lat: number }).lat) : '',
    lon: isGps ? String((loc as { lon: number }).lon) : '',
    x: isSite ? String((loc as { x: number }).x) : '',
    y: isSite ? String((loc as { y: number }).y) : '',
    label: loc?.label ?? '',
    fixed,
    custom,
  };
}

// lower case, spaces and dashes become underscores, so "Fleet no" is fleet_no
export function fieldKeyFrom(raw: string): string {
  return raw.toLowerCase().replace(/[\s-]+/g, '_');
}

type Num = { ok: true; value: number } | { ok: false; problem: string };

function readNum(raw: string, what: string, lo?: number, hi?: number): Num {
  const s = raw.trim();
  if (!s) return { ok: false, problem: `Enter the ${what}.` };
  if (/^-?\d+,\d+$/.test(s)) return { ok: false, problem: `Use a dot for decimals, like ${s.replace(',', '.')}.` };
  const n = Number(s);
  if (!Number.isFinite(n) || !/^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(s)) return { ok: false, problem: `The ${what} must be a number.` };
  if (lo !== undefined && hi !== undefined && (n < lo || n > hi)) return { ok: false, problem: `The ${what} must be between ${lo} and ${hi}.` };
  return { ok: true, value: n };
}

export type DraftErrors = Record<string, string>;

export function validateDraft(d: AssetDraft): DraftErrors {
  const e: DraftErrors = {};
  if (d.display_name.trim().length > LIMITS.name) e.display_name = `Keep the name to ${LIMITS.name} characters or fewer. It has ${d.display_name.trim().length}.`;
  if (d.type && !(ASSET_TYPES as readonly string[]).includes(d.type)) e.type = 'Pick one of the five types, or Not set.';
  if (d.tags.length > LIMITS.tags) e.tags = `An asset can have up to ${LIMITS.tags} tags. Remove ${d.tags.length - LIMITS.tags}.`;
  else {
    const bad = d.tags.map(tagProblem).find(Boolean);
    if (bad) e.tags = bad;
  }
  if (d.loc === 'gps') {
    const lat = readNum(d.lat, 'latitude', -90, 90);
    const lon = readNum(d.lon, 'longitude', -180, 180);
    if (!lat.ok) e.lat = lat.problem;
    if (!lon.ok) e.lon = lon.problem;
  } else if (d.loc === 'site') {
    const x = readNum(d.x, 'x position');
    const y = readNum(d.y, 'y position');
    if (!x.ok) e.x = x.problem;
    if (!y.ok) e.y = y.problem;
  }
  for (const k of FIXED_FIELDS) {
    if (d.fixed[k].trim().length > LIMITS.fieldValue) e[k] = `Keep it to ${LIMITS.fieldValue} characters or fewer.`;
  }
  const seen = new Set<string>(FIXED_FIELDS.filter((k) => d.fixed[k].trim()));
  for (const row of d.custom) {
    const k = row.key.trim();
    const v = row.value.trim();
    if (!k && !v) continue;
    if (!k) { e[`custom.${row.id}.key`] = 'Name this field, for example fleet_no.'; continue; }
    if (k.length > LIMITS.fieldKey) e[`custom.${row.id}.key`] = `Keep the field name to ${LIMITS.fieldKey} characters or fewer.`;
    else if (!/^[a-z0-9_]+$/.test(k)) e[`custom.${row.id}.key`] = 'Field names use lower case letters, digits and _ only.';
    else if ((FIXED_FIELDS as readonly string[]).includes(k)) e[`custom.${row.id}.key`] = `${FIXED_LABEL[k as FixedField]} has its own box above. Use that one.`;
    else if (seen.has(k)) e[`custom.${row.id}.key`] = 'Another field already has this name.';
    if (!v) e[`custom.${row.id}.value`] = 'Give it a value, or remove the field.';
    else if (v.length > LIMITS.fieldValue) e[`custom.${row.id}.value`] = `Keep it to ${LIMITS.fieldValue} characters or fewer.`;
    seen.add(k);
  }
  if (seen.size > LIMITS.fields) e.fields = `An asset can have up to ${LIMITS.fields} fields. Remove ${seen.size - LIMITS.fields}.`;
  return e;
}

export interface AssetPayload {
  display_name: string | null;
  type: AssetType | null;
  tags: string[];
  team_id: string | null;
  location: AssetLocation | null;
  fields: Record<string, string>;
}

export function toPayload(d: AssetDraft): AssetPayload {
  const label = d.label.trim();
  let location: AssetLocation | null = null;
  if (d.loc === 'gps') location = { lat: Number(d.lat.trim()), lon: Number(d.lon.trim()), ...(label ? { label } : {}) };
  else if (d.loc === 'site') location = { x: Number(d.x.trim()), y: Number(d.y.trim()), ...(label ? { label } : {}) };
  const entries: Array<[string, string]> = [];
  for (const k of FIXED_FIELDS) if (d.fixed[k].trim()) entries.push([k, d.fixed[k].trim()]);
  for (const r of d.custom) if (r.key.trim() && r.value.trim()) entries.push([r.key.trim(), r.value.trim()]);
  entries.sort((a, b) => a[0].localeCompare(b[0]));
  return {
    display_name: d.display_name.trim() || null,
    type: d.type || null,
    tags: d.tags,
    team_id: d.team_id || null,
    location,
    fields: Object.fromEntries(entries),
  };
}

export function isDirty(d: AssetDraft, original: AssetDraft): boolean {
  return JSON.stringify(toPayload(d)) !== JSON.stringify(toPayload(original));
}

// the server's {field: message} placed under the matching box, anything else goes on top
export function placeServerErrors(fields: unknown, d: AssetDraft): DraftErrors {
  const out: DraftErrors = {};
  if (!fields || typeof fields !== 'object') return out;
  const put = (k: string, m: string) => { out[k] = out[k] ? `${out[k]} ${m}` : m; };
  for (const [raw, msg] of Object.entries(fields as Record<string, unknown>)) {
    const m = String(msg ?? '').trim() || 'This is not valid.';
    const k = raw.replace(/\[(\w+)\]/g, '.$1');
    if (k === 'display_name' || k === 'name') put('display_name', m);
    else if (k === 'type') put('type', m);
    else if (k.startsWith('tags')) put('tags', m);
    else if (k === 'team_id' || k === 'team') put('team_id', m);
    else if (/^location\.(lat|lon|x|y)$/.test(k)) put(k.split('.')[1], m);
    else if (k.startsWith('location')) put(d.loc === 'gps' ? 'lat' : d.loc === 'site' ? 'x' : 'location', m);
    else if (k.startsWith('fields.')) {
      const fk = k.slice(7);
      if ((FIXED_FIELDS as readonly string[]).includes(fk)) put(fk, m);
      else {
        const row = d.custom.find((r) => r.key.trim() === fk);
        put(row ? `custom.${row.id}.value` : 'fields', m);
      }
    } else if (k === 'fields') put('fields', m);
    else put('form', m);
  }
  return out;
}

// import

export function csvPrecheck(text: string, bytes?: number): string | null {
  if (!text.trim()) return 'Paste the CSV or upload a file first.';
  const size = bytes ?? new Blob([text]).size;
  if (size > LIMITS.importBytes) return `That is ${(size / 1024 / 1024).toFixed(1)} MB. An import takes up to 2 MB, so split it into smaller files.`;
  const lines = text.replace(/^﻿/, '').split(/\r?\n/).filter((l) => l.trim());
  const header = lines[0].split(',').map((h) => h.trim().replace(/^"|"$/g, '').toLowerCase());
  if (!header.includes('group') || !header.includes('node')) return 'The first line must be the header row, with group and node columns. Download the template to see it.';
  if (lines.length < 2) return 'There is a header row but no assets under it. Add one line per asset.';
  if (lines.length - 1 > LIMITS.importRows) return `That is ${lines.length - 1} rows. An import takes up to ${LIMITS.importRows}, so split it into smaller files.`;
  return null;
}

export type ImportAction = 'create' | 'update' | 'unchanged' | 'error';

export interface ImportRow {
  line: number;
  key: string;
  group: string;
  node: string;
  device: string;
  display_name: string | null;
  type: string | null;
  tags: string[];
  location: AssetLocation | null;
  fields: Record<string, string>;
  action: ImportAction;
  errors: string[];
}

export interface ImportResult {
  rows: ImportRow[];
  summary: { create: number; update: number; unchanged: number; error: number };
  applied: boolean;
}

export const ACTION_TEXT: Record<ImportAction, string> = {
  create: 'Will add',
  update: 'Will update',
  unchanged: 'No change',
  error: 'Needs fixing',
};

export function importCount(r: ImportResult | null): number {
  return r ? r.summary.create + r.summary.update : 0;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString('en-US')} ${n === 1 ? one : many}`;
}

// plain words for anything the asset endpoints refuse
export function explainAssetError(e: unknown, action: 'load' | 'save' | 'delete' | 'import' | 'template'): string {
  const { status, code, message } = errLike(e);
  if (status === 0 || status === 401 || code === 'NETWORK_ERROR' || code === 'SESSION_EXPIRED' || code === 'NO_TOKEN') return explainTelemetryError(e, 'load');
  if (isPlain(message) && status !== 500) return message;
  if (status === 403) {
    return action === 'load' || action === 'template'
      ? 'This list is not shared with you. Viewing assets needs View machine telemetry, which an admin can grant under Admin, Permissions.'
      : 'Changing assets needs Manage telemetry. An admin can grant it under Admin, Permissions.';
  }
  if (status === 404) {
    if (action === 'save' || action === 'delete') return 'Abenix no longer knows this asset. Refresh the list to see the current ones.';
    return 'The asset list is not on this server yet. An admin can update Abenix to 2.5.8 or later and deploy again.';
  }
  if (status === 413) return 'That file is too big. An import takes up to 5000 rows and 2 MB, so split it into smaller files.';
  if (status === 422 || status === 400) return 'Some details are not valid. Check the fields marked in red and try again.';
  if (status === 429) return 'Too many requests in a short time. Wait a moment and try again.';
  const what = { load: 'loading the assets', save: 'saving the asset', delete: 'removing the name', import: 'importing the list', template: 'downloading the template' }[action];
  return `Abenix hit a problem ${what}. Try again in a moment, and if it keeps happening an admin can check the Alerts page.`;
}
