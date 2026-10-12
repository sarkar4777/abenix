'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { CartesianGrid, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Loader2 } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { clock, formatNumber, niceRange } from '@/lib/telemetry/format';
import { explainTelemetryError } from '@/lib/telemetry/errors';
import type { HistoryPoint } from '@/lib/telemetry/types';

export const RANGES = [
  { id: '5m', label: '5 min', ms: 5 * 60_000 },
  { id: '15m', label: '15 min', ms: 15 * 60_000 },
  { id: '1h', label: '1 hour', ms: 60 * 60_000 },
  { id: '6h', label: '6 hours', ms: 6 * 60 * 60_000 },
  { id: '24h', label: '24 hours', ms: 24 * 60 * 60_000 },
  { id: '7d', label: '7 days', ms: 7 * 24 * 60 * 60_000 },
] as const;
export type RangeId = (typeof RANGES)[number]['id'];

export const rangeOf = (id: string | null | undefined) => RANGES.find((r) => r.id === id) ?? RANGES[0];

// about 300 points across the chart whatever the range
export function stepFor(ms: number): number {
  return Math.max(1, Math.round(ms / 300 / 1000));
}

export function normalizeHistory(data: unknown, metric?: string): HistoryPoint[] {
  let raw: unknown = Array.isArray(data) ? data : null;
  if (!raw && data && typeof data === 'object') {
    const o = data as Record<string, unknown>;
    if (Array.isArray(o.series)) {
      // {series: [{metric, points}]}, one entry per metric asked for
      const list = o.series as Array<{ metric?: string; points?: unknown }>;
      const hit = list.find((x) => x && x.metric === metric) ?? (list.length === 1 ? list[0] : null);
      raw = hit?.points ?? (list.length && !('metric' in (list[0] || {})) ? list : null);
    } else raw = o.points ?? o.buckets;
  }
  if (!Array.isArray(raw)) return [];
  const out: HistoryPoint[] = [];
  for (const r of raw) {
    let t: unknown, v: unknown;
    if (Array.isArray(r)) [t, v] = r;
    else if (r && typeof r === 'object') {
      const o = r as Record<string, unknown>;
      t = o.t ?? o.time ?? o.bucket ?? o.ts;
      v = o.v ?? o.value ?? o.avg ?? o.num ?? o.mean;
    }
    const tm = typeof t === 'number' ? (t < 1e12 ? t * 1000 : t) : typeof t === 'string' ? Date.parse(t) : NaN;
    const vn = typeof v === 'boolean' ? (v ? 1 : 0) : Number(v);
    if (Number.isFinite(tm) && v !== null && v !== undefined && Number.isFinite(vn)) out.push({ t: tm, v: vn });
  }
  return out.sort((a, b) => a.t - b.t);
}

// stored history plus the live samples newer than it
export function mergeLive(history: HistoryPoint[], live: HistoryPoint[] | undefined, from: number): HistoryPoint[] {
  const lastT = history.length ? history[history.length - 1].t : -Infinity;
  const tail = (live || []).filter((p) => p.t > lastT && p.t >= from);
  const head = history.filter((p) => p.t >= from);
  return tail.length ? head.concat(tail) : head;
}

// a silence much longer than the usual spacing breaks the line instead of drawing across it
// stretches with no data, so the chart can mark them instead of leaving a silent hole
export function findGaps(points: HistoryPoint[], minGapMs = 10_000): Array<{ from: number; to: number }> {
  if (points.length < 3) return [];
  const steps = points.slice(1).map((p, i) => p.t - points[i].t).sort((a, b) => a - b);
  const typical = steps[Math.floor(steps.length / 2)] || 1000;
  const gap = Math.max(minGapMs, typical * 5);
  const out: Array<{ from: number; to: number }> = [];
  for (let i = 1; i < points.length; i++) if (points[i].t - points[i - 1].t > gap) out.push({ from: points[i - 1].t, to: points[i].t });
  return out;
}

