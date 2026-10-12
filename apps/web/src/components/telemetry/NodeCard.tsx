'use client';

import { memo, useEffect } from 'react';
import Link from 'next/link';
import { ChevronRight } from 'lucide-react';
import { useTelemetry, nodeGaps, nodeLastSeen, nodeRate, nodeStatus, type NodeEntry } from '@/lib/telemetry/store';
import { ago, clock, deviceKey, friendlyName, liveRate, toMs } from '@/lib/telemetry/format';
import type { HistoryPoint } from '@/lib/telemetry/types';
import { Sparkline, StatusDot, StatusPill } from './bits';

export const CARD_HEIGHT = 196;

// a minute of ingest rate per node, kept outside React so cards stay cheap
const rateHistory = new Map<string, HistoryPoint[]>();

export function recordRate(key: string, v: number, now: number) {
  const arr = rateHistory.get(key) ?? [];
  const last = arr[arr.length - 1];
  if (last && now - last.t < 500) last.v = v;
  else arr.push({ t: now, v });
  while (arr.length && arr[0].t < now - 65_000) arr.shift();
  rateHistory.set(key, arr);
}

export function nodeHref(n: { group: string; node: string }, device?: string) {
  const p = new URLSearchParams({ group: n.group, node: n.node });
  if (device !== undefined) p.set('device', device);
  return `/telemetry?${p.toString()}`;
}

const MAX_CHIPS = 6;

function NodeCardInner({ entry, now }: { entry: NodeEntry; now: number }) {
  const status = nodeStatus(entry);
  const healthRate = useTelemetry((s) => s.nodeRates[entry.key]);
  const r = healthRate ?? nodeRate(entry);
  const gaps = nodeGaps(entry);
  const seen = nodeLastSeen(entry);
  const nodeMetrics = useTelemetry((s) => s.metrics[deviceKey(entry.group, entry.node, '')]);
  const asset = useTelemetry((s) => s.assets[entry.key]);
  const name = asset?.display_name || friendlyName(nodeMetrics ? Object.values(nodeMetrics) : undefined);
  const unregistered = asset ? asset.registered === false : false;
  const devices = Object.values(entry.devices).sort((a, b) => a.device.localeCompare(b.device));
  const offlineAt = toMs(entry.self?.offline_at) ?? (status === 'offline' ? seen : null);

  useEffect(() => {
    recordRate(entry.key, status === 'offline' ? 0 : r, Date.now());
  }, [entry.key, r, status]);

  return (
    <article
      className={`flex h-full min-w-0 flex-col rounded-xl border bg-slate-900/50 p-3 transition-colors ${status === 'offline' ? 'border-rose-500/40' : status === 'partial' ? 'border-amber-500/30' : 'border-slate-700/60 hover:border-cyan-500/40'}`}
      data-testid="tel-node-card"
      data-node={entry.node}
      data-status={status}
    >
      <div className="flex min-w-0 items-start gap-2">
        <div className="min-w-0 flex-1">
          <Link href={nodeHref(entry)} className="block truncate font-mono text-sm font-semibold text-white hover:text-cyan-300" data-testid="tel-node-open">
            {entry.node}
          </Link>
          <p className="truncate text-xs text-slate-400">
            {name ? `${name} · ` : ''}{asset?.type ? `${asset.type} · ` : ''}{entry.group}
            {unregistered && (
              <Link href={`/telemetry/assets?edit=${encodeURIComponent(`${entry.group}/${entry.node}/`)}`} className="ml-1 text-cyan-300 hover:underline" data-testid="tel-name-asset">Name this asset</Link>
            )}
          </p>
        </div>
        <StatusPill status={status} testId="tel-node-status" />
      </div>

      <div className="mt-2 flex min-w-0 items-center gap-3">
        <div className="min-w-0" title="Messages a second from this asset">
          <p className="text-[10px] uppercase tracking-wide text-slate-500">Ingest</p>
          <p className="flex items-center gap-1.5 text-sm font-semibold tabular-nums text-white" data-testid="tel-node-rate">
            <StatusDot status={status === 'offline' ? 'offline' : 'online'} pulse={status !== 'offline' && r > 0} />
            {(() => {
              const readings = (entry.self?.readings_per_sec ?? 0) || Object.values(entry.devices).reduce((a, d) => a + (Number(d.readings_per_sec) || 0), 0);
              const lr = liveRate(r, readings, status !== 'offline');
              return (
                <>
                  <span className="inline-block min-w-[3.5ch] text-right">{lr.value}</span>
                  <span className="text-[11px] font-normal text-slate-400">{lr.unit}</span>
                </>
              );
            })()}
          </p>
        </div>
        <Sparkline points={rateHistory.get(entry.key)} now={now} width={84} height={26} label={`Ingest rate over the last minute for ${entry.node}`} />
        <div className="ml-auto min-w-0 text-right">
          <p className="text-[10px] uppercase tracking-wide text-slate-500" title="Messages missing in sequence">Gaps</p>
          <p className={`text-sm font-semibold tabular-nums ${gaps > 0 ? 'text-amber-200' : 'text-white'}`} data-testid="tel-node-gaps">{gaps}</p>
        </div>
      </div>

      <p className={`mt-1.5 truncate text-xs ${status === 'offline' ? 'text-rose-200' : 'text-slate-400'}`} data-testid="tel-node-seen">
        {status === 'offline'
          ? offlineAt ? `Offline since ${clock(offlineAt)}, ${ago(offlineAt, now)}` : 'Offline'
          : `Last message ${ago(seen, now)}`}
      </p>

      <div className="mt-auto flex min-w-0 flex-wrap gap-1 overflow-hidden pt-2" style={{ maxHeight: 56 }}>
        {devices.length === 0 && <span className="text-xs text-slate-500">No parts reported yet</span>}
        {devices.slice(0, MAX_CHIPS).map((d) => (
          <Link
            key={d.device}
            href={nodeHref(entry, d.device)}
            className={`inline-flex max-w-[9rem] items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] ${d.online ? 'border-slate-700 text-slate-200 hover:border-cyan-500/50' : 'border-rose-500/40 text-rose-200'}`}
            data-testid="tel-device-chip"
            data-device={d.device}
            title={d.online ? `${d.device}, online` : `${d.device}, offline`}
          >
            <StatusDot status={d.online ? 'online' : 'offline'} />
            <span className="truncate">{d.device}</span>
          </Link>
        ))}
        {devices.length > MAX_CHIPS && (
          <Link href={nodeHref(entry)} className="inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[11px] text-cyan-300 hover:underline">
            {devices.length - MAX_CHIPS} more <ChevronRight className="h-3 w-3" />
          </Link>
        )}
      </div>
    </article>
  );
}

export default memo(NodeCardInner);
