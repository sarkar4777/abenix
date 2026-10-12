// SAE J1939 decoding for the raw CAN trace, matching the J1939-71 and -73 layouts.

export interface SpnDef {
  key: string;
  label: string;
  spn: number;
  byte: number;
  bit: number;
  length: number;
  scale?: number;
  offset?: number;
  unit?: string;
  states?: Record<number, string>;
  // left out of the one line summary, still in the frame detail
  quiet?: boolean;
}

export interface PgnDef {
  pgn: number;
  acronym: string;
  name: string;
  spns: SpnDef[];
}

const TWO_BIT: Record<number, string> = { 0: 'off', 1: 'on', 2: 'error', 3: 'not available' };

export const PGNS: Record<number, PgnDef> = {};
function reg(p: PgnDef) {
  PGNS[p.pgn] = p;
}

reg({
  pgn: 61444, acronym: 'EEC1', name: 'Electronic Engine Controller 1', spns: [
    { key: 'engine_speed_rpm', label: 'Engine speed', spn: 190, byte: 3, bit: 0, length: 16, scale: 0.125, unit: 'rpm' },
    { key: 'torque_mode', label: 'Torque mode', spn: 899, byte: 0, bit: 0, length: 4, quiet: true },
    { key: 'drivers_demand_torque_pct', label: 'Demand torque', spn: 512, byte: 1, bit: 0, length: 8, offset: -125, unit: '%' },
    { key: 'actual_torque_pct', label: 'Actual torque', spn: 513, byte: 2, bit: 0, length: 8, offset: -125, unit: '%' },
    { key: 'controlling_sa', label: 'Controlling source', spn: 1483, byte: 5, bit: 0, length: 8, quiet: true },
    { key: 'starter_mode', label: 'Starter mode', spn: 1675, byte: 6, bit: 0, length: 4, quiet: true },
    { key: 'engine_demand_torque_pct', label: 'Engine demand torque', spn: 2432, byte: 7, bit: 0, length: 8, offset: -125, unit: '%' },
  ],
});
reg({
  pgn: 61445, acronym: 'ETC2', name: 'Electronic Transmission Controller 2', spns: [
    { key: 'selected_gear', label: 'Selected gear', spn: 524, byte: 0, bit: 0, length: 8, offset: -125 },
    { key: 'actual_gear_ratio', label: 'Gear ratio', spn: 526, byte: 1, bit: 0, length: 16, scale: 0.001 },
    { key: 'current_gear', label: 'Current gear', spn: 523, byte: 3, bit: 0, length: 8, offset: -125 },
  ],
});
reg({
  pgn: 65262, acronym: 'ET1', name: 'Engine Temperature 1', spns: [
    { key: 'coolant_c', label: 'Coolant', spn: 110, byte: 0, bit: 0, length: 8, offset: -40, unit: '°C' },
    { key: 'fuel_temp_c', label: 'Fuel', spn: 174, byte: 1, bit: 0, length: 8, offset: -40, unit: '°C' },
    { key: 'oil_temp_c', label: 'Oil', spn: 175, byte: 2, bit: 0, length: 16, scale: 0.03125, offset: -273, unit: '°C' },
    { key: 'turbo_oil_temp_c', label: 'Turbo oil', spn: 176, byte: 4, bit: 0, length: 16, scale: 0.03125, offset: -273, unit: '°C' },
    { key: 'intercooler_c', label: 'Intercooler', spn: 52, byte: 6, bit: 0, length: 8, offset: -40, unit: '°C' },
    { key: 'intercooler_thermostat_pct', label: 'Intercooler thermostat', spn: 1134, byte: 7, bit: 0, length: 8, scale: 0.4, unit: '%' },
  ],
});
reg({
  pgn: 65266, acronym: 'LFE1', name: 'Fuel Economy (Liquid)', spns: [
    { key: 'fuel_rate_lph', label: 'Fuel rate', spn: 183, byte: 0, bit: 0, length: 16, scale: 0.05, unit: 'L/h' },
    { key: 'inst_fuel_economy_kmpl', label: 'Instant economy', spn: 184, byte: 2, bit: 0, length: 16, scale: 1 / 512, unit: 'km/L' },
    { key: 'avg_fuel_economy_kmpl', label: 'Average economy', spn: 185, byte: 4, bit: 0, length: 16, scale: 1 / 512, unit: 'km/L' },
    { key: 'throttle_pct', label: 'Throttle', spn: 51, byte: 6, bit: 0, length: 8, scale: 0.4, unit: '%' },
    { key: 'throttle2_pct', label: 'Throttle 2', spn: 3673, byte: 7, bit: 0, length: 8, scale: 0.4, unit: '%' },
  ],
});
reg({
  pgn: 65267, acronym: 'VP', name: 'Vehicle Position', spns: [
    { key: 'latitude_deg', label: 'Latitude', spn: 584, byte: 0, bit: 0, length: 32, scale: 1e-7, offset: -210, unit: '°' },
    { key: 'longitude_deg', label: 'Longitude', spn: 585, byte: 4, bit: 0, length: 32, scale: 1e-7, offset: -210, unit: '°' },
  ],
});
reg({
  pgn: 65265, acronym: 'CCVS1', name: 'Cruise Control/Vehicle Speed 1', spns: [
    { key: 'parking_brake', label: 'Parking brake', spn: 70, byte: 0, bit: 2, length: 2, states: TWO_BIT },
    { key: 'wheel_speed_kmh', label: 'Wheel speed', spn: 84, byte: 1, bit: 0, length: 16, scale: 1 / 256, unit: 'km/h' },
  ],
});
reg({
  pgn: 65253, acronym: 'HOURS', name: 'Engine Hours, Revolutions', spns: [
    { key: 'engine_hours', label: 'Engine hours', spn: 247, byte: 0, bit: 0, length: 32, scale: 0.05, unit: 'h' },
    { key: 'engine_revolutions', label: 'Revolutions', spn: 249, byte: 4, bit: 0, length: 32, scale: 1000, unit: 'r' },
  ],
});
reg({
  pgn: 65256, acronym: 'VDS', name: 'Vehicle Direction/Speed', spns: [
    { key: 'compass_bearing_deg', label: 'Bearing', spn: 165, byte: 0, bit: 0, length: 16, scale: 1 / 128, unit: '°' },
    { key: 'nav_speed_kmh', label: 'Speed', spn: 517, byte: 2, bit: 0, length: 16, scale: 1 / 256, unit: 'km/h' },
    { key: 'pitch_deg', label: 'Pitch', spn: 583, byte: 4, bit: 0, length: 16, scale: 1 / 128, offset: -200, unit: '°' },
    { key: 'altitude_m', label: 'Altitude', spn: 580, byte: 6, bit: 0, length: 16, scale: 0.125, offset: -2500, unit: 'm' },
  ],
});
reg({ pgn: 65226, acronym: 'DM1', name: 'Active Diagnostic Trouble Codes', spns: [] });
reg({ pgn: 60416, acronym: 'TP.CM', name: 'Transport Protocol, Connection Management', spns: [] });
reg({ pgn: 60160, acronym: 'TP.DT', name: 'Transport Protocol, Data Transfer', spns: [] });

