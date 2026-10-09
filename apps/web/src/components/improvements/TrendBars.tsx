'use client';

import { severityMeta, trendText } from '@/lib/improvements';

// Fourteen daily bars, oldest on the left. The label says it in words.
export function TrendBars({ values, width = 84, height = 20 }: { values: number[] | undefined; width?: number; height?: number }) {
  const vals = values || [];
  const max = Math.max(1, ...vals);
  const step = width / Math.max(vals.length, 1);
  const label = trendText(vals);
  return (
    <span className="inline-flex items-center gap-2" data-testid="improvement-trend">
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
        <line x1={0} x2={width} y1={height - 0.5} y2={height - 0.5} stroke="#334155" strokeWidth={1} />
        {vals.map((v, i) => {
          if (!v) return null;
          const h = Math.max(2, (v / max) * (height - 2));
          return <rect key={i} x={i * step + 1} y={height - h} width={Math.max(1, step - 2)} height={h} rx={1} fill={i >= vals.length - 7 ? '#fb7185' : '#64748b'} />;
        })}
      </svg>
      <span className="text-[11px] text-slate-400">{label}</span>
    </span>
  );
}

export function SeverityPill({ severity }: { severity: string }) {
  const m = severityMeta(severity);
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${m.text} ${m.bg} ${m.border}`} data-testid="improvement-severity" data-severity={severity}>
      {m.label}
    </span>
  );
}
