'use client';

// One tick per scored action: held (up, green), missed (down, red), unknown (grey dot).
export default function Sparkline({ values, width = 80, height = 18 }: { values: Array<number | null> | undefined; width?: number; height?: number }) {
  const vals = (values || []).slice(-20);
  if (vals.length === 0) {
    return <span className="text-[10px] text-slate-500" data-testid="autonomy-spark-empty">No results yet</span>;
  }
  const step = width / Math.max(vals.length, 1);
  const mid = height / 2;
  const held = vals.filter((v) => v === 1).length;
  const scored = vals.filter((v) => v === 0 || v === 1).length;
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={scored ? `${held} of the last ${scored} results held` : 'No scored results yet'}
      data-testid="autonomy-spark"
    >
      <line x1={0} x2={width} y1={mid} y2={mid} stroke="#334155" strokeWidth={1} />
      {vals.map((v, i) => {
        const x = i * step + step / 2;
        if (v === 1) return <rect key={i} x={x - 1.5} y={2} width={3} height={mid - 2} rx={1} fill="#34d399" />;
        if (v === 0) return <rect key={i} x={x - 1.5} y={mid} width={3} height={mid - 2} rx={1} fill="#fb7185" />;
        return <circle key={i} cx={x} cy={mid} r={1.5} fill="#64748b" />;
      })}
    </svg>
  );
}
