// Sources of any kind: the transport catalogue, generated forms, mappings and push snippets.

export interface FieldDecl {
  key: string;
  label?: string;
  // secret | string | url | int | bool | select | text | list | file | json
  kind: string;
  required?: boolean;
  group?: string;
  description?: string;
  default?: string | number | boolean | null;
  options?: string[];
  placeholder?: string;
  // file inputs, like ".pem,.crt" or ".dbc"
  accept?: string;
}

export interface TransportDecl {
  transport: string;
  label: string;
  description?: string;
  config_fields: FieldDecl[];
  capabilities?: { receive?: string; write?: boolean };
  scale_mode?: string;
  // decoders that usually go with it, first is the default
  decoders?: string[];
  default_decoder?: string;
}

export interface DecoderDecl {
  name: string;
  label: string;
  description?: string;
  config_fields: FieldDecl[];
  stateful?: boolean;
  // whether it needs a mapping, Sparkplug and CAN frames carry their own structure
  uses_mapping?: boolean;
  needs_mapping?: boolean;
}

export type TsFormat = 'auto' | 'epoch_s' | 'epoch_ms' | 'epoch_us' | 'epoch_ns' | 'iso';

// the shape app/telemetry/mapping.py reads
export interface Mapping {
  group: string;
  node: string;
  device: string;
  // a list inside one message, each item is its own reading
  records?: string;
  timestamp: { path: string; format: TsFormat };
  signals: { include: string[]; exclude: string[]; flatten: boolean; units: Record<string, string>; types?: Record<string, string>; rename?: Record<string, string>; root?: string };
  // present when each message is also stored as an event
  event?: { name?: string } | null;
  // which messages to keep at all, the rest count as skipped
  filter?: MappingFilter | null;
  strict?: boolean;
  writable?: Array<{ signal: string; target: string }>;
}

export interface MappingFilter {
  require?: string[];
  match?: Record<string, string | string[]>;
  exclude?: Record<string, string | string[]>;
}

// "path = a, b" per line, the way people write a short rule
export function rulesToText(rules: Record<string, string | string[]> | undefined): string {
  return Object.entries(rules || {}).map(([p, v]) => `${p} = ${Array.isArray(v) ? v.join(', ') : v}`).join('\n');
}

export function textToRules(text: string): { rules: Record<string, string | string[]>; problem: string | null } {
  const rules: Record<string, string | string[]> = {};
  for (const [i, raw] of text.split('\n').entries()) {
    const line = raw.trim();
    if (!line) continue;
    const eq = line.indexOf('=');
    if (eq < 1) return { rules, problem: `Line ${i + 1} needs a path, an equals sign and a value, like $.type = tick.` };
    const path = line.slice(0, eq).trim();
    const vals = line.slice(eq + 1).split(',').map((v) => v.trim()).filter(Boolean);
    if (/\s/.test(path)) return { rules, problem: `Line ${i + 1}: the path "${path}" has a space in it.` };
    if (!vals.length) return { rules, problem: `Line ${i + 1} has no value after the equals sign.` };
    rules[path] = vals.length === 1 ? vals[0] : vals;
  }
  return { rules, problem: null };
}

export function cleanFilter(f: MappingFilter | null | undefined): MappingFilter | null {
  if (!f) return null;
  const out: MappingFilter = {};
  if (f.require?.length) out.require = f.require;
  if (f.match && Object.keys(f.match).length) out.match = f.match;
  if (f.exclude && Object.keys(f.exclude).length) out.exclude = f.exclude;
  return Object.keys(out).length ? out : null;
}

export const BLANK_MAPPING: Mapping = {
  group: '',
  node: '',
  device: '',
  timestamp: { path: '', format: 'auto' },
  signals: { include: [], exclude: [], flatten: true, units: {} },
};

export interface PreviewRecord {
  group: string;
  node: string;
  device: string;
  kind?: string;
  metrics: Array<{ name: string; value: unknown; type?: string; unit?: string; ts?: number | string | null; quality?: string }>;
}

export interface PreviewResult { records: PreviewRecord[]; errors: string[]; skipped?: boolean; skip_reason?: string | null }

export interface InspectorMessage {
  id?: string;
  t?: number | string;
  t_recv?: number | string;
  encoding?: string;
  result?: Array<{ kind?: string; group?: string; node?: string; device?: string; metrics?: string[]; frames?: number; event?: string | null }>;
  subject?: string;
  headers?: Record<string, unknown>;
  payload?: string;
  payload_encoding?: string;
  size?: number;
  ok?: boolean;
  records?: number;
  error?: string | null;
  reason?: string | null;
}

