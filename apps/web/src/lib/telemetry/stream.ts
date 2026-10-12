import type { DeviceRow, Health, Metric } from './types';
import { deviceKey } from './format';

export interface SseMessage { event: string; data: string }

// incremental text/event-stream parser, fed whatever chunks the network hands over
export class SseParser {
  private buf = '';
  private event = '';
  private data: string[] = [];

  feed(chunk: string): SseMessage[] {
    this.buf += chunk;
    const out: SseMessage[] = [];
    let nl: number;
    while ((nl = this.buf.search(/\r\n|\r|\n/)) >= 0) {
      const line = this.buf.slice(0, nl);
      const sep = this.buf[nl] === '\r' && this.buf[nl + 1] === '\n' ? 2 : 1;
      // a lone \r at the end may be half of \r\n, wait for the next chunk
      if (this.buf[nl] === '\r' && nl + 1 === this.buf.length) break;
      this.buf = this.buf.slice(nl + sep);
      if (line === '') {
        if (this.data.length) out.push({ event: this.event || 'message', data: this.data.join('\n') });
        this.event = '';
        this.data = [];
        continue;
      }
      if (line.startsWith(':')) continue;
      const colon = line.indexOf(':');
      const field = colon < 0 ? line : line.slice(0, colon);
      let value = colon < 0 ? '' : line.slice(colon + 1);
      if (value.startsWith(' ')) value = value.slice(1);
      if (field === 'event') this.event = value;
      else if (field === 'data') this.data.push(value);
    }
    return out;
  }
}

export type TelemetryEvent =
  | { kind: 'device'; row: Partial<DeviceRow> & { group: string; node: string; device: string } }
  | { kind: 'metrics'; group: string; node: string; device: string; metrics: Metric[] }
  | { kind: 'health'; health: Health }
  | { kind: 'snapshot'; rows: DeviceRow[] };

function metricsFrom(raw: unknown): Metric[] {
  if (Array.isArray(raw)) {
    return raw
      .filter((m) => m && typeof m === 'object' && typeof (m as Metric).name === 'string')
      .map((m) => m as Metric);
  }
  if (raw && typeof raw === 'object') {
    return Object.entries(raw as Record<string, unknown>).map(([name, v]) =>
      v && typeof v === 'object' && 'value' in (v as object) ? { name, ...(v as Omit<Metric, 'name'>) } : { name, value: v as Metric['value'] },
    );
  }
  return [];
}

const DEVICE_EVENTS = new Set(['device', 'state', 'device_state', 'online', 'offline', 'birth', 'death']);
const METRIC_EVENTS = new Set(['metrics', 'metric', 'delta', 'data', 'values']);

// takes the named event or a type field, and tolerates a few shapes for each
export function normalizeEvent(msg: SseMessage): TelemetryEvent[] {
  let body: unknown;
  try {
    body = JSON.parse(msg.data);
  } catch {
    return [];
  }
  if (Array.isArray(body)) return body.flatMap((b) => normalizeEvent({ event: msg.event, data: JSON.stringify(b) }));
  if (!body || typeof body !== 'object') return [];
  const o = body as Record<string, unknown>;
  const kind = String(msg.event !== 'message' ? msg.event : (o.type ?? o.kind ?? o.event ?? '')).toLowerCase();
  if (kind === 'ping' || kind === 'keepalive' || kind === 'hello') return [];
  if (kind === 'health') return [{ kind: 'health', health: (o.health ?? o) as Health }];
  if (kind === 'snapshot' && Array.isArray(o.devices)) return [{ kind: 'snapshot', rows: o.devices as DeviceRow[] }];
  const group = typeof o.group === 'string' ? o.group : '';
  const node = typeof o.node === 'string' ? o.node : '';
  const device = typeof o.device === 'string' ? o.device : '';
  if (!node) return [];
  const out: TelemetryEvent[] = [];
  const metrics = metricsFrom(o.metrics ?? o.values);
  const looksDevice = DEVICE_EVENTS.has(kind) || 'online' in o;
  if (looksDevice) {
    const row: Partial<DeviceRow> & { group: string; node: string; device: string } = { group, node, device };
    for (const k of ['online', 'last_seen', 'birth_at', 'msgs_per_sec', 'seq_gaps', 'metric_count', 'offline_at', 'connection_id'] as const) {
      if (k in o) (row as Record<string, unknown>)[k] = o[k];
    }
    if (kind === 'offline' || kind === 'death') row.online = false;
    if (kind === 'online' || kind === 'birth') row.online = true;
    out.push({ kind: 'device', row });
  }
  if (metrics.length && (METRIC_EVENTS.has(kind) || looksDevice || !kind)) out.push({ kind: 'metrics', group, node, device, metrics });
  return out;
}

export interface Batch {
  devices: Map<string, Partial<DeviceRow> & { group: string; node: string; device: string }>;
  metrics: Map<string, { group: string; node: string; device: string; metrics: Map<string, Metric>; samples: Map<string, Array<{ t: number; v: number }>> }>;
  health: Health | null;
  snapshot: DeviceRow[] | null;
}

