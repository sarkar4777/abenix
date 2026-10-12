'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { History, Loader2, RefreshCw } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { boundsOf, clockTime, fmt, previewBody, previewReady, type Condition, type Preview, type PreviewAsset, type RuleDraft } from './lib';
import { pluralShown } from '@/lib/plural';

const HOURS = [1, 6, 24] as const;

function num(v: unknown): number | null {
  const n = typeof v === 'number' ? v : Number(v);
  return v === '' || v === null || v === undefined || !Number.isFinite(n) ? null : n;
}

function SignalChart({ a, cond, from, to }: { a: PreviewAsset; cond: Condition; from: number; to: number }) {
  const sig = cond.signal || '';
  const series = a.series.find((s) => s.signal === sig) ?? a.series[0];
  const data = useMemo(() => (series?.points || []).map(([t, v]) => ({ t, v })), [series]);
  if (!data.length) {
    return <Timeline a={a} from={from} to={to} label={cond.kind === 'stale' ? 'data' : 'readings'} />;
  }
  const lines: number[] = [];
  if (cond.kind === 'threshold' && num(cond.value) !== null) lines.push(num(cond.value)!);
  if (cond.kind === 'count' && cond.when && !('equals' in cond.when) && num(cond.when.value) !== null) lines.push(num(cond.when.value)!);
  const lo = cond.kind === 'range' ? num(cond.min) : null;
  const hi = cond.kind === 'range' ? num(cond.max) : null;
  const vals = data.map((d) => d.v).concat(lines, lo ?? [], hi ?? []);
  const dmin = Math.min(...vals), dmax = Math.max(...vals);
  const pad = (dmax - dmin) * 0.08 || 1;
  return (
    <div className="h-40 w-full" data-testid="preview-chart">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
          <XAxis dataKey="t" type="number" domain={[from, to]} tickFormatter={(t) => clockTime(t).slice(0, 5)} stroke="#64748b" fontSize={11} />
          <YAxis domain={[dmin - pad, dmax + pad]} stroke="#64748b" fontSize={11} width={48} tickFormatter={(v) => fmt(Math.round(v * 100) / 100)} />
          <Tooltip
            contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 12 }}
            labelFormatter={(t) => clockTime(Number(t))}
            formatter={(v) => [fmt(v as number), series?.signal || sig]}
          />
          {lo !== null && hi !== null && <ReferenceArea y1={lo} y2={hi} fill="#10b981" fillOpacity={0.06} />}
          {lines.map((l) => <ReferenceLine key={l} y={l} stroke="#f59e0b" strokeDasharray="4 3" />)}
          {lo !== null && <ReferenceLine y={lo} stroke="#f59e0b" strokeDasharray="4 3" />}
          {hi !== null && <ReferenceLine y={hi} stroke="#f59e0b" strokeDasharray="4 3" />}
          {a.firings.map((f) => <ReferenceLine key={`f${f.t}`} x={f.t} stroke="#f43f5e" strokeWidth={2} />)}
          {a.clears.map((t) => <ReferenceLine key={`c${t}`} x={t} stroke="#10b981" strokeDasharray="2 3" />)}
          <Line type="monotone" dataKey="v" stroke="#22d3ee" dot={false} strokeWidth={1.5} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function Timeline({ a, from, to, label }: { a: PreviewAsset; from: number; to: number; label: string }) {
  const W = 600;
  const x = (t: number) => ((t - from) / Math.max(1, to - from)) * W;
  const ticks = (a.series[0]?.points || []).map(([t]) => t);
  return (
    <svg viewBox={`0 0 ${W} 48`} className="h-12 w-full" role="img" aria-label={`${label} over time with firings marked`} data-testid="preview-timeline">
      <line x1={0} x2={W} y1={24} y2={24} stroke="#334155" />
      {ticks.map((t, i) => <line key={i} x1={x(t)} x2={x(t)} y1={18} y2={30} stroke="#22d3ee" strokeOpacity={0.5} />)}
      {a.firings.map((f) => <line key={`f${f.t}`} x1={x(f.t)} x2={x(f.t)} y1={4} y2={44} stroke="#f43f5e" strokeWidth={2} />)}
      {a.clears.map((t) => <line key={`c${t}`} x1={x(t)} x2={x(t)} y1={8} y2={40} stroke="#10b981" strokeDasharray="2 3" />)}
    </svg>
  );
}

function TrackMap({ a, cond }: { a: PreviewAsset; cond: Condition }) {
  const W = 600, H = 300;
  const gnss = cond.frame === 'gnss';
  const poly = cond.polygon || [];
  const pts = a.track.map(([x, y]) => [x, y]);
  const k = gnss ? Math.cos(((poly[0]?.[1] ?? pts[0]?.[1] ?? 0) * Math.PI) / 180) || 1 : 1;
  const b = boundsOf([...pts, ...poly].map(([x, y]) => [x * k, y]), 0.1);
  if (!b) return null;
  const sx = (x: number) => ((x * k - b.minX) / (b.maxX - b.minX)) * W;
  const sy = (y: number) => H - ((y - b.minY) / (b.maxY - b.minY)) * H;
  const fired = a.firings.map((f) => a.track.find(([, , t]) => t >= f.t) ?? a.track[a.track.length - 1]).filter(Boolean) as number[][];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full rounded-md bg-slate-950" role="img" aria-label="The last hour's track against the zone, firings in red" data-testid="preview-map">
      {poly.length >= 3 && <polygon points={poly.map(([x, y]) => `${sx(x)},${sy(y)}`).join(' ')} fill="rgba(34,211,238,0.12)" stroke="#22d3ee" strokeWidth={2} />}
      {pts.length > 1 && <polyline points={pts.map(([x, y]) => `${sx(x)},${sy(y)}`).join(' ')} fill="none" stroke="#94a3b8" strokeWidth={1.5} />}
      {fired.map(([x, y], i) => <circle key={i} cx={sx(x)} cy={sy(y)} r={6} fill="#f43f5e" stroke="#0f172a" strokeWidth={2} />)}
    </svg>
  );
}