export const KNOWN_ACRONYMS = ['EEC1', 'ET1', 'LFE1', 'VP', 'VDS', 'ETC2', 'CCVS1', 'HOURS', 'DM1'];

export const FMI_TEXT: Record<number, string> = {
  0: 'Above normal range, most severe',
  1: 'Below normal range, most severe',
  2: 'Data erratic or incorrect',
  3: 'Voltage high or shorted high',
  4: 'Voltage low or shorted low',
  5: 'Current low or open circuit',
  6: 'Current high or grounded circuit',
  7: 'Mechanical system not responding',
  8: 'Abnormal frequency or pulse width',
  9: 'Abnormal update rate',
  10: 'Abnormal rate of change',
  11: 'Root cause not known',
  12: 'Bad intelligent device',
  13: 'Out of calibration',
  14: 'Special instructions',
  15: 'Above normal range, least severe',
  16: 'Above normal range, moderately severe',
  17: 'Below normal range, least severe',
  18: 'Below normal range, moderately severe',
  19: 'Received network data in error',
  31: 'Condition exists',
};

export const SPN_TEXT: Record<number, string> = {
  51: 'Throttle position',
  84: 'Wheel-based vehicle speed',
  100: 'Engine oil pressure',
  110: 'Engine coolant temperature',
  175: 'Engine oil temperature',
  177: 'Transmission oil temperature',
  190: 'Engine speed',
  584: 'Latitude (GNSS)',
  639: 'J1939 network 1',
  1638: 'Hydraulic temperature',
  1762: 'Hydraulic pressure',
  2602: 'Hydraulic oil level',
};

export interface CanId { priority: number; pgn: number; sa: number; da: number }

