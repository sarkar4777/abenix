'use client';

import { Clock } from 'lucide-react';

export function formatExpiry(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function isExpired(row: { expires_at?: string | null; expired?: boolean }): boolean {
  if (row.expired) return true;
  return !!row.expires_at && new Date(row.expires_at).getTime() <= Date.now();
}

/** "expires on …" or "expired" next to a share or grant row. */
export function ShareExpiryBadge({ row }: { row: { expires_at?: string | null; expired?: boolean } }) {
  if (!row.expires_at) return null;
  if (isExpired(row)) {
    return (
      <span className="text-[9px] px-1.5 py-0.5 rounded shrink-0 text-red-300 bg-red-500/10" data-testid="share-expired" title={`Expired ${formatExpiry(row.expires_at)}`}>
        expired
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded shrink-0 text-slate-300 bg-slate-700/40" data-testid="share-expires">
      <Clock className="w-2.5 h-2.5" /> expires on {formatExpiry(row.expires_at)}
    </span>
  );
}

/** Optional expiry picker. Value is a datetime-local string, empty means never. */
export function ShareExpiryInput({ value, onChange, testId = 'share-expiry-input' }: { value: string; onChange: (v: string) => void; testId?: string }) {
  return (
    <label className="flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
      <span>Access ends</span>
      <input
        type="datetime-local"
        value={value}
        min={toLocalInput(new Date())}
        onChange={(e) => onChange(e.target.value)}
        className="px-2 py-1 text-xs bg-slate-900/50 border border-slate-700 rounded-lg text-white [color-scheme:dark]"
        data-testid={testId}
        aria-label="Access ends"
      />
      {value ? (
        <button type="button" onClick={() => onChange('')} className="text-slate-500 hover:text-white underline">never</button>
      ) : (
        <span className="text-slate-500">never, unless you pick a date</span>
      )}
    </label>
  );
}

export function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** datetime-local value to an ISO string with the viewer's offset, or null. */
export function expiryToIso(v: string): string | null {
  if (!v) return null;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}
