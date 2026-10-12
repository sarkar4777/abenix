/**
 * A small MQTT 3.1.1 client and Sparkplug B encoder for browser specs, so a spec can act as an edge gateway
 * without extra packages. QoS 0 publish and subscribe only.
 */
import net from 'node:net';

// Sparkplug B datatypes
export const DT = { Int32: 3, Int64: 4, UInt64: 8, Float: 9, Double: 10, Boolean: 11, String: 12 } as const;

export interface SpMetric { name: string; datatype: number; value: number | boolean | string; timestamp?: number }

function varint(n: number | bigint): number[] {
  let v = BigInt(n);
  if (v < 0n) v += 1n << 64n;
  const out: number[] = [];
  do {
    let b = Number(v & 0x7fn);
    v >>= 7n;
    if (v > 0n) b |= 0x80;
    out.push(b);
  } while (v > 0n);
  return out;
}

const key = (field: number, wire: number) => varint((field << 3) | wire);
const lenField = (field: number, bytes: number[] | Buffer) => [...key(field, 2), ...varint(bytes.length), ...bytes];

function encodeMetric(m: SpMetric, now: number): number[] {
  const out: number[] = [...lenField(1, Buffer.from(m.name, 'utf8')), ...key(3, 0), ...varint(m.timestamp ?? now), ...key(4, 0), ...varint(m.datatype)];
  if (m.datatype === DT.Boolean) out.push(...key(14, 0), m.value ? 1 : 0);
  else if (m.datatype === DT.String) out.push(...lenField(15, Buffer.from(String(m.value), 'utf8')));
  else if (m.datatype === DT.Double) {
    const b = Buffer.alloc(8);
    b.writeDoubleLE(Number(m.value));
    out.push(...key(13, 1), ...b);
  } else if (m.datatype === DT.Float) {
    const b = Buffer.alloc(4);
    b.writeFloatLE(Number(m.value));
    out.push(...key(12, 5), ...b);
  } else if (m.datatype === DT.Int64 || m.datatype === DT.UInt64) out.push(...key(11, 0), ...varint(BigInt(Math.trunc(Number(m.value)))));
  else out.push(...key(10, 0), ...varint(Math.trunc(Number(m.value)) >>> 0));
  return out;
}

export function encodePayload(metrics: SpMetric[], seq: number | null, now = Date.now()): Buffer {
  const out: number[] = [...key(1, 0), ...varint(now)];
  for (const m of metrics) out.push(...lenField(2, encodeMetric(m, now)));
  if (seq !== null) out.push(...key(3, 0), ...varint(seq));
  return Buffer.from(out);
}

// enough of a protobuf reader to read back a command payload
export function decodePayload(buf: Buffer): { timestamp?: number; seq?: number; metrics: Array<{ name?: string; datatype?: number; value?: unknown }> } {
  const readVarint = (b: Buffer, pos: { i: number }) => {
    let r = 0n, s = 0n;
    for (;;) {
      const x = b[pos.i++];
      r |= BigInt(x & 0x7f) << s;
      if (!(x & 0x80)) break;
      s += 7n;
    }
    return r;
  };
  const fields = (b: Buffer) => {
    const pos = { i: 0 };
    const out: Array<{ f: number; w: number; v: bigint | Buffer }> = [];
    while (pos.i < b.length) {
      const k = Number(readVarint(b, pos));
      const f = k >> 3, w = k & 7;
      if (w === 0) out.push({ f, w, v: readVarint(b, pos) });
      else if (w === 2) { const n = Number(readVarint(b, pos)); out.push({ f, w, v: b.subarray(pos.i, pos.i + n) }); pos.i += n; }
      else if (w === 1) { out.push({ f, w, v: b.subarray(pos.i, pos.i + 8) }); pos.i += 8; }
      else if (w === 5) { out.push({ f, w, v: b.subarray(pos.i, pos.i + 4) }); pos.i += 4; }
      else break;
    }
    return out;
  };
  const res: ReturnType<typeof decodePayload> = { metrics: [] };
  for (const x of fields(buf)) {
    if (x.f === 1 && x.w === 0) res.timestamp = Number(x.v);
    if (x.f === 3 && x.w === 0) res.seq = Number(x.v);
    if (x.f === 2 && x.w === 2) {
      const m: { name?: string; datatype?: number; value?: unknown } = {};
      for (const y of fields(x.v as Buffer)) {
        if (y.f === 1) m.name = (y.v as Buffer).toString('utf8');
        if (y.f === 4) m.datatype = Number(y.v);
        if (y.f === 10 || y.f === 11) m.value = Number(y.v);
        if (y.f === 12) m.value = (y.v as Buffer).readFloatLE(0);
        if (y.f === 13) m.value = (y.v as Buffer).readDoubleLE(0);
        if (y.f === 14) m.value = Number(y.v) !== 0;
        if (y.f === 15) m.value = (y.v as Buffer).toString('utf8');
      }
      res.metrics.push(m);
    }
  }
  return res;
}