export function parseCanId(id: number): CanId {
  const priority = Math.floor(id / 2 ** 26) & 0x7;
  const dp = Math.floor(id / 2 ** 24) & 0x3;
  const pf = (id >>> 16) & 0xff;
  const ps = (id >>> 8) & 0xff;
  const sa = id & 0xff;
  if (pf < 240) return { priority, pgn: dp * 65536 + pf * 256, sa, da: ps };
  return { priority, pgn: dp * 65536 + pf * 256 + ps, sa, da: 0xff };
}

// J1939-71 keeps the top of each range for error and not available
export function maxValid(length: number): number {
  if (length === 2) return 1;
  if (length === 4) return 0xa;
  if (length === 8) return 0xfa;
  if (length === 16) return 0xfaff;
  if (length === 32) return 0xfaffffff;
  return 2 ** length - 1;
}

export function readBits(bytes: readonly number[], shift: number, length: number): number {
  let out = 0;
  for (let i = length - 1; i >= 0; i--) {
    const pos = shift + i;
    const b = bytes[pos >> 3] ?? 0xff;
    out = out * 2 + ((b >> (pos & 7)) & 1);
  }
  return out;
}

// "0A1B2C", "0a 1b 2c" or [10, 27, 44]
export function toBytes(data: unknown): number[] {
  if (Array.isArray(data)) return data.map((n) => Number(n) & 0xff);
  if (typeof data !== 'string') return [];
  const hex = data.replace(/^0x/i, '').replace(/[^0-9a-f]/gi, '');
  const out: number[] = [];
  for (let i = 0; i + 1 < hex.length; i += 2) out.push(parseInt(hex.slice(i, i + 2), 16));
  return out;
}

export function hexOf(bytes: readonly number[]): string {
  return bytes.map((b) => b.toString(16).toUpperCase().padStart(2, '0')).join(' ');
}

export function idHex(id: number): string {
  return id.toString(16).toUpperCase().padStart(8, '0');
}

export interface Signal { key: string; label: string; value: number | null; text: string; unit: string; quiet?: boolean }

function round(v: number, scale: number): number {
  const digits = scale >= 1 ? 0 : Math.min(7, Math.ceil(-Math.log10(scale)) + 1);
  return Number(v.toFixed(digits));
}

export function decodeSignals(pgn: number, bytes: readonly number[]): Signal[] {
  const def = PGNS[pgn];
  if (!def) return [];
  const padded = [...bytes.slice(0, 8)];
  while (padded.length < 8) padded.push(0xff);
  return def.spns.map((s) => {
    const raw = readBits(padded, s.byte * 8 + s.bit, s.length);
    const scale = s.scale ?? 1;
    const quiet = s.quiet;
    if (raw > maxValid(s.length)) return { key: s.key, label: s.label, value: null, text: 'n/a', unit: s.unit ?? '', quiet };
    if (s.states) return { key: s.key, label: s.label, value: raw, text: s.states[raw] ?? String(raw), unit: '', quiet };
    const value = round(raw * scale + (s.offset ?? 0), scale);
    return { key: s.key, label: s.label, value, text: String(value), unit: s.unit ?? '', quiet };
  });
}

export interface Dtc { spn: number; fmi: number; oc: number; spnText: string; fmiText: string }
export interface Lamps { mil: number; red_stop: number; amber_warning: number; protect: number }

export function decodeDm1(bytes: readonly number[]): { lamps: Lamps; dtcs: Dtc[] } {
  const b = bytes[0] ?? 0;
  const lamps = { mil: (b >> 6) & 3, red_stop: (b >> 4) & 3, amber_warning: (b >> 2) & 3, protect: b & 3 };
  const dtcs: Dtc[] = [];
  for (let i = 2; i + 3 < bytes.length; i += 4) {
    const c = bytes.slice(i, i + 4);
    if (c.every((x) => x === 0xff)) break;
    const spn = c[0] | (c[1] << 8) | (((c[2] >> 5) & 0x7) << 16);
    const fmi = c[2] & 0x1f;
    if (spn === 0 && fmi === 0) continue;
    dtcs.push({ spn, fmi, oc: c[3] & 0x7f, spnText: SPN_TEXT[spn] ?? `SPN ${spn}`, fmiText: FMI_TEXT[fmi] ?? `FMI ${fmi}` });
  }
  return { lamps, dtcs };
}

export interface RawFrame { t: number; id: number; data: number[]; dlc: number }

export interface DecodedFrame extends RawFrame {
  // epoch ms
  ms: number;
  pgn: number;
  sa: number;
  da: number;
  priority: number;
  acronym: string | null;
  name: string | null;
  summary: string;
  signals: Signal[];
  dm1?: { lamps: Lamps; dtcs: Dtc[] };
}