export function emptyBatch(): Batch {
  return { devices: new Map(), metrics: new Map(), health: null, snapshot: null };
}

function sampleTime(m: Metric, now: number): number {
  const ts = m.ts;
  if (typeof ts === 'number') return ts < 1e12 ? ts * 1000 : ts;
  if (typeof ts === 'string') {
    const d = Date.parse(ts);
    if (!Number.isNaN(d)) return d;
  }
  return now;
}

// folds one event into the pending batch, latest value wins but every numeric sample is kept for sparklines
export function addToBatch(b: Batch, e: TelemetryEvent, now = Date.now()): void {
  if (e.kind === 'health') {
    b.health = { ...(b.health ?? {}), ...e.health };
    return;
  }
  if (e.kind === 'snapshot') {
    b.snapshot = e.rows;
    return;
  }
  if (e.kind === 'device') {
    const k = deviceKey(e.row.group, e.row.node, e.row.device);
    b.devices.set(k, { ...(b.devices.get(k) ?? {}), ...e.row });
    return;
  }
  const k = deviceKey(e.group, e.node, e.device);
  let slot = b.metrics.get(k);
  if (!slot) {
    slot = { group: e.group, node: e.node, device: e.device, metrics: new Map(), samples: new Map() };
    b.metrics.set(k, slot);
  }
  for (const m of e.metrics) {
    slot.metrics.set(m.name, m);
    if (typeof m.value === 'number' && Number.isFinite(m.value)) {
      const arr = slot.samples.get(m.name) ?? [];
      arr.push({ t: sampleTime(m, now), v: m.value });
      slot.samples.set(m.name, arr);
    } else if (typeof m.value === 'boolean') {
      const arr = slot.samples.get(m.name) ?? [];
      arr.push({ t: sampleTime(m, now), v: m.value ? 1 : 0 });
      slot.samples.set(m.name, arr);
    }
  }
}

export interface Coalescer {
  push: (e: TelemetryEvent) => void;
  flushNow: () => void;
  stop: () => void;
}

// collects events and hands them over at most once per interval, so the UI paints at 10 Hz however fast the bus runs
export function createCoalescer(
  onFlush: (b: Batch) => void,
  intervalMs = 100,
  timers: { set: (fn: () => void, ms: number) => unknown; clear: (h: unknown) => void; now: () => number } = {
    set: (fn, ms) => setTimeout(fn, ms),
    clear: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
    now: () => Date.now(),
  },
): Coalescer {
  let batch = emptyBatch();
  let pending = false;
  let handle: unknown = null;
  let last = -Infinity;
  let stopped = false;

  const flush = () => {
    handle = null;
    if (!pending || stopped) return;
    const b = batch;
    batch = emptyBatch();
    pending = false;
    last = timers.now();
    onFlush(b);
  };

  return {
    push(e) {
      if (stopped) return;
      addToBatch(batch, e, timers.now());
      pending = true;
      if (handle !== null) return;
      const wait = Math.max(0, last + intervalMs - timers.now());
      handle = timers.set(flush, wait);
    },
    flushNow() {
      if (handle !== null) timers.clear(handle);
      flush();
    },
    stop() {
      stopped = true;
      if (handle !== null) timers.clear(handle);
      handle = null;
    },
  };
}

export type StreamState = 'connecting' | 'live' | 'retrying' | 'unsupported' | 'denied' | 'closed';

export interface StreamOptions {
  url: string;
  token: string | null;
  onMessage: (m: SseMessage) => void;
  onState: (s: StreamState, detail?: { attempt?: number; status?: number; retryInMs?: number }) => void;
  fetchImpl?: typeof fetch;
}

// SSE over fetch, so the bearer token goes in a header and not in the URL
export function openStream({ url, token, onMessage, onState, fetchImpl }: StreamOptions): () => void {
  const doFetch = fetchImpl ?? fetch;
  let ctrl: AbortController | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let attempt = 0;
  let closed = false;

  const retry = (status?: number) => {
    if (closed) return;
    const wait = Math.min(30_000, 1000 * 2 ** Math.min(attempt, 5));
    attempt += 1;
    onState('retrying', { attempt, status, retryInMs: wait });
    timer = setTimeout(run, wait);
  };

  async function run() {
    if (closed) return;
    ctrl = new AbortController();
    onState('connecting', { attempt });
    try {
      const res = await doFetch(url, {
        headers: { Accept: 'text/event-stream', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        signal: ctrl.signal,
        cache: 'no-store',
      });
      if (res.status === 404) {
        onState('unsupported', { status: 404 });
        return;
      }
      if (res.status === 401 || res.status === 403) {
        onState('denied', { status: res.status });
        return;
      }
      if (!res.ok || !res.body) {
        retry(res.status);
        return;
      }
      attempt = 0;
      onState('live');
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      const parser = new SseParser();
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        for (const m of parser.feed(dec.decode(value, { stream: true }))) onMessage(m);
      }
      retry();
    } catch {
      if (!closed) retry();
    }
  }

  void run();
  return () => {
    closed = true;
    if (timer) clearTimeout(timer);
    ctrl?.abort();
    onState('closed');
  };
}
