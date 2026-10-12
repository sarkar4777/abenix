import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SseParser, createCoalescer, normalizeEvent, type Batch } from '@/lib/telemetry/stream';
import { buildNodes, nodeStatus, useTelemetry } from '@/lib/telemetry/store';
import { niceRange, splitMetric } from '@/lib/telemetry/format';
import { mergeLive, normalizeHistory, withGaps } from '@/components/telemetry/HistoryChart';

describe('SSE parser', () => {
  it('joins events split across chunks and skips comments', () => {
    const p = new SseParser();
    expect(p.feed('event: metrics\ndata: {"node":')).toEqual([]);
    expect(p.feed('"ipc-ex1"}\n')).toEqual([]);
    const out = p.feed('\n: ping\n\ndata: {"a":1}\r\n\r\n');
    expect(out).toEqual([{ event: 'metrics', data: '{"node":"ipc-ex1"}' }, { event: 'message', data: '{"a":1}' }]);
  });
  it('waits when a chunk ends half way through a CRLF', () => {
    const p = new SseParser();
    expect(p.feed('data: x\r')).toEqual([]);
    expect(p.feed('\n\r\n')).toEqual([{ event: 'message', data: 'x' }]);
  });
});

describe('stream events', () => {
  it('reads named device and metric events', () => {
    expect(normalizeEvent({ event: 'device', data: '{"group":"g","node":"n","device":"engine","online":false}' })).toEqual([
      { kind: 'device', row: { group: 'g', node: 'n', device: 'engine', online: false } },
    ]);
    const [m] = normalizeEvent({ event: 'metrics', data: '{"group":"g","node":"n","device":"engine","metrics":[{"name":"Engine/Speed_rpm","value":1450}]}' });
    expect(m).toEqual({ kind: 'metrics', group: 'g', node: 'n', device: 'engine', metrics: [{ name: 'Engine/Speed_rpm', value: 1450 }] });
  });
  it('takes a type field and a metrics map, and ignores pings and junk', () => {
    const [m] = normalizeEvent({ event: 'message', data: '{"type":"metrics","group":"g","node":"n","device":"","metrics":{"Safety/Hold":{"value":true,"type":"Boolean"}}}' });
    expect(m).toMatchObject({ kind: 'metrics', device: '', metrics: [{ name: 'Safety/Hold', value: true, type: 'Boolean' }] });
    expect(normalizeEvent({ event: 'ping', data: '{}' })).toEqual([]);
    expect(normalizeEvent({ event: 'message', data: 'not json' })).toEqual([]);
  });
});

describe('throttling to 10 Hz', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('paints at most once every 100 ms however fast messages arrive', () => {
    const flushes: Batch[] = [];
    const c = createCoalescer((b) => flushes.push(b), 100);
    // 400 messages a second for one second, one every 2.5 ms
    for (let i = 0; i < 400; i++) {
      c.push({ kind: 'metrics', group: 'g', node: 'n', device: 'engine', metrics: [{ name: 'Engine/Speed_rpm', value: 1000 + i }] });
      vi.advanceTimersByTime(2.5);
    }
    vi.advanceTimersByTime(200);
    expect(flushes.length).toBeGreaterThanOrEqual(9);
    expect(flushes.length).toBeLessThanOrEqual(11);
    const last = flushes[flushes.length - 1].metrics.get('g/n/engine')!;
    expect(last.metrics.get('Engine/Speed_rpm')?.value).toBe(1399);
    // every sample is kept for the sparkline even though only ten paints happened
    const samples = flushes.reduce((n, b) => n + (b.metrics.get('g/n/engine')?.samples.get('Engine/Speed_rpm')?.length ?? 0), 0);
    expect(samples).toBe(400);
  });

  it('paints a lone message straight away and nothing after stop', () => {
    const flushes: Batch[] = [];
    const c = createCoalescer((b) => flushes.push(b), 100);
    c.push({ kind: 'device', row: { group: 'g', node: 'n', device: '', online: true } });
    vi.advanceTimersByTime(0);
    expect(flushes).toHaveLength(1);
    c.stop();
    c.push({ kind: 'device', row: { group: 'g', node: 'n', device: '', online: false } });
    vi.advanceTimersByTime(500);
    expect(flushes).toHaveLength(1);
  });

  it('merges device state so a later field never wipes an earlier one', () => {
    const flushes: Batch[] = [];
    const c = createCoalescer((b) => flushes.push(b), 100);
    c.push({ kind: 'device', row: { group: 'g', node: 'n', device: 'a', online: true, msgs_per_sec: 50 } });
    c.push({ kind: 'device', row: { group: 'g', node: 'n', device: 'a', seq_gaps: 2 } });
    vi.advanceTimersByTime(100);
    expect(flushes[0].devices.get('g/n/a')).toEqual({ group: 'g', node: 'n', device: 'a', online: true, msgs_per_sec: 50, seq_gaps: 2 });
  });
});

