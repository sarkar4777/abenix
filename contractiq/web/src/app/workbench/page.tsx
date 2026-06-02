'use client';

import { useEffect, useState } from 'react';
import { BrainCircuit, Loader2, AlertTriangle, Sparkles } from 'lucide-react';
import { authFetch } from '../lib/authFetch';

type ModelDef = { name: string; family: string; sample_features: Record<string, number> };

const KNOWN_MODELS: ModelDef[] = [
  { name: 'offtake_residential', family: 'GradientBoostingRegressor', sample_features: { hdd_7d: 6.5, cdd_7d: 0, weekday_idx: 3, weekend_flag: 0, churn_rate: 0.03, customer_mix_shift: 0.05, base_volume: 300 } },
  { name: 'offtake_industrial',  family: 'HistGradientBoostingRegressor', sample_features: { sector_pmi: 51, plant_utilisation: 0.82, cluster_id: 2, last_quarter_avg: 420, power_price_eur_mwh: 95, maintenance_flag: 0 } },
  { name: 'offtake_storage_cycling', family: 'GradientBoostingRegressor', sample_features: { front_winter_spread: 6, days_to_withdrawal: 120, inj_capacity_left: 0.5, linepack: 0.85, ttf_the_basis: 0.2 } },
  { name: 'price_fairvalue_gas_hubs',  family: 'BayesianRidge', sample_features: { storage_eu_pct: 62, ttf_basis_eur: 0.4, hh_eur_equiv: 13.2, brent_eur: 78, weather_anomaly_c: 0.5, lng_send_out_gwh: 2900 } },
  { name: 'price_fairvalue_power_hubs', family: 'BayesianRidge', sample_features: { ttf_eur_mwh: 36, eua_eur_t: 85, residual_load_gw: 52, wind_capf: 0.22, solar_capf: 0.18, hydro_reservoir_pct: 60, hour_of_day_idx: 14 } },
];

type ShapResult = {
  ok?: boolean;
  method?: string;
  model_name?: string;
  prediction?: number;
  feature_columns?: string[];
  contributions?: { feature: string; value: number }[];
  error?: string;
};

export default function WorkbenchPage() {
  const [modelIdx, setModelIdx] = useState(0);
  const [features, setFeatures] = useState<Record<string, number>>(KNOWN_MODELS[0].sample_features);
  const [result, setResult] = useState<ShapResult | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => { setFeatures(KNOWN_MODELS[modelIdx].sample_features); }, [modelIdx]);

  const run = async () => {
    setLoading(true);
    try {
      const res = await authFetch('/api/contractiq/workbench/explain', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_name: KNOWN_MODELS[modelIdx].name, feature_vector: features }),
      });
      setResult(await res.json());
    } catch (e: any) {
      setResult({ ok: false, error: String(e) });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { run(); }, [modelIdx]);

  const active = KNOWN_MODELS[modelIdx];

  return (
    <div className="min-h-screen text-slate-200 p-8 max-w-[1400px] mx-auto">
      <header className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <BrainCircuit className="w-7 h-7 text-emerald-400" />
          <h1 className="text-3xl font-bold text-white">Analyst Workbench</h1>
        </div>
        <p className="text-slate-400 max-w-3xl">
          Per-prediction explainability. Routes the (model, feature_vector) to the <span className="font-mono">shap_explainer</span> code-asset
          hosted in Abenix. Falls back to <span className="font-mono">ml_model.explain()</span> when SHAP is unavailable. No hand-crafted narratives.
        </p>
      </header>

      <div className="grid grid-cols-12 gap-6">
        <aside className="col-span-3 rounded-xl border border-slate-800 bg-slate-900/40 p-4">
          <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-3">Pick a model</p>
          <ul className="space-y-1">
            {KNOWN_MODELS.map((m, i) => (
              <li key={m.name}>
                <button
                  onClick={() => setModelIdx(i)}
                  className={`w-full text-left p-2.5 rounded-md border text-xs ${modelIdx === i ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-100' : 'bg-slate-950/40 border-slate-800 hover:bg-slate-800/40 text-slate-300'}`}
                >
                  <p className="font-mono font-semibold">{m.name}</p>
                  <p className="text-[10px] text-slate-500 mt-0.5">{m.family}</p>
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <section className="col-span-9 space-y-6">
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
            <div className="flex items-baseline justify-between mb-4">
              <h2 className="text-lg font-semibold text-white">{active.name}</h2>
              <span className="text-[10px] uppercase tracking-wider text-slate-500 bg-slate-900 border border-slate-800 px-2 py-0.5 rounded">{active.family}</span>
            </div>

            <div className="grid grid-cols-2 gap-3 mb-4">
              {Object.entries(features).map(([k, v]) => (
                <label key={k} className="block">
                  <span className="text-[10px] text-slate-500 uppercase tracking-wider font-mono">{k}</span>
                  <input
                    type="number"
                    step="0.01"
                    value={v}
                    onChange={e => setFeatures({ ...features, [k]: Number(e.target.value) })}
                    className="mt-1 w-full bg-slate-950/60 border border-slate-800 rounded-md p-1.5 text-xs text-white font-mono focus:outline-none focus:border-emerald-500/40"
                  />
                </label>
              ))}
            </div>
            <button onClick={run} disabled={loading} className="px-4 py-2 text-xs bg-emerald-600/80 hover:bg-emerald-600 disabled:bg-slate-700 text-white rounded-md inline-flex items-center gap-2">
              {loading ? <><Loader2 className="w-3 h-3 animate-spin" /> Running</> : 'Run SHAP'}
            </button>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
            <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-1.5"><Sparkles className="w-3.5 h-3.5 text-amber-400" /> Feature attributions</h3>
            {result?.ok === false && (
              <div className="rounded-lg border border-amber-700/50 bg-amber-900/20 p-4 mb-3 flex items-start gap-3">
                <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
                <div className="text-sm">
                  <p className="font-semibold text-amber-200">Code-asset not registered yet</p>
                  <p className="text-amber-300/80 text-xs mt-1 font-mono">{result.error ?? 'shap_explainer not found'}</p>
                </div>
              </div>
            )}
            {result?.ok && (
              <>
                <p className="text-xs text-slate-500 mb-3">
                  Method <span className="font-mono text-emerald-300">{result.method}</span> · prediction <span className="font-mono text-white">{result.prediction?.toFixed(3)}</span>
                </p>
                <div className="space-y-2.5">
                  {(result.contributions ?? []).slice(0, 10).map(c => {
                    const pos = c.value >= 0;
                    const mag = Math.min(100, Math.abs(c.value) * 25);
                    return (
                      <div key={c.feature}>
                        <div className="flex items-baseline justify-between mb-1">
                          <span className="text-xs font-mono text-slate-300">{c.feature}</span>
                          <span className={`text-xs font-mono ${pos ? 'text-emerald-400' : 'text-rose-400'}`}>{pos ? '+' : ''}{c.value.toFixed(3)}</span>
                        </div>
                        <div className="h-1.5 bg-slate-800 rounded overflow-hidden">
                          <div className={`h-full ${pos ? 'bg-emerald-500/70' : 'bg-rose-500/70'}`} style={{ width: `${mag}%` }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
