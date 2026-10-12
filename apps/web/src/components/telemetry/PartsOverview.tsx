'use client';

import dynamic from 'next/dynamic';
import Link from 'next/link';
import { ChevronRight } from 'lucide-react';
import { SERIES_COLORS, defaultSignals } from '@/lib/telemetry/charts';
import { ago, deviceKey, formatValue, isNumeric, liveRate, splitMetric, toMs } from '@/lib/telemetry/format';
import { useTelemetry, type NodeEntry } from '@/lib/telemetry/store';
import type { HistoryPoint, Metric } from '@/lib/telemetry/types';
import { Sparkline, StatusDot } from './bits';
import { RANGES, type RangeId } from './HistoryChart';
import { nodeHref } from './NodeCard';

const HistoryChart = dynamic(() => import('./HistoryChart'), {
  ssr: false,
  loading: () => <div className="h-[120px] animate-pulse rounded-lg bg-slate-900/40" />,
});

export interface PartSummary {
  device: string;
  online: boolean;
  rate: { value: string; unit: string };
  lastSeen: number | null;
  headline: Metric[];
  metricCount: number;
}

// each part with its status, rate and headline values, so a whole asset never looks silent when its parts talk
export function partSummaries(
  entry: NodeEntry | undefined,
  metrics: Record<string, Record<string, Metric>>,
  samples: Record<string, Record<string, HistoryPoint[]>>,
  count = 3,
): PartSummary[] {
  if (!entry) return [];
  return Object.values(entry.devices)
    .sort((a, b) => a.device.localeCompare(b.device))
    .map((d) => {
      const key = deviceKey(entry.group, entry.node, d.device);
      const m = metrics[key] || {};
      const names = defaultSignals(Object.values(m), samples[key], count);
      return {
        device: d.device,
        online: d.online,
        rate: liveRate(d.msgs_per_sec, d.readings_per_sec, d.online),
        lastSeen: toMs(d.last_seen),
        headline: names.map((n) => m[n]).filter(Boolean),
        metricCount: Object.keys(m).length || d.metric_count || 0,
      };
    });
}

export default function PartsOverview({ group, node, entry, now, rangeId, setRange, focus }: {
  group: string; node: string; entry: NodeEntry | undefined; now: number; rangeId: RangeId; setRange: (r: RangeId) => void; focus?: boolean;
}) {
  const metrics = useTelemetry((s) => s.metrics);
  const samples = useTelemetry((s) => s.samples);
  const parts = partSummaries(entry, metrics, samples, 3);
  const charted = parts.filter((p) => p.headline.some((m) => isNumeric(m.value)));
  const perPart = focus ? 2 : 1;
  const height = focus ? 150 : 110;

  if (!parts.length) return null;

  return (
    <div className="space-y-3" data-testid="tel-parts">
      <section className="min-w-0 overflow-hidden rounded-xl border border-slate-700/60 bg-slate-900/40" aria-label="Parts">
        <div className="border-b border-slate-700/60 px-3 py-2">
          <h3 className="text-sm font-medium text-white">Parts <span className="font-normal text-slate-500">({parts.length})</span></h3>
          <p className="text-[11px] text-slate-500">This asset reports through its parts. Open one to see all its values.</p>
        </div>
        <ul className="divide-y divide-slate-800/80">
          {parts.map((p) => {
            const key = deviceKey(group, node, p.device);
            return (
              <li key={p.device} data-testid="tel-part-row" data-device={p.device}>
                <Link href={nodeHref({ group, node }, p.device)} className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 hover:bg-slate-800/40">
                  <span className="flex w-36 min-w-0 items-center gap-1.5">
                    <StatusDot status={p.online ? 'online' : 'offline'} pulse={p.online} />
                    <span className="truncate font-mono text-sm text-slate-100">{p.device}</span>
                  </span>
                  <span className="w-28 text-xs tabular-nums text-slate-300">{p.rate.value} <span className="text-slate-500">{p.rate.unit}</span></span>
                  <span className="w-24 text-xs text-slate-500">{p.online ? ago(p.lastSeen, now) : `offline ${ago(p.lastSeen, now)}`}</span>
                  <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4 gap-y-1">
                    {p.headline.length === 0 && <span className="text-xs text-slate-500">{p.metricCount ? `${p.metricCount} values, none numeric` : 'No values reported yet'}</span>}
                    {p.headline.map((m) => {
                      const info = splitMetric(m.name);
                      return (
                        <span key={m.name} className="inline-flex min-w-0 items-center gap-1.5 text-xs" title={m.name}>
                          <span className="truncate text-slate-400">{info.label}</span>
                          <span className="font-semibold tabular-nums text-white">{formatValue(m.value)}</span>
                          {info.unit && isNumeric(m.value) && <span className="text-slate-500">{info.unit}</span>}
                          {isNumeric(m.value) && <Sparkline points={samples[key]?.[m.name]} now={now} width={56} height={16} label={`${info.label} over the last minute`} />}
                        </span>
                      );
                    })}
                  </span>
                  <ChevronRight className="h-4 w-4 shrink-0 text-slate-600" aria-hidden />
                </Link>
              </li>
            );
          })}
        </ul>
      </section>

      {charted.length > 0 && (
        <section className="min-w-0 rounded-xl border border-slate-700/60 bg-slate-900/40 p-3" aria-label="Parts over time" data-testid="tel-parts-charts">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <h3 className="flex-1 text-sm font-medium text-white">Headline signals by part</h3>
            <div className="flex flex-wrap gap-1" role="group" aria-label="Time range">
              {RANGES.map((r) => (
                <button key={r.id} type="button" onClick={() => setRange(r.id)} aria-pressed={rangeId === r.id} className={`rounded-md px-2 py-1 text-[11px] ${rangeId === r.id ? 'bg-slate-700 text-white' : 'text-slate-400 hover:bg-slate-800 hover:text-white'}`} data-testid={`tel-range-${r.id}`}>
                  {r.label}
                </button>
              ))}
            </div>
          </div>
          <div className={`grid gap-3 ${focus ? 'xl:grid-cols-2' : ''}`}>
            {charted.flatMap((p, pi) => p.headline.filter((m) => isNumeric(m.value)).slice(0, perPart).map((m, mi) => {
              const info = splitMetric(m.name);
              const color = SERIES_COLORS[(pi * perPart + mi) % SERIES_COLORS.length];
              return (
                <div key={`${p.device}:${m.name}`} data-testid="tel-chart-panel" data-metric={m.name} data-device={p.device}>
                  <div className="flex min-w-0 items-center gap-2 text-xs">
                    <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: color }} aria-hidden />
                    <span className="min-w-0 truncate text-slate-200"><span className="font-mono text-slate-400">{p.device}</span> · {info.label}</span>
                    <span className="ml-auto shrink-0 font-semibold tabular-nums text-white">{formatValue(m.value)}{info.unit ? <span className="ml-0.5 font-normal text-slate-400">{info.unit}</span> : null}</span>
                  </div>
                  <HistoryChart group={group} node={node} device={p.device} metric={m.name} label={info.label} unit={info.unit} rangeId={rangeId} live={samples[deviceKey(group, node, p.device)]?.[m.name]} height={height} color={color} syncId={`tel-parts-${group}-${node}`} />
                </div>
              );
            }))}
          </div>
        </section>
      )}
    </div>
  );
}
