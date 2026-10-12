import type { MetricValue } from './types';

export const nodeKey = (group: string, node: string) => `${group}/${node}`;
export const deviceKey = (group: string, node: string, device: string) => `${group}/${node}/${device}`;

const UNIT_TEXT: Record<string, string> = {
  pct: '%', c: '°C', degc: '°C', f: '°F', deg: '°', kmh: 'km/h', kph: 'km/h', mps: 'm/s', ms2: 'm/s²', lph: 'L/h',
  rads: 'rad/s', degs: '°/s', kpa: 'kPa', mpa: 'MPa', hz: 'Hz', kw: 'kW', kwh: 'kWh', v: 'V', a: 'A', mm: 'mm',
  t: 't', kg: 'kg', m: 'm', s: 's', h: 'h', rpm: 'rpm', bar: 'bar', rad: 'rad', l: 'L', nm: 'N·m', mms: 'mm/s',
};

// CamelCase into words, keeping short capitals like DTCs, ECUs or P99 as they are
export function words(s: string): string {
  const parts = s.replace(/[_-]+/g, ' ').match(/[A-Z]+\d*s?(?![a-z])|[A-Z]?[a-z]+\d*|\d+[a-z]*/g);
  if (!parts) return s;
  const caps = (w: string) => /^[A-Z]+\d*s?$/.test(w);
  return parts.map((w, i) => {
    if (caps(w)) return w;
    const lower = w.toLowerCase();
    return i === 0 ? lower.charAt(0).toUpperCase() + lower.slice(1) : lower;
  }).join(' ');
}

// "Hydraulics/BoomPressure_bar" -> Hydraulics, "Boom pressure", "bar"
export function splitMetric(name: string): { group: string; label: string; unit: string } {
  const slash = name.lastIndexOf('/');
  const group = slash > 0 ? name.slice(0, slash) : '';
  let rest = slash >= 0 ? name.slice(slash + 1) : name;
  let unit = '';
  // rates like Frames_per_s or Errors_per_min, the unit is the whole "per" part
  const per = /^(.+?)_?(?:per|Per)_?(s|sec|second|min|minute|h|hr|hour)$/.exec(rest);
  if (per && /[_]|Per_/.test(rest.slice(per[1].length))) {
    const span = per[2].toLowerCase();
    return { group, label: words(per[1]), unit: span.startsWith('s') ? '/s' : span.startsWith('m') ? '/min' : '/h' };
  }
  const us = rest.lastIndexOf('_');
  if (us > 0) {
    const suffix = rest.slice(us + 1);
    if (suffix.length <= 5 && /^[a-z0-9%]+$/i.test(suffix) && (/^[a-z0-9%]+$/.test(suffix) || UNIT_TEXT[suffix.toLowerCase()] !== undefined)) {
      unit = UNIT_TEXT[suffix.toLowerCase()] ?? suffix;
      rest = rest.slice(0, us);
    }
  }
  return { group, label: words(rest), unit };
}

export type ValueFlag = 'bad' | 'uncertain' | 'ahead';

// what is off about one value, if anything: the source's own quality, or a time from the future
export function valueFlags(m: { quality?: string | number | null; ts?: string | number | null }, now = Date.now()): ValueFlag[] {
  const out: ValueFlag[] = [];
  const q = m.quality;
  if (q !== null && q !== undefined && q !== '') {
    if (typeof q === 'number') {
      if (q < 64) out.push('bad');
      else if (q < 192) out.push('uncertain');
    } else if (/bad/i.test(String(q))) out.push('bad');
    else if (/uncertain|stale|suspect/i.test(String(q))) out.push('uncertain');
  }
  const t = toMs(m.ts ?? null);
  if (t !== null && t - now > 5000) out.push('ahead');
  return out;
}

export const FLAG_TEXT: Record<ValueFlag, { label: string; why: string }> = {
  bad: { label: 'bad', why: 'The source marked this value as bad, for example a failed sensor. Do not act on it.' },
  uncertain: { label: 'uncertain', why: 'The source is not sure of this value, for example a sensor out of range or a value held over.' },
  ahead: { label: 'clock ahead', why: 'This value is stamped later than now, so the sender clock is ahead. Check its clock or the time format in the mapping.' },
};

// online but silent for a minute or more, its values may be out of date
export function silentFor(lastSeen: string | number | null | undefined, online: boolean, now = Date.now()): number | null {
  if (!online) return null;
  const t = toMs(lastSeen);
  if (t === null) return null;
  const gap = now - t;
  return gap >= 60_000 ? gap : null;
}

export function isNumeric(v: MetricValue): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

