// Consistent rendering for "honest zero" vs "never configured" so admin
// dashboards don't look like a forest of meaningless 0s.
//
// Rules:
//   null / undefined / NaN  -> "—"  (never configured / unknown)
//   0                       -> "0"  (a real zero — idle, no cache hits, etc)
//   positive numbers        -> formatted with thousands separators

export type Nullable = number | null | undefined;

function isMissing(n: Nullable): n is null | undefined {
  return n == null || (typeof n === 'number' && Number.isNaN(n));
}

export function formatCount(n: Nullable): string {
  if (isMissing(n)) return '—';
  if (n === 0) return '0';
  return n.toLocaleString();
}

export function formatRate(n: Nullable): string {
  if (isMissing(n)) return '—';
  if (n === 0) return '0/s';
  const v = n >= 10 ? n.toFixed(1) : n.toFixed(2);
  return `${v}/s`;
}

export function formatPct(n: Nullable): string {
  if (isMissing(n)) return '—';
  if (n === 0) return '0%';
  return `${Math.round(n)}%`;
}

export function formatMs(n: Nullable): string {
  if (isMissing(n)) return '—';
  if (n === 0) return '0ms';
  if (n >= 1000) return `${(n / 1000).toFixed(1)}s`;
  return `${Math.round(n)}ms`;
}

export function formatUsd(n: Nullable): string {
  if (isMissing(n)) return '—';
  if (n === 0) return '$0';
  if (n >= 1) return `$${n.toFixed(2)}`;
  return `$${n.toFixed(4)}`;
}

// Tailwind class for an "honest zero" — same value, dimmer so it
// doesn't compete with real data on the page.
export const dimZero = 'text-slate-500';

// Decide which class to apply: dim when 0, default-passed-in when real.
export function zeroDim(n: Nullable, normalClass = ''): string {
  if (isMissing(n)) return 'text-slate-600';
  if (n === 0) return dimZero;
  return normalClass;
}
