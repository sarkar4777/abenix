'use client';

import { sparkPoints, type HistoryPoint } from '@/lib/cluster';

export default function ReplicaSparkline({ history, width = 96, height = 24 }: { history: HistoryPoint[]; width?: number; height?: number }) {
  const { ready, desired, max } = sparkPoints(history, width, height);
  if (!ready) {
    return (
      <span className="text-[10px] text-slate-500 whitespace-nowrap" data-testid="service-spark-empty" title="The chart fills in as the page refreshes">
        Collecting history
      </span>
    );
  }
  const first = history[0];
  const last = history[history.length - 1];
  const mins = Math.max(1, Math.round((last.t - first.t) / 60));
  const changed = history.some((h) => h.ready !== last.ready || h.desired !== last.desired);
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`Ready replicas over the last ${mins} minutes, now ${last.ready} of ${last.desired}${changed ? ', it changed in that time' : ', steady'}`}
      data-testid="service-spark"
      className="shrink-0"
    >
      <title>{`Ready pods over the last ${mins} min (dashed line is desired, peak ${max})`}</title>
      <polyline points={desired} fill="none" stroke="#475569" strokeWidth={1} strokeDasharray="3 2" />
      <polyline points={ready} fill="none" stroke="#22d3ee" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