export default function PreviewPanel({ draft }: { draft: RuleDraft }) {
  const [hours, setHours] = useState<(typeof HOURS)[number]>(1);
  const [res, setRes] = useState<Preview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [nonce, setNonce] = useState(0);
  const ready = previewReady(draft);
  const body = useMemo(() => (ready ? JSON.stringify(previewBody(draft, hours)) : ''), [draft, hours, ready]);
  const seq = useRef(0);

  useEffect(() => {
    if (!body) { setRes(null); setErr(null); return; }
    const my = ++seq.current;
    const t = setTimeout(async () => {
      setBusy(true);
      const r = await apiFetch<Preview>('/api/telemetry/rules/preview', { method: 'POST', body, silent: true, throwOnError: false });
      if (my !== seq.current) return;
      setBusy(false);
      if (r.error || !r.data) {
        setErr(r.error || 'The preview did not come back. Try again.');
        setRes(null);
      } else {
        setErr(null);
        setRes(r.data);
      }
    }, 600);
    return () => clearTimeout(t);
  }, [body, nonce]);

  const from = res ? Date.parse(res.from) : 0;
  const to = res ? Date.parse(res.to) : 0;
  const shown = (res?.assets || []).slice(0, 6);

  return (
    <section className="min-w-0 rounded-xl border border-slate-700/60 bg-slate-900/40 p-4 [overflow-wrap:anywhere]" data-testid="rule-preview" aria-live="polite">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <History className="h-4 w-4 text-cyan-300" aria-hidden />
        <h2 className="text-sm font-semibold text-white">What it would have done</h2>
        <div className="ml-auto flex items-center gap-1" role="group" aria-label="How far back">
          {HOURS.map((h) => (
            <button key={h} type="button" onClick={() => setHours(h)} aria-pressed={hours === h}
              className={`min-h-[32px] rounded-md px-2.5 text-xs ${hours === h ? 'bg-cyan-500/20 text-cyan-200' : 'text-slate-400 hover:bg-slate-800'}`}
              data-testid={`preview-hours-${h}`}>
              {h === 1 ? 'Last hour' : `${h} h`}
            </button>
          ))}
          <button type="button" onClick={() => setNonce((n) => n + 1)} disabled={!ready || busy} aria-label="Run the preview again" className="rounded-md p-1.5 text-slate-400 hover:bg-slate-800 disabled:opacity-40">
            <RefreshCw className={`h-3.5 w-3.5 ${busy ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>
      {!ready ? (
        <p className="text-sm text-slate-400" data-testid="preview-waiting">Pick what to watch and fill in the condition. The rule is then replayed over the stored history, so you see how often it would have fired before you save it.</p>
      ) : err ? (
        <p className="text-sm text-amber-200" role="alert" data-testid="preview-error">{err}</p>
      ) : !res ? (
        <p className="flex items-center gap-2 text-sm text-slate-400"><Loader2 className="h-4 w-4 animate-spin" /> Replaying the history</p>
      ) : (
        <div className="space-y-3">
          <p className={`text-sm font-medium ${res.fired ? 'text-amber-100' : 'text-slate-200'}`} data-testid="preview-summary" data-fired={res.fired}>{res.summary}</p>
          {res.truncated && <p className="text-xs text-slate-500">Only the first assets are shown. The rule watches {pluralShown(res.targets, (res.targets).toLocaleString('en-US'), 'asset')}.</p>}
          {shown.map((a) => (
            <div key={a.key} className="rounded-lg border border-slate-700/50 bg-slate-950/40 p-2" data-testid="preview-asset" data-key={a.key}>
              <div className="mb-1 flex flex-wrap items-baseline gap-x-2 text-xs">
                <span className="font-medium text-slate-100">{a.name}</span>
                <span className="text-slate-500">{pluralShown(a.samples, a.samples.toLocaleString('en-US'), 'reading')}</span>
                <span className={a.firings.length ? 'text-rose-300' : 'text-slate-500'}>{a.firings.length ? `fired ${a.firings.length}` : 'no firing'}</span>
              </div>
              {draft.condition.kind === 'geofence'
                ? <TrackMap a={a} cond={draft.condition} />
                : <SignalChart a={a} cond={draft.condition} from={from} to={to} />}
              {a.firings.length > 0 && (
                <ul className="mt-1 space-y-0.5 text-xs text-slate-400" data-testid="preview-firings">
                  {a.firings.slice(0, 5).map((f) => <li key={f.t}><span className="tabular-nums text-slate-300">{clockTime(f.t)}</span> {f.words}</li>)}
                  {a.firings.length > 5 && <li>and {a.firings.length - 5} more</li>}
                </ul>
              )}
            </div>
          ))}
          <p className="text-[11px] text-slate-500">Red lines are firings, green dashes are where it cleared. History keeps about one reading a second, so very short spikes may be missing here but are still caught live.</p>
        </div>
      )}
    </section>
  );
}
