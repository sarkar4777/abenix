'use client';

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import useSWR from 'swr';
import { Boxes, Compass, Inbox, Plug, Plus, RadioTower } from 'lucide-react';
import PageHeader from '@/components/layout/PageHeader';
import NoAccess from '@/components/layout/NoAccess';
import ViewOnlyBanner from '@/components/shared/ViewOnlyBanner';
import { usePageTitle } from '@/hooks/usePageTitle';
import { apiFetch } from '@/lib/api-client';
import { holds, useMyPermissions } from '@/lib/capabilities';
import { explainTelemetryError } from '@/lib/telemetry/errors';
import { nodeKey } from '@/lib/telemetry/format';
import { useTelemetry, nodeGaps, nodeRate, nodeStatus, sortedNodes, type NodeFilter } from '@/lib/telemetry/store';
import { useTelemetryFeed, type FeedScope } from '@/lib/telemetry/useTelemetryFeed';
import type { DeviceRow, Health } from '@/lib/telemetry/types';
import { parseSignals } from '@/lib/telemetry/charts';
import { toastError, toastSuccess } from '@/stores/toastStore';
import DevicesTab, { type DevicesView } from '@/components/telemetry/DevicesTab';
import DeviceDetail from '@/components/telemetry/DeviceDetail';
import MessagesTab, { type MessagesView } from '@/components/telemetry/MessagesTab';
import SourcesTab, { type Source, type TestbedInfo } from '@/components/telemetry/SourcesTab';
import SourceDiagnoses, { type DiagnosisAction } from '@/components/telemetry/SourceDiagnosis';
import GetStarted from '@/components/telemetry/GetStarted';
import WhatNext from '@/components/telemetry/WhatNext';
import SourceWizard, { type WizardStart } from '@/components/telemetry/SourceWizard';
import { BulkForgetDialog } from '@/components/telemetry/ForgetDialogs';
import type { BulkQuery } from '@/lib/telemetry/forget';
import type { TransportDecl } from '@/lib/telemetry/sources';
import type { AssetInfo } from '@/lib/telemetry/store';
import { IngestHealth, LiveBadge, QuotaBanner } from '@/components/telemetry/IngestHealth';
import { RANGES, type RangeId } from '@/components/telemetry/HistoryChart';

type Tab = 'assets' | 'messages' | 'sources';
const TABS: { id: Tab; label: string; icon: typeof Boxes }[] = [
  { id: 'assets', label: 'Assets', icon: Boxes },
  { id: 'messages', label: 'Messages', icon: Inbox },
  { id: 'sources', label: 'Sources', icon: Plug },
];
// links made before the tabs were renamed keep working
const TAB_ALIAS: Record<string, Tab> = { devices: 'assets', frames: 'messages', connections: 'sources' };
const LIST_KEYS = ['q', 'grp', 'status', 'team', 'atype', 'tag', 'view'];

const PURPOSE = 'Live data streams from machines, devices and software, over MQTT, Kafka, RabbitMQ, NATS, OPC UA, Modbus, WebSockets or HTTP.';

function fetcher(url: string) {
  return apiFetch<unknown>(url, { silent: true });
}

function useNow(ms = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const h = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(h);
  }, [ms]);
  return now;
}