function remaining(n: number): number[] {
  const out: number[] = [];
  do {
    let b = n % 128;
    n = Math.floor(n / 128);
    if (n > 0) b |= 0x80;
    out.push(b);
  } while (n > 0);
  return out;
}
const str = (s: string) => { const b = Buffer.from(s, 'utf8'); return [b.length >> 8, b.length & 0xff, ...b]; };

export class MiniMqtt {
  private sock: net.Socket | null = null;
  private buf = Buffer.alloc(0);
  private ping: NodeJS.Timeout | null = null;
  private handlers: Array<(topic: string, payload: Buffer) => void> = [];
  private pid = 1;

  constructor(private host: string, private port: number, private clientId: string) {}

  static fromUrl(url: string, clientId: string): MiniMqtt {
    const m = /^mqtts?:\/\/([^:/]+)(?::(\d+))?/.exec(url);
    if (!m) throw new Error(`bad broker url ${url}`);
    return new MiniMqtt(m[1], Number(m[2] || 1883), clientId);
  }

  connect(will?: { topic: string; payload: Buffer }, timeoutMs = 5000): Promise<void> {
    return new Promise((resolve, reject) => {
      const sock = net.createConnection({ host: this.host, port: this.port });
      this.sock = sock;
      const timer = setTimeout(() => { sock.destroy(); reject(new Error(`no CONNACK from ${this.host}:${this.port}`)); }, timeoutMs);
      sock.once('error', (e) => { clearTimeout(timer); reject(e); });
      sock.on('connect', () => {
        const flags = 0x02 | (will ? 0x04 : 0);
        const vh = [...str('MQTT'), 4, flags, 0, 60];
        const pl = [...str(this.clientId), ...(will ? [...str(will.topic), will.payload.length >> 8, will.payload.length & 0xff, ...will.payload] : [])];
        const body = [...vh, ...pl];
        sock.write(Buffer.from([0x10, ...remaining(body.length), ...body]));
      });
      let acked = false;
      sock.on('data', (d) => {
        this.buf = Buffer.concat([this.buf, d]);
        for (;;) {
          if (this.buf.length < 2) return;
          let mult = 1, len = 0, i = 1, b: number;
          do {
            if (i >= this.buf.length) return;
            b = this.buf[i++];
            len += (b & 0x7f) * mult;
            mult *= 128;
          } while (b & 0x80);
          if (this.buf.length < i + len) return;
          const hdr = this.buf[0];
          const type = hdr >> 4;
          const body = this.buf.subarray(i, i + len);
          this.buf = this.buf.subarray(i + len);
          if (type === 2 && !acked) {
            acked = true;
            clearTimeout(timer);
            if (body[1] !== 0) { reject(new Error(`broker refused the connection, code ${body[1]}`)); return; }
            this.ping = setInterval(() => this.sock?.write(Buffer.from([0xc0, 0])), 30_000);
            resolve();
          } else if (type === 3) {
            const tl = (body[0] << 8) | body[1];
            const topic = body.subarray(2, 2 + tl).toString('utf8');
            const qos = (hdr >> 1) & 3;
            const payload = body.subarray(2 + tl + (qos ? 2 : 0));
            for (const h of this.handlers) h(topic, payload);
          }
        }
      });
    });
  }

