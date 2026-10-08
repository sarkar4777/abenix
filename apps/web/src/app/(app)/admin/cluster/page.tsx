'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import {
  Activity, AlertOctagon, AlertTriangle, BarChart3, CheckCircle2, Cpu, Database, ExternalLink, HardDrive,
  HelpCircle, Info, Layers, Pause, Play, RefreshCw, Search, Server, X,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { usePageTitle } from '@/hooks/usePageTitle';
import NodeCard from '@/components/cluster/NodeCard';
import ServiceRow from '@/components/cluster/ServiceRow';
import PodDrawer from '@/components/cluster/PodDrawer';
import WarningsTimeline from '@/components/cluster/WarningsTimeline';
import AccessPanel from '@/components/cluster/AccessPanel';
import PageHeader from '@/components/layout/PageHeader';
import { AccessGate } from '@/components/layout/NoAccess';
import {
  GROUPS, VERDICT_STYLE, agoText, filterWorkloads, fmtBytes, fmtCores, groupSummary, groupWorkloads, isProblem,
  type Group, type Overview, type Reason, type StatusFilter,
} from '@/lib/cluster';

const GRAFANA_ENV = (process.env.NEXT_PUBLIC_GRAFANA_URL || '').replace(/\/$/, '');
const REFRESH_MS = 15_000;
const PAUSE_KEY = 'cluster-view-paused';

interface DbInfo { bytes?: number | null; top_tables?: { name: string; bytes: number }[]; error?: string }

function readPaused(): boolean {
  try { return localStorage.getItem(PAUSE_KEY) === '1'; } catch { return false; }
}
function writePaused(v: boolean) {
  try { localStorage.setItem(PAUSE_KEY, v ? '1' : '0'); } catch { /* storage blocked */ }
}

function Tile({ label, value, sub, testid, tone }: { label: string; value: React.ReactNode; sub?: React.ReactNode; testid?: string; tone?: 'warn' | 'bad' }) {
  return (
    <div className="rounded-lg bg-black/20 border border-white/5 px-3 py-2.5 min-w-0">
      <div className="text-[10px] uppercase tracking-wider text-slate-400">{label}</div>
      <div className={`text-xl font-bold tabular-nums truncate ${tone === 'bad' ? 'text-red-300' : tone === 'warn' ? 'text-amber-300' : 'text-white'}`} data-testid={testid}>{value}</div>
      {sub && <div className="text-[11px] text-slate-400 truncate">{sub}</div>}
    </div>
  );
}

function ReasonIcon({ level }: { level: Reason['level'] }) {
  if (level === 'critical') return <AlertOctagon className="w-3.5 h-3.5 text-red-300 shrink-0 mt-0.5" />;
  if (level === 'warning') return <AlertTriangle className="w-3.5 h-3.5 text-amber-300 shrink-0 mt-0.5" />;
  if (level === 'ok') return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-300 shrink-0 mt-0.5" />;
  return <Info className="w-3.5 h-3.5 text-slate-400 shrink-0 mt-0.5" />;
}

function LoadingState() {
  return (
    <div data-testid="cluster-loading" aria-busy="true">
      <div className="h-40 rounded-2xl bg-slate-800/40 animate-pulse mb-6" />
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 mb-6">
        {[0, 1, 2].map((i) => <div key={i} className="h-48 rounded-xl bg-slate-800/40 animate-pulse" />)}
      </div>
      {[0, 1, 2, 3].map((i) => <div key={i} className="h-16 rounded-xl bg-slate-800/40 animate-pulse mb-2" />)}
      <p className="text-xs text-slate-500 mt-3">Reading nodes, services and events from the cluster.</p>
    </div>
  );
}

