'use client';

import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { List, type RowComponentProps } from 'react-window';
import { AlertTriangle, Archive, LayoutGrid, Plug, Radio, Rows3, Search, X } from 'lucide-react';
import { nodeGaps, nodeLastSeen, nodeRate, nodeStatus, sortedNodes, useTelemetry, type NodeEntry, type NodeFilter } from '@/lib/telemetry/store';
import { ago, clock, rate, toMs } from '@/lib/telemetry/format';
import type { Connection } from '@/lib/telemetry/types';
import { FirstSources, type Source, type TestbedInfo } from './SourcesTab';
import NodeCard, { CARD_HEIGHT, nodeHref } from './NodeCard';
import { StatusDot } from './bits';

export type DevicesView = 'cards' | 'table';

// above this many cards the grid is windowed, below it a plain grid scrolls with the page
export const PLAIN_GRID_MAX = 24;
const GAP = 12;
const ROW_H = 40;

// a callback ref, so a grid that mounts after a loading state is still measured
export function useWidth<T extends HTMLElement>(): [(el: T | null) => void, number] {
  const [el, setEl] = useState<T | null>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    if (!el) return;
    setW(el.clientWidth);
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  return [setEl, w];
}

export function columnsFor(width: number): number {
  if (width >= 1180) return 4;
  if (width >= 860) return 3;
  if (width >= 560) return 2;
  return 1;
}

interface OfflineItem { key: string; label: string; href: string; at: number | null }

export function offlineItems(nodes: NodeEntry[]): OfflineItem[] {
  const out: OfflineItem[] = [];
  for (const n of nodes) {
    const st = nodeStatus(n);
    if (st === 'offline') {
      out.push({ key: n.key, label: n.node, href: nodeHref(n), at: toMs(n.self?.offline_at) ?? nodeLastSeen(n) });
      continue;
    }
    for (const d of Object.values(n.devices)) {
      if (!d.online) out.push({ key: `${n.key}/${d.device}`, label: `${n.node} / ${d.device}`, href: nodeHref(n, d.device), at: toMs(d.offline_at) ?? toMs(d.last_seen) });
    }
  }
  return out.sort((a, b) => (b.at ?? 0) - (a.at ?? 0));
}

export function OfflineBanner({ items, now, testId = 'tel-offline-banner' }: { items: OfflineItem[]; now: number; testId?: string }) {
  if (!items.length) return null;
  const shown = items.slice(0, 3);
  return (
    <div role="alert" className="flex items-start gap-3 rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-100" data-testid={testId}>
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-rose-300" />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-white">
          {items.length === 1 ? `${items[0].label} is offline.` : `${items.length} assets or parts are offline.`}
        </p>
        <ul className="mt-1 space-y-0.5">
          {shown.map((i) => (
            <li key={i.key} className="truncate">
              <Link href={i.href} className="font-mono text-rose-50 hover:underline">{i.label}</Link>
              {i.at ? <span className="text-rose-200/90"> went offline at {clock(i.at)}, {ago(i.at, now)}</span> : <span className="text-rose-200/90"> has not reported since it started</span>}
            </li>
          ))}
          {items.length > shown.length && <li className="text-rose-200/80">and {items.length - shown.length} more, filter by Offline to see them all</li>}
        </ul>
        <p className="mt-1 text-rose-200/80">
          Its last values stay on screen, greyed out. It comes back when it sends a new birth message.{' '}
          <Link href="/alerts" className="text-cyan-300 hover:underline" data-testid="tel-offline-alerts">See alerts</Link>
        </p>
      </div>
    </div>
  );
}

interface GridRowProps { rows: NodeEntry[][]; cols: number; now: number }

function GridRow({ index, style, rows, cols, now }: RowComponentProps<GridRowProps>) {
  const row = rows[index];
  return (
    <div style={{ ...style, display: 'grid', gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, gap: GAP, paddingBottom: GAP }}>
      {row.map((n) => <NodeCard key={n.key} entry={n} now={now} />)}
    </div>
  );
}

interface TableRowProps { items: Array<{ n: NodeEntry; device: string }>; now: number }

