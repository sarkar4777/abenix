'use client';

import dynamic from 'next/dynamic';
import { Plus, X } from 'lucide-react';
import { MAX_SIGNALS, SERIES_COLORS } from '@/lib/telemetry/charts';
import { formatValue, isNumeric, splitMetric } from '@/lib/telemetry/format';
import type { HistoryPoint, Metric } from '@/lib/telemetry/types';
import { RANGES, type RangeId } from './HistoryChart';

const HistoryChart = dynamic(() => import('./HistoryChart'), {
  ssr: false,
  loading: () => <div className="h-[150px] animate-pulse rounded-lg bg-slate-900/40" />,
});

// one small chart per signal on a shared time axis, never two scales on one chart
export default function SignalCharts({
  group, node, device, signals, setSignals, metrics, samples, rangeId, setRange, loading, tall, onFocus, focused,
}: {
  group: string; node: string; device: string; signals: string[]; setSignals: (s: string[]) => void;
  metrics: Record<string, Metric> | undefined; samples: Record<string, HistoryPoint[]> | undefined;
  rangeId: RangeId; setRange: (r: RangeId) => void; loading: boolean;
  tall?: boolean; onFocus?: () => void; focused?: boolean;
}) {
  const shown = signals.filter((s) => metrics?.[s] !== undefined);
  const addable = Object.values(metrics || {})
    .filter((m) => (isNumeric(m.value) || typeof m.value === 'boolean') && !shown.includes(m.name))
    .sort((a, b) => a.name.localeCompare(b.name));
  const height = tall
    ? shown.length <= 1 ? 440 : shown.length === 2 ? 220 : shown.length === 3 ? 140 : 100
    : shown.length <= 1 ? 240 : shown.length === 2 ? 170 : 132;
  const syncId = `tel-${group}-${node}-${device}`;

  return (
    <section className="min-w-0 rounded-xl border border-slate-700/60 bg-slate-900/40 p-3" aria-label="History" data-testid="tel-charts" data-signals={shown.join(',')}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="flex-1 text-sm font-medium text-white" data-testid="tel-chart-title">
          {shown.length > 1 ? `${shown.length} signals` : shown[0] ? (() => { const s = splitMetric(shown[0]); return `${s.label}${s.unit ? ` (${s.unit})` : ''}`; })() : 'History'}
        </h3>
        {onFocus && (
          <button type="button" onClick={onFocus} className="rounded-md border border-slate-700 px-2 py-1 text-[11px] text-slate-300 hover:bg-slate-800" data-testid="tel-chart-focus">
            {focused ? 'Show the values too' : 'Charts only'}
          </button>
        )}
        <div className="flex flex-wrap gap-1" role="group" aria-label="Time range">
          {RANGES.map((r) => (
            <button key={r.id} type="button" onClick={() => setRange(r.id)} aria-pressed={rangeId === r.id} className={`rounded-md px-2 py-1 text-[11px] ${rangeId === r.id ? 'bg-slate-700 text-white' : 'text-slate-400 hover:bg-slate-800 hover:text-white'}`} data-testid={`tel-range-${r.id}`}>
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {shown.length === 0 ? (
        <div className="flex h-[240px] items-center justify-center p-4 text-center text-sm text-slate-400" data-testid="tel-chart-none">
          {loading ? 'Loading' : addable.length ? 'Pick a signal below or in the table to chart it.' : 'This has no numeric values to chart yet.'}
        </div>
      ) : (
        <div className="space-y-2">
          {shown.map((name, i) => {
            const m = metrics?.[name];
            const info = splitMetric(name);
            const color = SERIES_COLORS[i % SERIES_COLORS.length];
            return (
              <div key={name} data-testid="tel-chart-panel" data-metric={name}>
                <div className="flex min-w-0 items-center gap-2 text-xs">
                  <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: color }} aria-hidden />
                  <span className="min-w-0 truncate text-slate-200" title={name}>{info.group ? `${info.group} · ` : ''}{info.label}</span>
                  <span className="ml-auto shrink-0 font-semibold tabular-nums text-white">{m ? formatValue(m.value) : ''}{info.unit && m && isNumeric(m.value) ? <span className="ml-0.5 font-normal text-slate-400">{info.unit}</span> : null}</span>
                  {shown.length > 1 && (
                    <button type="button" onClick={() => setSignals(shown.filter((s) => s !== name))} aria-label={`Take ${info.label} off the chart`} className="shrink-0 rounded p-0.5 text-slate-500 hover:text-white" data-testid="tel-chart-remove">
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
                <HistoryChart
                  group={group}
                  node={node}
                  device={device}
                  metric={name}
                  label={info.label}
                  unit={info.unit}
                  rangeId={rangeId}
                  live={samples?.[name]}
                  boolean={typeof m?.value === 'boolean'}
                  height={height}
                  color={color}
                  syncId={syncId}
                  compact={i < shown.length - 1}
                />
              </div>
            );
          })}
        </div>
      )}

      {addable.length > 0 && shown.length < MAX_SIGNALS && (
        <label className="mt-2 flex items-center gap-2 text-xs text-slate-400">
          <Plus className="h-3.5 w-3.5" />
          <span className="sr-only">Add a signal to the chart</span>
          <select value="" onChange={(e) => e.target.value && setSignals([...shown, e.target.value])} className="min-w-0 flex-1 rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-200" data-testid="tel-chart-add">
            <option value="">Add a signal to the chart</option>
            {addable.map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
          </select>
        </label>
      )}
    </section>
  );
}