function OutsideState({ reason }: { reason?: string }) {
  return (
    <div className="rounded-2xl border border-slate-700/60 bg-slate-900/40 p-6 md:p-8" data-testid="cluster-outside">
      <div className="w-12 h-12 rounded-2xl bg-slate-800 flex items-center justify-center mb-4">
        <HelpCircle className="w-6 h-6 text-slate-400" />
      </div>
      <h2 className="text-lg font-semibold text-white">This platform is not running in Kubernetes</h2>
      <p className="text-sm text-slate-400 mt-2 max-w-2xl">
        The API could not find a cluster to read. That is expected under docker-compose or when running the API on a laptop
        without a kubeconfig. There are no nodes or pods to show, but everything else in the platform works the same.
      </p>
      <ul className="text-sm text-slate-400 mt-4 space-y-2 list-disc pl-5 max-w-2xl">
        <li>Under docker-compose, <code className="px-1 rounded bg-slate-800 text-slate-300">docker compose ps</code> shows the containers and their health.</li>
        <li>To see this page filled in, deploy to minikube with <code className="px-1 rounded bg-slate-800 text-slate-300">scripts/deploy.sh</code> or to AKS with <code className="px-1 rounded bg-slate-800 text-slate-300">scripts/deploy-azure.sh</code>.</li>
        <li>A local API can also read a cluster through your kubeconfig, if one is set up.</li>
      </ul>
      {reason && <p className="text-[11px] text-slate-600 mt-4 break-words">Detail: {reason}</p>}
    </div>
  );
}