function TableRow({ index, style, items, now }: RowComponentProps<TableRowProps>) {
  const { n, device } = items[index];
  const d = device ? n.devices[device] : n.self;
  const online = d ? d.online : nodeStatus(n) !== 'offline';
  const seen = d ? toMs(d.last_seen) : nodeLastSeen(n);
  return (
    <div style={style} className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_5.5rem_4.5rem] items-center gap-2 border-b border-slate-800/80 px-3 text-sm sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_6rem_5rem_5rem_minmax(0,1fr)]" data-testid="tel-device-row" data-node={n.node} data-device={device}>
      <Link href={nodeHref(n, device || undefined)} className="truncate font-mono text-slate-100 hover:text-cyan-300">{n.node}</Link>
      <span className="truncate font-mono text-slate-300">{device || <span className="font-sans text-slate-500">the asset</span>}</span>
      <span className={`inline-flex items-center gap-1.5 text-xs ${online ? 'text-emerald-300' : 'text-rose-200'}`}><StatusDot status={online ? 'online' : 'offline'} />{online ? 'Online' : 'Offline'}</span>
      <span className="text-right tabular-nums text-slate-200">{rate(d ? d.msgs_per_sec : nodeRate(n))}</span>
      <span className={`hidden text-right tabular-nums sm:block ${(d ? d.seq_gaps : nodeGaps(n)) > 0 ? 'text-amber-200' : 'text-slate-400'}`}>{d ? d.seq_gaps : nodeGaps(n)}</span>
      <span className="hidden truncate text-xs text-slate-400 sm:block">{ago(seen, now)}</span>
    </div>
  );
}

export interface DevicesTabProps {
  nodes: Record<string, NodeEntry>;
  loaded: boolean;
  error: string | null;
  onRetry: () => void;
  filter: NodeFilter;
  setFilter: (f: Partial<NodeFilter>) => void;
  view: DevicesView;
  setView: (v: DevicesView) => void;
  onVisible: (nodeKeys: string[]) => void;
  connections: Connection[] | null;
  canManage: boolean;
  openConnections: (add?: boolean) => void;
  onFirst: (transport: string) => void;
  testbed?: TestbedInfo | null;
  unregistered?: number;
  onBulkForget?: () => void;
  now: number;
  total?: number | null;
  loadedRows?: number;
}

