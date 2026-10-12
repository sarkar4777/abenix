// Device and gateway keys on push sources: CSV checks, snippets and ingest errors in plain words.
import { sdkSnippets } from './sources';

export interface DeviceKey {
  id: string;
  kind: 'device' | 'gateway';
  device_id?: string | null;
  group?: string | null;
  allowed_nodes?: string[] | null;
  label?: string | null;
  key_prefix?: string | null;
  last_used_at?: string | number | null;
  revoked_at?: string | number | null;
  created_at?: string | number | null;
  // only on the response that made it
  key?: string;
}

export interface CsvRow { line: number; device_id: string; label: string; group: string; problem: string | null }

export const BULK_MAX = 5000;

export function deviceIdProblem(raw: string): string | null {
  const v = raw.trim();
  if (!v) return 'Give the device id it will send as, for example van-042 or the serial number.';
  if (/\s/.test(v)) return 'A device id cannot contain spaces.';
  if (v.length > 128) return 'Keep the device id under 128 characters.';
  if (/[/#+]/.test(v)) return 'A device id cannot contain /, # or +.';
  return null;
}

function splitCsvLine(line: string): string[] {
  const out: string[] = [];
  let cur = '';
  let q = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (q) {
      if (c === '"' && line[i + 1] === '"') { cur += '"'; i++; } else if (c === '"') q = false; else cur += c;
    } else if (c === '"') q = true;
    else if (c === ',') { out.push(cur); cur = ''; } else cur += c;
  }
  out.push(cur);
  return out.map((s) => s.trim());
}

// rows to create, each with its problem, the header row is optional
export function parseKeysCsv(text: string): { rows: CsvRow[]; problem: string | null } {
  const lines = text.replace(/\r/g, '').split('\n').map((l, i) => ({ l, i: i + 1 })).filter((x) => x.l.trim());
  if (!lines.length) return { rows: [], problem: 'Paste or upload a CSV with a device_id column, one device per line.' };
  let cols = ['device_id', 'label', 'group'];
  const head = splitCsvLine(lines[0].l).map((h) => h.toLowerCase());
  if (head.includes('device_id')) { cols = head; lines.shift(); }
  const at = (k: string) => cols.indexOf(k);
  const seen = new Set<string>();
  const rows = lines.map(({ l, i }) => {
    const c = splitCsvLine(l);
    const device_id = (c[at('device_id')] ?? '').trim();
    const row: CsvRow = { line: i, device_id, label: at('label') >= 0 ? c[at('label')] ?? '' : '', group: at('group') >= 0 ? c[at('group')] ?? '' : '', problem: deviceIdProblem(device_id) };
    if (!row.problem && seen.has(device_id)) row.problem = 'This device id is already on an earlier line.';
    seen.add(device_id);
    return row;
  });
  if (rows.length > BULK_MAX) return { rows, problem: `That is ${rows.length} devices. Up to ${BULK_MAX} go in one upload, split the file and upload the rest after.` };
  return { rows, problem: null };
}

export function rowsToCsv(rows: Array<Pick<CsvRow, 'device_id' | 'label' | 'group'>>): string {
  const esc = (s: string) => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
  return ['device_id,label,group', ...rows.map((r) => [r.device_id, r.label, r.group].map(esc).join(','))].join('\n');
}

export function keysToCsv(keys: DeviceKey[]): string {
  const esc = (s: string) => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
  return ['device_id,label,group,key', ...keys.map((k) => [k.device_id ?? '', k.label ?? '', k.group ?? '', k.key ?? ''].map(esc).join(','))].join('\n');
}

export function deviceSnippets(endpoint: string, key: string, deviceId: string): { curl: string; python: string; js: string } {
  const k = key || '<device key>';
  const sdk = sdkSnippets(
    endpoint,
    k,
    { py: '{"ts": int(time.time() * 1000), "speed_kmh": 48, "fuel_pct": 63}', js: '{ ts: Date.now(), speed_kmh: 48, fuel_pct: 63 }' },
    // the same key on a retry means it is stored once
    { py: 'str(uuid.uuid4())', js: 'crypto.randomUUID()' },
  );
  return {
    curl: `curl -X POST '${endpoint}' \\\n  -H 'Authorization: Bearer ${k}' \\\n  -H 'Content-Type: application/json' \\\n  -H 'Idempotency-Key: ${deviceId}-1760175000000' \\\n  -d '{"ts": 1760175000000, "speed_kmh": 48, "fuel_pct": 63}'`,
    python: sdk.python.replace('import asyncio\n', 'import asyncio\nimport time\nimport uuid\n'),
    js: sdk.js,
  };
}

// what a push to the ingest address got back, for the person testing it
export function ingestError(status: number, code?: string | null): string {
  const c = (code || '').toUpperCase();
  if (status === 401 || c === 'UNAUTHORIZED') return 'The key or token was refused. Check it was copied whole, and that it has not been revoked or rotated.';
  if (status === 403) return 'This key may only write as its own device. Send it from that device, or use a gateway key for many assets.';
  if (status === 409 || c === 'DISABLED') return 'The source is turned off, so nothing is accepted. Turn it on under Sources, then send again.';
  if (status === 413 || c === 'PAYLOAD_TOO_LARGE') return 'The message is over the size limit, 1 MB unless an admin changed it. Send smaller batches.';
  if (status === 415 || c === 'UNSUPPORTED_MEDIA_TYPE') return 'That content type is not taken. Send JSON, one JSON per line, CSV or plain text, with a matching Content-Type header.';
  if (status === 429) return 'Too many messages right now, the workspace is over its limit. Try again in a moment.';
  if (status === 0) return 'Could not reach Abenix from this browser. Check your network connection.';
  return 'Abenix did not take the message. Check the source is on, then try again.';
}
