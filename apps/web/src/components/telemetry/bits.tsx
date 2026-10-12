'use client';

import { memo, type ReactNode } from 'react';
import type { HistoryPoint } from '@/lib/telemetry/types';

// fixed size, so a value arriving never moves the row around it
export const Sparkline = memo(function Sparkline({
  points, now, windowMs = 60_000, width = 96, height = 22, label,
}: { points: HistoryPoint[] | undefined; now: number; windowMs?: number; width?: number; height?: number; label?: string }) {
  const all = points || [];
  const end = all.length ? Math.max(now, all[all.length - 1].t) : now;
  const pts = all.filter((p) => p.t >= end - windowMs - 1000);
  // a short history fills the box instead of hugging the right edge
  const from = pts.length ? Math.max(end - windowMs, Math.min(pts[0].t, end - 5000)) : end - windowMs;
  const span = Math.max(1, end - from);
  if (pts.length < 2) {
    return (
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden className="block shrink-0">
        <line x1={0} x2={width} y1={height / 2} y2={height / 2} stroke="#334155" strokeWidth={1} strokeDasharray="2 3" />
      </svg>
    );
  }
  let lo = Infinity, hi = -Infinity;
  for (const p of pts) {
    if (p.v < lo) lo = p.v;
    if (p.v > hi) hi = p.v;
  }
  if (lo === hi) { lo -= 1; hi += 1; }
  const pad = 2;
  const x = (t: number) => Math.max(0, Math.min(width, ((t - from) / span) * width));
  const y = (v: number) => pad + (1 - (v - lo) / (hi - lo)) * (height - pad * 2);
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join('');
  const last = pts[pts.length - 1];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label || 'recent trend'} className="block shrink-0 overflow-visible">
      <path d={d} fill="none" stroke="#22d3ee" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(last.t)} cy={y(last.v)} r={2} fill="#22d3ee" />
    </svg>
  );
});

export function StatusDot({ status, pulse }: { status: 'online' | 'offline' | 'partial' | 'unknown'; pulse?: boolean }) {
  const color = status === 'online' ? 'bg-emerald-400' : status === 'partial' ? 'bg-amber-400' : status === 'offline' ? 'bg-rose-500' : 'bg-slate-500';
  return (
    <span className="relative inline-flex h-2.5 w-2.5 shrink-0" aria-hidden>
      {pulse && status === 'online' && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-50" />}
      <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${color}`} />
    </span>
  );
}

export function StatusPill({ status, testId }: { status: 'online' | 'offline' | 'partial'; testId?: string }) {
  const cls = status === 'online'
    ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
    : status === 'partial'
      ? 'border-amber-500/40 bg-amber-500/10 text-amber-200'
      : 'border-rose-500/40 bg-rose-500/10 text-rose-200';
  const text = status === 'online' ? 'Online' : status === 'partial' ? 'Some devices offline' : 'Offline';
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium ${cls}`} data-testid={testId} data-status={status}>
      <StatusDot status={status} /> {text}
    </span>
  );
}

export function Stat({ label, value, hint, tone = 'plain', testId }: { label: string; value: ReactNode; hint?: ReactNode; tone?: 'plain' | 'warn' | 'bad'; testId?: string }) {
  const valueCls = tone === 'bad' ? 'text-rose-200' : tone === 'warn' ? 'text-amber-200' : 'text-white';
  return (
    <div className="min-w-0 rounded-lg border border-slate-700/50 bg-slate-900/40 px-3 py-2" data-testid={testId}>
      <p className="truncate text-[11px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-0.5 truncate text-lg font-semibold tabular-nums leading-tight ${valueCls}`}>{value}</p>
      {hint && <p className="mt-0.5 truncate text-[11px] text-slate-500">{hint}</p>}
    </div>
  );
}
