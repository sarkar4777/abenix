'use client';

import { useMemo, useState } from 'react';

import { pct, type EvalRun } from '@/lib/evals';

const W = 640;
const H = 180;
const PAD = { l: 36, r: 12, t: 12, b: 24 };

// score per baseline run over time, with the pass threshold as a dashed rule
export default function RunsChart({ runs, threshold }: { runs: EvalRun[]; threshold: number }) {
  const pts = useMemo(
    () => runs.filter((r) => r.status === 'completed' && r.score != null && !r.model_override).slice().reverse(),
    [runs],
  );
  const [hover, setHover] = useState<number | null>(null);
  if (pts.length === 0) {
    return <p className="text-sm text-slate-500 py-6 text-center">Scores appear here after the first run.</p>;
  }
  const iw = W - PAD.l - PAD.r;
  const ih = H - PAD.t - PAD.b;
  const x = (i: number) => PAD.l + (pts.length === 1 ? iw / 2 : (i / (pts.length - 1)) * iw);
  const y = (v: number) => PAD.t + (1 - v) * ih;
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.score!).toFixed(1)}`).join(' ');
  const h = hover != null ? pts[hover] : null;
  return (
    <div className="relative" data-testid="runs-chart">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label={`Score over the last ${pts.length} runs`} onMouseLeave={() => setHover(null)}>
        {[0, 0.5, 1].map((g) => (
          <g key={g}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(g)} y2={y(g)} stroke="currentColor" className="text-slate-800" strokeWidth={1} />
            <text x={PAD.l - 6} y={y(g) + 3} textAnchor="end" className="fill-slate-500" fontSize={10}>{g * 100}%</text>
          </g>
        ))}
        <line x1={PAD.l} x2={W - PAD.r} y1={y(threshold)} y2={y(threshold)} stroke="currentColor" className="text-slate-400" strokeDasharray="4 4" strokeWidth={1} />
        <text x={W - PAD.r} y={y(threshold) - 4} textAnchor="end" className="fill-slate-400" fontSize={10}>threshold {pct(threshold)}</text>
        <path d={line} fill="none" stroke="#22d3ee" strokeWidth={2} strokeLinejoin="round" />
        {pts.map((p, i) => (
          <g key={p.id}>
            <circle cx={x(i)} cy={y(p.score!)} r={hover === i ? 6 : 4} fill={p.threshold_met ? '#22d3ee' : '#0f172a'} stroke="#22d3ee" strokeWidth={2} />
            <rect x={x(i) - iw / Math.max(pts.length, 1) / 2} y={PAD.t} width={Math.max(iw / Math.max(pts.length, 1), 8)} height={ih} fill="transparent" onMouseEnter={() => setHover(i)} />
          </g>
        ))}
        {h && <line x1={x(hover!)} x2={x(hover!)} y1={PAD.t} y2={PAD.t + ih} stroke="currentColor" className="text-slate-600" strokeWidth={1} />}
      </svg>
      {h && (
        <div
          className="pointer-events-none absolute top-0 rounded-lg border border-slate-700 bg-slate-900/95 px-3 py-2 text-xs shadow-xl"
          style={{ left: `${Math.min(Math.max((x(hover!) / W) * 100, 10), 75)}%` }}
        >
          <div className="text-white font-medium">{pct(h.score)} {h.threshold_met ? 'passed' : 'below threshold'}</div>
          <div className="text-slate-400">{h.passed} passed, {h.failed} failed</div>
          <div className="text-slate-500">{h.model} · {h.created_at ? new Date(h.created_at).toLocaleString() : ''}</div>
        </div>
      )}
      <p className="mt-1 text-[11px] text-slate-500">
        Filled points met the threshold, hollow ones did not. Model comparison runs are left out. Open a run from the list below.
      </p>
      <span className="sr-only">{pts.map((p) => `${p.created_at}: ${pct(p.score)}`).join(', ')}</span>
    </div>
  );
}

export function Sparkline({ values }: { values: (number | null)[] }) {
  const v = values.filter((x): x is number => x != null);
  if (v.length < 2) return null;
  const w = 80;
  const h = 24;
  const d = v.map((s, i) => `${i ? 'L' : 'M'}${((i / (v.length - 1)) * (w - 4) + 2).toFixed(1)},${(2 + (1 - s) * (h - 4)).toFixed(1)}`).join(' ');
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-label={`Trend over ${v.length} runs`} role="img">
      <path d={d} fill="none" stroke="#22d3ee" strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  );
}
