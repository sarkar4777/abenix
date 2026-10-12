// which signals to chart first, so a fresh view never opens on a flat or empty line
import type { HistoryPoint, Metric } from './types';
import { isNumeric } from './format';

// headline signals by kind of asset, most telling first
const PRIORITY: RegExp[] = [
  /engine.*(speed|rpm)|(^|\/)speed_rpm$|_rpm$/i,
  /coolant|engine.*(oil.?temp|temp)/i,
  /pressure|_bar$|_kpa$|_psi$/i,
  /(^|\/)(load|torque)|_pct$/i,
  /fuel.*rate|_lph$|flow/i,
  /(vehicle|wheel|nav|ground)?.?speed.*(kmh|mps|kph)|speed_kmh|_kmh$/i,
  /latitude|(^|\/)lat(_deg)?$|gnss\/x|gnss\/y|longitude|(^|\/)lon(_deg)?$/i,
  /power|_kw$|_w$|energy|_kwh$/i,
  /voltage|_v$|current|_a$/i,
  /swing|boom|slew|hoist|luff|blade|kinematics/i,
  /temp|_c$|humidity/i,
];

export const SERIES_COLORS = ['#22d3ee', '#a78bfa', '#fbbf24', '#34d399', '#f472b6', '#60a5fa'];
export const MAX_SIGNALS = 6;

function varies(points: HistoryPoint[] | undefined): boolean {
  if (!points || points.length < 3) return true;
  let lo = Infinity, hi = -Infinity;
  for (const p of points.slice(-60)) {
    if (p.v < lo) lo = p.v;
    if (p.v > hi) hi = p.v;
  }
  return hi > lo;
}

export function defaultSignals(metrics: Metric[], samples: Record<string, HistoryPoint[]> | undefined, count = 3): string[] {
  const nums = metrics.filter((m) => isNumeric(m.value)).sort((a, b) => a.name.localeCompare(b.name));
  const score = (m: Metric) => {
    const i = PRIORITY.findIndex((re) => re.test(m.name));
    const rank = i < 0 ? PRIORITY.length : i;
    // a flat line says little on screen, it goes last
    return rank + (varies(samples?.[m.name]) ? 0 : 100);
  };
  const ranked = [...nums].sort((a, b) => score(a) - score(b) || a.name.localeCompare(b.name));
  const out: string[] = [];
  const seenRank = new Set<number>();
  // one per kind first, so rpm and coolant beat two temperatures
  for (const m of ranked) {
    const r = PRIORITY.findIndex((re) => re.test(m.name));
    if (r >= 0 && seenRank.has(r)) continue;
    seenRank.add(r);
    out.push(m.name);
    if (out.length >= count) return out;
  }
  for (const m of ranked) {
    if (!out.includes(m.name)) out.push(m.name);
    if (out.length >= count) break;
  }
  return out;
}

export function parseSignals(raw: string | null | undefined): string[] {
  return (raw || '').split(',').map((s) => s.trim()).filter(Boolean).slice(0, MAX_SIGNALS);
}
