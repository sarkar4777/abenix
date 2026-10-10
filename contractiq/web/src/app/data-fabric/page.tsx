'use client';

import { useEffect, useState } from 'react';
import { Database, AlertTriangle, Loader2, RefreshCw, Boxes, Brain, Wrench } from 'lucide-react';
import { authFetch } from '../lib/authFetch';
import { PageExplainer } from '@/components/PageExplainer';

type ToolStatus = 'live' | 'simulated' | 'unavailable';

type FabricSource = {
  name: string;
  category: string;
  status: ToolStatus;
  purpose?: string;
  last_used_at?: string;
};

type MlModel = {
  name?: string;
  version?: string;
  status?: string;
  framework?: string;
  last_run_at?: string;
  purpose?: string;
};

type FabricResponse = {
  sources: FabricSource[];
  summary: {
    ml_models_registered?: number;
    ml_models?: MlModel[];
    recent_executions_by_status?: Record<string, number>;
    recent_executions_total?: number;
    tools_total?: number;
    tools_live?: number;
    tools_simulated?: number;
    tools_unavailable?: number;
    tools_by_category?: Record<string, { total: number; live: number; simulated: number; unavailable: number }>;
  };
  errors: string[];
};

const CATEGORY_ORDER: string[] = [
  'market-prices',
  'search-and-news',
  'filings-and-registry',
  'credit-and-rating',
  'weather',
  'compute-and-explain',
  'extraction',
];

const CATEGORY_LABEL: Record<string, string> = {
  'market-prices': 'Market prices',
  'search-and-news': 'Search and news',
  'filings-and-registry': 'Filings and registry',
  'credit-and-rating': 'Credit and rating',
  'weather': 'Weather',
  'compute-and-explain': 'Compute and explain',
  'extraction': 'Extraction',
};

function statusBadgeClass(s: ToolStatus): string {
  if (s === 'live') return 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30';
  if (s === 'simulated') return 'bg-amber-500/10 text-amber-300 border-amber-500/30';
  return 'bg-slate-700/40 text-slate-400 border-slate-600/40';
}

type ModelDomain = 'Forecasting' | 'Risk' | 'Pricing' | 'Compliance' | 'Other';

// Lightweight catalog so we can group + describe models even when the backend
// hasn't yet plumbed purpose/last_run into the response.
const MODEL_CATALOG: Record<string, { domain: ModelDomain; purpose: string }> = {
  // Forecasting
  offtake_residential:       { domain: 'Forecasting', purpose: 'Residential load forecast (P10/P50/P90).' },
  offtake_industrial:        { domain: 'Forecasting', purpose: 'Industrial baseload forecast.' },
  offtake_storage_cycling:   { domain: 'Forecasting', purpose: 'Storage injection / withdrawal optimiser.' },
  lng_send_out_optimiser:    { domain: 'Forecasting', purpose: 'LNG slot calendar optimisation.' },
  // Pricing
  price_fairvalue_gas_hubs:  { domain: 'Pricing',     purpose: 'Bayesian fair-value across TTF/THE/CEGH.' },
  price_fairvalue_power_hubs:{ domain: 'Pricing',     purpose: 'Bayesian fair-value across DE/HU/PL/CZ/IT.' },
  scenario_prior_gas:        { domain: 'Pricing',     purpose: 'Regime prior for gas scenarios.' },
  scenario_prior_power:      { domain: 'Pricing',     purpose: 'Regime prior for power scenarios.' },
  recommendation_thesis:     { domain: 'Pricing',     purpose: 'LLM-written thesis on top trades.' },
  // Risk
  price_anomaly:                 { domain: 'Risk', purpose: 'IsolationForest residual anomaly detector.' },
  'contractiq-price-anomaly':    { domain: 'Risk', purpose: 'IsolationForest joint anomaly on contracts.' },
  'contractiq-risk-tier-predictor':  { domain: 'Risk', purpose: 'Calibrated deal-risk tier (low/med/high/critical).' },
  'contractiq-counterparty-default': { domain: 'Risk', purpose: 'Counterparty 12m P(default).' },
  // Compliance
  'contractiq-clause-classifier': { domain: 'Compliance', purpose: 'ETRM clause-type classifier (~30 classes).' },
};

