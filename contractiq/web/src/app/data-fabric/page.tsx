'use client';

import { useEffect, useState } from 'react';
import { Database, AlertTriangle, CheckCircle2, Loader2, RefreshCw, Boxes, Brain } from 'lucide-react';
import { authFetch } from '../lib/authFetch';

type FabricSource = {
  id?: string;
  kind?: string;
  name?: string;
  status?: string;
  endpoint_url?: string;
  last_polled_at?: string;
  tags?: string[];
};

type FabricResponse = {
  sources: FabricSource[];
  summary: {
    ml_models_registered?: number;
    ml_models?: { name?: string; version?: string; status?: string; framework?: string }[];
    recent_executions_by_status?: Record<string, number>;
    recent_executions_total?: number;
  };
  errors: string[];
};

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
    <div className="min-h-screen text-slate-200 p-8 max-w-[1400px] mx-auto">
      <header className="mb-6 flex items-baseline justify-between">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <Database className="w-7 h-7 text-cyan-400" />
            <h1 className="text-3xl font-bold text-white">Energy Data Fabric</h1>
          </div>
          <p className="text-slate-400 max-w-3xl">
            Live view of what Abenix is actually connected to for this tenant: market-data sources, registered ML
            models, and recent execution telemetry. Nothing is hardcoded — empty sections mean nothing is wired yet.
          </p>
        </div>
        <button onClick={load} disabled={loading} className="px-3 py-1.5 text-xs bg-cyan-600/20 hover:bg-cyan-600/30 disabled:bg-slate-700 text-cyan-200 border border-cyan-500/30 rounded-md inline-flex items-center gap-2">
          <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </header>

      {(data?.errors ?? []).length > 0 && (
        <div className="rounded-lg border border-amber-700/40 bg-amber-900/15 p-3 mb-4 text-xs text-amber-300/90">
          {data!.errors.map((e, i) => <div key={i} className="flex items-start gap-1.5"><AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" /> {e}</div>)}
        </div>
      )}

      <div className="grid grid-cols-3 gap-4 mb-6">
        <Tile icon={Database} label="Market-data sources" value={loading ? '...' : String(data?.sources.length ?? 0)} caption="live + planned connectors" />
        <Tile icon={Brain} label="ML models" value={loading ? '...' : String(data?.summary.ml_models_registered ?? 0)} caption="registered for this tenant" />
        <Tile icon={Boxes} label="Recent executions" value={loading ? '...' : String(data?.summary.recent_executions_total ?? 0)} caption="last 200 across all agents" />
      </div>

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-6 mb-6">
        <h2 className="text-sm font-semibold text-white mb-3">Connected sources</h2>
        {loading ? (
          <div className="text-center text-slate-500 py-8"><Loader2 className="w-5 h-5 animate-spin inline mr-2" /> querying Abenix...</div>
        ) : (data?.sources ?? []).length === 0 ? (
          <p className="text-xs text-slate-500 italic">
            No market-data sources registered yet. Connectors are configured in Abenix admin (Market Data → Sources).
            ContractIQ will surface them here automatically once they're added.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-[10px] uppercase tracking-wider text-slate-500">
              <tr><th className="text-left py-2">Name</th><th className="text-left">Kind</th><th className="text-left">Status</th><th className="text-left">Endpoint</th><th className="text-left">Last poll</th></tr>
            </thead>
            <tbody>
              {data!.sources.map(s => (
                <tr key={s.id ?? s.name} className="border-t border-slate-800/60">
                  <td className="py-2 text-slate-200">{s.name ?? '—'}</td>
                  <td className="text-slate-400 text-xs">{s.kind ?? '—'}</td>
                  <td className={`text-xs ${s.status === 'healthy' || s.status === 'ready' ? 'text-emerald-400' : 'text-amber-400'}`}>{s.status ?? '—'}</td>
                  <td className="text-slate-500 text-xs font-mono truncate max-w-xs">{s.endpoint_url ?? '—'}</td>
                  <td className="text-slate-500 text-xs">{s.last_polled_at ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-6 mb-6">
        <h2 className="text-sm font-semibold text-white mb-3">ML models in the registry</h2>
        {(data?.summary.ml_models ?? []).length === 0 ? (
          <p className="text-xs text-slate-500 italic">No models registered yet.</p>
        ) : (
          <div className="grid grid-cols-3 gap-2">
            {data!.summary.ml_models!.map(m => (
              <div key={(m.name ?? '') + (m.version ?? '')} className="rounded-md border border-slate-800 bg-slate-950/40 p-3">
                <p className="text-xs font-mono text-slate-200">{m.name}</p>
                <p className="text-[10px] text-slate-500 mt-1">v{m.version ?? '?'} · {m.framework ?? '?'}</p>
                <p className={`text-[10px] mt-0.5 ${m.status === 'ready' ? 'text-emerald-400' : 'text-amber-400'}`}>{m.status ?? '?'}</p>
              </div>
            ))}
          </div>
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
          <p className="text-xs text-slate-500 italic">No executions yet.</p>
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
