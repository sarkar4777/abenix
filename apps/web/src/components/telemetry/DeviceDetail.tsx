'use client';

import { memo, useEffect, useMemo, useState } from 'react';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { AlertTriangle, Archive, ArrowLeft, BellPlus, Binary, Bot, Loader2, Search, Send } from 'lucide-react';
import { ForgetOneDialog } from './ForgetDialogs';
import { apiFetch } from '@/lib/api-client';
import { useTelemetry, nodeStatus, type NodeEntry } from '@/lib/telemetry/store';
import { addToBatch, emptyBatch } from '@/lib/telemetry/stream';
import { pushDetail } from '@/lib/telemetry/useTelemetryFeed';
import { FLAG_TEXT, ago, clock, deviceKey, formatValue, friendlyName, isNumeric, liveRate, silentFor, splitMetric, toMs, valueFlags } from '@/lib/telemetry/format';
import { explainTelemetryError } from '@/lib/telemetry/errors';
import type { HistoryPoint, Metric, NodeDetail } from '@/lib/telemetry/types';
import { OfflineBanner } from './DevicesTab';
import { nodeHref } from './NodeCard';
import { Sparkline, StatusDot, StatusPill } from './bits';
import type { RangeId } from './HistoryChart';
import SignalCharts from './SignalCharts';
import { MAX_SIGNALS, defaultSignals } from '@/lib/telemetry/charts';
import SendCommandDialog from './SendCommandDialog';
import PartsOverview from './PartsOverview';


// the value people usually look at first, then the first number
const HEADLINE = [/speed|_rpm$/i, /pressure|_bar$/i, /load|_pct$/i, /temp|_c$/i];

export function defaultMetric(list: Metric[]): string {
  const nums = list.filter((m) => isNumeric(m.value)).sort((a, b) => a.name.localeCompare(b.name));
  for (const re of HEADLINE) {
    const hit = nums.find((m) => re.test(m.name));
    if (hit) return hit.name;
  }
  return nums[0]?.name ?? '';
}

const MetricRow = memo(function MetricRow({ m, samples, now, selected, onPick, stale, ruleHref }: { m: Metric; samples: HistoryPoint[] | undefined; now: number; selected: boolean; onPick: (n: string) => void; stale: boolean; ruleHref: string }) {
  const { group, label, unit } = splitMetric(m.name);
  const chartable = isNumeric(m.value) || typeof m.value === 'boolean';
  const flags = valueFlags(m, now);
  return (
    <div className={`flex items-stretch border-b border-slate-800/80 ${selected ? 'bg-cyan-500/10' : 'hover:bg-slate-800/40'}`}>
    <button
      type="button"
      onClick={() => chartable && onPick(m.name)}
      aria-pressed={selected}
      title={chartable ? (selected ? `Take ${m.name} off the chart` : `Chart ${m.name}`) : m.name}
      className={`grid h-11 min-w-0 flex-1 grid-cols-[minmax(0,1fr)_7.5rem] items-center gap-2 pl-3 text-left sm:grid-cols-[minmax(0,1fr)_8rem_6.5rem_4.5rem] ${chartable ? '' : 'cursor-default'} ${stale ? 'opacity-60' : ''}`}
      data-testid="tel-metric-row"
      data-metric={m.name}
    >
      <span className="min-w-0">
        <span className="block truncate text-sm text-slate-100">{label}</span>
        <span className="block truncate font-mono text-[10px] text-slate-500">{group ? `${group}/` : ''}{m.name.split('/').pop()}</span>
      </span>
      <span className="flex min-w-0 items-baseline justify-end gap-1 text-right">
        <span className={`truncate text-sm font-semibold tabular-nums ${flags.includes('bad') ? 'text-rose-200 line-through decoration-rose-400/60' : flags.length ? 'text-amber-100' : 'text-white'}`} data-testid="tel-metric-value">{formatValue(m.value)}</span>
        {unit && isNumeric(m.value) && <span className="shrink-0 text-[11px] text-slate-400">{unit}</span>}
        {flags.map((f) => (
          <span key={f} className={`shrink-0 rounded px-1 text-[10px] ${f === 'bad' ? 'bg-rose-500/15 text-rose-200' : 'bg-amber-500/15 text-amber-200'}`} title={FLAG_TEXT[f].why} data-testid={`tel-flag-${f}`}>{FLAG_TEXT[f].label}</span>
        ))}
      </span>
      <span className="hidden justify-end sm:flex">
        {chartable ? <Sparkline points={samples} now={now} width={96} height={22} label={`${label} over the last minute`} /> : <span className="text-[11px] text-slate-600">text</span>}
      </span>
      <span className="hidden truncate text-right text-[11px] text-slate-500 sm:block">{ago(m.ts ?? null, now)}</span>
    </button>
    <Link href={`${ruleHref}&signal=${encodeURIComponent(m.name)}`} title="Make a rule from this signal" aria-label={`Make a rule from ${m.name}`} className="flex w-9 shrink-0 items-center justify-center text-slate-500 hover:text-cyan-300" data-testid="tel-metric-rule">
      <BellPlus className="h-3.5 w-3.5" />
    </Link>
    </div>
  );
});