function TelemetryPage() {
  usePageTitle('Telemetry');
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { perms, loading: permsLoading } = useMyPermissions();
  const caps = perms?.capabilities;
  const canView = holds(caps, 'telemetry.view');
  const canManage = holds(caps, 'telemetry.manage');
  const canCommand = holds(caps, 'telemetry.command');

  const rawTab = params.get('tab') || '';
  const tab: Tab = TABS.some((t) => t.id === rawTab) ? (rawTab as Tab) : TAB_ALIAS[rawTab] ?? 'assets';
  const nodeParam = params.get('node') || '';
  const groupParam = params.get('group') || '';
  const deviceParam = params.get('device') || '';
  const filter: NodeFilter = useMemo(() => ({
    q: params.get('q') || '',
    group: params.get('grp') || '',
    status: (['online', 'offline'].includes(params.get('status') || '') ? params.get('status') : '') as NodeFilter['status'],
    team: params.get('team') || '',
    type: params.get('atype') || '',
    tag: params.get('tag') || '',
  }), [params]);
  const view: DevicesView = params.get('view') === 'table' ? 'table' : 'cards';
  const rangeId = (RANGES.some((r) => r.id === params.get('range')) ? params.get('range') : '5m') as RangeId;
  const metric = params.get('metric') || '';
  const mview = params.get('mview') || '';
  // a chart-first view for screens and film, the page chrome steps back
  const focus = params.get('focus') === 'charts' && !!nodeParam;
  const msgView: MessagesView = mview === 'problems' || mview === 'frames' ? mview : rawTab === 'frames' ? 'frames' : 'recent';

  const setParams = useCallback((patch: Record<string, string | null>) => {
    const next = new URLSearchParams(Array.from(params.entries()));
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === '') next.delete(k);
      else next.set(k, v);
    }
    const qs = next.toString();
    router.replace(`${pathname}${qs ? `?${qs}` : ''}`, { scroll: false });
  }, [params, pathname, router]);

  // the list's filters, so the back link from an asset returns to them
  const lastListQs = useRef('');
  useEffect(() => {
    if (nodeParam) return;
    const keep = new URLSearchParams();
    for (const k of LIST_KEYS) {
      const v = params.get(k);
      if (v) keep.set(k, v);
    }
    lastListQs.current = keep.toString();
  }, [params, nodeParam]);

  const roster = useSWR(canView ? '/api/telemetry/devices?limit=5000' : null, fetcher, { refreshInterval: 10_000, revalidateOnFocus: false });
  const conns = useSWR(canView ? '/api/telemetry/connections' : null, fetcher, { refreshInterval: tab === 'sources' ? 5000 : 15_000, revalidateOnFocus: false });
  const healthRes = useSWR(canView ? '/api/telemetry/health' : null, fetcher, { refreshInterval: 5000, revalidateOnFocus: false });
  const testbedRes = useSWR(canManage ? '/api/telemetry/testbed' : null, fetcher, { revalidateOnFocus: false });
  const testbed = testbedRes.data?.data && typeof testbedRes.data.data === 'object' ? (testbedRes.data.data as TestbedInfo) : null;
  const transportsRes = useSWR(canView ? '/api/telemetry/transports' : null, fetcher, { revalidateOnFocus: false });
  const transports = Array.isArray(transportsRes.data?.data) ? (transportsRes.data!.data as TransportDecl[]) : null;
  const teamsRes = useSWR(canManage ? '/api/telemetry/teams' : null, fetcher, { revalidateOnFocus: false });
  const teams = Array.isArray(teamsRes.data?.data) ? (teamsRes.data!.data as Array<{ id: string; name: string }>) : [];
  const assetsRes = useSWR(canView ? '/api/telemetry/assets?limit=5000' : null, fetcher, { refreshInterval: 60_000, revalidateOnFocus: false });
  const setAssets = useTelemetry((s) => s.setAssets);
  useEffect(() => {
    const d = assetsRes.data?.data;
    const rows = Array.isArray(d) ? d : d && typeof d === 'object' && Array.isArray((d as { assets?: unknown }).assets) ? (d as { assets: unknown[] }).assets : null;
    if (rows) setAssets(rows as AssetInfo[]);
  }, [assetsRes.data, setAssets]);
  const [guideOpen, setGuideOpen] = useState(false);
  const [wizard, setWizard] = useState<WizardStart | null>(null);
  const [bulkForget, setBulkForget] = useState<(Partial<BulkQuery> & { autoPreview?: boolean }) | null>(null);
  const [forgetTick, setForgetTick] = useState(0);

  const setRows = useTelemetry((s) => s.setRows);
  const nodes = useTelemetry((s) => s.nodes);
  const loaded = useTelemetry((s) => s.loaded);
  const streamHealth = useTelemetry((s) => s.health);

  useEffect(() => {
    const d = roster.data?.data;
    if (Array.isArray(d)) setRows(d as DeviceRow[]);
  }, [roster.data, setRows]);

  const rosterErr = roster.data?.error
    ? explainTelemetryError({ status: roster.data.errorDetail?.code, code: roster.data.errorDetail?.error_code, message: roster.data.error }, 'load')
    : roster.error ? explainTelemetryError(roster.error, 'load') : null;
  const sources = Array.isArray(conns.data?.data) ? (conns.data!.data as Source[]) : null;
  const connErr = conns.data?.error ? explainTelemetryError({ status: conns.data.errorDetail?.code, code: conns.data.errorDetail?.error_code, message: conns.data.error }, 'load') : null;
  const healthMissing = healthRes.data?.errorDetail?.code === 404;
  const health: Health | null = useMemo(() => {
    const polled = healthRes.data?.data && typeof healthRes.data.data === 'object' ? (healthRes.data.data as Health) : null;
    if (!polled && !streamHealth) return null;
    return { ...(polled ?? {}), ...(streamHealth ?? {}) };
  }, [healthRes.data, streamHealth]);
  const setNodeRates = useTelemetry((s) => s.setNodeRates);
  useEffect(() => {
    const by = health?.messages_per_second_by_node;
    if (!Array.isArray(by)) return;
    const map: Record<string, number> = {};
    for (const r of by) map[nodeKey(r.group, r.node)] = Number(r.messages_per_second) || 0;
    setNodeRates(map);
  }, [health?.messages_per_second_by_node, setNodeRates]);
  const total = typeof roster.data?.meta?.total === 'number' ? (roster.data.meta.total as number) : null;

  const nodeList = useMemo(() => sortedNodes(nodes, { q: '', group: '', status: '', team: '' }), [nodes]);
  const totals = useMemo(() => {
    let r = 0, gaps = 0, online = 0;
    for (const n of nodeList) {
      if (nodeStatus(n) !== 'offline') { online += 1; r += nodeRate(n); }
      gaps += nodeGaps(n);
    }
    return { rate: r, gaps, online, total: nodeList.length };
  }, [nodeList]);

  // a deep link may name only the asset, the group comes from the roster
  const selected = useMemo(() => {
    if (!nodeParam) return null;
    const hit = nodeList.find((n) => n.node === nodeParam && (!groupParam || n.group === groupParam));
    return hit ?? (groupParam ? { group: groupParam, node: nodeParam } : null);
  }, [nodeParam, groupParam, nodeList]);
  const selectedEntry = selected ? nodes[nodeKey(selected.group, selected.node)] : undefined;

  const [visible, setVisible] = useState<string[]>([]);
  const onVisible = useCallback((keys: string[]) => {
    setVisible((prev) => (prev.length === keys.length && prev.every((k, i) => k === keys[i]) ? prev : keys));
  }, []);
  const scope: FeedScope | null = useMemo(() => {
    if (tab !== 'assets') return null;
    if (selected) return { kind: 'device', group: selected.group, node: selected.node, device: deviceParam };
    return { kind: 'nodes', nodes: visible };
  }, [tab, selected, deviceParam, visible]);
  const feed = useTelemetryFeed(scope, canView);
  const now = useNow(1000);

  const openSources = useCallback((add?: boolean | string) => setParams({ tab: 'sources', add: add ? (typeof add === 'string' ? add : 'any') : null, node: null, device: null }), [setParams]);
  const setFilter = useCallback((f: Partial<NodeFilter>) => {
    const patch: Record<string, string | null> = {};
    if ('q' in f) patch.q = f.q || null;
    if ('group' in f) patch.grp = f.group || null;
    if ('status' in f) patch.status = f.status || null;
    if ('team' in f) patch.team = f.team || null;
    if ('type' in f) patch.atype = f.type || null;
    if ('tag' in f) patch.tag = f.tag || null;
    setParams(patch);
  }, [setParams]);

  const assetsBySource = useMemo(() => {
    const m = new Map<string, number>();
    for (const n of nodeList) {
      const ids = new Set([n.self?.connection_id, ...Object.values(n.devices).map((d) => d.connection_id)].filter(Boolean) as string[]);
      ids.forEach((id) => m.set(id, (m.get(id) ?? 0) + 1));
    }
    return m;
  }, [nodeList]);

  const onDiagnosis = useCallback(async (s: Source, a: DiagnosisAction) => {
    if (a === 'problems' || a === 'messages') { setParams({ tab: 'messages', source: s.id, mview: a === 'problems' ? 'problems' : null }); return; }
    if (a === 'turn_on') {
      const res = await apiFetch(`/api/telemetry/connections/${s.id}`, { method: 'PATCH', body: JSON.stringify({ enabled: true }), throwOnError: false });
      if (res.error) toastError(`Could not turn on ${s.name}`, explainTelemetryError({ status: res.errorDetail?.code, code: res.errorDetail?.error_code, message: res.error }, 'toggle'));
      else toastSuccess(`${s.name} turned on`, 'Abenix starts reading it within 5 seconds.');
      void conns.mutate();
      return;
    }
    setParams({ tab: 'sources', focus: s.id, faction: a, node: null, device: null });
  }, [setParams, conns]);

  const onFirst = useCallback(async (transport: string) => {
    if (transport === 'guide') { setGuideOpen(true); return; }
    if (transport !== 'testbed') { openSources(transport); return; }
    const res = await apiFetch<unknown>('/api/telemetry/testbed/connect', { method: 'POST', throwOnError: false });
    const made = Array.isArray(res.data) ? res.data.length : null;
    if (res.error) toastError('Could not connect the testbed', explainTelemetryError({ status: res.errorDetail?.code, code: res.errorDetail?.error_code, message: res.error }, 'save'));
    else toastSuccess(made ? `${made} testbed sources ready` : 'Testbed sources ready', 'Their assets show up here within a few seconds. Sources lists them.');
    void conns.mutate();
    void roster.mutate();
  }, [openSources, conns, roster]);

  // an empty page opens the guide once per visit, for the people who can act on it
  const autoGuide = useRef(false);
  useEffect(() => {
    if (autoGuide.current || !canManage || !sources || sources.length > 0) return;
    autoGuide.current = true;
    let seen = false;
    try { seen = sessionStorage.getItem('telemetry.guide.auto') === '1'; sessionStorage.setItem('telemetry.guide.auto', '1'); } catch { /* storage blocked */ }
    if (!seen) setGuideOpen(true);
  }, [canManage, sources]);

  if (permsLoading && !perms) {
    return <div className="mx-auto max-w-7xl"><div className="h-40 animate-pulse rounded-xl bg-slate-800/40" /></div>;
  }
  if (perms && !canView) {
    return (
      <NoAccess
        testId="tel-no-access"
        title="Telemetry"
        purpose={PURPOSE}
        icon={RadioTower}
        need={{ capability: 'telemetry.view', label: 'View machine telemetry' }}
        role={perms.role}
        instead={{ text: 'Alerts lists anything that went wrong, including assets that went offline.', href: '/alerts', label: 'Open Alerts' }}
      />
    );
  }

  const noSources = !!sources && sources.length === 0;
  const primary = canManage
    ? noSources || tab === 'sources'
      ? { label: 'Add a source', icon: Plus, onClick: () => openSources(true), testId: 'tel-primary' }
      : { label: 'Sources', icon: Plug, onClick: () => openSources(false), testId: 'tel-primary' }
    : undefined;

  return (
    <div className="mx-auto max-w-7xl space-y-4" data-testid="tel-page">
      <PageHeader
        title="Telemetry"
        purpose={PURPOSE}
        icon={RadioTower}
        storageKey="telemetry"
        docSlug="08-howto/17-telemetry"
        compact={focus}
        meta={<LiveBadge feed={feed} />}
        primaryAction={primary}
        secondaryAction={{ label: 'Get started', icon: Compass, onClick: () => setGuideOpen(true), testId: 'tel-get-started' }}
        steps={[
          { title: 'Source', body: 'Where the data comes from: a broker, a stream, an industrial protocol, or a system posting to Abenix over HTTP. An admin adds it under Sources and tests it.' },
          { title: 'Decoder', body: 'Turns each raw message into values: JSON, CSV, Avro, Protobuf, Sparkplug B, J1939 CAN frames and more.' },
          { title: 'Mapping', body: 'Says which asset and part each message belongs to, which signals to keep, their units and their time. A live preview shows the result before anything is stored.' },
          { title: 'Stored and live', body: 'Latest values stream here up to 10 times a second and history is kept for charts. Anything that fails waits under Messages, Problems, with the reason.' },
        ]}
        howItWorks={
          <p className="text-xs text-slate-400">
            Names follow Group, Asset and Part. On Sparkplug B sources these are the group, edge node and device. Devices that stop reporting can be forgotten, which frees their place in the workspace limit and keeps their history. Abenix also forgets devices offline for a set number of days on its own, 30 unless an admin changes it{perms?.is_admin ? <> under <a href="/admin/llm-settings" className="text-cyan-300 hover:underline">platform settings</a></> : null}. People with Send machine commands can write a value back to a signal that accepts writes, with a reason that goes on the audit log. An asset going offline raises an alert.
          </p>
        }
      />

      {!canManage && !canCommand && tab !== 'sources' && (
        <ViewOnlyBanner testId="tel-view-only">
          You can watch the streams shared with you or your team, live. Sending commands needs Send machine commands, and changing sources needs Manage telemetry brokers. An admin can give you either under Admin, Permissions.
        </ViewOnlyBanner>
      )}

      {!focus && <QuotaBanner health={health} isAdmin={!!perms?.is_admin} canManage={canManage} refreshKey={forgetTick} onForget={() => setBulkForget({ offline_for_s: 3600, autoPreview: true })} />}
      {(loaded || health) && tab === 'assets' && !focus && <IngestHealth health={health} totals={totals} healthMissing={healthMissing} />}

      <div className="scrollbar-none flex gap-1 overflow-x-auto border-b border-slate-800" role="tablist" aria-label="Telemetry">
        {TABS.map((t) => {
          const Icon = t.icon;
          const on = tab === t.id;
          const problems = (sources || []).reduce((a, s) => a + (s.dlq_count ?? 0), 0);
          const broken = (sources || []).filter((c) => c.enabled && c.status === 'error').length;
          const badge = t.id === 'assets' ? totals.total - totals.online : t.id === 'messages' ? problems : broken;
          const why = t.id === 'assets' ? `${badge} offline` : t.id === 'messages' ? `${badge} messages could not be stored` : `${badge} cannot connect`;
          return (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={on}
              aria-controls={`tel-panel-${t.id}`}
              onClick={() => setParams({ tab: t.id === 'assets' ? null : t.id, add: null, ...(t.id !== 'assets' ? { device: null, metric: null } : {}) })}
              className={`-mb-px inline-flex shrink-0 items-center gap-2 border-b-2 px-4 py-2.5 text-sm transition ${on ? 'border-cyan-400 text-white' : 'border-transparent text-slate-400 hover:text-white'}`}
              data-testid={`tel-tab-${t.id}`}
            >
              <Icon className="h-4 w-4" /> {t.label}
              {badge > 0 && <span className={`rounded-full px-1.5 text-[11px] ${t.id === 'messages' ? 'bg-amber-500/20 text-amber-200' : 'bg-rose-500/20 text-rose-200'}`} title={why}>{badge}</span>}
            </button>
          );
        })}
      </div>

      <div id={`tel-panel-${tab}`} role="tabpanel" className="min-w-0">
        {tab === 'assets' && (
          selected || nodeParam ? (
            selected ? (
              <DeviceDetail
                group={selected.group}
                node={selected.node}
                device={deviceParam}
                entry={selectedEntry}
                loaded={loaded}
                canCommand={canCommand}
                now={now}
                focus={focus}
                setFocus={(on) => setParams({ focus: on ? 'charts' : null })}
                canManage={canManage}
                onForgotten={() => { void roster.mutate(); void healthRes.mutate(); setForgetTick((n) => n + 1); router.push(`/telemetry${lastListQs.current ? `?${lastListQs.current}` : ''}`); }}
                signals={parseSignals(params.get('signals') ?? metric)}
                setSignals={(list) => setParams({ signals: list.join(',') || null, metric: null })}
                rangeId={rangeId}
                setRange={(r) => setParams({ range: r === '5m' ? null : r })}
                onOpenFrames={() => setParams({ tab: 'messages', mview: 'frames', signals: null, source: selectedEntry?.self?.connection_id ?? Object.values(selectedEntry?.devices ?? {})[0]?.connection_id ?? null, device: null, metric: null })}
                backHref={`/telemetry${lastListQs.current ? `?${lastListQs.current}` : ''}`}
              />
            ) : rosterErr ? (
              <p className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-100" role="alert">{rosterErr}</p>
            ) : !loaded ? (
              <div className="h-60 animate-pulse rounded-xl bg-slate-800/40" data-testid="tel-device-resolving" />
            ) : (
              <DeviceDetail group="" node={nodeParam} device={deviceParam} entry={undefined} loaded canCommand={false} now={now} signals={[]} setSignals={() => {}} rangeId={rangeId} setRange={() => {}} onOpenFrames={() => {}} backHref="/telemetry" missing />
            )
          ) : (
            <>
            {nodeList.length > 0 && <div className="mb-3"><WhatNext /></div>}
            {sources && sources.length > 0 && (
              <div className="mb-3">
                <SourceDiagnoses sources={sources} canManage={canManage} assetsBySource={(id) => assetsBySource.get(id) ?? (nodeList.length && !assetsBySource.size ? 1 : 0)} onAction={onDiagnosis} />
              </div>
            )}
            <DevicesTab
              nodes={nodes}
              loaded={loaded}
              error={rosterErr}
              onRetry={() => roster.mutate()}
              filter={filter}
              setFilter={setFilter}
              view={view}
              setView={(v) => setParams({ view: v === 'cards' ? null : v })}
              onVisible={onVisible}
              connections={sources}
              canManage={canManage}
              openConnections={(add) => openSources(add)}
              onFirst={onFirst}
              testbed={testbed}
              unregistered={typeof assetsRes.data?.meta?.unregistered === 'number' ? (assetsRes.data.meta.unregistered as number) : undefined}
              onBulkForget={() => setBulkForget({ offline_for_s: 3600 })}
              now={now}
              total={total}
              loadedRows={Array.isArray(roster.data?.data) ? (roster.data!.data as unknown[]).length : 0}
            />
            </>
          )
        )}
        <GetStarted open={guideOpen} onClose={() => setGuideOpen(false)} canManage={canManage} transports={transports} onSource={(s) => setWizard(s)} />
        {bulkForget && (
          <BulkForgetDialog
            groups={Array.from(new Set(nodeList.map((n) => n.group))).sort()}
            sources={(sources || []).map((s) => ({ id: s.id, name: s.name }))}
            initial={bulkForget}
            onClose={() => setBulkForget(null)}
            onDone={() => { void roster.mutate(); void healthRes.mutate(); setForgetTick((n) => n + 1); }}
          />
        )}
        {wizard && (
          <SourceWizard start={wizard} existingNames={(sources || []).map((s) => s.name)} teams={teams} onClose={() => setWizard(null)} onSaved={() => { void conns.mutate(); void roster.mutate(); }} />
        )}
        {tab === 'messages' && (
          <MessagesTab
            sources={sources || []}
            sourceId={params.get('source') || ''}
            setSource={(id) => setParams({ source: id })}
            view={msgView}
            setView={(v) => setParams({ mview: v === 'recent' ? null : v, ...(rawTab === 'frames' ? { tab: 'messages' } : {}) })}
            nodes={nodeList}
            group={selected?.group ?? nodeList[0]?.group ?? ''}
            node={selected?.node ?? nodeList[0]?.node ?? ''}
            setNode={(g, n) => setParams({ group: g, node: n })}
            canManage={canManage}
            openSources={() => openSources(canManage)}
            active
            reloadSources={() => { void conns.mutate(); }}
          />
        )}
        {tab === 'sources' && (
          <SourcesTab
            rows={sources}
            loading={conns.isLoading}
            error={connErr}
            reload={() => { void conns.mutate(); }}
            canManage={canManage}
            addRequest={params.get('add')}
            onAddHandled={() => setParams({ add: null })}
            openMessages={(id, problems) => setParams({ tab: 'messages', source: id, mview: problems ? 'problems' : null })}
            now={now}
            focus={params.get('focus') ? { id: params.get('focus')!, action: (params.get('faction') as 'edit' | 'mapping' | 'test' | 'endpoint') || 'edit' } : null}
            onFocusHandled={() => setParams({ focus: null, faction: null })}
            openGuide={() => setGuideOpen(true)}
          />
        )}
      </div>
    </div>
  );
}

export default function TelemetryRoute() {
  return (
    <Suspense fallback={<div className="mx-auto max-w-7xl"><div className="h-40 animate-pulse rounded-xl bg-slate-800/40" /></div>}>
      <TelemetryPage />
    </Suspense>
  );
}
