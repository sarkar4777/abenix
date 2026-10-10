'use client';

import { useEffect, useRef, useState } from 'react';
import { BrainCircuit, Loader2, AlertTriangle, Sparkles } from 'lucide-react';
import { authFetch } from '../lib/authFetch';
import { PageExplainer } from '@/components/PageExplainer';

type ModelDef = { name: string; family: string; sample_features: Record<string, number> };

const KNOWN_MODELS: ModelDef[] = [
  { name: 'offtake_residential', family: 'GradientBoostingRegressor', sample_features: { hdd_7d: 6.5, cdd_7d: 0, weekday_idx: 3, weekend_flag: 0, churn_rate: 0.03, customer_mix_shift: 0.05, base_volume: 300 } },
  { name: 'offtake_industrial',  family: 'HistGradientBoostingRegressor', sample_features: { sector_pmi: 51, plant_utilisation: 0.82, cluster_id: 2, last_quarter_avg: 420, power_price_eur_mwh: 95, maintenance_flag: 0 } },
  { name: 'offtake_storage_cycling', family: 'GradientBoostingRegressor', sample_features: { front_winter_spread: 6, days_to_withdrawal: 120, inj_capacity_left: 0.5, linepack: 0.85, ttf_the_basis: 0.2 } },
  { name: 'price_fairvalue_gas_hubs',  family: 'BayesianRidge', sample_features: { storage_eu_pct: 62, ttf_basis_eur: 0.4, hh_eur_equiv: 13.2, brent_eur: 78, weather_anomaly_c: 0.5, lng_send_out_gwh: 2900 } },
  { name: 'price_fairvalue_power_hubs', family: 'BayesianRidge', sample_features: { ttf_eur_mwh: 36, eua_eur_t: 85, residual_load_gw: 52, wind_capf: 0.22, solar_capf: 0.18, hydro_reservoir_pct: 60, hour_of_day_idx: 14 } },
];

const EXPLAIN_LIMIT_MS = 60_000;

type Contribution = { feature: string; value: number; baseline: number; contribution: number };
type Step = { feature: string; contribution: number; start: number; end: number };

type Explanation = {
  ok?: boolean;
  method?: string;
  target?: string;
  model_name?: string;
  prediction?: number;
  base_value?: number;
  baseline_source?: string;
  contributions?: Contribution[];
  waterfall?: Step[];
};

const METHOD_LABELS: Record<string, string> = {
  linear: 'exact, coefficient times distance from baseline',
  'linear-shap': 'exact, linear SHAP',
  'tree-shap': 'tree SHAP',
  'exact-shapley': 'Shapley values over every feature mix',
  'sampled-shapley': 'Shapley values, sampled',
};

function baselineLabel(source?: string): string {
  if (!source) return 'unknown';
  if (source === 'zeros') return 'zero for every feature, the model has no stored training averages';
  if (source.startsWith('request')) return 'the values you sent';
  return 'the training averages';
}

const fmt = (n?: number) => (typeof n === 'number' && Number.isFinite(n) ? n.toFixed(3) : 'n/a');

// top steps by size, the rest folded into one so the waterfall still ends at the prediction
function foldSteps(steps: Step[], keep = 10): Step[] {
  if (steps.length <= keep) return steps;
  const head = steps.slice(0, keep);
  const rest = steps.slice(keep);
  const sum = rest.reduce((a, s) => a + s.contribution, 0);
  return [...head, { feature: `${rest.length} other features`, contribution: sum, start: rest[0].start, end: rest[0].start + sum }];
}

