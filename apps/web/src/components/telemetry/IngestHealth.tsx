'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Archive, Gauge, Loader2, WifiOff } from 'lucide-react';
import { forgetPreview } from '@/lib/telemetry/forget';
import type { Health } from '@/lib/telemetry/types';
import { formatNumber, rate } from '@/lib/telemetry/format';
import type { FeedStatus } from '@/lib/telemetry/useTelemetryFeed';
import { Stat, StatusDot } from './bits';

export interface Totals { rate: number; gaps: number; online: number; total: number }

export function LiveBadge({ feed }: { feed: FeedStatus }) {
  if (feed.state === 'live') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-300" data-testid="tel-live" data-state="live">
        <StatusDot status="online" pulse /> Live
      </span>
    );
  }
  if (feed.polling) {
    const why = feed.state === 'retrying' && feed.retryInMs ? `Live stream dropped, reconnecting in ${Math.round(feed.retryInMs / 1000)} s.` : 'Live stream not available here.';
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-200" title={`${why} Values refresh every few seconds meanwhile.`} data-testid="tel-live" data-state="polling">
        <WifiOff className="h-3 w-3" /> Refreshing every few seconds
      </span>
    );
  }
  if (feed.state === 'connecting') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-600 px-2 py-0.5 text-[11px] text-slate-300" data-testid="tel-live" data-state="connecting">
        <Loader2 className="h-3 w-3 animate-spin" /> Connecting
      </span>
    );
  }
  return null;
}

// messages a second, ingest delay, seq gaps and machines online, the four numbers that say ingest is healthy
export function IngestHealth({ health, totals, healthMissing }: { health: Health | null; totals: Totals; healthMissing: boolean }) {
  const mps = health?.messages_per_second ?? totals.rate;
  const p99 = health?.ingest_latency_ms_p99 ?? health?.ingest_latency_ms?.p99;
  const p50 = health?.ingest_latency_ms_p50 ?? health?.ingest_latency_ms?.p50;
  const gaps = health?.seq_gaps ?? totals.gaps;
  const online = health?.nodes_online ?? totals.online;
  const total = health?.nodes_total ?? totals.total;
  const dropped = health?.dropped ?? 0;
  return (
    <section className="grid grid-cols-2 gap-2 sm:grid-cols-4" aria-label="Ingest health" data-testid="tel-health">
      <Stat label="Messages a second" value={rate(mps)} hint={dropped > 0 ? `${formatNumber(dropped)} dropped` : 'across all sources'} tone={dropped > 0 ? 'warn' : 'plain'} testId="tel-health-rate" />
      <Stat
        label="Ingest delay (p99)"
        value={p99 === null || p99 === undefined ? <span className="text-sm font-normal text-slate-400">{healthMissing ? 'Not reported' : 'Waiting'}</span> : `${formatNumber(p99)} ms`}
        hint={p99 === null || p99 === undefined ? (healthMissing ? 'This server does not report it yet' : 'Measured once messages flow') : p50 !== null && p50 !== undefined ? `typical ${formatNumber(p50)} ms` : 'bus to live store'}
        tone={p99 !== null && p99 !== undefined && p99 > 50 ? 'warn' : 'plain'}
        testId="tel-health-latency"
      />
      <Stat label="Gaps in sequence" value={formatNumber(gaps)} hint={gaps > 0 ? 'messages missed, resend asked' : 'no messages missed'} tone={gaps > 0 ? 'warn' : 'plain'} testId="tel-health-gaps" />
      <Stat label="Assets online" value={`${online} of ${total}`} hint={total - online > 0 ? `${total - online} offline` : total ? 'all online' : 'none yet'} tone={total - online > 0 ? 'bad' : 'plain'} testId="tel-health-online" />
    </section>
  );
}

// over a quota or slowed down, said plainly with who can change it
export function QuotaBanner({ health, isAdmin, canManage, onForget, refreshKey }: { health: Health | null; isAdmin: boolean; canManage?: boolean; onForget?: () => void; refreshKey?: number }) {
  const q = health?.quota;
  const deviceLimit = !!(q?.max_devices && (q.used?.devices ?? 0) >= q.max_devices) || /device/i.test(health?.throttle_reason ?? '');
  // how many could go right now, so the banner always offers a way out
  const [stale, setStale] = useState<number | null>(null);
  useEffect(() => {
    if (!deviceLimit || !canManage) { setStale(null); return; }
    let stop = false;
    void forgetPreview({ offline_for_s: 3600 }).then((r) => { if (!stop) setStale(r.result ? r.result.matched : null); });
    return () => { stop = true; };
  }, [deviceLimit, canManage, refreshKey]);
  const lines: string[] = [];
  if (health && health.ingest_up === false) {
    lines.push('The ingest service is not running, so no new readings arrive and every asset will look offline. The values on screen are the last ones stored.');
  }
  if (health?.throttled) {
    lines.push(health.throttle_reason?.trim() || 'Ingest is being slowed down because this workspace sends more messages than its limit. Messages over the limit are counted and dropped.');
  }
  // the server's own reason already names the limit, so the quota lines below would repeat it
  const said = !!health?.throttle_reason?.trim();
  if (!said && q?.max_msgs_per_sec && (q.used?.msgs_per_sec ?? 0) > q.max_msgs_per_sec && !health?.throttled) {
    lines.push(`Sources send ${formatNumber(q.used?.msgs_per_sec ?? 0)} messages a second and the limit is ${formatNumber(q.max_msgs_per_sec)}. Messages over the limit are dropped.`);
  }
  if (!said && q?.max_devices && (q.used?.devices ?? 0) >= q.max_devices) {
    lines.push(`This workspace has reached its limit of ${formatNumber(q.max_devices)} devices. New devices are not added until some are removed or the limit is raised.`);
  }
  if (!said && q?.max_connections && (q.used?.connections ?? 0) >= q.max_connections) {
    lines.push(`This workspace has all ${formatNumber(q.max_connections)} broker connections it is allowed. Remove one or ask for a higher limit to add another.`);
  }
  if (!lines.length) return null;
  return (
    <div role="alert" className="flex items-start gap-3 rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-100" data-testid="tel-quota-banner">
      <Gauge className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
      <div className="min-w-0 space-y-1">
        {lines.map((l) => <p key={l}>{l}</p>)}
        {deviceLimit && canManage && onForget && stale !== null && (
          stale > 0 ? (
            <button type="button" onClick={onForget} className="mt-1 inline-flex items-center gap-1.5 rounded-md border border-amber-400/50 px-2.5 py-1 text-xs font-medium text-amber-50 hover:bg-amber-500/20" data-testid="tel-quota-forget">
              <Archive className="h-3.5 w-3.5" /> Forget {stale.toLocaleString()} device{stale === 1 ? '' : 's'} offline for more than 1 hour
            </button>
          ) : (
            <p className="text-amber-200/90" data-testid="tel-quota-forget-none">No device has been offline for more than an hour, so there is nothing to forget yet. Forget devices from the Assets tab, or ask for a higher limit.</p>
          )
        )}
        <p className="text-amber-200/80">
          {health?.ingest_up === false
            ? isAdmin ? <>Check the abenix-telemetry-ingest service on <Link href="/admin/cluster" className="text-cyan-300 hover:underline">Cluster Health</Link>. </> : 'An admin can check it on Cluster Health. '
            : isAdmin ? 'Limits are set per workspace by the platform operator. ' : 'An admin can ask for a higher limit. '}
          <Link href="/alerts" className="text-cyan-300 hover:underline">See alerts</Link>
        </p>
      </div>
    </div>
  );
}