export function withGaps(points: HistoryPoint[], minGapMs = 10_000): Array<{ t: number; v: number | null }> {
  if (points.length < 3) return points;
  const steps = points.slice(1).map((p, i) => p.t - points[i].t).sort((a, b) => a - b);
  const typical = steps[Math.floor(steps.length / 2)] || 1000;
  const gap = Math.max(minGapMs, typical * 5);
  const out: Array<{ t: number; v: number | null }> = [points[0]];
  for (let i = 1; i < points.length; i++) {
    if (points[i].t - points[i - 1].t > gap) out.push({ t: points[i - 1].t + 1, v: null });
    out.push(points[i]);
  }
  return out;
}

// where the stored values begin when the range reaches back further than them
export function dataStartsText(firstT: number | undefined, from: number, rangeMs: number): string | null {
  if (firstT === undefined || firstT - from < rangeMs * 0.1) return null;
  const sameDay = new Date(firstT).toDateString() === new Date().toDateString();
  const when = sameDay ? clock(firstT).slice(0, 5) : `${new Date(firstT).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })} ${clock(firstT).slice(0, 5)}`;
  return `Data starts ${when}`;
}

function tickFormat(ms: number, rangeMs: number): string {
  if (rangeMs > 24 * 60 * 60_000) return new Date(ms).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
  if (rangeMs > 60 * 60_000) return clock(ms).slice(0, 5);
  return clock(ms);
}

