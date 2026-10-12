'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowRight, Bot, Radio } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';

interface Point { t: number; avg: number | null; min: number | null; max: number | null }

interface CommandPayload {
  summary?: string;
  command?: { group: string; node: string; device: string; signal: string; value: unknown };
  asset?: { key: string; name: string; type?: string | null; tags?: string[] };
  reason?: string;
  agent?: { id: string; name: string };
  current?: { value: unknown; ts?: number | null } | null;
  preview?: { topic?: string | null; payload?: unknown };
  history?: { minutes?: number; points?: Point[]; summary?: Record<string, number> | null } | null;
  states?: State[] | null;
  evidence?: Array<{ source: 'firing' | 'read'; title: string; signal: string | null; unit?: string | null; key?: string; rule?: string; detail?: string; marks?: Mark[]; caption?: string | null; gap?: Gap | null; points: Point[] }>;
  requested_at?: number;
  policy?: string;
  why?: string;
  sent_at?: number;
}

function show(v: unknown): string {
  if (v === null || v === undefined) return 'unknown';
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

function hhmm(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export interface Mark { label: string; value: number; kind?: 'limit' | 'normal' }
export interface Gap { from: number; to: number; label: string }

function fmtNum(v: number): string {
  return Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2);
}

// the signal over the last minutes, a min to max band with the average on top and the rule's lines dashed
export function HistoryChart({ points, target, marks = [], unit, gap }: { points: Point[]; target?: number | null; marks?: Mark[]; unit?: string | null; gap?: Gap | null }) {
  const nums = points.filter((p) => p.avg !== null && p.min !== null && p.max !== null) as Array<Required<{ t: number; avg: number; min: number; max: number }>>;
  if (nums.length < 2) {
    return <p className="text-[11px] text-slate-500" data-testid="command-history-empty">Only {nums.length === 1 ? 'one reading' : 'no readings'} in this window so far, so there is no line to draw.</p>;
  }
  const W = 320, H = 80, pad = 2;
  const dlo = Math.min(...nums.map((p) => p.min)), dhi = Math.max(...nums.map((p) => p.max));
  const span = Math.max(dhi - dlo, Math.abs(dhi) * 0.05, 1e-6);
  // a line far from the readings would flatten them, it is named instead of drawn
  const near = (v: number) => v >= dlo - span && v <= dhi + span;
  const drawn = marks.filter((m) => near(m.value));
  const offChart = marks.filter((m) => !near(m.value));
  const lines = [...drawn.map((m) => m.value), ...(typeof target === 'number' ? [target] : [])];
  const vals = nums.flatMap((p) => [p.min, p.max]).concat(lines);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (lo === hi) { lo -= 1; hi += 1; }
  const t0 = nums[0].t, t1 = Math.max(nums[nums.length - 1].t || t0 + 1, gap?.to || 0);
  const x = (t: number) => pad + ((t - t0) / Math.max(1, t1 - t0)) * (W - pad * 2);
  const y = (v: number) => H - pad - ((v - lo) / (hi - lo)) * (H - pad * 2);
  const band = `${nums.map((p) => `${x(p.t)},${y(p.max)}`).join(' ')} ${nums.slice().reverse().map((p) => `${x(p.t)},${y(p.min)}`).join(' ')}`;
  const line = nums.map((p) => `${x(p.t)},${y(p.avg)}`).join(' ');
  const u = unit ? ` ${unit}` : '';
  const last = nums[nums.length - 1].avg;
  return (
    <figure className="min-w-0" data-testid="command-history-chart">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-20 w-full" preserveAspectRatio="none" role="img" aria-label={`From ${fmtNum(lo)} to ${fmtNum(hi)}${u} between ${hhmm(t0)} and ${hhmm(t1)}, now ${fmtNum(last)}${u}`}>
        <polygon points={band} fill="rgba(34,211,238,0.15)" />
        <polyline points={line} fill="none" stroke="#22d3ee" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
        {gap && <rect x={x(Math.max(gap.from, t0))} y={0} width={Math.max(1, x(gap.to) - x(Math.max(gap.from, t0)))} height={H} fill="rgba(148,163,184,0.18)" />}
        {drawn.map((m) => (
          <line key={m.label} x1={pad} x2={W - pad} y1={y(m.value)} y2={y(m.value)} stroke={m.kind === 'normal' ? '#94a3b8' : '#f87171'} strokeDasharray={m.kind === 'normal' ? '2 3' : '4 3'} strokeWidth={1} vectorEffect="non-scaling-stroke" />
        ))}
        {typeof target === 'number' && (
          <line x1={pad} x2={W - pad} y1={y(target)} y2={y(target)} stroke="#fbbf24" strokeDasharray="4 3" strokeWidth={1} vectorEffect="non-scaling-stroke" />
        )}
      </svg>
      <figcaption className="mt-0.5 flex flex-wrap justify-between gap-x-2 text-[10px] text-slate-500">
        <span>{hhmm(t0)}</span>
        <span>
          now {fmtNum(last)}{u}, low {fmtNum(lo)}, high {fmtNum(hi)}
          {drawn.some((m) => m.kind === 'normal') ? `, grey dots: ${drawn.filter((m) => m.kind === 'normal').map((m) => m.label).join(', ')}` : ''}
          {drawn.some((m) => m.kind !== 'normal') ? `, red dashes: ${drawn.filter((m) => m.kind !== 'normal').map((m) => m.label).join(', ')}` : ''}
          {gap ? `, shaded: ${gap.label}` : ''}
          {offChart.length ? `, ${offChart.map((m) => `${m.label} is ${m.value < dlo ? 'below' : 'above'} the chart`).join(', ')}` : ''}
          {typeof target === 'number' ? ', amber dashes: the new value' : ''}
        </span>
        <span>{hhmm(t1)}</span>
      </figcaption>
    </figure>
  );
}

export interface State { t: number | null; value: unknown; before?: boolean }

// a text or on/off signal as the states it was in, the one it is in now, when it was asked, and the proposal
export function StateTimeline({ states, next, askedAt }: { states: State[]; next: unknown; askedAt?: number | null }) {
  if (!states.length) return null;
  const lastI = states.length - 1;
  return (
    <ol className="flex flex-wrap items-center gap-1.5 text-[11px]" data-testid="command-states" aria-label="The states it was in, when it was asked, and the new one">
      {states.map((s, i) => (
        <li key={i} className="flex items-center gap-1.5" data-testid={i === lastI ? 'command-state-now' : 'command-state'}>
          <span className="rounded border border-slate-600 bg-slate-900/70 px-1.5 py-0.5 text-slate-200">{show(s.value)}</span>
          <span className="text-slate-500">
            {s.t ? (i === lastI ? `since ${s.before ? 'before ' : ''}${hhmm(s.t)}` : `${s.before ? 'before ' : 'from '}${hhmm(s.t)}`) : ''}
          </span>
          <ArrowRight className="h-3 w-3 text-slate-500" aria-hidden />
        </li>
      ))}
      {askedAt ? (
        <li className="flex items-center gap-1.5" data-testid="command-asked-at">
          <span className="rounded-full border border-cyan-500/40 px-1.5 py-0.5 text-cyan-200">asked {hhmm(askedAt)}</span>
          <ArrowRight className="h-3 w-3 text-slate-500" aria-hidden />
        </li>
      ) : null}
      <li><span className="rounded border border-amber-500/50 bg-amber-500/15 px-1.5 py-0.5 font-semibold text-amber-100">{show(next)}</span> <span className="text-slate-500">proposed</span></li>
    </ol>
  );
}

export default function CommandApproval({ payload, pending, executionId }: { payload: Record<string, unknown>; pending: boolean; executionId?: string | null }) {
  const p = payload as CommandPayload;
  const c = p.command;
  const [now, setNow] = useState<{ value: unknown; online: boolean } | null>(null);

  // while it waits, show the reading as it is now, not only as it was when asked
  useEffect(() => {
    if (!pending || !c) return;
    let alive = true;
    const read = async () => {
      const res = await apiFetch<{ online: boolean; metrics: Array<{ name: string; value: unknown }>; devices: Array<{ device: string; online: boolean; metrics: Array<{ name: string; value: unknown }> }> }>(
        `/api/telemetry/devices/${encodeURIComponent(c.group)}/${encodeURIComponent(c.node)}${c.device ? `?device=${encodeURIComponent(c.device)}` : ''}`, { silent: true });
      if (!alive || !res.data) return;
      const part = c.device ? res.data.devices.find((d) => d.device === c.device) : null;
      const metrics = part ? part.metrics : res.data.metrics;
      const m = metrics.find((x) => x.name === c.signal);
      setNow({ value: m ? m.value : undefined, online: part ? part.online : res.data.online });
    };
    void read();
    const h = setInterval(read, 5000);
    return () => { alive = false; clearInterval(h); };
  }, [pending, c]);

  if (!c) return null;
  const name = p.asset?.name || `${c.node}${c.device ? `/${c.device}` : ''}`;
  const target = typeof c.value === 'number' ? c.value : Number.isFinite(Number(c.value)) && typeof c.value === 'string' && c.value.trim() !== '' ? Number(c.value) : null;
  return (
    <div className="mt-2 space-y-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3" data-testid="command-approval">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <span className="font-medium text-white">{name}</span>
        <span className="font-mono text-xs text-slate-400">{(p.asset?.key || `${c.group}/${c.node}/${c.device}`).replace(/\/+$/, '')}</span>
        {now && !now.online && <span className="rounded-full border border-rose-500/40 px-2 text-[10px] text-rose-200">offline now, approving will not send it</span>}
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="command-approval-change">
        <span className="font-mono text-xs text-cyan-200">{c.signal}</span>
        <span className="rounded bg-slate-900/70 px-2 py-0.5 text-slate-300" title="When it was asked">{show(p.current?.value)}</span>
        <ArrowRight className="h-4 w-4 text-amber-300" aria-label="to" />
        <span className="rounded bg-amber-500/20 px-2 py-0.5 font-semibold text-amber-100" data-testid="command-approval-value">{show(c.value)}</span>
        {now && pending && (
          <span className="inline-flex items-center gap-1 text-[11px] text-slate-400" data-testid="command-approval-now"><Radio className="h-3 w-3" /> now {show(now.value)}</span>
        )}
      </div>
      {p.reason && (
        <p className="text-xs text-slate-200" data-testid="command-approval-reason">
          <Bot className="mr-1 inline h-3.5 w-3.5 text-cyan-300" aria-hidden />
          <span className="text-slate-400">{p.agent?.name || 'The agent'}&apos;s reason: </span>“{p.reason}”
        </p>
      )}
      {(p.evidence || []).map((ev) => (
        <div key={`${ev.key}-${ev.signal}`} data-testid="command-evidence" data-source={ev.source}>
          <p className="mb-1 text-[11px] font-medium text-slate-300">{ev.title}</p>
          {ev.detail && <p className="mb-1 text-[11px] text-slate-500">{ev.detail}</p>}
          {ev.points.some((x) => x.avg !== null) && <HistoryChart points={ev.points} marks={ev.marks || []} unit={ev.unit} gap={ev.gap} />}
          {ev.caption && <p className="mt-0.5 text-[11px] text-slate-400" data-testid="command-evidence-caption">{ev.caption}</p>}
        </div>
      ))}
      {p.states && p.states.length > 0 ? (
        <div>
          <p className="mb-1 text-[11px] text-slate-500">{c.signal}, last {p.history?.minutes || 15} minutes</p>
          <StateTimeline states={p.states} next={c.value} askedAt={p.requested_at} />
        </div>
      ) : p.history?.points && p.history.points.some((x) => x.avg !== null) ? (
        <div>
          <p className="mb-1 text-[11px] text-slate-500">{c.signal}, last {p.history.minutes || 15} minutes before it asked</p>
          <HistoryChart points={p.history.points} target={target} />
        </div>
      ) : null}
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-500">
        {p.why && <span>{p.why}</span>}
        {p.preview?.topic && <span>Goes out on <span className="font-mono text-slate-400">{p.preview.topic}</span></span>}
        {p.sent_at && <span className="text-emerald-300">Sent {new Date(p.sent_at).toLocaleTimeString()}</span>}
        <Link href={`/telemetry?group=${encodeURIComponent(c.group)}&node=${encodeURIComponent(c.node)}`} className="text-cyan-300 hover:underline">See it live on Telemetry</Link>
        {executionId && <Link href={`/executions/${encodeURIComponent(executionId)}`} className="text-cyan-300 hover:underline">What the agent read</Link>}
      </div>
      {pending && <p className="text-[11px] text-slate-400">Approving sends it at once. Denying stops it, and the agent is told your reason.</p>}
    </div>
  );
}
