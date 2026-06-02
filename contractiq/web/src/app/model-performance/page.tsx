'use client';

import { useEffect, useMemo, useState } from 'react';
import { Activity, AlertTriangle, CheckCircle2, History, Loader2 } from 'lucide-react';
import { authFetch } from '../lib/authFetch';

type RegistryRow = {
  id?: string;
  name: string;
  version?: string;
  framework?: string;
  status?: string;
  training_metrics?: Record<string, any>;
  tags?: string[];
  updated_at?: string;
  created_at?: string;
};

export default function ModelPerformancePage() {
  const [models, setModels] = useState<RegistryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string>('');
  const [error, setError] = useState<string>('');

  useEffect(() => {
    setLoading(true);
    authFetch('/api/contractiq/ml-models/registry')
      .then(r => r.json())
      .then(j => {
        const list: RegistryRow[] = j.data ?? [];
        setModels(list);
        if (list.length > 0) setSelected(list[0].name);
        if (j.error) setError(j.error);
      })
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  const m = useMemo(() => models.find(x => x.name === selected) ?? null, [models, selected]);

  const metrics = (m?.training_metrics ?? {}) as Record<string, number>;
  const mae = metrics.mae ?? metrics.mae_gwh ?? metrics.mae_eur_mwh ?? null;
  const rmse = metrics.rmse ?? metrics.rmse_gwh ?? metrics.rmse_eur_mwh ?? null;
  const mape = metrics.mape ?? metrics.mape_pct ?? null;
  const sigma = metrics.avg_sigma ?? null;

  return (
    <div className="min-h-screen text-slate-200 p-8 max-w-[1400px] mx-auto">
      <header className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <Activity className="w-7 h-7 text-emerald-400" />
          <h1 className="text-3xl font-bold text-white">Model Performance &amp; Backtesting</h1>
        </div>
        <p className="text-slate-400 max-w-3xl">
          Live view of the Abenix ML registry — what's deployed for this tenant, training metrics, and freshness.
          Reads <span className="font-mono">GET /api/contractiq/ml-models/registry</span> which proxies the platform's
          <span className="font-mono"> /api/ml-models</span>. No hardcoded model list.
        </p>
      </header>

      {error && !loading && (
        <div className="rounded-lg border border-amber-700/40 bg-amber-900/15 p-3 mb-4 text-xs text-amber-300/90 flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />
          <span>Registry returned an error: {error}</span>
        </div>
      )}

      {loading ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-12 text-center">
          <Loader2 className="w-6 h-6 animate-spin text-emerald-400 mx-auto mb-2" />
          <p className="text-sm text-slate-400">Loading ML registry...</p>
        </div>
      ) : models.length === 0 ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-12 text-center">
          <AlertTriangle className="w-6 h-6 text-amber-400 mx-auto mb-2" />
          <p className="text-sm text-slate-300">No ML models registered for this tenant yet.</p>
          <p className="text-xs text-slate-500 mt-1">Run the seed: <span className="font-mono">scripts/deploy-azure.sh --seed-ml</span></p>
        </div>
      ) : (
        <div className="grid grid-cols-12 gap-6">
          <aside className="col-span-4 rounded-xl border border-slate-800 bg-slate-900/40 p-4">
            <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-3">Registered models ({models.length})</p>
            <ul className="space-y-1 max-h-[600px] overflow-y-auto">
              {models.map(mm => (
                <li key={mm.name + (mm.version ?? '')}>
                  <button
                    onClick={() => setSelected(mm.name)}
                    className={`w-full text-left p-2.5 rounded-md border text-xs ${selected === mm.name ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-100' : 'bg-slate-950/40 border-slate-800 hover:bg-slate-800/40 text-slate-300'}`}
                  >
                    <div className="flex items-baseline justify-between">
                      <span className="font-mono font-semibold">{mm.name}</span>
                      <span className="text-[9px] text-slate-500">{mm.version ?? '—'}</span>
                    </div>
                    <p className="text-[10px] text-slate-500 mt-0.5 flex items-center gap-1.5">
                      <span>{mm.framework ?? '—'}</span>
                      <span>·</span>
                      <span className={mm.status === 'ready' ? 'text-emerald-400' : 'text-amber-400'}>{mm.status ?? '—'}</span>
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          </aside>

          <section className="col-span-8 space-y-4">
            {m && (
              <>
                <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
                  <div className="flex items-baseline justify-between mb-2">
                    <h2 className="text-lg font-semibold text-white font-mono">{m.name}</h2>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] uppercase tracking-wider text-slate-500 bg-slate-900 border border-slate-800 px-2 py-0.5 rounded">{m.framework ?? 'custom'}</span>
                      <span className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded border ${m.status === 'ready' ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30' : 'bg-amber-500/10 text-amber-300 border-amber-500/30'}`}>{m.status ?? 'unknown'}</span>
                    </div>
                  </div>
                  <div className="grid grid-cols-4 gap-4 mt-4">
                    <Metric label="MAE"   value={mae?.toFixed(3)} />
                    <Metric label="RMSE"  value={rmse?.toFixed(3)} />
                    <Metric label="MAPE"  value={mape == null ? null : `${mape.toFixed(2)}%`} />
                    <Metric label="σ avg" value={sigma?.toFixed(3)} />
                  </div>
                </div>

                <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
                  <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-1.5"><History className="w-3.5 h-3.5 text-cyan-400" /> Training metrics (raw)</h3>
                  <pre className="text-[11px] font-mono text-slate-300 bg-slate-950/60 p-3 rounded border border-slate-800 overflow-x-auto whitespace-pre-wrap">
{JSON.stringify(m.training_metrics ?? {}, null, 2)}
                  </pre>
                </div>

                <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
                  <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-1.5"><CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> Tags</h3>
                  <div className="flex flex-wrap gap-1.5">
                    {(m.tags ?? []).map(t => (
                      <span key={t} className="text-[10px] font-mono px-2 py-0.5 rounded border border-slate-800 bg-slate-950/60 text-slate-400">{t}</span>
                    ))}
                  </div>
                </div>
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div>
      <p className="text-xs text-slate-500">{label}</p>
      <p className="text-2xl font-bold font-mono text-emerald-300">{value == null ? '—' : value}</p>
    </div>
  );
}