export default function HistoryChart({
  group, node, device, metric, label, unit, rangeId, live, boolean, paused, height = 240, color = '#22d3ee', syncId, compact,
}: {
  group: string; node: string; device: string; metric: string; label: string; unit: string;
  rangeId: RangeId; live: HistoryPoint[] | undefined; boolean?: boolean; paused?: boolean;
  height?: number; color?: string; syncId?: string; compact?: boolean;
}) {
  const range = rangeOf(rangeId);
  const [history, setHistory] = useState<HistoryPoint[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [reload, setReload] = useState(0);
  const yRef = useRef<[number, number] | null>(null);

  useEffect(() => {
    yRef.current = null;
    setHistory(null);
    setErr(null);
  }, [metric, rangeId, device, node]);

  useEffect(() => {
    let stop = false;
    const load = async () => {
      const to = Date.now();
      const from = to - range.ms;
      const qs = new URLSearchParams({ group, node, device, metric, from: new Date(from).toISOString(), to: new Date(to).toISOString(), step: String(stepFor(range.ms)) });
      const res = await apiFetch<unknown>(`/api/telemetry/history?${qs}`, { silent: true });
      if (stop) return;
      if (res.error) {
        setErr(explainTelemetryError({ status: res.errorDetail?.code, code: res.errorDetail?.error_code, message: res.error }, 'history'));
        setHistory((h) => h ?? []);
        return;
      }
      setErr(null);
      setHistory(normalizeHistory(res.data, metric));
    };
    void load();
    const h = setInterval(load, range.ms <= 60 * 60_000 ? 30_000 : 60_000);
    return () => {
      stop = true;
      clearInterval(h);
    };
  }, [group, node, device, metric, range.ms, reload]);

  // slides the window smoothly, faster for short ranges
  useEffect(() => {
    if (paused) return;
    const every = range.ms <= 15 * 60_000 ? 250 : range.ms <= 6 * 60 * 60_000 ? 5000 : 30_000;
    const h = setInterval(() => setNow(Date.now()), every);
    return () => clearInterval(h);
  }, [range.ms, paused]);

  const from = now - range.ms;
  const data = useMemo(() => mergeLive(history ?? [], live, from), [history, live, from]);
  const drawn = useMemo(() => withGaps(data), [data]);
  const gaps = useMemo(() => findGaps(data), [data]);
  const hatchId = `tel-gap-${metric.replace(/[^a-z0-9]/gi, '')}`;
  const domainY = useMemo(() => {
    if (boolean) return [0, 1] as [number, number];
    const next = niceRange(data.map((p) => p.v), yRef.current, unit);
    yRef.current = next;
    return next;
  }, [data, boolean, unit]);

  const startsText = dataStartsText(data.find((p) => p.v !== null)?.t, from, range.ms);

  if (history === null) {
    return (
      <div className="flex items-center justify-center gap-2 rounded-lg bg-slate-900/40 text-xs text-slate-400" style={{ height }} data-testid="tel-chart-loading">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading the last {range.label}
      </div>
    );
  }
  return (
    <div className="relative" style={{ height }} data-testid="tel-chart" data-points={data.length} data-metric={metric}>
      {data.length === 0 && (
        <div className="absolute inset-0 z-10 flex items-center justify-center p-4 text-center text-sm text-slate-400" data-testid="tel-chart-empty">
          {err ? (
            <span className="text-rose-200">{err} <button type="button" className="text-cyan-300 hover:underline" onClick={() => setReload((n) => n + 1)}>Try again</button></span>
          ) : (
            `No values for ${label} in the last ${range.label} yet. They are stored as they arrive.`
          )}
        </div>
      )}
      {unit && !boolean && (
        <span className="pointer-events-none absolute left-1 top-0 z-[1] text-[10px] text-slate-500" data-testid="tel-chart-unit">{unit}</span>
      )}
      {startsText && data.length > 0 && (
        <span className="pointer-events-none absolute right-3 top-0 z-[1] rounded bg-slate-900/80 px-1 text-[10px] text-slate-400" data-testid="tel-chart-starts">{startsText}</span>
      )}
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={drawn} margin={{ top: unit && !boolean ? 16 : 6, right: 12, bottom: compact ? 0 : 4, left: 4 }} syncId={syncId}>
          <defs>
            <pattern id={hatchId} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="6" stroke="#475569" strokeWidth="1.5" strokeOpacity="0.5" />
            </pattern>
          </defs>
          <CartesianGrid stroke="#1e293b" strokeDasharray="0" vertical={false} />
          {gaps.map((g) => (
            <ReferenceArea
              key={g.from}
              x1={Math.max(g.from, from)}
              x2={Math.min(g.to, now)}
              fill={`url(#${hatchId})`}
              fillOpacity={1}
              strokeOpacity={0}
              ifOverflow="hidden"
              label={(g.to - g.from) / range.ms > 0.08 ? { value: `no data ${clock(g.from).slice(0, 5)} to ${clock(g.to).slice(0, 5)}`, position: 'insideTop', fill: '#94a3b8', fontSize: 10 } : undefined}
            />
          ))}
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={[from, now]}
            allowDataOverflow
            tickFormatter={(v: number) => tickFormat(v, range.ms)}
            tick={compact ? false : { fill: '#94a3b8', fontSize: 11 }}
            height={compact ? 4 : 30}
            tickLine={false}
            axisLine={{ stroke: '#334155' }}
            minTickGap={40}
            tickCount={6}
          />
          <YAxis
            domain={domainY}
            allowDataOverflow
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            width={boolean ? 36 : 56}
            ticks={boolean ? [0, 1] : domainY[0] === 0 && domainY[1] === 100 ? [0, 25, 50, 75, 100] : undefined}
            tickCount={boolean ? undefined : 5}
            tickFormatter={(v: number) => (boolean ? (v ? 'On' : 'Off') : formatNumber(v))}
          />
          <Tooltip
            isAnimationActive={false}
            cursor={{ stroke: '#64748b', strokeWidth: 1 }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const p = payload[0].payload as { t: number; v: number | null };
              const inGap = gaps.find((g) => p.t > g.from && p.t < g.to);
              if (p.v === null || inGap) {
                const g = inGap ?? gaps.find((x) => Math.abs(x.from - p.t) < 2);
                return g ? (
                  <div className="rounded-md border border-slate-600 bg-slate-900/95 px-2 py-1 text-xs text-slate-300 shadow-lg">No data from {clock(g.from)} to {clock(g.to)}</div>
                ) : null;
              }
              return (
                <div className="rounded-md border border-slate-600 bg-slate-900/95 px-2 py-1 text-xs shadow-lg">
                  <p className="text-slate-400">{clock(p.t, range.ms <= 15 * 60_000)}</p>
                  <p className="font-semibold tabular-nums text-white">{boolean ? (p.v ? 'On' : 'Off') : formatNumber(p.v)} {boolean ? '' : unit}</p>
                </div>
              );
            }}
          />
          <Line type={boolean ? 'stepAfter' : 'linear'} dataKey="v" stroke={color} strokeWidth={2} dot={false} activeDot={{ r: 4, stroke: '#0b0f19', strokeWidth: 2 }} isAnimationActive={false} connectNulls={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