const EXAMPLES: Array<[RegExp, string, string]> = [
  [/^broker_url$|^url$/, 'mqtt://broker.example.com:1883', 'The full address with its scheme and port.'],
  [/bootstrap/, 'broker-1:9092, broker-2:9092', 'The Kafka brokers to start from, separated by commas.'],
  [/^topics?$/, 'payments.orders', 'Where the messages are published. Wildcards like # or + work where the transport allows them.'],
  [/raw_topics/, 'site/+/can/raw', 'Topics that carry raw CAN frames for the Frames view.'],
  [/group_id|consumer/, 'abenix-telemetry', 'Every Abenix replica joins this group, so each message is read once.'],
  [/^username$|^user$/, 'abenix', 'The user Abenix signs in as.'],
  [/password|secret|token/, '', 'Stored encrypted and never shown again.'],
  [/^host$/, 'plc-1.plant.local', 'The host name or IP address.'],
  [/^port$/, '502', 'The TCP port.'],
  [/unit_id|slave/, '1', 'The Modbus unit or slave id.'],
  [/queue/, 'telemetry', 'The queue Abenix reads from.'],
  [/exchange/, 'events', 'The exchange the queue is bound to.'],
  [/routing_key|binding/, 'orders.#', 'Which routing keys reach the queue.'],
  [/^subjects?$/, 'plant.>', 'The NATS subjects to read.'],
  [/stream/, 'TELEMETRY', 'The JetStream stream name.'],
  [/durable/, 'abenix', 'A durable consumer name, so nothing is missed across restarts.'],
  [/endpoint/, 'opc.tcp://plc-1:4840', 'The OPC UA server address.'],
  [/node_ids|nodes/, 'ns=2;s=Line1.Temperature', 'One node id per line.'],
  [/poll|interval/, '1000', 'How often to read, in milliseconds.'],
  [/registers|register_map/, '[{"address": 0, "type": "uint16", "name": "flow", "scale": 0.1, "unit": "L/min"}]', 'Each register to read, with its type, scale and unit.'],
  [/subscribe/, '{"op": "subscribe", "channel": "ticks"}', 'Sent once after connecting, if the feed needs it.'],
  [/tls_ca|ca_cert|^ca$/, '-----BEGIN CERTIFICATE-----', 'The certificate authority that signed the server certificate. Needed for private CAs only.'],
  [/tls_cert|client_cert/, '-----BEGIN CERTIFICATE-----', 'Your client certificate, for mutual TLS.'],
  [/tls_key|client_key/, '', 'The private key for the client certificate. Stored encrypted.'],
  [/dbc/, 'VERSION ""', 'The DBC file that describes the CAN messages.'],
  [/proto|descriptor/, 'syntax = "proto3";', 'The .proto file, or a compiled descriptor set.'],
  [/schema/, '{"type": "record", "name": "Reading", "fields": []}', 'The Avro schema as JSON.'],
  [/message_type/, 'telemetry.Reading', 'The message type in the .proto to decode with.'],
  [/delimiter|separator/, ',', 'The character between columns.'],
];

// help and an example for any field, so no field arrives without them
export function fieldHelp(f: FieldDecl): { help: string; example: string } {
  const hit = EXAMPLES.find(([re]) => re.test(f.key.toLowerCase()));
  const dflt = f.default !== undefined && f.default !== null && String(f.default) !== '' ? String(f.default) : '';
  const example = f.placeholder || dflt || (hit ? hit[1] : f.kind === 'int' ? '10' : f.kind === 'url' ? 'https://example.com' : '');
  return { help: f.description || (hit ? hit[2] : ''), example: f.kind === 'secret' || f.kind === 'bool' || f.kind === 'select' ? '' : example };
}

export function fieldLabel(f: FieldDecl): string {
  if (f.label) return f.label;
  const s = f.key.replace(/[_.-]+/g, ' ').trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// certificates, keys and schema files, offered as an upload as well as a paste
export function isFileLike(f: FieldDecl): boolean {
  if (f.kind === 'file') return true;
  if (f.kind !== 'string' && f.kind !== 'secret' && f.kind !== 'text') return false;
  return /(^|_)(ca|cert|certificate|key|pem|dbc|proto|descriptor|schema|avsc)(_|$)/i.test(f.key);
}

function asBool(v: unknown): boolean {
  return v === true || v === 'true' || v === '1' || v === 1;
}

export function isSecret(f: FieldDecl): boolean {
  return f.kind === 'secret' || (f.kind === 'file' && /key|cert|password|token/i.test(f.key));
}

export function initialValues(fields: FieldDecl[], current: Record<string, unknown> = {}): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    const v = current[f.key] !== undefined ? current[f.key] : f.default;
    if (f.kind === 'bool') out[f.key] = v === undefined || v === null ? false : asBool(v);
    else out[f.key] = v === undefined || v === null ? '' : v;
  }
  return out;
}