export default function DevicesTab(p: DevicesTabProps) {
  const { nodes, filter, setFilter, view, now, onVisible } = p;
  const all = useMemo(() => Object.values(nodes), [nodes]);
  const assets = useTelemetry((s) => s.assets);
  const list = useMemo(() => sortedNodes(nodes, filter, assets), [nodes, filter, assets]);
  const types = useMemo(() => Array.from(new Set(Object.values(assets).map((a) => a.type).filter(Boolean) as string[])).sort(), [assets]);
  const tags = useMemo(() => Array.from(new Set(Object.values(assets).flatMap((a) => a.tags ?? []))).sort(), [assets]);
  const groups = useMemo(() => Array.from(new Set(all.map((n) => n.group))).sort(), [all]);
  const teams = useMemo(() => {
    const t = new Set<string>();
    for (const n of all) {
      if (n.self?.team_name) t.add(n.self.team_name);
      for (const d of Object.values(n.devices)) if (d.team_name) t.add(d.team_name);
    }
    return Array.from(t).sort();
  }, [all]);
  const offline = useMemo(() => offlineItems(list), [list]);
  const [wrapRef, width] = useWidth<HTMLDivElement>();
  const cols = columnsFor(width || (typeof window !== 'undefined' ? window.innerWidth : 1200));
  const [q, setQ] = useState(filter.q);
  useEffect(() => setQ(filter.q), [filter.q]);
  useEffect(() => {
    if (q === filter.q) return;
    const t = setTimeout(() => setFilter({ q }), 250);
    return () => clearTimeout(t);
  }, [q, filter.q, setFilter]);

  const windowed = view === 'cards' && list.length > PLAIN_GRID_MAX;
  const rows = useMemo(() => {
    const out: NodeEntry[][] = [];
    for (let i = 0; i < list.length; i += cols) out.push(list.slice(i, i + cols));
    return out;
  }, [list, cols]);
  const tableItems = useMemo(() => {
    const out: Array<{ n: NodeEntry; device: string }> = [];
    const qq = filter.q.trim().toLowerCase();
    for (const n of list) {
      const devs = Object.keys(n.devices).sort();
      if (!devs.length) out.push({ n, device: '' });
      for (const d of devs) {
        const row = n.devices[d];
        if (filter.status === 'online' && !row.online) continue;
        if (filter.status === 'offline' && row.online) continue;
        if (qq && !n.node.toLowerCase().includes(qq) && !n.group.toLowerCase().includes(qq) && !d.toLowerCase().includes(qq)) continue;
        out.push({ n, device: d });
      }
    }
    return out;
  }, [list, filter]);

  // the plain grid shows everything, so it is all on screen
  const plainKeys = useMemo(() => (!windowed && view === 'cards' ? list.map((n) => n.key) : null), [windowed, view, list]);
  useEffect(() => {
    if (plainKeys) onVisible(plainKeys);
  }, [plainKeys, onVisible]);
  const onGridRows = useCallback((v: { startIndex: number; stopIndex: number }) => {
    onVisible(rows.slice(v.startIndex, v.stopIndex + 1).flat().map((n) => n.key));
  }, [rows, onVisible]);
  const onTableRows = useCallback((v: { startIndex: number; stopIndex: number }) => {
    onVisible(Array.from(new Set(tableItems.slice(v.startIndex, v.stopIndex + 1).map((i) => i.n.key))));
  }, [tableItems, onVisible]);

  const filtered = !!(filter.q || filter.group || filter.status || filter.team || filter.type || filter.tag);
  const listHeight = 'max(420px, calc(100vh - 380px))';

  if (p.error && !p.loaded) {
    return (
      <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-100" role="alert" data-testid="tel-devices-error">
        <p>{p.error}</p>
        <button type="button" onClick={p.onRetry} className="mt-2 rounded-md border border-slate-600 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800">Try again</button>
      </div>
    );
  }
  if (!p.loaded) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" data-testid="tel-devices-loading" aria-busy="true">
        {[0, 1, 2, 3].map((i) => <div key={i} className="animate-pulse rounded-xl border border-slate-800 bg-slate-800/30" style={{ height: CARD_HEIGHT }} />)}
      </div>
    );
  }

  if (!all.length) return <NoDevices connections={p.connections} canManage={p.canManage} openConnections={p.openConnections} onFirst={p.onFirst} testbed={p.testbed} />;

  return (
    <div className="space-y-3">
      <OfflineBanner items={offlineItems(list)} now={now} />

      <div className="flex flex-wrap items-center gap-2" data-testid="tel-filters">
        <label className="relative min-w-[12rem] flex-1 sm:max-w-xs">
          <span className="sr-only">Search assets and parts</span>
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search asset or part"
            className="w-full rounded-lg border border-slate-700 bg-slate-900 py-2 pl-8 pr-8 text-sm text-white placeholder:text-slate-500"
            data-testid="tel-search"
          />
          {q && (
            <button type="button" onClick={() => { setQ(''); setFilter({ q: '' }); }} aria-label="Clear search" className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1 text-slate-400 hover:text-white">
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </label>
        {groups.length > 1 && (
          <select value={filter.group} onChange={(e) => setFilter({ group: e.target.value })} aria-label="Group" className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-sm text-slate-200" data-testid="tel-filter-group">
            <option value="">All groups</option>
            {groups.map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
        )}
        <select value={filter.status} onChange={(e) => setFilter({ status: e.target.value as NodeFilter['status'] })} aria-label="Status" className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-sm text-slate-200" data-testid="tel-filter-status">
          <option value="">Online and offline</option>
          <option value="online">Online</option>
          <option value="offline">Offline</option>
        </select>
        {types.length > 0 && (
          <select value={filter.type ?? ''} onChange={(e) => setFilter({ type: e.target.value })} aria-label="Asset type" className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-sm text-slate-200" data-testid="tel-filter-type">
            <option value="">All types</option>
            {types.map((t) => <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>)}
          </select>
        )}
        {tags.length > 0 && (
          <select value={filter.tag ?? ''} onChange={(e) => setFilter({ tag: e.target.value })} aria-label="Tag" className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-sm text-slate-200" data-testid="tel-filter-tag">
            <option value="">All tags</option>
            {tags.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        )}
        {teams.length > 0 && (
          <select value={filter.team} onChange={(e) => setFilter({ team: e.target.value })} aria-label="Team" className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-sm text-slate-200" data-testid="tel-filter-team">
            <option value="">All teams</option>
            {teams.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        )}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {p.unregistered ? (
            <Link href="/telemetry/assets?status=unregistered" className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[11px] text-amber-200 hover:underline" data-testid="tel-unregistered" title="Assets that arrived from streams and have no name, type or tags yet">
              {p.unregistered} unnamed
            </Link>
          ) : null}
          {p.canManage && p.onBulkForget && (
            <button type="button" onClick={p.onBulkForget} className="inline-flex items-center gap-1 rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800" data-testid="tel-bulk-forget-open" title="Take devices that stopped reporting off the list, their history stays">
              <Archive className="h-3.5 w-3.5" /> Forget offline devices
            </button>
          )}
          <span className="text-xs text-slate-400" data-testid="tel-count">
            {view === 'table' ? `${tableItems.length} part${tableItems.length === 1 ? '' : 's'}` : `${list.length} of ${all.length} asset${all.length === 1 ? '' : 's'}`}
            {p.total && p.loadedRows && p.total > p.loadedRows ? `, ${p.loadedRows} of ${p.total} loaded, search to narrow` : ''}
          </span>
          <div className="inline-flex rounded-lg border border-slate-700 p-0.5" role="group" aria-label="Layout">
            <button type="button" onClick={() => p.setView('cards')} aria-pressed={view === 'cards'} className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs ${view === 'cards' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`} data-testid="tel-view-cards">
              <LayoutGrid className="h-3.5 w-3.5" /> Cards
            </button>
            <button type="button" onClick={() => p.setView('table')} aria-pressed={view === 'table'} className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs ${view === 'table' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`} data-testid="tel-view-table">
              <Rows3 className="h-3.5 w-3.5" /> Table
            </button>
          </div>
        </div>
      </div>

      <div ref={wrapRef} className="min-w-0">
        {filtered && (view === 'cards' ? list.length === 0 : tableItems.length === 0) ? (
          <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-6 text-center text-sm text-slate-300" data-testid="tel-no-match">
            <p>No assets match these filters.</p>
            <button type="button" onClick={() => { setQ(''); setFilter({ q: '', group: '', status: '', team: '', type: '', tag: '' }); }} className="mt-2 text-cyan-300 hover:underline" data-testid="tel-clear-filters">Clear filters</button>
          </div>
        ) : view === 'table' ? (
          <div className="overflow-hidden rounded-xl border border-slate-700/60 bg-slate-900/40" data-testid="tel-table">
            <div className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_5.5rem_4.5rem] gap-2 border-b border-slate-700 px-3 py-2 text-[11px] uppercase tracking-wide text-slate-500 sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_6rem_5rem_5rem_minmax(0,1fr)]">
              <span>Asset</span><span>Part</span><span>Status</span><span className="text-right">msg/s</span><span className="hidden text-right sm:block" title="Messages missing in sequence">Gaps</span><span className="hidden sm:block">Last message</span>
            </div>
            <List
              rowCount={tableItems.length}
              rowHeight={ROW_H}
              rowComponent={TableRow}
              rowProps={{ items: tableItems, now }}
              overscanCount={8}
              onRowsRendered={onTableRows}
              defaultHeight={480}
              style={{ height: tableItems.length > 12 ? listHeight : tableItems.length * ROW_H + 2 }}
            />
          </div>
        ) : windowed ? (
          <List
            rowCount={rows.length}
            rowHeight={CARD_HEIGHT + GAP}
            rowComponent={GridRow}
            rowProps={{ rows, cols, now }}
            overscanCount={2}
            onRowsRendered={onGridRows}
            defaultHeight={720}
            style={{ height: listHeight }}
            data-testid="tel-grid-windowed"
          />
        ) : (
          <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, gridAutoRows: CARD_HEIGHT }} data-testid="tel-grid">
            {list.map((n) => <NodeCard key={n.key} entry={n} now={now} />)}
          </div>
        )}
      </div>
    </div>
  );
}