export default function DeviceDetail({
  group, node, device, entry, loaded, canCommand, now, signals, setSignals, rangeId, setRange, onOpenFrames, backHref, missing, focus, setFocus, canManage, onForgotten,
}: {
  group: string; node: string; device: string; entry: NodeEntry | undefined; loaded: boolean; canCommand: boolean; now: number;
  signals: string[]; setSignals: (s: string[]) => void; rangeId: RangeId; setRange: (r: RangeId) => void; onOpenFrames: () => void;
  backHref: string; missing?: boolean; focus?: boolean; setFocus?: (on: boolean) => void;
  canManage?: boolean; onForgotten?: () => void;
}) {
  const key = deviceKey(group, node, device);
  const metrics = useTelemetry((s) => s.metrics[key]);
  const samples = useTelemetry((s) => s.samples[key]);
  const nodeMetrics = useTelemetry((s) => s.metrics[deviceKey(group, node, '')]);
  const [state, setState] = useState<'loading' | 'ready' | 'missing' | 'error'>('loading');
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const [cmdOpen, setCmdOpen] = useState(false);
  const [forgetOpen, setForgetOpen] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let stop = false;
    if (missing) { setState('missing'); return; }
    setState('loading');
    (async () => {
      const res = await apiFetch<NodeDetail>(`/api/telemetry/devices/${encodeURIComponent(group)}/${encodeURIComponent(node)}${device ? `?device=${encodeURIComponent(device)}` : ''}`, { silent: true });
      if (stop) return;
      if (res.error) {
        if (res.errorDetail?.code === 404) { setState('missing'); return; }
        setErr(explainTelemetryError({ status: res.errorDetail?.code, code: res.errorDetail?.error_code, message: res.error }, 'load'));
        setState('error');
        return;
      }
      if (res.data) {
        const b = emptyBatch();
        pushDetail({ ...res.data, group: res.data.group || group, node: res.data.node || node }, device, (e) => addToBatch(b, e));
        useTelemetry.getState().applyBatch(b);
      }
      setState('ready');
    })();
    return () => { stop = true; };
  }, [group, node, device, reload, missing]);

  // the default charts are picked once a moment of data is in, then they stay put
  const [defaults, setDefaults] = useState<string[] | null>(null);
  const haveMetrics = Object.keys(metrics || {}).length > 0;
  useEffect(() => { setDefaults(null); }, [group, node, device]);
  useEffect(() => {
    if (defaults || !haveMetrics) return;
    const t = setTimeout(() => {
      const st = useTelemetry.getState();
      setDefaults(defaultSignals(Object.values(st.metrics[key] || {}), st.samples[key]));
    }, 1500);
    return () => clearTimeout(t);
  }, [defaults, haveMetrics, key]);
  const chosen = signals.filter((s) => metrics?.[s] !== undefined);
  const charted = chosen.length ? chosen : defaults ?? [];
  const togglePick = (name: string) => {
    const cur = charted;
    if (cur.includes(name)) { if (cur.length > 1) setSignals(cur.filter((x) => x !== name)); return; }
    setSignals([...cur, name].slice(-MAX_SIGNALS));
  };
  // the charted values' group first, so the headline numbers sit at the top
  const lead = charted[0] ? splitMetric(charted[0]).group : '';
  const list = useMemo(() => {
    const rank = (n: string) => (lead && splitMetric(n).group === lead ? 0 : 1);
    const all = Object.values(metrics || {}).sort((a, b) => rank(a.name) - rank(b.name) || a.name.localeCompare(b.name));
    const qq = q.trim().toLowerCase();
    return qq ? all.filter((m) => m.name.toLowerCase().includes(qq)) : all;
  }, [metrics, q, lead]);

  // a writable signal the agent can act on, the one being charted first
  const writable = charted.find((n) => metrics?.[n]?.writable) ?? Object.values(metrics || {}).find((m) => m.writable || m.name === 'Safety/Hold')?.name;
  const watchHref = `/telemetry/agents?asset=${encodeURIComponent(`${group}/${node}`)}&template=machine-health-watcher${writable ? `&signal=${encodeURIComponent(writable)}` : ''}`;
  const row = device ? entry?.devices[device] : entry?.self ?? undefined;
  const status = device ? (row ? (row.online ? 'online' : 'offline') : 'offline') : entry ? nodeStatus(entry) : 'offline';
  const online = status !== 'offline';
  const name = friendlyName(nodeMetrics ? Object.values(nodeMetrics) : undefined);
  const devices = entry ? Object.values(entry.devices).sort((a, b) => a.device.localeCompare(b.device)) : [];
  // node-level values such as Sparkplug Bus/Load, shown beside the parts when there are any
  const ownMetrics = Object.keys(metrics || {}).length > 0;
  const offlineAt = toMs(row?.offline_at) ?? toMs(row?.last_seen);
  const target = device ? `${node} / ${device}` : node;

  if (missing || state === 'missing' || (loaded && !entry && state === 'ready')) {
    return (
      <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-6 text-sm text-slate-300" data-testid="tel-device-missing">
        <Link href={backHref} className="mb-3 inline-flex items-center gap-1 text-xs text-slate-400 hover:text-cyan-300"><ArrowLeft className="h-3 w-3" /> All assets</Link>
        <p className="text-base font-semibold text-white">{target} is not known to Abenix yet.</p>
        <p className="mt-1">An asset shows up with the first message that maps to it, for Sparkplug B that is its birth message. Check the name in the link, or go back to the list to pick one.</p>
      </div>
    );
  }

  return (
    <div className="space-y-3" data-testid="tel-device-detail" data-node={node} data-device={device}>
      <div className="flex min-w-0 flex-wrap items-start gap-3">
        <div className="min-w-[min(100%,18rem)] flex-1">
          <Link href={backHref} className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-cyan-300" data-testid="tel-back"><ArrowLeft className="h-3 w-3" /> All assets</Link>
          <div className="mt-1 flex min-w-0 flex-wrap items-center gap-2">
            <h2 className="min-w-0 truncate font-mono text-xl font-semibold text-white" data-testid="tel-device-title">{target}</h2>
            <StatusPill status={status} testId="tel-device-status" />
          </div>
          <p className="mt-0.5 truncate text-xs text-slate-400">
            {name ? `${name} · ` : ''}{group}
            {row?.birth_at && online ? <span title="When it last came online. For Sparkplug B sources this is its last birth message."> · online since {clock(toMs(row.birth_at) ?? 0)}</span> : null}
          </p>
        </div>
        <dl className="grid grid-cols-3 gap-3 text-right">
          {(() => {
            const lr = liveRate(row?.msgs_per_sec, row?.readings_per_sec, online);
            return <div><dt className="text-[10px] uppercase tracking-wide text-slate-500">{lr.unit}</dt><dd className="text-sm font-semibold tabular-nums text-white" data-testid="tel-device-rate">{lr.value}</dd></div>;
          })()}
          <div><dt className="text-[10px] uppercase tracking-wide text-slate-500" title="Messages missing in sequence">Gaps</dt><dd className={`text-sm font-semibold tabular-nums ${(row?.seq_gaps ?? 0) > 0 ? 'text-amber-200' : 'text-white'}`}>{row?.seq_gaps ?? 0}</dd></div>
          <div><dt className="text-[10px] uppercase tracking-wide text-slate-500">Last</dt><dd className="text-sm tabular-nums text-slate-200">{ago(row?.last_seen ?? null, now)}</dd></div>
        </dl>
        <div className="flex w-full flex-wrap gap-2 sm:w-auto">
          {canManage && (
            <button type="button" onClick={() => setForgetOpen(true)} className="inline-flex min-h-[36px] flex-1 items-center justify-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800 sm:flex-none" data-testid="tel-forget" title={device ? 'Take this part off the list, its history stays' : 'Take this asset off the list, its history stays'}>
              <Archive className="h-4 w-4" /> {device ? 'Forget this part' : 'Forget this asset'}
            </button>
          )}
          <Link href={watchHref} className="inline-flex min-h-[36px] flex-1 items-center justify-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800 sm:flex-none" data-testid="tel-watch-agent" title="Make an agent that watches this asset and acts on what it sees">
            <Bot className="h-4 w-4" /> Watch this asset with an agent
          </Link>
          <button type="button" onClick={onOpenFrames} className="inline-flex min-h-[36px] flex-1 items-center justify-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800 sm:flex-none" data-testid="tel-open-frames">
            <Binary className="h-4 w-4" /> Raw messages
          </button>
          {!canCommand && (
            <p className="flex-1 self-center text-xs text-slate-400 sm:max-w-[16rem]" data-testid="tel-command-needs">Writing values back needs Send machine commands. An admin can give it to you under Admin, Permissions, for example with the Machine operators set.</p>
          )}
          {canCommand && (
            online ? (
              <button type="button" onClick={() => setCmdOpen(true)} className="inline-flex min-h-[36px] flex-1 items-center justify-center gap-1.5 rounded-lg bg-cyan-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-cyan-400 sm:flex-none" data-testid="tel-send-command">
                <Send className="h-4 w-4" /> Send command
              </button>
            ) : (
              <p className="flex-1 self-center text-xs text-slate-400 sm:max-w-[13rem]" data-testid="tel-command-offline-note">Commands open again when {target} is back online.</p>
            )
          )}
        </div>
      </div>

      {(devices.length > 0 || device) && (
        <nav className="scrollbar-none -mx-1 flex gap-1 overflow-x-auto px-1 pb-1" aria-label="Parts of this asset">
          <Link href={nodeHref({ group, node }, '')} className={`inline-flex shrink-0 items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs ${!device ? 'border-cyan-400 bg-cyan-500/10 text-white' : 'border-slate-700 text-slate-300 hover:border-slate-500'}`} data-testid="tel-device-tab" data-device="">
            <StatusDot status={entry && entry.self ? (entry.self.online ? 'online' : 'offline') : 'unknown'} /> Whole asset
          </Link>
          {devices.map((d) => (
            <Link key={d.device} href={nodeHref({ group, node }, d.device)} className={`inline-flex shrink-0 items-center gap-1.5 rounded-md border px-2.5 py-1 font-mono text-xs ${device === d.device ? 'border-cyan-400 bg-cyan-500/10 text-white' : 'border-slate-700 text-slate-300 hover:border-slate-500'}`} data-testid="tel-device-tab" data-device={d.device}>
              <StatusDot status={d.online ? 'online' : 'offline'} /> {d.device}
            </Link>
          ))}
        </nav>
      )}

      {!online && (
        <OfflineBanner items={[{ key, label: target, href: nodeHref({ group, node }, device), at: offlineAt }]} now={now} testId="tel-device-offline" />
      )}

      {online && silentFor(row?.last_seen ?? null, online, now) !== null && (
        <div className="flex items-start gap-2 rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-2.5 text-sm text-amber-100" role="status" data-testid="tel-device-silent">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
          <p>Nothing from {target} for {ago(row?.last_seen ?? null, now).replace(' ago', '')}, though it has not said it went offline. The values below may be out of date. Some sources only send when a value changes, so this can be normal for a quiet asset.</p>
        </div>
      )}

      {state === 'error' && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-3 text-sm text-rose-100" role="alert">
          {err} <button type="button" className="ml-1 text-cyan-300 hover:underline" onClick={() => setReload((n) => n + 1)}>Try again</button>
        </div>
      )}

      {!device && devices.length > 0 && (
        <PartsOverview group={group} node={node} entry={entry} now={now} rangeId={rangeId} setRange={setRange} focus={focus} />
      )}

      {(device || ownMetrics || devices.length === 0) && (
      <div className={`grid min-w-0 gap-3 ${focus ? '' : 'lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]'}`}>
        {!focus && (
        <section className="min-w-0 overflow-hidden rounded-xl border border-slate-700/60 bg-slate-900/40" aria-label="Live metrics">
          <div className="flex items-center gap-2 border-b border-slate-700/60 px-3 py-2">
            <h3 className="flex-1 text-sm font-medium text-white">Live values <span className="font-normal text-slate-500">({Object.keys(metrics || {}).length})</span></h3>
            {Object.keys(metrics || {}).length > 10 && (
              <label className="relative w-40">
                <span className="sr-only">Filter metrics</span>
                <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
                <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter" className="w-full rounded-md border border-slate-700 bg-slate-950 py-1 pl-7 pr-2 text-xs text-white placeholder:text-slate-500" data-testid="tel-metric-filter" />
              </label>
            )}
          </div>
          <div className="hidden grid-cols-[minmax(0,1fr)_8rem_6.5rem_4.5rem] gap-2 border-b border-slate-800 py-1.5 pl-3 pr-12 text-[10px] uppercase tracking-wide text-slate-500 sm:grid">
            <span>Metric</span><span className="text-right">Value</span><span className="text-right">Last minute</span><span className="text-right">Updated</span>
          </div>
          {state === 'loading' && !list.length ? (
            <div className="flex items-center gap-2 p-4 text-xs text-slate-400" data-testid="tel-metrics-loading"><Loader2 className="h-4 w-4 animate-spin" /> Loading the latest values</div>
          ) : !list.length ? (
            <p className="p-4 text-sm text-slate-400" data-testid="tel-metrics-empty">
              {q ? 'No metric matches this filter.' : device ? `${target} has not reported any values yet. They appear with its next birth or data message.` : `Nothing from ${target} or any of its parts yet. Values appear with the first message, for Sparkplug B the birth message. If a source should be sending, the Messages tab says why nothing arrives.`}
            </p>
          ) : (
            <div className="max-h-[520px] overflow-y-auto" data-testid="tel-metrics">
              {list.map((m) => (
                <MetricRow key={m.name} m={m} samples={samples?.[m.name]} now={now} selected={charted.includes(m.name)} onPick={togglePick} stale={!online} ruleHref={`/telemetry/rules/new?group=${encodeURIComponent(group)}&node=${encodeURIComponent(node)}&device=${encodeURIComponent(device)}`} />
              ))}
            </div>
          )}
          {list.some((m) => valueFlags(m, now).length > 0) && (
            <p className="border-t border-slate-800 px-3 py-2 text-[11px] text-slate-400" data-testid="tel-flags-legend">
              {Array.from(new Set(list.flatMap((m) => valueFlags(m, now)))).map((f) => `${FLAG_TEXT[f].label}: ${FLAG_TEXT[f].why}`).join(' ')}
            </p>
          )}
        </section>

        )}
        <SignalCharts
          tall={focus}
          onFocus={setFocus ? () => setFocus(!focus) : undefined}
          focused={!!focus}
          group={group}
          node={node}
          device={device}
          signals={charted}
          setSignals={setSignals}
          metrics={metrics}
          samples={samples}
          rangeId={rangeId}
          setRange={setRange}
          loading={state === 'loading' || (!defaults && !signals.length && Object.keys(metrics || {}).length > 0)}
        />
      </div>
      )}

      {forgetOpen && (
        <ForgetOneDialog group={group} node={node} device={device} onClose={() => setForgetOpen(false)} onDone={() => { setForgetOpen(false); onForgotten?.(); }} />
      )}

      {canCommand && cmdOpen && (
        <SendCommandDialog open={cmdOpen} onClose={() => setCmdOpen(false)} group={group} node={node} device={device} online={online} />
      )}
    </div>
  );
}
