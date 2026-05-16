'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Gauge, Loader2, RefreshCw, Search, Pause, Play,
  AlertTriangle, TrendingUp, X, CheckCircle2, Edit3,
  DollarSign, Users, Zap, Server,
} from 'lucide-react';

// Same resolution as apps/web/src/lib/api-client.ts — fall back to
// localhost:8000 in dev, which the Next.js build bakes in at compile
// time from NEXT_PUBLIC_API_URL when set.
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
function getToken() {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('access_token') || localStorage.getItem('token');
}

type Pool = {
  key: string;
  label: string;
  description: string;
  default_min_replicas: number;
  default_max_replicas: number;
  default_concurrency: number;
  node_affinity: string | null;
  agent_count: number;
  executions_24h: number;
};

type AgentScale = {
  id: string;
  name: string;
  slug: string;
  category: string | null;
  status: string;
  agent_type: string;
  runtime_pool: string;
  dedicated_mode?: boolean;
  effective_pool?: string;
  min_replicas: number;
  max_replicas: number;
  concurrency_per_replica: number;
  rate_limit_qps: number | null;
  daily_budget_usd: number | null;
  daily_cost_limit: number | null;
  model: string | null;
};

type CostProjection = {
  agent_id: string;
  telemetry_24h: {
    runs: number;
    total_cost_usd: number;
    avg_cost_per_run_usd: number;
    avg_duration_ms: number;
    runs_per_hour: number;
  };
  scenarios: Record<'shared' | 'dedicated' | 'peak', {
    replicas_avg: number;
    infra_usd_per_hour: number;
    token_usd_per_hour: number;
    total_usd_per_hour: number;
    total_usd_per_day: number;
    total_usd_per_month: number;
  }>;
  current: 'shared' | 'dedicated';
  notes: string[];
};

const POOL_COLORS: Record<string, { border: string; bg: string; text: string }> = {
  default:            { border: 'border-slate-500/40', bg: 'bg-slate-500/10', text: 'text-slate-300' },
  chat:               { border: 'border-emerald-500/40', bg: 'bg-emerald-500/10', text: 'text-emerald-300' },
  'heavy-reasoning':  { border: 'border-violet-500/40', bg: 'bg-violet-500/10', text: 'text-violet-300' },
  gpu:                { border: 'border-amber-500/40', bg: 'bg-amber-500/10', text: 'text-amber-300' },
  'long-running':     { border: 'border-orange-500/40', bg: 'bg-orange-500/10', text: 'text-orange-300' },
};

const STATUS_COLORS: Record<string, string> = {
  active:         'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
  draft:          'bg-slate-500/15 text-slate-300 border-slate-500/40',
  pending_review: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
  archived:       'bg-rose-500/15 text-rose-300 border-rose-500/40',
  rejected:       'bg-rose-500/15 text-rose-300 border-rose-500/40',
};