export function formatNumber(v: number): string {
  const a = Math.abs(v);
  if (a >= 100000) return v.toLocaleString('en-US', { maximumFractionDigits: 0 });
  if (a >= 100) return v.toLocaleString('en-US', { maximumFractionDigits: 1 });
  if (a >= 1) return v.toLocaleString('en-US', { maximumFractionDigits: 2 });
  if (a === 0) return '0';
  return v.toLocaleString('en-US', { maximumSignificantDigits: 3 });
}

export function formatValue(v: MetricValue): string {
  if (v === null || v === undefined) return 'No value';
  if (typeof v === 'boolean') return v ? 'On' : 'Off';
  if (typeof v === 'number') return Number.isFinite(v) ? formatNumber(v) : 'No value';
  const s = String(v);
  if (!s.trim()) return '–';
  return s.length > 80 ? `${s.slice(0, 77)}...` : s;
}

export function toMs(ts: string | number | null | undefined): number | null {
  if (ts === null || ts === undefined || ts === '') return null;
  if (typeof ts === 'number') return ts < 1e12 ? ts * 1000 : ts;
  const n = Number(ts);
  if (Number.isFinite(n)) return n < 1e12 ? n * 1000 : n;
  const d = Date.parse(ts);
  return Number.isNaN(d) ? null : d;
}

export function ago(ts: string | number | null | undefined, now = Date.now()): string {
  const ms = toMs(ts);
  if (ms === null) return 'never';
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 3) return 'just now';
  if (s < 60) return `${s} s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} h ago`;
  return new Date(ms).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}

const pad = (n: number, w = 2) => String(n).padStart(w, '0');

export function clock(ms: number, withMs = false): string {
  const d = new Date(ms);
  const base = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  return withMs ? `${base}.${pad(d.getMilliseconds(), 3)}` : base;
}

// a live source that batches sends under one message a second, so say readings, or "under 1", never a bare 0
export function liveRate(msgs: number | null | undefined, readings: number | null | undefined, online: boolean): { value: string; unit: string } {
  if (!online) return { value: '0', unit: 'msg/s' };
  const m = Number(msgs) || 0;
  const r = Number(readings) || 0;
  if (m >= 1) return { value: rate(m), unit: 'msg/s' };
  if (r > 0) return { value: rate(r), unit: 'readings/s' };
  if (m > 0) return { value: m.toFixed(1), unit: 'msg/s' };
  return { value: 'under 1', unit: 'msg/s' };
}

export function rate(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '0';
  if (v >= 1000) return `${(v / 1000).toFixed(1)}k`;
  if (v >= 10) return Math.round(v).toString();
  return v.toFixed(1).replace(/\.0$/, '');
}

// a y range with headroom that only moves when the data leaves it, so the axis does not twitch
// the axis respects the signal: no negative axis for values that never go below 0, and percentages stop at 100
export function niceRange(values: number[], prev?: [number, number] | null, unit?: string): [number, number] {
  if (!values.length) return prev ?? [0, 1];
  let lo = Infinity, hi = -Infinity;
  for (const v of values) {
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  const clamp = ([a, b]: [number, number]): [number, number] => {
    let x = a, y = b;
    if (lo >= 0 && x < 0) x = 0;
    if (unit === '%' && lo >= 0 && hi <= 100) { x = Math.max(0, x); y = Math.min(100, y); }
    return [x, y];
  };
  if (prev && lo >= prev[0] && hi <= prev[1]) {
    const span = prev[1] - prev[0];
    // shrink only when the data uses under a third of the range
    if (hi - lo > span / 3 || span === 0) return clamp(prev);
  }
  if (lo === hi) {
    const d = Math.abs(lo) * 0.1 || 1;
    lo -= d;
    hi += d;
  }
  const span = hi - lo;
  const step = 10 ** Math.floor(Math.log10(span / 4));
  const step2 = [1, 2, 2.5, 5, 10].map((m) => m * step).find((u) => span / u <= 6) ?? step * 10;
  const nlo = Math.floor((lo - span * 0.05) / step2) * step2;
  const nhi = Math.ceil((hi + span * 0.05) / step2) * step2;
  return clamp([Number(nlo.toPrecision(12)), Number(nhi.toPrecision(12))]);
}

// a friendly name the node publishes about itself, such as Machine/Name or Properties/Name
const NAME_METRICS = ['Machine/Name', 'Properties/Name', 'Node/Name', 'Properties/Description', 'Machine/Description'];

export function friendlyName(metrics: Array<{ name: string; value: MetricValue }> | undefined): string | null {
  if (!metrics) return null;
  for (const n of NAME_METRICS) {
    const m = metrics.find((x) => x.name === n);
    if (m && typeof m.value === 'string' && m.value.trim()) return m.value.trim().slice(0, 60);
  }
  return null;
}