  publish(topic: string, payload: Buffer | string, retain = false): void {
    const p = typeof payload === 'string' ? Buffer.from(payload, 'utf8') : payload;
    const body = [...str(topic), ...p];
    this.sock?.write(Buffer.from([0x30 | (retain ? 1 : 0), ...remaining(body.length), ...body]));
  }

  subscribe(filter: string, onMessage: (topic: string, payload: Buffer) => void): void {
    this.handlers.push(onMessage);
    const id = this.pid++;
    const body = [id >> 8, id & 0xff, ...str(filter), 0];
    this.sock?.write(Buffer.from([0x82, ...remaining(body.length), ...body]));
  }

  // a clean disconnect, no last will
  end(): void {
    if (this.ping) clearInterval(this.ping);
    try { this.sock?.write(Buffer.from([0xe0, 0])); } catch { /* already closed */ }
    this.sock?.end();
    this.sock = null;
  }

  // drops the socket so the broker fires the last will, like a gateway losing power
  drop(): void {
    if (this.ping) clearInterval(this.ping);
    this.sock?.destroy();
    this.sock = null;
  }
}

// one Sparkplug edge node with devices, birth, data and death
export class EdgeNode {
  seq = 0;
  bdSeq = 0;
  readonly client: MiniMqtt;

  constructor(url: string, readonly group: string, readonly node: string) {
    this.client = MiniMqtt.fromUrl(url, `abenix-uat-${node}-${Date.now().toString(36)}`);
  }

  private nextSeq() {
    const s = this.seq;
    this.seq = (this.seq + 1) % 256;
    return s;
  }

  topic(kind: string, device?: string) {
    return `spBv1.0/${this.group}/${kind}/${this.node}${device ? `/${device}` : ''}`;
  }

  async start(nodeMetrics: SpMetric[]) {
    const death = encodePayload([{ name: 'bdSeq', datatype: DT.UInt64, value: this.bdSeq }], null);
    await this.client.connect({ topic: this.topic('NDEATH'), payload: death });
    this.seq = 0;
    this.client.publish(this.topic('NBIRTH'), encodePayload([
      { name: 'bdSeq', datatype: DT.UInt64, value: this.bdSeq },
      { name: 'Node Control/Rebirth', datatype: DT.Boolean, value: false },
      ...nodeMetrics,
    ], this.nextSeq()));
  }

  birthDevice(device: string, metrics: SpMetric[]) {
    this.client.publish(this.topic('DBIRTH', device), encodePayload(metrics, this.nextSeq()));
  }

  data(device: string, metrics: SpMetric[]) {
    this.client.publish(this.topic(device ? 'DDATA' : 'NDATA', device || undefined), encodePayload(metrics, this.nextSeq()));
  }

  frames(rawTopic: string, frames: Array<{ t: number; id: number; data: string; dlc: number }>) {
    this.client.publish(rawTopic, JSON.stringify(frames));
  }

  onCommand(handler: (topic: string, decoded: ReturnType<typeof decodePayload>) => void) {
    this.client.subscribe(`spBv1.0/${this.group}/DCMD/${this.node}/#`, (t, p) => handler(t, decodePayload(p)));
    this.client.subscribe(`spBv1.0/${this.group}/NCMD/${this.node}`, (t, p) => handler(t, decodePayload(p)));
  }

  // says goodbye the Sparkplug way, then closes cleanly
  stop() {
    try {
      this.client.publish(this.topic('NDEATH'), encodePayload([{ name: 'bdSeq', datatype: DT.UInt64, value: this.bdSeq }], null));
    } catch { /* socket already gone, the broker sent the last will */ }
    this.client.end();
  }
}