function NoDevices({ connections, canManage, openConnections, onFirst, testbed }: { connections: Connection[] | null; canManage: boolean; openConnections: (add?: boolean) => void; onFirst: (transport: string) => void; testbed?: TestbedInfo | null }) {
  const conns = connections || [];
  if (!conns.length) return <FirstSources canManage={canManage} onPick={onFirst} testbed={testbed} />;
  const broken = conns.filter((c) => c.enabled && c.status === 'error');
  const on = conns.filter((c) => c.enabled);
  const sparkplug = on.some((c) => !(c as Source).decoder || (c as Source).decoder === 'sparkplug_b');
  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-6 sm:p-10" data-testid="tel-empty-no-devices">
      <Radio className="mx-auto h-8 w-8 text-cyan-400" />
      <h2 className="mt-3 text-center text-base font-semibold text-white">No assets yet: they appear with the first message that maps to one</h2>
      <div className="mx-auto mt-3 max-w-xl space-y-2 text-sm text-slate-300">
        <p>{on.length ? `Abenix is reading ${on.map((c) => c.name).join(', ')}.` : 'Every source is turned off, so Abenix is not reading anything.'} An asset shows up as soon as a message arrives that the mapping turns into one. What each source is doing is listed above{broken.length ? ', starting with the ones that need attention' : ''}.</p>
        {sparkplug && <p className="text-slate-400">For Sparkplug B, devices appear when a node sends its birth message (NBIRTH on <code className="rounded bg-slate-800 px-1 text-xs">spBv1.0/&lt;group&gt;/NBIRTH/&lt;node&gt;</code>). Most gateways send one when they connect or restart.</p>}
      </div>
      <div className="mt-4 flex flex-wrap justify-center gap-2">
        <button type="button" onClick={() => openConnections(false)} className="inline-flex min-h-[40px] items-center gap-2 rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800" data-testid="tel-empty-open-connections">
          <Plug className="h-4 w-4" /> {canManage ? 'Test the source' : 'See the sources'}
        </button>
      </div>
    </div>
  );
}