function modelDomain(name?: string): ModelDomain {
  if (!name) return 'Other';
  if (MODEL_CATALOG[name]) return MODEL_CATALOG[name].domain;
  const n = name.toLowerCase();
  if (n.includes('forecast') || n.includes('offtake') || n.includes('load')) return 'Forecasting';
  if (n.includes('price') || n.includes('fairvalue') || n.includes('scenario')) return 'Pricing';
  if (n.includes('risk') || n.includes('anomaly') || n.includes('default') || n.includes('var')) return 'Risk';
  if (n.includes('clause') || n.includes('compliance') || n.includes('kyc') || n.includes('sanction')) return 'Compliance';
  return 'Other';
}

function modelPurpose(m: MlModel): string {
  return m.purpose || (m.name && MODEL_CATALOG[m.name]?.purpose) || '—';
}

export default function DataFabricPage() {
  const [data, setData] = useState<FabricResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const res = await authFetch('/api/contractiq/data-fabric/sources');
      const j = await res.json();
      setData(j);
    } catch (e: any) {
      setData({ sources: [], summary: {}, errors: [String(e)] });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="min-h-screen text-slate-200 p-4 sm:p-8 max-w-[1400px] mx-auto">
      <header className="mb-6 flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <Database className="w-7 h-7 text-cyan-400" />
            <h1 className="text-3xl font-bold text-white">Energy Data Fabric</h1>
          </div>
          <p className="text-slate-400 max-w-3xl">
            Live view of what this tenant can actually call: the market-data tools registered in the agent
            runtime, the ML models in the registry, and recent execution telemetry. Everything below is pulled
            from the platform at refresh time.
          </p>
        </div>
        <button onClick={load} disabled={loading} className="px-3 py-1.5 text-xs bg-cyan-600/20 hover:bg-cyan-600/30 disabled:bg-slate-700 text-cyan-200 border border-cyan-500/30 rounded-md inline-flex items-center gap-2">
          <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </header>
      <PageExplainer routeKey="data-fabric" />

      {(data?.errors ?? []).length > 0 && (
        <div className="rounded-lg border border-amber-700/40 bg-amber-900/15 p-3 mb-4 text-xs text-amber-300/90">
          {data!.errors.map((e, i) => <div key={i} className="flex items-start gap-1.5"><AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" /> {e}</div>)}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <Tile icon={Wrench} label="Market-data tools" value={loading ? '...' : String(data?.summary.tools_total ?? data?.sources.length ?? 0)} caption={`${data?.summary.tools_live ?? 0} live · ${data?.summary.tools_simulated ?? 0} simulated · ${data?.summary.tools_unavailable ?? 0} unavailable`} />
        <Tile icon={Brain} label="ML models" value={loading ? '...' : String(data?.summary.ml_models_registered ?? 0)} caption="registered for this tenant" />
        <Tile icon={Boxes} label="Recent executions" value={loading ? '...' : String(data?.summary.recent_executions_total ?? 0)} caption="last 200 across all agents" />
      </div>

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-6 mb-6">
        <h2 className="text-sm font-semibold text-white mb-1">Market-data tools available to agents</h2>
        <p className="text-xs text-slate-400 mb-4 max-w-3xl">
          Market data flows into agents through tools. Below is the registry of tools your tenant can call.
          <span className="text-emerald-300"> Live</span> means the tool fetches from a real public source.
          <span className="text-amber-300"> Simulated</span> means the tool produces output without an external call.
          <span className="text-slate-400"> Unavailable</span> means the tool exists but the upstream feed needs a paid
          subscription this tenant does not have.
        </p>
        {loading ? (
          <div className="text-center text-slate-500 py-8"><Loader2 className="w-5 h-5 animate-spin inline mr-2" /> loading tool registry...</div>
        ) : (data?.sources ?? []).length === 0 ? (
          <div className="rounded-md border border-amber-700/40 bg-amber-900/15 px-3 py-2 text-xs text-amber-300/90 inline-flex items-center gap-2">
            <AlertTriangle className="w-3.5 h-3.5" /> No market-data tools registered. The agent runtime registry is empty.
          </div>
        ) : (
          CATEGORY_ORDER.map(cat => {
            const inCat = (data!.sources ?? []).filter(s => s.category === cat);
            if (!inCat.length) return null;
            const cs = data!.summary.tools_by_category?.[cat];
            return (
              <div key={cat} className="mb-5 last:mb-0">
                <div className="flex items-baseline justify-between mb-2">
                  <h3 className="text-[11px] uppercase tracking-wider text-slate-500">{CATEGORY_LABEL[cat] ?? cat}</h3>
                  {cs && (
                    <p className="text-[10px] text-slate-600 font-mono">
                      {cs.live} live · {cs.simulated} sim · {cs.unavailable} unavail
                    </p>
                  )}
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                  {inCat.map(s => (
                    <div key={s.name} className="rounded-md border border-slate-800 bg-slate-950/40 p-3">
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <p className="text-xs font-mono text-slate-200 truncate">{s.name}</p>
                        <span className={`text-[10px] uppercase tracking-wider font-mono px-1.5 py-0.5 rounded border ${statusBadgeClass(s.status)}`}>{s.status}</span>
                      </div>
                      <p className="text-[11px] text-slate-400 leading-snug">{s.purpose ?? '—'}</p>
                      <p className="text-[10px] text-slate-500 mt-2">
                        Last used: {s.last_used_at ? new Date(s.last_used_at).toLocaleString() : <span className="italic text-slate-600">not seen yet</span>}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            );
          })
        )}
        <p className="text-[11px] text-slate-500 mt-5 leading-relaxed">
          Adding a new tool: build it as a Python module under <span className="font-mono text-slate-400">apps/agent-runtime/engine/tools/</span> and register it.
          Agents that include the tool in their YAML config can use it next deploy.
        </p>
      </section>

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-6 mb-6">
        <h2 className="text-sm font-semibold text-white mb-3">ML models in the registry</h2>
        {(data?.summary.ml_models ?? []).length === 0 ? (
          <div className="rounded-md border border-amber-700/40 bg-amber-900/15 px-3 py-2 text-xs text-amber-300/90 inline-flex items-center gap-2">
            <AlertTriangle className="w-3.5 h-3.5" /> No models registered yet. Run <span className="font-mono">scripts/dev-local.sh</span> from the agentforge root — it seeds the sample ML registry as part of the standard local bootstrap.
          </div>
        ) : (
          (['Forecasting', 'Risk', 'Pricing', 'Compliance', 'Other'] as ModelDomain[]).map(domain => {
            const inDomain = (data!.summary.ml_models ?? []).filter(m => modelDomain(m.name) === domain);
            if (!inDomain.length) return null;
            return (
              <div key={domain} className="mb-5 last:mb-0">
                <h3 className="text-[11px] uppercase tracking-wider text-slate-500 mb-2">{domain}</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                  {inDomain.map(m => (
                    <div key={(m.name ?? '') + (m.version ?? '')} className="rounded-md border border-slate-800 bg-slate-950/40 p-3">
                      <p className="text-xs font-mono text-slate-200 truncate">{m.name}</p>
                      <p className="text-[11px] text-slate-400 mt-1 leading-snug">{modelPurpose(m)}</p>
                      <div className="flex items-center justify-between mt-2 gap-2">
                        <p className="text-[10px] text-slate-500">v{m.version ?? '?'} · {m.framework ?? '?'}</p>
                        <p className={`text-[10px] ${m.status === 'ready' ? 'text-emerald-400' : 'text-amber-400'}`}>{m.status ?? '?'}</p>
                      </div>
                      <p className="text-[10px] text-slate-500 mt-1">
                        Last run: {m.last_run_at ? new Date(m.last_run_at).toLocaleString() : <span className="italic text-slate-600">not run yet</span>}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            );
          })
        )}
      </section>

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
        <h2 className="text-sm font-semibold text-white mb-3">Execution telemetry (last 200)</h2>
        {data && data.summary.recent_executions_by_status ? (
          <div className="flex flex-wrap gap-2">
            {Object.entries(data.summary.recent_executions_by_status).map(([k, v]) => (
              <span key={k} className={`text-xs font-mono px-3 py-1.5 rounded border ${k === 'completed' ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30' : k === 'failed' ? 'bg-rose-500/10 text-rose-300 border-rose-500/30' : 'bg-slate-900 text-slate-400 border-slate-800'}`}>
                {k}: {v}
              </span>
            ))}
          </div>
        ) : (
          <div className="rounded-md border border-amber-700/40 bg-amber-900/15 px-3 py-2 text-xs text-amber-300/90 inline-flex items-center gap-2">
            <AlertTriangle className="w-3.5 h-3.5" /> No agent executions in the last batch — run any workflow to populate this panel.
          </div>
        )}
      </section>
    </div>
  );
}

function Tile({ icon: Icon, label, value, caption }: { icon: any; label: string; value: string; caption: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
      <div className="flex items-center gap-2 mb-2">
        <Icon className="w-4 h-4 text-cyan-400" />
        <p className="text-xs text-slate-400">{label}</p>
      </div>
      <p className="text-3xl font-bold text-white font-mono">{value}</p>
      <p className="text-[10px] text-slate-500 mt-1">{caption}</p>
    </div>
  );
}
