import type { LineOutcome, Review, Status } from './api';

export const STATUS_LABEL: Record<Status, string> = {
  waiting: 'Waiting',
  processing: 'Processing',
  success: 'Success',
  clarification: 'Need customer clarification',
  escalated: 'Escalated',
  system_error: 'System error',
};

/** Shorter labels for the status cards and rows. */
export const STATUS_SHORT: Record<Status, string> = {
  ...STATUS_LABEL,
  clarification: 'Clarify with customer',
};

export const STATUS_TONE: Record<Status, { text: string; dot: string; ring: string; bg: string }> = {
  waiting: { text: 'text-slate-400', dot: 'bg-slate-600', ring: 'ring-slate-700', bg: 'bg-slate-800/40' },
  processing: { text: 'text-sky-300', dot: 'bg-sky-400', ring: 'ring-sky-500/40', bg: 'bg-sky-500/10' },
  success: { text: 'text-emerald-300', dot: 'bg-emerald-400', ring: 'ring-emerald-500/40', bg: 'bg-emerald-500/10' },
  clarification: { text: 'text-amber-300', dot: 'bg-amber-400', ring: 'ring-amber-500/40', bg: 'bg-amber-500/10' },
  escalated: { text: 'text-violet-300', dot: 'bg-violet-400', ring: 'ring-violet-500/40', bg: 'bg-violet-500/10' },
  system_error: { text: 'text-rose-300', dot: 'bg-rose-400', ring: 'ring-rose-500/40', bg: 'bg-rose-500/10' },
};

export const REVIEW_LABEL: Record<Exclude<Review, null>, string> = {
  awaiting_review: 'awaiting review',
  redrafting: 'redrafting',
  review_expired: 'review expired',
  sent: 'sent',
};

export const OUTCOME_LABEL: Record<LineOutcome, string> = {
  matched: 'Matched',
  needs_clarification: 'Needs clarification',
  not_in_catalogue: 'Not in catalogue',
  erp_record_inconsistent: 'ERP record inconsistent',
};

export const OUTCOME_TONE: Record<LineOutcome, string> = {
  matched: 'text-emerald-300 bg-emerald-500/10 ring-emerald-500/30',
  needs_clarification: 'text-amber-300 bg-amber-500/10 ring-amber-500/30',
  not_in_catalogue: 'text-violet-300 bg-violet-500/10 ring-violet-500/30',
  erp_record_inconsistent: 'text-rose-300 bg-rose-500/10 ring-rose-500/30',
};

/** MIL-STD-681 colour codes, as used in M22759 and JSS 51034 part numbers. */
export const COLOUR_CODES: Record<string, string> = {
  '0': 'black', '1': 'brown', '2': 'red', '3': 'orange', '4': 'yellow',
  '5': 'green', '6': 'blue', '7': 'violet', '8': 'grey', '9': 'white',
};

/** "Daniel Okafor, Quillfeather Avionics" → ["Daniel Okafor", "Quillfeather Avionics"]. */
export function splitSender(fromName: string): [string, string | null] {
  const i = fromName.indexOf(',');
  return i < 0 ? [fromName, null] : [fromName.slice(0, i).trim(), fromName.slice(i + 1).trim()];
}

export function unit(uom?: string): string {
  if (!uom) return 'm';
  const u = uom.toLowerCase();
  if (u.startsWith('kg') || u.startsWith('kilo')) return 'kg';
  if (u.startsWith('m')) return 'm';
  return u;
}

export function money(value: number | null | undefined, currency = 'USD', unitPrice = false): string {
  if (value === null || value === undefined) return '–';
  return `${currency} ${value.toLocaleString('en-GB', {
    minimumFractionDigits: 2,
    maximumFractionDigits: unitPrice ? 4 : 2,
  })}`;
}

export function qty(value: number | null | undefined): string {
  if (value === null || value === undefined) return '–';
  return value.toLocaleString('en-GB');
}

/** In days, as the ERP gives it and the drafted emails quote it. */
export function leadTime(days?: number | null): string {
  if (days === null || days === undefined) return '–';
  return `${days} day${days === 1 ? '' : 's'}`;
}

export function seconds(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '';
  const s = Math.round(ms / 1000);
  return s < 120 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
}

export function clock(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay
    ? d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

/**
 * A product name, safe to render whatever shape it came in. The model copies
 * product records from the ERP as they are, and the API passes them through,
 * so this keeps one odd answer from breaking the page. The API already turns
 * the free-text fields (reasons, problems, references) into text.
 */
export function asText(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(asText).filter(Boolean).join('; ');
  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${asText(v)}`).join('; ');
  }
  return String(value);
}

const KEY_LABEL: Record<string, string> = {
  awg: 'AWG',
  od_mm: 'OD (mm)',
  od_tolerance_mm: 'OD tolerance (mm)',
  min_voltage_v: 'min voltage (V)',
  voltage_v: 'voltage (V)',
  voltage: 'voltage (V)',
  min_test_voltage_v: 'min test voltage (V)',
  temp_min_c: 'min temp (°C)',
  temp_max_c: 'max temp (°C)',
  colour_code: 'colour',
  standard_part_number: 'part number',
  part_number: 'part number',
};

export function keyLabel(key: string): string {
  return KEY_LABEL[key] ?? key.replace(/_/g, ' ');
}

/** A value from the matcher's understanding or filters, readable. */
export function valueLabel(key: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '–';
  if (Array.isArray(value)) return value.map((v) => valueLabel(key, v)).join(', ');
  if (key === 'colour_code' && typeof value === 'string' && COLOUR_CODES[value]) {
    return `${value} (${COLOUR_CODES[value]})`;
  }
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
