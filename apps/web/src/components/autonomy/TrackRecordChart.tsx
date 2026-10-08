'use client';

import { fmtNum, type ChartPoint } from '@/lib/autonomy';

const W = 640;
const H = 220;
const PAD = { l: 40, r: 12, t: 12, b: 22 };

// Each action as its predicted band with the actual as a dot. Breaks in revision or world model are dashed lines.
export default function TrackRecordChart({ points, metric }: { points: ChartPoint[] | undefined; metric?: string | null }) {
  const pts = (points || []).filter((p) => [p.low, p.high, p.value, p.actual].some((v) => typeof v === 'number'));
  if (pts.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-700 p-6 text-center text-sm text-slate-400" data-testid="autonomy-chart-empty">
        No predictions with results yet. Each action shows here once its result comes in.
      </div>
    );
  }
  const nums: number[] = [];
  for (const p of pts) for (const v of [p.low, p.high, p.value, p.actual]) if (typeof v === 'number' && Number.isFinite(v)) nums.push(v);
  let lo = Math.min(...nums);
  let hi = Math.max(...nums);
  if (lo === hi) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.08;
  lo -= pad; hi += pad;
  const iw = W - PAD.l - PAD.r;
  const ih = H - PAD.t - PAD.b;
  const step = iw / pts.length;
  const x = (i: number) => PAD.l + i * step + step / 2;
  const y = (v: number) => PAD.t + ih - ((v - lo) / (hi - lo)) * ih;
  const bw = Math.max(2, Math.min(14, step * 0.6));
  const ticks = [lo, (lo + hi) / 2, hi];
  const inside = pts.filter((p) => p.within_band === true).length;
  const outside = pts.filter((p) => p.within_band === false).length;

  return (
    <figure data-testid="autonomy-chart">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={`Track record: ${inside} inside the band, ${outside} outside, of ${pts.length} actions`}>
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke="#1e293b" strokeWidth={1} />
            <text x={PAD.l - 6} y={y(t) + 3} textAnchor="end" fontSize={10} fill="#64748b">{fmtNum(Math.round(t * 100) / 100)}</text>
          </g>
        ))}
        {pts.map((p, i) => (
          <g key={p.id}>
            {(p.revision_marker || p.world_model_marker) && (
              <line
                x1={x(i) - step / 2} x2={x(i) - step / 2} y1={PAD.t} y2={H - PAD.b}
                stroke={p.revision_marker ? '#a78bfa' : '#fbbf24'} strokeDasharray="3 3" strokeWidth={1}
                data-testid={p.revision_marker ? 'autonomy-chart-revision' : 'autonomy-chart-wm'}
              >
                <title>{p.revision_marker ? 'The agent changed here' : 'The prediction method changed here'}</title>
              </line>
            )}
            {typeof p.low === 'number' && typeof p.high === 'number' && (
              <rect x={x(i) - bw / 2} y={y(p.high)} width={bw} height={Math.max(1, y(p.low) - y(p.high))} rx={2} fill="#22d3ee" fillOpacity={0.18} stroke="#22d3ee" strokeOpacity={0.4}>
                <title>{`Predicted ${fmtNum(p.low)} to ${fmtNum(p.high)}`}</title>
              </rect>
            )}
            {typeof p.value === 'number' && (
              <line x1={x(i) - bw / 2} x2={x(i) + bw / 2} y1={y(p.value)} y2={y(p.value)} stroke="#22d3ee" strokeWidth={1.5} />
            )}
            {typeof p.actual === 'number' && (
              <circle
                cx={x(i)} cy={y(p.actual)} r={3.5}
                fill={p.within_band === true ? '#34d399' : p.within_band === false ? '#fb7185' : '#94a3b8'}
                stroke="#0f172a" strokeWidth={1}
                data-testid="autonomy-chart-dot"
              >
                <title>{`Actual ${fmtNum(p.actual)}${p.within_band === true ? ', inside the band' : p.within_band === false ? ', outside the band' : ''}${p.created_at ? `, ${new Date(p.created_at).toLocaleString()}` : ''}`}</title>
              </circle>
            )}
          </g>
        ))}
      </svg>
      <figcaption className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-400">
        <span className="inline-flex items-center gap-1"><span className="inline-block h-3 w-2 rounded-sm border border-cyan-400/50 bg-cyan-400/20" /> Predicted{metric ? ` ${metric.replace(/_/g, ' ')}` : ''}</span>
        <span className="inline-flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-emerald-400" /> Inside ({inside})</span>
        <span className="inline-flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-rose-400" /> Outside ({outside})</span>
        <span className="inline-flex items-center gap-1"><span className="inline-block h-3 border-l border-dashed border-violet-400" /> Agent changed</span>
        <span className="inline-flex items-center gap-1"><span className="inline-block h-3 border-l border-dashed border-amber-400" /> Prediction method changed</span>
      </figcaption>
    </figure>
  );
}
