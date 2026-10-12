'use client';

import { useEffect, useId, useMemo, useRef, useState } from 'react';
import useSWR from 'swr';
import { Activity, Loader2 } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { fmt, type Scope, type SignalRow } from './lib';
import { cls } from './ui';

function fetcher(url: string) {
  return apiFetch<SignalRow[]>(url, { silent: true });
}

export function signalsUrl(scope: Scope): string | null {
  const q = new URLSearchParams();
  if (scope.kind === 'asset') {
    if (!scope.group || !scope.node) return null;
    q.set('group', scope.group);
    q.set('node', scope.node);
    if (scope.device !== undefined) q.set('device', scope.device);
  } else if (scope.kind === 'type') {
    if (!scope.type) return null;
    q.set('kind', 'type');
    q.set('type', scope.type);
    if (scope.group) q.set('group', scope.group);
  } else {
    if (!scope.tag) return null;
    q.set('kind', 'tag');
    q.set('tag', scope.tag);
    if (scope.group) q.set('group', scope.group);
  }
  return `/api/telemetry/rules/signals?${q.toString()}`;
}

export function useSignals(scope: Scope) {
  const url = signalsUrl(scope);
  const res = useSWR(url, fetcher, { refreshInterval: 5000, revalidateOnFocus: false, keepPreviousData: true });
  const rows = Array.isArray(res.data?.data) ? (res.data!.data as SignalRow[]) : null;
  return { rows, loading: !!url && !res.data && !res.error, error: res.data?.error || null, ready: !!url };
}

export default function SignalPicker({
  value, onChange, scope, label, error, help, testId, disabled, prefer,
}: {
  value: string;
  onChange: (v: string) => void;
  scope: Scope;
  label: string;
  error?: string | null;
  help?: string;
  testId: string;
  disabled?: boolean;
  // numbers first for limits, anything for states
  prefer?: 'numeric' | 'any';
}) {
  const id = useId();
  const { rows, loading, ready } = useSignals(scope);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState(value);
  const [hi, setHi] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => setQ(value), [value]);
  useEffect(() => {
    const off = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', off);
    return () => document.removeEventListener('mousedown', off);
  }, []);

  const list = useMemo(() => {
    const ql = q.trim().toLowerCase();
    const all = (rows || []).filter((r) => !ql || r.signal.toLowerCase().includes(ql));
    if (prefer === 'numeric') all.sort((a, b) => Number(!!b.numeric) - Number(!!a.numeric) || a.signal.localeCompare(b.signal));
    return all.slice(0, 80);
  }, [rows, q, prefer]);
  const known = !value || (rows || []).some((r) => r.signal === value);
  const picked = (rows || []).find((r) => r.signal === value);

  const pick = (s: string) => { onChange(s); setQ(s); setOpen(false); };

  return (
    <div className="min-w-0" ref={box} data-testid={testId}>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-slate-300">{label}</label>
      <div className="relative">
        <Activity className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" aria-hidden />
        <input
          id={id}
          role="combobox"
          aria-expanded={open}
          aria-controls={`${id}-list`}
          aria-autocomplete="list"
          value={q}
          disabled={disabled}
          placeholder={ready ? 'Search the signals streaming now' : 'Pick what to watch first'}
          onFocus={() => setOpen(true)}
          onChange={(e) => { setQ(e.target.value); setOpen(true); setHi(0); onChange(e.target.value.trim()); }}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setHi((h) => Math.min(h + 1, list.length - 1)); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)); }
            else if (e.key === 'Enter' && open && list[hi]) { e.preventDefault(); pick(list[hi].signal); }
            else if (e.key === 'Escape') setOpen(false);
          }}
          className={`${cls(error)} pl-8 font-mono`}
          data-testid={`${testId}-input`}
        />
        {loading && <Loader2 className="absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-slate-500" aria-label="Loading signals" />}
        {open && !disabled && (
          <ul
            id={`${id}-list`}
            role="listbox"
            className="absolute z-30 mt-1 max-h-72 w-full overflow-auto rounded-lg border border-slate-700 bg-slate-950 py-1 shadow-xl"
            data-testid={`${testId}-list`}
          >
            {!ready ? (
              <li className="px-3 py-2 text-xs text-slate-400">Pick the asset, type or tag above, then its signals show here.</li>
            ) : loading ? (
              <li className="px-3 py-2 text-xs text-slate-400">Reading what is streaming now</li>
            ) : list.length === 0 ? (
              <li className="px-3 py-2 text-xs text-slate-400">
                {rows && rows.length === 0 ? 'Nothing is streaming from this yet. You can still type a signal name.' : 'No streaming signal matches. You can keep the name you typed.'}
              </li>
            ) : (
              list.map((r, i) => (
                <li
                  key={r.signal}
                  role="option"
                  aria-selected={i === hi}
                  onMouseDown={(e) => { e.preventDefault(); pick(r.signal); }}
                  onMouseEnter={() => setHi(i)}
                  className={`flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm ${i === hi ? 'bg-slate-800' : ''}`}
                  data-testid={`${testId}-option`}
                  data-signal={r.signal}
                >
                  <span className="min-w-0 flex-1 truncate font-mono text-slate-100">{r.signal}</span>
                  {r.value !== undefined && r.value !== null && (
                    <span className="shrink-0 tabular-nums text-xs text-cyan-300">{fmt(r.value)}{r.unit ? ` ${r.unit}` : ''}</span>
                  )}
                  {r.assets.length > 1 && <span className="shrink-0 text-[11px] text-slate-500">on {r.assets.length}</span>}
                </li>
              ))
            )}
          </ul>
        )}
      </div>
      {error ? (
        <p className="mt-1 text-xs text-rose-300" role="alert">{error}</p>
      ) : value && !known && ready && rows ? (
        <p className="mt-1 text-xs text-amber-300">Not streaming from this right now. The rule starts watching it when it appears.</p>
      ) : picked && picked.value !== undefined && picked.value !== null ? (
        <p className="mt-1 text-xs text-slate-400" data-testid={`${testId}-now`}>Now {fmt(picked.value)}{picked.unit ? ` ${picked.unit}` : ''}{picked.assets.length > 1 ? `, on ${picked.assets.length} assets` : ''}</p>
      ) : help ? (
        <p className="mt-1 text-xs text-slate-500">{help}</p>
      ) : null}
    </div>
  );
}