describe('store', () => {
  beforeEach(() => useTelemetry.getState().reset());

  it('marks when a device went offline and keeps its last values', () => {
    const s = useTelemetry.getState();
    s.setRows([{ group: 'g', node: 'n', device: '', online: true, last_seen: 1, birth_at: 1, msgs_per_sec: 10, seq_gaps: 0, metric_count: 3 }]);
    s.setDeviceMetrics('g', 'n', '', [{ name: 'Engine/Speed_rpm', value: 1200 }]);
    const devices = new Map([['g/n/', { group: 'g', node: 'n', device: '', online: false }]]);
    s.applyBatch({ devices, metrics: new Map(), health: null, snapshot: null }, 5000);
    const st = useTelemetry.getState();
    expect(st.nodes['g/n'].self?.online).toBe(false);
    expect(st.nodes['g/n'].self?.offline_at).toBe(5000);
    expect(st.metrics['g/n/']['Engine/Speed_rpm'].value).toBe(1200);
    expect(nodeStatus(st.nodes['g/n'])).toBe('offline');
  });

  it('calls a node partly online when one device dropped', () => {
    const nodes = buildNodes([
      { group: 'g', node: 'n', device: '', online: true, last_seen: 1, birth_at: 1, msgs_per_sec: 1, seq_gaps: 0, metric_count: 0 },
      { group: 'g', node: 'n', device: 'engine', online: true, last_seen: 1, birth_at: 1, msgs_per_sec: 1, seq_gaps: 0, metric_count: 0 },
      { group: 'g', node: 'n', device: 'safety', online: false, last_seen: 1, birth_at: 1, msgs_per_sec: 0, seq_gaps: 0, metric_count: 0 },
    ]);
    expect(nodeStatus(nodes['g/n'])).toBe('partial');
  });
});

describe('formatting', () => {
  it('reads Group/Name_unit metric names', () => {
    expect(splitMetric('Hydraulics/BoomPressure_bar')).toEqual({ group: 'Hydraulics', label: 'Boom pressure', unit: 'bar' });
    expect(splitMetric('Engine/Speed_rpm')).toEqual({ group: 'Engine', label: 'Speed', unit: 'rpm' });
    expect(splitMetric('Safety/Hold')).toEqual({ group: 'Safety', label: 'Hold', unit: '' });
    expect(splitMetric('Engine/Coolant_c').unit).toBe('°C');
    expect(splitMetric('Engine/CoolantTemp_C')).toEqual({ group: 'Engine', label: 'Coolant temp', unit: '°C' });
  });
  it('keeps the chart axis still while values stay inside it', () => {
    const first = niceRange([1400, 1500]);
    expect(first[0]).toBeLessThanOrEqual(1400);
    expect(first[1]).toBeGreaterThanOrEqual(1500);
    expect(niceRange([1420, 1480], first)).toEqual(first);
    const grown = niceRange([1400, 1900], first);
    expect(grown[1]).toBeGreaterThanOrEqual(1900);
  });
});

describe('history', () => {
  it('reads the series the server returns per metric, and plain point lists', () => {
    const T = 1760000000000;
    const doc = { source: 'raw', series: [{ metric: 'Engine/Speed_rpm', points: [{ t: T + 1000, avg: 1500 }, { t: T, avg: 1400 }] }, { metric: 'Engine/Coolant_c', points: [{ t: T, avg: 80 }] }] };
    expect(normalizeHistory(doc, 'Engine/Speed_rpm')).toEqual([{ t: T, v: 1400 }, { t: T + 1000, v: 1500 }]);
    expect(normalizeHistory([[1, 5], { time: '1970-01-01T00:00:02Z', value: 6 }])).toEqual([{ t: 1000, v: 5 }, { t: 2000, v: 6 }]);
    expect(mergeLive([{ t: 1000, v: 1 }], [{ t: 900, v: 0 }, { t: 1500, v: 2 }], 0)).toEqual([{ t: 1000, v: 1 }, { t: 1500, v: 2 }]);
  });
  it('breaks the line where the data stopped', () => {
    const pts = [0, 1000, 2000, 3000, 60000, 61000].map((t) => ({ t, v: 1 }));
    expect(withGaps(pts).filter((p) => p.v === null)).toEqual([{ t: 3001, v: null }]);
  });
});

describe('metric names read naturally', () => {
  it('reads rates, units and plain names', () => {
    expect(splitMetric('Bus/Frames_per_s')).toEqual({ group: 'Bus', label: 'Frames', unit: '/s' });
    expect(splitMetric('Bus/Errors_per_min')).toEqual({ group: 'Bus', label: 'Errors', unit: '/min' });
    expect(splitMetric('Bus/FramesPer_s')).toEqual({ group: 'Bus', label: 'Frames', unit: '/s' });
    expect(splitMetric('Bus/FramesPerSecond')).toEqual({ group: 'Bus', label: 'Frames per second', unit: '' });
    expect(splitMetric('Uplink/MessagesPerSecond').label).toBe('Messages per second');
    expect(splitMetric('Bus/Load_pct')).toEqual({ group: 'Bus', label: 'Load', unit: '%' });
    expect(splitMetric('GNSS/Speed_kmh')).toEqual({ group: 'GNSS', label: 'Speed', unit: 'km/h' });
    expect(splitMetric('Engine/Coolant_C')).toEqual({ group: 'Engine', label: 'Coolant', unit: '°C' });
    expect(splitMetric('Bus/InjectNoise_s')).toEqual({ group: 'Bus', label: 'Inject noise', unit: 's' });
    expect(splitMetric('Latency/BusQueueP99_ms')).toEqual({ group: 'Latency', label: 'Bus queue P99', unit: 'ms' });
    expect(splitMetric('Bus/Bitrate_kbps')).toEqual({ group: 'Bus', label: 'Bitrate', unit: 'kbps' });
    expect(splitMetric('Diagnostics/DTCs')).toEqual({ group: 'Diagnostics', label: 'DTCs', unit: '' });
    expect(splitMetric('Bus/TPSessions').label).toBe('TP sessions');
    expect(splitMetric('Engine/ControllingSA').label).toBe('Controlling SA');
    expect(splitMetric('GNSS/X_m')).toEqual({ group: 'GNSS', label: 'X', unit: 'm' });
    expect(splitMetric('Hydraulics/BoomPressure_bar').label).toBe('Boom pressure');
  });
});
