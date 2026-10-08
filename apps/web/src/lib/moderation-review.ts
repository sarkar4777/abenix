// Pure helpers for the held content inbox and the redaction editor.

export interface Span {
  start: number;
  end: number;
  category: string;
}

export interface Segment {
  text: string;
  category?: string;
}

// sorted, overlaps joined, clipped to the text
export function normaliseSpans(spans: Span[] | undefined, length: number): Span[] {
  const sorted = (spans || [])
    .map((s) => ({ start: Math.max(0, Math.min(length, s.start)), end: Math.max(0, Math.min(length, s.end)), category: s.category || '' }))
    .filter((s) => s.end > s.start)
    .sort((a, b) => a.start - b.start || a.end - b.end);
  const out: Span[] = [];
  for (const s of sorted) {
    const last = out[out.length - 1];
    if (last && s.start <= last.end) {
      last.end = Math.max(last.end, s.end);
      const cats = new Set([...last.category.split(','), ...s.category.split(',')].filter(Boolean));
      last.category = Array.from(cats).join(',');
    } else {
      out.push({ ...s });
    }
  }
  return out;
}

// the text cut into plain and matched pieces, for highlighting
export function segments(text: string, spans: Span[] | undefined): Segment[] {
  const merged = normaliseSpans(spans, text.length);
  const out: Segment[] = [];
  let at = 0;
  for (const s of merged) {
    if (s.start > at) out.push({ text: text.slice(at, s.start) });
    out.push({ text: text.slice(s.start, s.end), category: s.category });
    at = s.end;
  }
  if (at < text.length) out.push({ text: text.slice(at) });
  return out;
}

// every matched span replaced by the mask
export function maskAll(text: string, spans: Span[] | undefined, mask: string): string {
  return normaliseSpans(spans, text.length)
    .reverse()
    .reduce((acc, s) => acc.slice(0, s.start) + mask + acc.slice(s.end), text);
}

// one selection in the editor replaced by the mask
export function maskRange(text: string, start: number, end: number, mask: string): string {
  const a = Math.max(0, Math.min(start, end));
  const b = Math.min(text.length, Math.max(start, end));
  if (b <= a) return text;
  return text.slice(0, a) + mask + text.slice(b);
}

// custom:0 is the policy's first pattern, the way /moderation numbers them
export function categoryLabel(cat: string): string {
  const m = /^custom:(\d+)$/.exec(cat);
  if (!m) return cat.replace(/\//g, ' / ');
  return `custom pattern ${Number(m[1]) + 1}`;
}

export function slaText(expiresAt: string | null, timeoutAction: string, now: number): { text: string; urgent: boolean } {
  if (!expiresAt) return { text: '', urgent: false };
  const ms = new Date(expiresAt).getTime() - now;
  if (Number.isNaN(ms)) return { text: '', urgent: false };
  const verb = timeoutAction === 'release' ? 'Releases' : 'Rejects';
  if (ms <= 0) return { text: `${verb} on its own any moment now`, urgent: true };
  const min = Math.ceil(ms / 60_000);
  const when = min < 60 ? `${min} min` : min < 48 * 60 ? `${Math.floor(min / 60)} h ${min % 60 ? `${min % 60} min` : ''}`.trim() : `${Math.round(min / 1440)} days`;
  return { text: `${verb} on its own in ${when}`, urgent: min <= 10 };
}

export function ago(iso: string | null, now: number): string {
  if (!iso) return '';
  const ms = now - new Date(iso).getTime();
  if (Number.isNaN(ms)) return '';
  const min = Math.floor(ms / 60_000);
  if (min < 1) return 'just now';
  if (min < 60) return `${min} min ago`;
  const h = Math.floor(min / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.floor(h / 24)} days ago`;
}

export const PRIORITY_STYLE: Record<number, string> = {
  3: 'bg-rose-500/15 text-rose-200 ring-rose-500/40',
  2: 'bg-amber-500/15 text-amber-200 ring-amber-500/40',
  1: 'bg-slate-600/30 text-slate-200 ring-slate-500/40',
};

// keys the inbox listens for, shown in its help panel
export const SHORTCUTS: Array<[string, string]> = [
  ['j / k', 'Next or previous item'],
  ['x', 'Select or unselect the item'],
  ['c', 'Claim it'],
  ['u', 'Unassign it'],
  ['r', 'Release it as written'],
  ['e', 'Redact, then release'],
  ['d', 'Reject it with a reason'],
  ['?', 'Show or hide these shortcuts'],
];

export const HOLD_MAX_MINUTES = 7 * 24 * 60;

// the review time limit as typed, or why it cannot be saved
export function holdMinutesError(raw: string): string | null {
  const v = raw.trim();
  if (!v) return 'Enter how many minutes a reviewer has.';
  if (!/^\d+$/.test(v)) return 'Use a whole number of minutes.';
  const n = Number(v);
  if (n < 1 || n > HOLD_MAX_MINUTES) return `Between 1 and ${HOLD_MAX_MINUTES} minutes (7 days).`;
  return null;
}