function ClusterPage() {
  usePageTitle('Cluster Health');
  const [data, setData] = useState<Overview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchedAt, setFetchedAt] = useState<number | null>(null);
  const [paused, setPaused] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [q, setQ] = useState('');
  const [group, setGroup] = useState<Group | 'all'>('all');
  const [status, setStatus] = useState<StatusFilter>('all');
  const [openSvc, setOpenSvc] = useState<Set<string>>(new Set());
  const [pod, setPod] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [db, setDb] = useState<DbInfo | null>(null);
  const inflight = useRef(false);

  const load = useCallback(async () => {
    if (inflight.current) return;
    inflight.current = true;
    setLoading(true);
    const { data: payload, error } = await apiFetch<Overview>('/api/admin/cluster/overview', { silent: true });
    if (error || !payload) setErr(error || 'The cluster overview came back empty.');
    else {
      setData(payload);
      setErr(null);
      setFetchedAt(Date.now() - (payload.cache_age_seconds || 0) * 1000);
    }
    setLoading(false);
    inflight.current = false;
  }, []);

  useEffect(() => {
    setPaused(readPaused());
    try {
      const p = new URLSearchParams(window.location.search).get('pod');
      if (p) setPod(p);
    } catch { /* no window */ }
    void load();
    apiFetch<DbInfo>('/api/admin/cluster/database', { silent: true }).then(({ data: d, error }) => setDb(d || { error: error || undefined }));
  }, [load]);

  useEffect(() => {
    if (paused) return;
    const id = setInterval(() => {
      if (typeof document !== 'undefined' && document.hidden) return;
      void load();
    }, REFRESH_MS);
    return () => clearInterval(id);
  }, [paused, load]);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const openPod = useCallback((name: string | null) => {
    setPod(name);
    try {
      const url = new URL(window.location.href);
      if (name) url.searchParams.set('pod', name);
      else url.searchParams.delete('pod');
      window.history.replaceState(null, '', url.toString());
    } catch { /* ignore */ }
  }, []);

  const togglePause = () => {
    setPaused((p) => { writePaused(!p); return !p; });
  };

  const focus = useCallback((kind: string | undefined, target: string | null | undefined) => {
    if (!target) return;
    if (kind === 'workload') {
      setGroup('all');
      setStatus('all');
      setQ('');
      setOpenSvc((s) => new Set(s).add(target));
    }
    setFlash(target);
    setTimeout(() => {
      const el = document.getElementById(kind === 'node' ? `node-${target}` : `svc-${target}`);
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 50);
    setTimeout(() => setFlash(null), 2500);
  }, []);

  const workloads = useMemo(() => data?.workloads ?? [], [data]);
  const filtered = useMemo(() => filterWorkloads(workloads, q, group, status), [workloads, q, group, status]);
  const grouped = useMemo(() => groupWorkloads(filtered), [filtered]);
  const problemCount = useMemo(() => workloads.filter(isProblem).length, [workloads]);
  const grafana = (GRAFANA_ENV || data?.grafana_url || '').replace(/\/$/, '');
  const outside = data?.source === 'outside';
  const accessByKey = Object.fromEntries((data?.access ?? []).map((a) => [a.key, a]));
  const nodesHidden = accessByKey.nodes && !accessByKey.nodes.ok ? accessByKey.nodes : null;
  const eventsHidden = accessByKey.events && !accessByKey.events.ok ? accessByKey.events.fix || 'Events could not be read.' : null;
  const metricsAvailable = !!accessByKey.node_metrics?.ok;
  const t = data?.totals ?? {};
  const v = data?.verdict;
  const vs = VERDICT_STYLE[v?.state ?? 'unknown'];
  const updatedAgo = fetchedAt ? (now - fetchedAt) / 1000 : null;
  const stale = updatedAgo != null && updatedAgo > 90;

  const toggleSvc = (name: string) => setOpenSvc((s) => {
    const n = new Set(s);
    if (n.has(name)) n.delete(name); else n.add(name);
    return n;
  });

  return (
    <div className="max-w-7xl mx-auto px-4 py-5 md:p-6">
      <PageHeader
        className="mb-5"
        title="Cluster Health"
        purpose="Check whether the cluster running the platform is healthy, with its nodes, services and warnings read live from Kubernetes. For admins."
        icon={Server}
        storageKey="admin-cluster"
        docSlug="06-deployment/04-observability"
        meta={data?.namespace ? (
          <code className="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-300">{data.namespace}</code>
        ) : null}
        primaryAction={{
          label: 'Refresh',
          icon: RefreshCw,
          onClick: () => void load(),
          busy: loading,
          title: loading ? 'Already refreshing' : 'Refresh now',
          testId: 'cluster-refresh',
        }}
        extraActions={
          <div className="flex flex-wrap items-center gap-2">
            <span className={`text-xs ${stale ? 'text-amber-300' : 'text-slate-500'}`} data-testid="cluster-updated" aria-live="polite">
              {fetchedAt ? `Updated ${agoText(updatedAgo)}` : loading ? 'Loading' : 'Not loaded'}
              {paused ? ' · paused' : ''}
            </span>
            <button
              type="button"
              onClick={togglePause}
              className="inline-flex min-h-[40px] items-center gap-1.5 text-xs px-3 py-2 rounded-lg border border-slate-700/60 bg-slate-900/40 text-slate-300 hover:bg-slate-800/60"
              data-testid="cluster-pause"
              aria-pressed={paused}
              title={paused ? 'Resume refreshing every 15 seconds' : 'Stop refreshing every 15 seconds'}
            >
              {paused ? <Play className="w-3.5 h-3.5" /> : <Pause className="w-3.5 h-3.5" />} {paused ? 'Resume' : 'Pause'}
            </button>
          </div>
        }
        steps={[
          'The banner at the top gives one verdict for the whole cluster and lists what is wrong, if anything.',
          'Node cards show how busy each machine is. Services are grouped by role and can be filtered by name or status.',
          'Click a pod to see its details and recent logs. The page refreshes every 15 seconds unless you pause it.',
          'If a section is hidden, the access panel says which permission the platform is missing and how to grant it.',
        ]}
      />

      <nav className="flex flex-wrap gap-2 mb-5 text-xs" aria-label="Related pages">
        <Link href="/admin/scaling" className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-700/60 bg-slate-900/40 text-slate-300 hover:bg-slate-800/60" data-testid="cluster-link-scaling">
          <Layers className="w-3.5 h-3.5" /> Scaling
        </Link>
        <Link href="/executions/live" className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-700/60 bg-slate-900/40 text-slate-300 hover:bg-slate-800/60" data-testid="cluster-link-live">
          <Activity className="w-3.5 h-3.5" /> Live Debug
        </Link>
        {grafana ? (
          <a href={`${grafana}/d/abenix-overview`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-cyan-500/40 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/20" data-testid="cluster-link-grafana">
            <BarChart3 className="w-3.5 h-3.5" /> Grafana <ExternalLink className="w-3 h-3" />
          </a>
        ) : (
          <span
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-800 text-slate-500 cursor-not-allowed"
            title="Grafana's address is not configured. Set GRAFANA_URL on the API or NEXT_PUBLIC_GRAFANA_URL on the web app."
            data-testid="cluster-link-grafana-disabled"
          >
            <BarChart3 className="w-3.5 h-3.5" /> Grafana address not set
          </span>
        )}
      </nav>

      {err && data && (
        <div className="mb-4 p-3 rounded-xl border border-amber-500/40 bg-amber-500/10 text-amber-200 text-xs flex items-start gap-2" data-testid="cluster-refresh-error">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>The last refresh failed ({err}). Showing what was read {agoText(updatedAgo)}.</span>
        </div>
      )}

      {!data && err && (
        <div className="p-6 rounded-2xl border border-red-500/40 bg-red-500/10 text-red-200" data-testid="cluster-error">
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 mt-0.5 shrink-0" />
            <div>
              <div className="font-semibold">Could not load the cluster view</div>
              <div className="text-sm opacity-80 mt-1 break-words">{err}</div>
              <button type="button" onClick={() => void load()} className="mt-3 text-xs px-3 py-2 rounded-lg border border-red-400/40 hover:bg-red-500/20">Try again</button>
            </div>
          </div>
        </div>
      )}

      {!data && !err && <LoadingState />}

      {data && outside && <OutsideState reason={data.outside_reason} />}

      {data && !outside && v && (
        <>
          <section className={`rounded-2xl border ${vs.ring} ${vs.bg} p-4 md:p-5 mb-6`} data-testid="cluster-verdict" data-state={v.state}>
            <div className="flex flex-col xl:flex-row gap-5">
              <div className="xl:w-[42%] min-w-0">
                <div className="flex items-center gap-2.5">
                  <span className="relative flex w-3 h-3">
                    {v.state !== 'healthy' && <span className={`absolute inline-flex h-full w-full rounded-full ${vs.dot} opacity-60 animate-ping`} />}
                    <span className={`relative inline-flex w-3 h-3 rounded-full ${vs.dot}`} />
                  </span>
                  <h2 className={`text-xl font-bold ${vs.text}`} data-testid="cluster-verdict-label">{v.label}</h2>
                </div>
                <ul className="mt-3 space-y-1.5">
                  {v.reasons.slice(0, 6).map((r, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm" data-testid="cluster-verdict-reason" data-level={r.level}>
                      <ReasonIcon level={r.level} />
                      {r.target && (r.kind === 'workload' || r.kind === 'node') ? (
                        <button type="button" onClick={() => focus(r.kind, r.target)} className="text-left text-slate-200 hover:underline break-words">{r.text}</button>
                      ) : (
                        <span className="text-slate-200 break-words">{r.text}</span>
                      )}
                    </li>
                  ))}
                  {v.reasons.length > 6 && <li className="text-xs text-slate-400 pl-5">and {v.reasons.length - 6} more below</li>}
                </ul>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 flex-1 content-start">
                <Tile
                  label="Nodes"
                  value={nodesHidden ? '—' : <span data-testid="cluster-node-count">{t.nodes ?? 0}</span>}
                  sub={nodesHidden ? 'Hidden, see below' : `${t.nodes_ready ?? 0} ready`}
                  tone={!nodesHidden && (t.nodes_ready ?? 0) < (t.nodes ?? 0) ? 'bad' : undefined}
                />
                <Tile
                  label="CPU"
                  value={nodesHidden ? '—' : <span data-testid="cluster-core-count" data-cores={t.cpu_cores ?? 0}>{fmtCores(t.cpu_cores ?? 0)} cores</span>}
                  sub={t.cpu_used_cores != null ? `${fmtCores(t.cpu_used_cores)} in use` : nodesHidden ? 'Hidden' : 'Use needs metrics-server'}
                />
                <Tile
                  label="Memory"
                  value={nodesHidden ? '—' : fmtBytes(t.mem_bytes ?? 0)}
                  sub={t.mem_used_bytes != null ? `${fmtBytes(t.mem_used_bytes)} in use` : nodesHidden ? 'Hidden' : 'Use needs metrics-server'}
                />
                <Tile
                  label="Services"
                  value={<span data-testid="cluster-services-healthy">{t.services_healthy ?? 0}/{t.services ?? 0}</span>}
                  sub={problemCount ? `${problemCount} need attention` : 'healthy or idle'}
                  tone={problemCount ? 'warn' : undefined}
                />
                <Tile label="Pods" value={t.pods ?? 0} sub={`${t.pod_phases?.Running ?? 0} running`} />
                <Tile
                  label="Warnings"
                  value={eventsHidden ? '—' : t.warnings_recent ?? 0}
                  sub={eventsHidden ? 'Hidden' : 'last 15 minutes'}
                  tone={(t.warnings_recent ?? 0) > 20 ? 'warn' : undefined}
                />
              </div>
            </div>
          </section>

          <AccessPanel access={data.access} rbacValue={data.rbac_value} rbacSetting={data.rbac_setting} />

          <section className="mb-8" aria-labelledby="nodes-h">
            <h2 id="nodes-h" className="text-sm font-semibold text-slate-200 mb-3 flex items-center gap-2">
              <Cpu className="w-4 h-4 text-cyan-300" /> Nodes
              {!nodesHidden && <span className="text-xs font-normal text-slate-500">{data.nodes.length}</span>}
            </h2>
            {nodesHidden ? (
              <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4 text-sm text-slate-400" data-testid="cluster-nodes-hidden">
                Node details are hidden. {nodesHidden.fix}
              </div>
            ) : data.nodes.length ? (
              <div className={`grid grid-cols-1 gap-4 ${data.nodes.length === 2 ? 'md:grid-cols-2' : data.nodes.length > 2 ? 'md:grid-cols-2 xl:grid-cols-3' : ''}`}>
                {data.nodes.map((n) => (
                  <NodeCard key={n.name} node={n} metricsAvailable={metricsAvailable} highlight={flash === n.name} wide={data.nodes.length === 1} />
                ))}
              </div>
            ) : (
              <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4 text-sm text-slate-400" data-testid="cluster-nodes-empty">
                The cluster reported no nodes.
              </div>
            )}
          </section>

          <section className="mb-8" aria-labelledby="svc-h">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 mb-3">
              <h2 id="svc-h" className="text-sm font-semibold text-slate-200 flex items-center gap-2">
                <Layers className="w-4 h-4 text-cyan-300" /> Services
                <span className="text-xs font-normal text-slate-500">{filtered.length === workloads.length ? workloads.length : `${filtered.length} of ${workloads.length}`}</span>
              </h2>
              <div className="relative w-full md:w-72">
                <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="Search services, pods or images"
                  className="w-full text-sm bg-slate-900/60 border border-slate-700/60 rounded-lg pl-8 pr-8 py-2 text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-cyan-500/50"
                  aria-label="Search services"
                  data-testid="cluster-search"
                />
                {q && (
                  <button type="button" onClick={() => setQ('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300" aria-label="Clear search">
                    <X className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>
            <div className="flex flex-wrap gap-2 mb-3">
              {(['all', ...GROUPS] as const).map((g) => {
                const count = g === 'all' ? workloads.length : workloads.filter((w) => w.group === g).length;
                return (
                  <button
                    key={g}
                    type="button"
                    onClick={() => setGroup(g)}
                    disabled={g !== 'all' && count === 0}
                    title={g !== 'all' && count === 0 ? `No ${g.toLowerCase()} in this namespace` : undefined}
                    className={`text-xs px-3 py-1.5 rounded-full border disabled:opacity-40 disabled:cursor-not-allowed ${group === g ? 'border-cyan-500/50 bg-cyan-500/15 text-cyan-200' : 'border-slate-700/60 text-slate-400 hover:text-slate-200'}`}
                    data-testid={`cluster-group-${g === 'all' ? 'all' : g.toLowerCase().replace(/\s+/g, '-')}`}
                    aria-pressed={group === g}
                  >
                    {g === 'all' ? 'All' : g} <span className="opacity-60">{count}</span>
                  </button>
                );
              })}
              <span className="hidden sm:block w-px bg-slate-800 mx-1" />
              {([['all', 'Any status'], ['problems', 'Needs attention'], ['idle', 'Idle']] as const).map(([k, label]) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => setStatus(k)}
                  className={`text-xs px-3 py-1.5 rounded-full border ${status === k ? 'border-cyan-500/50 bg-cyan-500/15 text-cyan-200' : 'border-slate-700/60 text-slate-400 hover:text-slate-200'}`}
                  data-testid={`cluster-status-${k}`}
                  aria-pressed={status === k}
                >
                  {label}{k === 'problems' && problemCount ? ` ${problemCount}` : ''}
                </button>
              ))}
            </div>

            {!workloads.length ? (
              <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-6 text-center text-sm text-slate-400" data-testid="cluster-services-empty">
                {accessByKey.deployments && !accessByKey.deployments.ok
                  ? `Services are hidden. ${accessByKey.deployments.fix}`
                  : 'No deployments or stateful sets in this namespace yet.'}
              </div>
            ) : !filtered.length ? (
              <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-6 text-center" data-testid="cluster-services-nomatch">
                <div className="text-sm text-slate-300">
                  {status === 'problems' && !q && group === 'all' ? 'Nothing needs attention right now.' : 'No services match these filters.'}
                </div>
                <button type="button" onClick={() => { setQ(''); setGroup('all'); setStatus('all'); }} className="mt-2 text-xs text-cyan-300 hover:underline">Clear filters</button>
              </div>
            ) : (
              <div className="space-y-6">
                {grouped.map(({ group: g, items }) => {
                  const sum = groupSummary(items);
                  return (
                    <div key={g} data-testid="service-group" data-group={g}>
                      <div className="flex items-baseline justify-between gap-2 mb-2">
                        <h3 className="text-xs uppercase tracking-wider text-slate-400">{g}</h3>
                        <span className={`text-[11px] ${sum.tone === 'bad' ? 'text-red-300' : sum.tone === 'warn' ? 'text-amber-300' : 'text-slate-500'}`}>{sum.text}</span>
                      </div>
                      <div className="space-y-2">
                        {items.map((w) => (
                          <ServiceRow
                            key={w.name}
                            w={w}
                            open={openSvc.has(w.name)}
                            onToggle={() => toggleSvc(w.name)}
                            onOpenPod={(name) => openPod(name)}
                            highlight={flash === w.name}
                          />
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          <section className="mb-8" aria-labelledby="warn-h">
            <h2 id="warn-h" className="text-sm font-semibold text-slate-200 mb-3 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-300" /> Recent warnings
              <span className="text-xs font-normal text-slate-500">last hour</span>
            </h2>
            <WarningsTimeline events={data.events} eventsHidden={eventsHidden} onWorkload={(w) => focus('workload', w)} />
          </section>

          <section className="mb-4 grid grid-cols-1 lg:grid-cols-2 gap-4" aria-label="Storage">
            <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4 min-w-0">
              <h2 className="text-sm font-semibold text-slate-200 mb-3 flex items-center gap-2"><HardDrive className="w-4 h-4 text-cyan-300" /> Volumes</h2>
              {data.pvcs.length ? (
                <ul className="divide-y divide-slate-800/70 text-xs">
                  {data.pvcs.map((d) => (
                    <li key={d.pvc} className="py-2 flex items-center justify-between gap-3">
                      <span className="text-slate-300 break-all">{d.pvc}</span>
                      <span className="text-slate-500 shrink-0">{fmtBytes(d.capacity_bytes || d.requested_bytes)} · <span className={d.status === 'Bound' ? 'text-emerald-300' : 'text-amber-300'}>{d.status || '—'}</span></span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-slate-500">
                  {accessByKey.pvcs && !accessByKey.pvcs.ok ? accessByKey.pvcs.fix : 'No volume claims in this namespace.'}
                </p>
              )}
            </div>
            <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4 min-w-0" data-testid="cluster-database">
              <h2 className="text-sm font-semibold text-slate-200 mb-3 flex items-center gap-2">
                <Database className="w-4 h-4 text-cyan-300" /> Database
                {db?.bytes != null && <span className="text-xs font-normal text-slate-400">{fmtBytes(db.bytes)}</span>}
              </h2>
              {!db ? (
                <div className="space-y-2">{[0, 1, 2].map((i) => <div key={i} className="h-4 rounded bg-slate-800/60 animate-pulse" />)}</div>
              ) : db.error ? (
                <p className="text-xs text-amber-300">{db.error}</p>
              ) : db.top_tables?.length ? (
                <ul className="divide-y divide-slate-800/70 text-xs">
                  {db.top_tables.map((tb) => (
                    <li key={tb.name} className="py-2 flex items-center justify-between gap-3">
                      <span className="text-slate-300 break-all">{tb.name}</span>
                      <span className="text-slate-500 shrink-0">{fmtBytes(tb.bytes)}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-slate-500">No tables yet.</p>
              )}
            </div>
          </section>

          <p className="text-[11px] text-slate-600">
            Read {data.source === 'kubeconfig' ? 'through a kubeconfig' : 'from inside the cluster'}. The API caches this view for {data.ttl_seconds} seconds so many admins cost one read.
          </p>
        </>
      )}

      <PodDrawer pod={pod} onClose={() => openPod(null)} />
    </div>
  );
}

export default function ClusterPageGated() {
  return (
    <AccessGate
      title="Cluster Health"
      purpose="Check whether the cluster running the platform is healthy, with its nodes, services and warnings read live from Kubernetes. For admins."
      icon={Server}
      need={{ admin: true }}
      instead={{ text: 'You can follow your own runs and how long they take on Executions.', href: '/executions', label: 'Open Executions' }}
    >
      <ClusterPage />
    </AccessGate>
  );
}