export function normalizeFrame(f: unknown): RawFrame | null {
  if (!f || typeof f !== 'object') return null;
  const o = f as Record<string, unknown>;
  const id = typeof o.id === 'string' ? parseInt(o.id.replace(/^0x/i, ''), 16) : Number(o.id);
  if (!Number.isFinite(id)) return null;
  const data = toBytes(o.data);
  const t = Number(o.t ?? o.ts ?? o.time ?? 0);
  return { t, id, data, dlc: Number.isFinite(Number(o.dlc)) ? Number(o.dlc) : data.length };
}

// seconds or milliseconds since the epoch
export function frameMs(t: number): number {
  return t < 1e12 ? t * 1000 : t;
}

function lampText(l: Lamps): string {
  const on = [l.mil === 1 && 'check engine', l.red_stop === 1 && 'red stop', l.amber_warning === 1 && 'amber warning', l.protect === 1 && 'protect'].filter(Boolean);
  return on.length ? `lamps: ${on.join(', ')}` : 'no lamps on';
}

export function dm1Summary(d: { lamps: Lamps; dtcs: Dtc[] }): string {
  if (!d.dtcs.length) return `No active faults, ${lampText(d.lamps)}`;
  const codes = d.dtcs.map((x) => `${x.spnText} (SPN ${x.spn} FMI ${x.fmi}), ${x.fmiText.toLowerCase()}`).join('. ');
  return `${d.dtcs.length} active fault${d.dtcs.length === 1 ? '' : 's'}, ${lampText(d.lamps)}. ${codes}`;
}

export function decodeFrame(raw: RawFrame): DecodedFrame {
  const { priority, pgn, sa, da } = parseCanId(raw.id);
  const def = PGNS[pgn];
  const base = { ...raw, ms: frameMs(raw.t), pgn, sa, da, priority, acronym: def?.acronym ?? null, name: def?.name ?? null, signals: [] as Signal[] };
  if (!def) {
    const pf = (pgn >> 8) & 0xff;
    return { ...base, summary: pf === 0xff ? 'Proprietary B, maker specific' : pf === 0xef ? 'Proprietary A, maker specific' : 'Not decoded' };
  }
  if (def.acronym === 'DM1') {
    const dm1 = decodeDm1(raw.data);
    return { ...base, dm1, summary: dm1Summary(dm1) };
  }
  if (def.acronym === 'TP.CM') {
    const d = raw.data;
    const size = (d[1] ?? 0) | ((d[2] ?? 0) << 8);
    const target = (d[5] ?? 0) | ((d[6] ?? 0) << 8) | ((d[7] ?? 0) << 16);
    const name = PGNS[target]?.acronym ?? `PGN ${target}`;
    return { ...base, summary: d[0] === 32 ? `Announces ${name}, ${size} bytes in ${d[3] ?? 0} packets` : `Transport control for ${name}` };
  }
  if (def.acronym === 'TP.DT') return { ...base, summary: `Packet ${raw.data[0] ?? '?'} of a multi-packet message` };
  const signals = decodeSignals(pgn, raw.data);
  const summary = signals
    .filter((s) => s.value !== null && !s.quiet)
    .map((s) => `${s.label} ${s.text}${s.unit ? ` ${s.unit}` : ''}`)
    .join(', ');
  return { ...base, signals, summary: summary || 'All values not available' };
}

// reassembles BAM transfers per source address so a long DM1 decodes on its last packet
export class BamAssembler {
  private open = new Map<number, { pgn: number; size: number; packets: number; parts: number[][] }>();

  push(f: DecodedFrame): DecodedFrame {
    if (f.acronym === 'TP.CM' && f.data[0] === 32) {
      const d = f.data;
      this.open.set(f.sa, { pgn: d[5] | (d[6] << 8) | (d[7] << 16), size: d[1] | (d[2] << 8), packets: d[3], parts: [] });
      return f;
    }
    if (f.acronym !== 'TP.DT') return f;
    const s = this.open.get(f.sa);
    if (!s) return f;
    const seq = f.data[0];
    s.parts[seq - 1] = f.data.slice(1, 8);
    if (seq < s.packets) return f;
    this.open.delete(f.sa);
    const payload = s.parts.flat().slice(0, s.size);
    const def = PGNS[s.pgn];
    if (def?.acronym === 'DM1') {
      const dm1 = decodeDm1(payload);
      return { ...f, acronym: 'DM1', name: def.name, pgn: s.pgn, dm1, summary: `${dm1Summary(dm1)} (reassembled)` };
    }
    return { ...f, summary: `Last packet of ${def?.acronym ?? `PGN ${s.pgn}`}, ${s.size} bytes` };
  }
}