export default function WorkbenchPage() {
  const [modelIdx, setModelIdx] = useState(0);
  const [features, setFeatures] = useState<Record<string, number>>(KNOWN_MODELS[0].sample_features);
  const [result, setResult] = useState<Explanation | null>(null);
  const [loading, setLoading] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    setFeatures(KNOWN_MODELS[modelIdx].sample_features);
    setResult(null);
    setRunError(null);
  }, [modelIdx]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const run = async () => {
    setLoading(true);
    setResult(null);
    setRunError(null);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const limit = setTimeout(() => ctrl.abort(), EXPLAIN_LIMIT_MS);
    try {
      const res = await authFetch('/api/contractiq/workbench/explain', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_name: KNOWN_MODELS[modelIdx].name, feature_vector: features }),
        signal: ctrl.signal,
      });
      const body = await res.json().catch(() => null);
      if (!res.ok || !body?.ok) {
        const detail = typeof body?.detail === 'string' ? body.detail : body?.error;
        setRunError(detail || `The explainer returned HTTP ${res.status}.`);
      } else {
        setResult(body);
      }
    } catch (e: any) {
      if (ctrl.signal.aborted) {
        setRunError('No answer after a minute. Run it again, and if it still hangs check that the model is ready on the Abenix ML Models page.');
      } else {
        setRunError(`Could not reach the ContractIQ API: ${e?.message || e}`);
      }
    } finally {
      clearTimeout(limit);
      abortRef.current = null;
      setLoading(false);
    }
  };

  const resetSample = () => {
    setFeatures(KNOWN_MODELS[modelIdx].sample_features);
  };

  const active = KNOWN_MODELS[modelIdx];
  const steps = foldSteps(result?.waterfall ?? []);
  const base = result?.base_value ?? 0;
  const points = [base, result?.prediction ?? base, ...steps.flatMap((s) => [s.start, s.end])];
  const lo = Math.min(...points);
  const span = Math.max(...points) - lo || 1;
  const pct = (v: number) => ((v - lo) / span) * 100;
  const values = new Map((result?.contributions ?? []).map((c) => [c.feature, c]));

  return (
    <div className="min-h-screen text-slate-200 p-8 max-w-[1400px] mx-auto">
      <header className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <BrainCircuit className="w-7 h-7 text-emerald-400" />
          <h1 className="text-3xl font-bold text-white">Analyst Workbench</h1>
        </div>
        <p className="text-slate-400 max-w-3xl">
          Per-prediction explainability. Abenix scores the feature vector with the registered model and splits the gap between the
          baseline and the prediction across the features. Sample feature vector, edit it before relying on the explanation.
        </p>
        <PageExplainer routeKey="workbench" />
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

            <div className="flex items-center justify-between mb-3">
              <span className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-amber-300 bg-amber-500/10 border border-amber-500/30 px-2 py-0.5 rounded">
                Sample inputs
              </span>
              <button onClick={resetSample} className="text-[10px] uppercase tracking-wider text-slate-400 hover:text-slate-200 border border-slate-800 hover:border-slate-700 px-2 py-0.5 rounded">
                Reset to sample values
              </button>
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
              {loading ? <><Loader2 className="w-3 h-3 animate-spin" /> Running</> : 'Run Explain'}
            </button>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
            {result === null && !loading && !runError && (
              <p className="text-xs text-slate-500">Click Run Explain to score the current feature vector.</p>
            )}
            {loading && (
              <div data-testid="explain-progress" role="status" className="flex items-center gap-3 text-xs text-slate-300">
                <Loader2 className="w-4 h-4 animate-spin text-emerald-400 flex-shrink-0" />
                <p>Scoring the feature vector and its baseline in Abenix</p>
              </div>
            )}
            {runError && !loading && (
              <div data-testid="explain-error" role="alert" className="rounded-lg border border-rose-700/50 bg-rose-900/20 p-4 flex items-start gap-3">
                <AlertTriangle className="w-5 h-5 text-rose-400 flex-shrink-0 mt-0.5" />
                <div className="text-sm">
                  <p className="font-semibold text-rose-200">The explainer could not explain this prediction</p>
                  <p className="text-rose-300/80 text-xs mt-1 font-mono">{runError}</p>
                </div>
              </div>
            )}
            {result && !loading && (
              <>
                <h3 className="text-sm font-semibold text-white mb-1 flex items-center gap-1.5"><Sparkles className="w-3.5 h-3.5 text-emerald-400" /> Feature contributions</h3>
                <p className="text-xs text-slate-500 mb-4">
                  Explains the {result.target || 'prediction'} · method <span className="font-mono text-emerald-300">{result.method}</span>
                  {result.method && METHOD_LABELS[result.method] ? ` (${METHOD_LABELS[result.method]})` : ''} · baseline is {baselineLabel(result.baseline_source)}
                </p>
                <div className="grid grid-cols-2 gap-3 mb-5">
                  <div className="rounded-md border border-slate-800 bg-slate-950/40 p-3">
                    <p className="text-[10px] uppercase tracking-wider text-slate-500">Baseline value</p>
                    <p className="font-mono text-white text-lg">{fmt(result.base_value)}</p>
                  </div>
                  <div className="rounded-md border border-slate-800 bg-slate-950/40 p-3">
                    <p className="text-[10px] uppercase tracking-wider text-slate-500">Prediction</p>
                    <p data-testid="explain-prediction" className="font-mono text-white text-lg">{fmt(result.prediction)}</p>
                  </div>
                </div>
                <div className="space-y-2.5" data-testid="explain-waterfall">
                  {steps.map((s) => {
                    const pos = s.contribution >= 0;
                    const c = values.get(s.feature);
                    return (
                      <div key={s.feature}>
                        <div className="flex items-baseline justify-between mb-1 gap-3">
                          <span className="text-xs font-mono text-slate-300 truncate">
                            {s.feature}
                            {c && <span className="text-slate-500"> = {fmt(c.value)} (baseline {fmt(c.baseline)})</span>}
                          </span>
                          <span className={`text-xs font-mono ${pos ? 'text-emerald-400' : 'text-rose-400'}`}>{pos ? '+' : ''}{s.contribution.toFixed(3)}</span>
                        </div>
                        <div className="relative h-2 bg-slate-800 rounded">
                          <div
                            className={`absolute h-full rounded ${pos ? 'bg-emerald-500/70' : 'bg-rose-500/70'}`}
                            style={{ left: `${pct(Math.min(s.start, s.end))}%`, width: `${Math.max(0.5, (Math.abs(s.contribution) / span) * 100)}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                  {steps.length === 0 && (
                    <p className="text-xs text-slate-500">The model returned no per-feature contributions for this input.</p>
                  )}
                </div>
              </>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