export default function AdminScalingPage() {
  const [pools, setPools] = useState<Pool[]>([]);
  const [agents, setAgents] = useState<AgentScale[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [poolFilter, setPoolFilter] = useState<string>('all');
  const [editing, setEditing] = useState<AgentScale | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const token = getToken();
    if (!token) { setLoading(false); setError('Not signed in'); return; }
    try {
      const [pr, ar] = await Promise.all([
        fetch(`${API_URL}/api/admin/scaling/pools`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API_URL}/api/admin/scaling/agents?limit=500`, { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      if (pr.status === 403 || ar.status === 403) {
        setError('Admin role required to view this page.');
        setLoading(false); return;
      }
      const pj = await pr.json();
      const aj = await ar.json();
      setPools(pj.data?.pools || []);
      setAgents(aj.data?.agents || []);
    } catch (e: any) {
      setError(e?.message || 'Failed to load');
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const filteredAgents = useMemo(() => {
    const q = search.trim().toLowerCase();
    return agents.filter(a => {
      if (poolFilter !== 'all' && a.runtime_pool !== poolFilter) return false;
      if (q && !(a.name.toLowerCase().includes(q) || a.slug.toLowerCase().includes(q))) return false;
      return true;
    });
  }, [agents, search, poolFilter]);

  const totals = useMemo(() => {
    const exec24 = pools.reduce((s, p) => s + (p.executions_24h || 0), 0);
    const maxRep = agents.reduce((s, a) => s + (a.max_replicas || 0), 0);
    const withBudget = agents.filter(a => a.daily_budget_usd != null).length;
    const withRateLimit = agents.filter(a => a.rate_limit_qps != null).length;
    return { exec24, maxRep, withBudget, withRateLimit };
  }, [pools, agents]);

  const saveAgent = async (id: string, updates: Partial<AgentScale>) => {
    const token = getToken();
    const r = await fetch(`${API_URL}/api/admin/scaling/agents/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(updates),
    });
    const j = await r.json();
    if (j.error) throw new Error(j.error.message || 'Update failed');
    setAgents(prev => prev.map(a => a.id === id ? { ...a, ...(j.data || {}) } : a));
    return j.data;
  };

  const togglePause = async (a: AgentScale) => {
    const token = getToken();
    const op = a.status === 'archived' ? 'resume' : 'pause';
    const r = await fetch(`${API_URL}/api/admin/scaling/agents/${a.id}/${op}`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}` },
    });
    const j = await r.json();
    if (!j.error) setAgents(prev => prev.map(x => x.id === a.id ? { ...x, status: j.data.status } : x));
  };

  const toggleDedicated = async (a: AgentScale) => {
    const token = getToken();
    const enabled = !a.dedicated_mode;
    const r = await fetch(`${API_URL}/api/admin/scaling/agents/${a.id}/dedicated-mode`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    });
    const j = await r.json();
    if (!j.error) {
      setAgents(prev => prev.map(x => x.id === a.id ? { ...x, ...(j.data || {}) } : x));
    }
  };

  if (loading) {
    return (
      <div className="min-h-[70vh] flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-cyan-400" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 max-w-2xl mx-auto">
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-6 text-rose-200 text-sm">
          <AlertTriangle className="w-5 h-5 mb-2" /> {error}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6" data-testid="admin-scaling">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-cyan-500/20 to-violet-500/20 border border-cyan-500/30 flex items-center justify-center">
              <Gauge className="w-6 h-6 text-cyan-400" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white">Scaling Console</h1>
              <p className="text-xs text-slate-400">
                Per-agent pool routing, replicas, concurrency, rate-limits, and budgets. No YAML or helm-upgrade required.
              </p>
              <p className="text-[11px] text-amber-300/80 mt-1">
                <span className="inline-block rounded bg-amber-500/10 border border-amber-500/30 px-1.5 py-0.5 mr-1.5">platform-wide</span>
                Counts below cover every tenant in the cluster — intentionally broader than the tenant-scoped sidebar stats.
              </p>
            </div>
          </div>
          <button
            onClick={load}
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/60 border border-slate-700/50 text-xs text-slate-300 hover:bg-slate-800"
          >
            <RefreshCw className="w-3 h-3" /> Refresh
          </button>
        </div>

        {/* KPI strip */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3" data-testid="scaling-kpis">
          {[
            { label: 'Pools',                    value: pools.length,             icon: Server,    color: 'text-cyan-400' },
            { label: 'Agents (all tenants)',     value: agents.length,            icon: Zap,       color: 'text-violet-400' },
            { label: 'Execs last 24h (fleet)',   value: totals.exec24,            icon: TrendingUp,color: 'text-emerald-400' },
            { label: 'With rate-limit',          value: totals.withRateLimit,     icon: Gauge,     color: 'text-amber-400' },
            { label: 'With daily budget',        value: totals.withBudget,        icon: DollarSign,color: 'text-rose-400' },
          ].map(k => (
            <div key={k.label} className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-4">
              <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-slate-500 mb-1">
                <k.icon className={`w-3.5 h-3.5 ${k.color}`} /> {k.label}
              </div>
              <p className={`text-2xl font-bold ${k.color}`}>{k.value}</p>
            </div>
          ))}
        </div>

        {/* Pool health cards */}
        <section>
          <h2 className="text-sm font-semibold text-white mb-3">Pool health</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {pools.map(p => {
              const colors = POOL_COLORS[p.key] || POOL_COLORS.default;
              return (
                <button
                  key={p.key}
                  onClick={() => setPoolFilter(p.key)}
                  className={`text-left rounded-xl border ${colors.border} ${colors.bg} p-4 hover:border-white/40 transition`}
                  data-testid={`pool-${p.key}`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <p className={`text-sm font-semibold ${colors.text}`}>{p.label}</p>
                    <span className="text-[10px] text-slate-500">{p.key}</span>
                  </div>
                  <p className="text-[11px] text-slate-400 leading-snug line-clamp-2 mb-3">{p.description}</p>
                  <div className="grid grid-cols-3 gap-2 text-center">
                    <div>
                      <p className="text-[9px] uppercase text-slate-500">Agents</p>
                      <p className={`text-lg font-semibold ${colors.text}`}>{p.agent_count}</p>
                    </div>
                    <div>
                      <p className="text-[9px] uppercase text-slate-500">Min–Max</p>
                      <p className={`text-lg font-semibold ${colors.text}`}>{p.default_min_replicas}–{p.default_max_replicas}</p>
                    </div>
                    <div>
                      <p className="text-[9px] uppercase text-slate-500">24 h execs</p>
                      <p className={`text-lg font-semibold ${colors.text}`}>{p.executions_24h}</p>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </section>

        {/* Agent table */}
        <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
          <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
            <h2 className="text-sm font-semibold text-white">Agents ({filteredAgents.length})</h2>
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1.5 bg-slate-900/50 rounded-lg px-3 py-1.5 border border-slate-700/50">
                <Search className="w-3 h-3 text-slate-500" />
                <input
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder="Search agents..."
                  className="bg-transparent outline-none text-xs text-white w-48"
                  data-testid="agent-search"
                />
              </div>
              <select
                value={poolFilter}
                onChange={e => setPoolFilter(e.target.value)}
                className="bg-slate-900/50 border border-slate-700/50 rounded-lg px-3 py-1.5 text-xs text-white"
                data-testid="pool-filter"
              >
                <option value="all">All pools</option>
                {pools.map(p => <option key={p.key} value={p.key}>{p.label}</option>)}
              </select>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[10px] uppercase text-slate-500 border-b border-slate-700/50">
                  <th className="py-2 pl-2">Agent</th>
                  <th className="py-2">Pool</th>
                  <th className="py-2">Mode</th>
                  <th className="py-2">Replicas</th>
                  <th className="py-2">Concurrency</th>
                  <th className="py-2">Rate limit (qps)</th>
                  <th className="py-2">Daily $ budget</th>
                  <th className="py-2">Status</th>
                  <th className="py-2 pr-2"></th>
                </tr>
              </thead>
              <tbody>
                {filteredAgents.map(a => {
                  const pc = POOL_COLORS[a.runtime_pool] || POOL_COLORS.default;
                  return (
                    <tr key={a.id} className="border-b border-slate-800/60 hover:bg-slate-800/30" data-testid={`agent-row-${a.slug}`}>
                      <td className="py-2 pl-2">
                        <p className="text-white font-medium">{a.name}</p>
                        <p className="text-[10px] text-slate-500 font-mono">{a.slug}</p>
                      </td>
                      <td className="py-2">
                        <span className={`text-[10px] px-2 py-0.5 rounded border ${pc.border} ${pc.bg} ${pc.text}`}>
                          {a.runtime_pool}
                        </span>
                      </td>
                      <td className="py-2">
                        <button
                          onClick={() => toggleDedicated(a)}
                          className={`text-[10px] px-2 py-0.5 rounded border transition ${
                            a.dedicated_mode
                              ? 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/20'
                              : 'border-slate-600/40 bg-slate-700/20 text-slate-300 hover:bg-slate-700/40'
                          }`}
                          title={a.dedicated_mode
                            ? 'Dedicated: this agent has its own pod / NATS subject. Click to fall back to the shared pool.'
                            : 'Shared: this agent runs on its pool. Click to opt-in to dedicated per-agent pod scaling.'}
                          data-testid={`mode-${a.slug}`}
                        >
                          {a.dedicated_mode ? 'Dedicated' : 'Shared'}
                        </button>
                      </td>
                      <td className="py-2 tabular-nums text-slate-200">{a.min_replicas} – {a.max_replicas}</td>
                      <td className="py-2 tabular-nums text-slate-200">{a.concurrency_per_replica}</td>
                      <td className="py-2 tabular-nums text-slate-300">
                        {a.rate_limit_qps != null ? a.rate_limit_qps : <span className="text-slate-600">—</span>}
                      </td>
                      <td className="py-2 tabular-nums text-slate-300">
                        {a.daily_budget_usd != null ? `$${a.daily_budget_usd}` : <span className="text-slate-600">—</span>}
                      </td>
                      <td className="py-2">
                        <span className={`text-[10px] px-2 py-0.5 rounded border ${STATUS_COLORS[a.status] || STATUS_COLORS.draft}`}>
                          {a.status}
                        </span>
                      </td>
                      <td className="py-2 pr-2">
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => setEditing(a)}
                            className="p-1.5 rounded hover:bg-slate-700/60 text-slate-400 hover:text-white"
                            title="Edit scaling"
                            data-testid={`edit-${a.slug}`}
                          >
                            <Edit3 className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => togglePause(a)}
                            className="p-1.5 rounded hover:bg-slate-700/60 text-slate-400 hover:text-white"
                            title={a.status === 'archived' ? 'Resume' : 'Pause'}
                            data-testid={`pause-${a.slug}`}
                          >
                            {a.status === 'archived' ? <Play className="w-3.5 h-3.5" /> : <Pause className="w-3.5 h-3.5" />}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {filteredAgents.length === 0 && (
                  <tr><td colSpan={8} className="py-10 text-center text-slate-500">No agents match the filter.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        {/* Edit modal */}
        {editing && (
          <EditScaleModal
            agent={editing}
            pools={pools}
            onClose={() => setEditing(null)}
            onSave={async (updates) => {
              await saveAgent(editing.id, updates);
              setEditing(null);
            }}
          />
        )}
      </div>
    </div>
  );
}


function EditScaleModal({
  agent, pools, onClose, onSave,
}: {
  agent: AgentScale;
  pools: Pool[];
  onClose: () => void;
  onSave: (updates: Partial<AgentScale>) => Promise<void>;
}) {
  const [form, setForm] = useState({
    runtime_pool: agent.runtime_pool,
    min_replicas: agent.min_replicas,
    max_replicas: agent.max_replicas,
    concurrency_per_replica: agent.concurrency_per_replica,
    rate_limit_qps: agent.rate_limit_qps,
    daily_budget_usd: agent.daily_budget_usd,
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    setSaving(true); setErr(null);
    try {
      const updates: Record<string, any> = {};
      for (const k of Object.keys(form) as (keyof typeof form)[]) {
        if ((form as any)[k] !== (agent as any)[k]) (updates as any)[k] = (form as any)[k];
      }
      if (Object.keys(updates).length === 0) { onClose(); return; }
      await onSave(updates);
    } catch (e: any) {
      setErr(e?.message || 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-6"
      onClick={onClose}
      data-testid="scale-modal"
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }}
        onClick={e => e.stopPropagation()}
        className="bg-[#0B0F19] border border-slate-700/60 rounded-2xl max-w-2xl w-full max-h-[85vh] overflow-y-auto"
      >
        <div className="p-5 border-b border-slate-700/50 flex items-center justify-between">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-500">Scaling config</p>
            <h2 className="text-base font-semibold text-white">{agent.name}</h2>
            <p className="text-xs text-slate-500 font-mono">{agent.slug}</p>
          </div>
          <button onClick={onClose} className="p-2 rounded-lg text-slate-400 hover:bg-slate-800/60 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-5">
          {/*
            Two-step execution picker — business users set the TOGGLE,
            and only tech-savvy users need to pick a specific pool. We
            keep both controls wired to the same runtime_pool field so
            the API contract is unchanged.
          */}
          <div>
            <label className="text-[10px] uppercase tracking-wider text-slate-500 mb-2 block">
              How should this agent run?
            </label>
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setForm({ ...form, runtime_pool: 'inline' })}
                data-testid="edit-mode-fast"
                className={`rounded-xl border p-3 text-left transition-colors ${
                  form.runtime_pool === 'inline'
                    ? 'border-emerald-500/60 bg-emerald-500/10'
                    : 'border-slate-700/60 bg-slate-900/50 hover:bg-slate-800/60'
                }`}
              >
                <p className="text-sm font-semibold text-white">Fast mode <span className="text-[10px] text-amber-300 font-normal">(single-tenant only)</span></p>
                <p className="text-[11px] text-slate-400 mt-1">
                  Runs in the main app. Lowest latency. Best for simple chat bots that finish in &lt; 2s.
                </p>
              </button>
              <button
                type="button"
                onClick={() => setForm({ ...form, runtime_pool: form.runtime_pool === 'inline' ? 'default' : form.runtime_pool })}
                data-testid="edit-mode-worker"
                className={`rounded-xl border p-3 text-left transition-colors ${
                  form.runtime_pool !== 'inline'
                    ? 'border-cyan-500/60 bg-cyan-500/10'
                    : 'border-slate-700/60 bg-slate-900/50 hover:bg-slate-800/60'
                }`}
              >
                <p className="text-sm font-semibold text-white">
                  Dedicated worker <span className="text-[10px] text-cyan-300 font-normal">(recommended)</span>
                </p>
                <p className="text-[11px] text-slate-400 mt-1">
                  Runs on its own worker. Crash-safe and auto-scales under load.
                </p>
              </button>
            </div>
          </div>

          {form.runtime_pool === 'inline' && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-[11px] text-amber-100 flex items-start gap-2">
              <span className="text-amber-300 font-bold">⚠</span>
              <div>
                <p className="font-semibold text-amber-200">Multi-tenant warning</p>
                <p className="mt-1 text-amber-100/80">
                  Fast-mode agents run on the API event loop with no queue isolation. While this agent is executing
                  (LLM call, tool calls, even sub-second waits), the same API worker cannot serve other tenants&apos;
                  requests. One slow Fast-mode agent can starve the whole cluster.
                </p>
                <p className="mt-1 text-amber-100/80">
                  <strong>Use it only for:</strong> single-tenant deployments, dev/test, or trivial agents that
                  return in &lt;500&nbsp;ms. For everything else, switch to <em>Dedicated worker</em>.
                </p>
              </div>
            </div>
          )}

          {form.runtime_pool !== 'inline' && (
            <>
              <div>
                <label className="text-[10px] uppercase tracking-wider text-slate-500 mb-1 block">
                  Worker pool <span className="text-slate-600 normal-case">(advanced)</span>
                </label>
                <select
                  value={form.runtime_pool}
                  onChange={e => setForm({ ...form, runtime_pool: e.target.value })}
                  className="w-full bg-slate-900/50 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white"
                  data-testid="edit-pool"
                >
                  {pools.filter(p => p.key !== 'inline').map(p => (
                    <option key={p.key} value={p.key}>{p.label}</option>
                  ))}
                </select>
                <p className="text-[10px] text-slate-500 mt-1">
                  {pools.find(p => p.key === form.runtime_pool)?.description}
                </p>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <NumInput label="Min replicas" value={form.min_replicas} min={0} max={50}
                  onChange={v => setForm({ ...form, min_replicas: v })} data-testid="edit-min" />
                <NumInput label="Max replicas" value={form.max_replicas} min={1} max={100}
                  onChange={v => setForm({ ...form, max_replicas: v })} data-testid="edit-max" />
                <NumInput label="Concurrency / pod" value={form.concurrency_per_replica} min={1} max={20}
                  onChange={v => setForm({ ...form, concurrency_per_replica: v })} data-testid="edit-conc" />
              </div>
            </>
          )}

          <div className="grid grid-cols-2 gap-3">
            <NumInput label="Rate limit (qps)" value={form.rate_limit_qps ?? 0} min={0} max={10000} nullable
              onChange={v => setForm({ ...form, rate_limit_qps: v === 0 ? null : v })} data-testid="edit-rate" />
            <NumInput label="Daily budget ($)" value={form.daily_budget_usd ?? 0} min={0} max={100000} step={1} nullable
              onChange={v => setForm({ ...form, daily_budget_usd: v === 0 ? null : v })} data-testid="edit-budget" />
          </div>

          {err && (
            <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-300">
              {err}
            </div>
          )}

          <div className="rounded-lg border border-cyan-500/20 bg-cyan-500/5 p-3 text-[11px] text-slate-300">
            <p className="font-semibold text-cyan-300 mb-1">What will happen</p>
            <p>
              Saving updates the row in <code className="text-cyan-300">agents</code>.
              The runtime re-reads scaling on every execution, so new requests hit the new config immediately.
              Helm / KEDA pick up replicas on their next reconcile cycle (≤ 30 s).
            </p>
          </div>
        </div>

        <div className="p-4 border-t border-slate-700/50 bg-slate-900/50 flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-white">
            Cancel
          </button>
          <button
            onClick={submit} disabled={saving}
            className="inline-flex items-center gap-2 px-4 py-1.5 rounded-lg bg-gradient-to-r from-cyan-500 to-violet-500 text-white text-xs font-semibold disabled:opacity-50"
            data-testid="scale-save"
          >
            {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3" />}
            Save
          </button>
        </div>
      </motion.div>
    </div>
  );
}


function NumInput({
  label, value, onChange, min, max, step = 1, nullable, ...rest
}: {
  label: string; value: number;
  onChange: (v: number) => void;
  min: number; max: number; step?: number; nullable?: boolean;
  [k: string]: any;
}) {
  return (
    <div>
      <label className="text-[10px] uppercase tracking-wider text-slate-500 mb-1 block">{label}</label>
      <input
        type="number" value={value} min={min} max={max} step={step}
        onChange={e => onChange(parseInt(e.target.value || '0', 10))}
        className="w-full bg-slate-900/50 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white font-mono"
        {...rest}
      />
      {nullable && (
        <p className="text-[9px] text-slate-600 mt-0.5">0 or empty = unlimited</p>
      )}
    </div>
  );
}