// the problem with one generated field, said at the field
export function fieldProblem(f: FieldDecl, v: unknown, keepingSecret = false): string | null {
  const empty = v === undefined || v === null || (typeof v === 'string' && !v.trim()) || (Array.isArray(v) && !v.length);
  if (empty) {
    if (f.required && !keepingSecret && f.kind !== 'bool') return `${fieldLabel(f)} is needed.`;
    return null;
  }
  if (f.kind === 'int') {
    const n = Number(v);
    if (!Number.isInteger(n)) return `${fieldLabel(f)} must be a whole number.`;
  }
  if (f.kind === 'url' && typeof v === 'string') {
    const s = v.trim();
    if (/\s/.test(s)) return 'The address cannot contain spaces.';
    const m = /^([a-z][a-z0-9+.-]*):\/\/([^/\s:?#]+)(?::(\d+))?/i.exec(s);
    if (!m) return `Use the full address with its scheme${f.placeholder ? `, for example ${f.placeholder}` : ''}.`;
    if (f.options?.length && !f.options.includes(m[1].toLowerCase())) return `Start the address with ${f.options.map((o) => `${o}://`).join(' or ')}.`;
    if (m[3] !== undefined && !(Number(m[3]) >= 1 && Number(m[3]) <= 65535)) return 'The port must be a number from 1 to 65535.';
  }
  if (f.kind === 'json' && typeof v === 'string') {
    try { JSON.parse(v); } catch { return 'That is not valid JSON. Check the quotes and brackets.'; }
  }
  if (f.kind === 'select' && f.options?.length && !f.options.includes(String(v))) return 'Pick one of the options.';
  return null;
}

export function splitList(v: unknown): string[] {
  if (Array.isArray(v)) return v.map(String).map((s) => s.trim()).filter(Boolean);
  return String(v ?? '').split(/[\n,]+/).map((s) => s.trim()).filter(Boolean);
}

const WHAT_TO_READ = ['subjects', 'subject', 'queue', 'nodes', 'browse_path', 'registers', 'topics'];

// a subscribing transport that does not declare what to read gets a Topics field, sent as the connection's subjects
export function withSubjects(t: TransportDecl): FieldDecl[] {
  const fields = t.config_fields || [];
  if (t.capabilities?.receive !== 'subscribe' || fields.some((f) => WHAT_TO_READ.includes(f.key))) return fields;
  const label = t.transport === 'kafka' ? 'Topics' : t.transport === 'nats' ? 'Subjects' : 'Topics or subjects';
  const example = t.transport === 'kafka' ? 'payments.orders' : t.transport === 'nats' ? 'plant.>' : 'events';
  return [{ key: 'subjects', label, kind: 'list', required: true, description: `What Abenix reads from. Wildcards work where ${t.label} allows them.`, placeholder: example }, ...fields];
}

// list fields go to the server as arrays, ints as numbers, empty secrets are left out so the stored one stays
export function toPayload(fields: FieldDecl[], values: Record<string, unknown>, keepSecrets: Set<string>): { config: Record<string, unknown>; secrets: Record<string, unknown> } {
  const config: Record<string, unknown> = {};
  const secrets: Record<string, unknown> = {};
  for (const f of fields) {
    const v = values[f.key];
    if (isSecret(f)) {
      if (keepSecrets.has(f.key)) continue;
      if (v === '' || v === undefined) continue;
      secrets[f.key] = v;
      continue;
    }
    if (f.kind === 'list') config[f.key] = splitList(v);
    else if (f.kind === 'int') config[f.key] = v === '' || v === undefined ? null : Number(v);
    else if (f.kind === 'bool') config[f.key] = !!v;
    else if (f.kind === 'json' && typeof v === 'string') config[f.key] = v.trim() ? JSON.parse(v) : null;
    else config[f.key] = v;
  }
  return { config, secrets };
}

const SUBJECT_KEYS = ['topics', 'topic', 'subjects', 'subject', 'queue', 'exchange', 'routing_key', 'stream', 'nodes', 'node_ids', 'registers', 'url', 'path'];

// what the source listens to, in one short line
export function subjectSummary(config: Record<string, unknown> | undefined, legacyTopics?: string[]): string[] {
  if (legacyTopics?.length) return legacyTopics;
  const c = config || {};
  for (const k of SUBJECT_KEYS) {
    const v = c[k];
    if (Array.isArray(v) && v.length) return v.map((x) => (typeof x === 'string' ? x : JSON.stringify(x))).slice(0, 6);
    if (typeof v === 'string' && v.trim()) return [v.trim()];
  }
  return [];
}

export function addressOf(config: Record<string, unknown> | undefined, legacy?: string | null): string {
  if (legacy) return legacy;
  const c = config || {};
  for (const k of ['broker_url', 'url', 'bootstrap_servers', 'servers', 'endpoint', 'host']) {
    const v = c[k];
    if (Array.isArray(v) && v.length) return v.join(', ');
    if (typeof v === 'string' && v) return k === 'host' && c.port ? `${v}:${String(c.port)}` : v;
  }
  return '';
}

// the address split back into the server and the source id, for the SDK calls
export function splitIngest(endpoint: string): { base: string; id: string } {
  const m = /^(.*)\/api\/telemetry\/ingest\/([^/?#]+)/.exec(endpoint);
  return m ? { base: m[1], id: m[2] } : { base: endpoint, id: '<source id>' };
}

export function sdkSnippets(endpoint: string, key: string, body: { py: string; js: string }, idem: { py: string; js: string }): { python: string; js: string } {
  const { base, id } = splitIngest(endpoint);
  return {
    python: `import asyncio\nfrom abenix_sdk import Abenix\n\n\nasync def main():\n    # pushing needs only the key below, not an API key\n    forge = Abenix(api_key="", base_url="${base}")\n    await forge.telemetry.ingest(\n        "${id}",\n        ${body.py},\n        token="${key}",\n        idempotency_key=${idem.py},\n    )\n\n\nasyncio.run(main())`,
    js: `import { Abenix } from '@abenix/sdk';\n\n// pushing needs only the key below, not an API key\nconst forge = new Abenix({ apiKey: '', baseUrl: '${base}' });\nawait forge.telemetry.ingest(\n  '${id}',\n  ${body.js},\n  { token: '${key}', idempotencyKey: ${idem.js} },\n);`,
  };
}

export function pushSnippets(endpoint: string, token: string): { curl: string; python: string; js: string } {
  const tok = token || '<your source token>';
  const sample = '{"asset": "pump-7", "temperature_c": 61.5, "pressure_bar": 4.2}';
  return {
    curl: `curl -X POST '${endpoint}' \\\n  -H 'Authorization: Bearer ${tok}' \\\n  -H 'Content-Type: application/json' \\\n  -H 'Idempotency-Key: pump-7-1760175000000' \\\n  -d '${sample}'`,
    ...sdkSnippets(endpoint, tok, { py: '{"asset": "pump-7", "temperature_c": 61.5, "pressure_bar": 4.2}', js: "{ asset: 'pump-7', temperature_c: 61.5, pressure_bar: 4.2 }" }, { py: '"pump-7-1760175000000"', js: "'pump-7-1760175000000'" }),
  };
}

// a guess at the asset template from a JSON sample, used before the server suggests one
export function localSuggest(sample: string): Partial<Mapping> | null {
  let doc: unknown;
  try { doc = JSON.parse(sample); } catch { return null; }
  if (!doc || typeof doc !== 'object' || Array.isArray(doc)) return null;
  const o = doc as Record<string, unknown>;
  const idKey = ['asset', 'asset_id', 'device', 'device_id', 'machine', 'machine_id', 'id', 'name', 'sensor'].find((k) => typeof o[k] === 'string' || typeof o[k] === 'number');
  const tsKey = ['ts', 'timestamp', 'time', 't', 'event_time', 'created_at'].find((k) => o[k] !== undefined);
  let format: TsFormat = 'auto';
  if (tsKey) {
    const v = o[tsKey];
    if (typeof v === 'string') format = 'iso';
    else if (typeof v === 'number') format = v > 1e17 ? 'epoch_ns' : v > 1e14 ? 'epoch_us' : v > 1e11 ? 'epoch_ms' : 'epoch_s';
  }
  return {
    node: idKey ? `$.${idKey}` : '{subject.0}',
    timestamp: { path: tsKey ? `$.${tsKey}` : '', format },
    signals: { include: [], exclude: [idKey, tsKey].filter(Boolean).map((k) => `$.${k}`), flatten: true, units: {} },
  };
}
