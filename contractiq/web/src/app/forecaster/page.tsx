'use client';

import { useEffect, useMemo, useState } from 'react';
import { TrendingUp, Factory, Users, Database, Sparkles, Loader2, AlertTriangle } from 'lucide-react';
import { authFetch } from '../lib/authFetch';

type Surface = 'residential' | 'industrial' | 'storage';

const SURFACE_META: Record<Surface, { label: string; icon: any; unit: string; model: string; horizon: number }> = {
  residential: { label: 'Residential / SME',  icon: Users,    unit: 'GWh/day', model: 'offtake_residential',      horizon: 14 },
  industrial:  { label: 'Industrial baseload',icon: Factory,  unit: 'GWh/day', model: 'offtake_industrial',       horizon: 14 },
  storage:     { label: 'Storage cycling',    icon: Database, unit: 'GWh/day', model: 'offtake_storage_cycling',  horizon: 14 },
};

type Point = { day: number; p10: number; p50: number; p90: number };
type Driver = { feature: string; importance?: number; coef?: number; rank: number };

type ForecastResult = {
  status?: string;
  model_used?: string;
  forecast?: Point[];
  drivers?: Driver[];
  model_metrics?: { mae?: number; rmse?: number; mape?: number };
  summary?: { live_sources?: string[]; needs_configuration?: string[]; warnings?: string[] };
  error?: string;
};

export default function ForecasterPage() {
  const [surface, setSurface] = useState<Surface>('residential');
  const [tempShift, setTempShift] = useState(0);
  const [demandShift, setDemandShift] = useState(0);
  const [churn, setChurn] = useState(0);
  const [result, setResult] = useState<ForecastResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [counterpartyId, setCounterpartyId] = useState<string>('');

  useEffect(() => {
    authFetch('/api/contractiq/counterparties').then(r => r.json()).then(j => {
      const first = (j.data || j.items || j || [])[0];
      if (first?.id) setCounterpartyId(first.id);
    }).catch(() => {});
  }, []);

  const runForecast = async () => {
    if (!counterpartyId) return;
    setLoading(true);
    try {
      const fv: Record<string, number> = surface === 'residential'
        ? { hdd_7d: 6.5 - tempShift, cdd_7d: Math.max(0, tempShift - 2), weekday_idx: 3, weekend_flag: 0, churn_rate: churn, customer_mix_shift: demandShift, base_volume: 300 }
        : surface === 'industrial'
        ? { sector_pmi: 51, plant_utilisation: 0.8 + demandShift * 0.1, cluster_id: 2, last_quarter_avg: 420, power_price_eur_mwh: 95, maintenance_flag: 0 }
        : { front_winter_spread: 6 + demandShift * 4, days_to_withdrawal: 120, inj_capacity_left: 0.5, linepack: 0.85, ttf_the_basis: 0.2 };

      const res = await authFetch('/api/contractiq/forecaster/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          counterparty_id: counterpartyId,
          segment: surface,
          horizon_days: SURFACE_META[surface].horizon,
          feature_vector: fv,
        }),
      });
      const j = await res.json();
      setResult(j);
    } catch (e: any) {
      setResult({ status: 'failed', error: String(e), summary: { warnings: [String(e)] } });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { if (counterpartyId) runForecast(); }, [counterpartyId, surface]);

  const meta = SURFACE_META[surface];
  const curve = result?.forecast ?? [];
  const hasCurve = curve.length > 0;
  const needsConfig = (result?.summary?.needs_configuration ?? []).length > 0;
  const warnings = result?.summary?.warnings ?? [];

  const { fanPath, medianPath, yMin, yMax, w, h, xs, ys } = useMemo(() => {
    if (!hasCurve) return { fanPath: '', medianPath: '', yMin: 0, yMax: 1, w: 920, h: 280, xs: () => 0, ys: () => 0 };
    const yMin = Math.min(...curve.map(p => p.p10)) - 10;
    const yMax = Math.max(...curve.map(p => p.p90)) + 10;
    const w = 920; const h = 280;
    const xs = (t: number) => 40 + (t / Math.max(1, curve.length - 1)) * (w - 60);
    const ys = (v: number) => h - 30 - ((v - yMin) / (yMax - yMin)) * (h - 60);
    const fan = curve.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xs(i)} ${ys(p.p90)}`).join(' ')
      + ' ' + curve.slice().reverse().map((p, i) => `L ${xs(curve.length - 1 - i)} ${ys(p.p10)}`).join(' ') + ' Z';
    const med = curve.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xs(i)} ${ys(p.p50)}`).join(' ');
    return { fanPath: fan, medianPath: med, yMin, yMax, w, h, xs, ys };
  }, [curve, hasCurve]);

  return (
    <div className="min-h-screen text-slate-200 p-8 max-w-[1400px] mx-auto">
      <header className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <TrendingUp className="w-7 h-7 text-emerald-400" />
          <h1 className="text-3xl font-bold text-white">Predictive Offtake Forecaster</h1>
        </div>
        <p className="text-slate-400 max-w-3xl">
          Calls the <span className="font-mono text-emerald-300">{meta.model}</span> model registered in Abenix via
          the <span className="font-mono">ciq-offtake-forecaster</span> agent. Fan + drivers come from the model's
          training metrics + SHAP / feature importance. No values are synthesised.
        </p>
      </header>

      <div className="grid grid-cols-3 gap-3 mb-6">
        {(Object.keys(SURFACE_META) as Surface[]).map(s => {
          const m = SURFACE_META[s];
          const Ic = m.icon;
          const active = surface === s;
          return (
            <button key={s} onClick={() => setSurface(s)}
              className={`rounded-xl border p-4 text-left transition-all ${active ? 'border-emerald-500/50 bg-emerald-500/10' : 'border-slate-800 bg-slate-900/40 hover:bg-slate-800/40'}`}>
              <div className="flex items-center gap-2 mb-1.5">
                <Ic className={`w-5 h-5 ${active ? 'text-emerald-400' : 'text-slate-500'}`} />
                <span className={`text-sm font-semibold ${active ? 'text-white' : 'text-slate-300'}`}>{m.label}</span>
              </div>
              <p className="text-[11px] text-slate-500"><span className="font-mono">{m.model}</span> · {m.horizon}d · {m.unit}</p>
            </button>
          );
        })}
      </div>

      {needsConfig && (
        <div className="rounded-lg border border-amber-700/50 bg-amber-900/20 p-4 mb-6 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
          <div className="text-sm">
            <p className="font-semibold text-amber-200">Model not yet deployed to this tenant</p>
            <p className="text-amber-300/80 text-xs mt-1">
              Expected: <span className="font-mono">{result?.summary?.needs_configuration?.join(', ')}</span>.
              Run <span className="font-mono">scripts/deploy-azure.sh --seed-ml</span> to register the .pkl. No
              data is being shown until the model is live — by design.
            </p>
          </div>
        </div>
      )}
      {warnings.length > 0 && !needsConfig && (
        <div className="rounded-lg border border-amber-700/40 bg-amber-900/15 p-3 mb-6 text-xs text-amber-300/90">
          {warnings.map((w, i) => <div key={i}>• {w}</div>)}
        </div>
      )}

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-6 mb-6">
        <div className="flex items-baseline justify-between mb-3">
          <h2 className="text-lg font-semibold text-white">{curve.length}-day fan chart</h2>
          <p className="text-xs text-slate-500 font-mono">
            {result?.model_used ?? '...'} · MAE {result?.model_metrics?.mae?.toFixed(2) ?? '—'} {meta.unit}
          </p>
        </div>
        {!hasCurve && !loading && (
          <div className="h-[280px] flex items-center justify-center text-slate-500 text-sm">
            {needsConfig ? 'Awaiting model registration in Abenix' : 'No forecast yet — click Run'}
          </div>
        )}
        {loading && <div className="h-[280px] flex items-center justify-center text-slate-500"><Loader2 className="w-5 h-5 animate-spin mr-2" /> Calling agent...</div>}
        {hasCurve && (
          <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-auto">
            <defs>
              <linearGradient id="fc-fan" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#10b981" stopOpacity="0.30" />
                <stop offset="100%" stopColor="#10b981" stopOpacity="0.05" />
              </linearGradient>
            </defs>
            {[0, 0.25, 0.5, 0.75, 1].map(g => {
              const y = 30 + g * (h - 60);
              return <line key={g} x1="40" x2={w - 20} y1={y} y2={y} stroke="#1e293b" strokeWidth="0.5" strokeDasharray="2 4" />;
            })}
            <path d={fanPath} fill="url(#fc-fan)" />
            <path d={medianPath} fill="none" stroke="#10b981" strokeWidth="2.5" />
            {curve.map((p, i) => (
              <circle key={p.day} cx={xs(i)} cy={ys(p.p50)} r="2.5" fill="#0B0F19" stroke="#10b981" strokeWidth="2" />
            ))}
            <text x="36" y="30" textAnchor="end" fill="#64748b" fontSize="10">{yMax.toFixed(0)}</text>
            <text x="36" y={h - 30} textAnchor="end" fill="#64748b" fontSize="10">{yMin.toFixed(0)}</text>
          </svg>
        )}
      </section>

      <div className="grid grid-cols-3 gap-6">
        <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
          <h2 className="text-sm font-semibold text-white mb-4">Re-run with what-if</h2>
          <div className="space-y-5">
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-[11px] text-slate-500 uppercase tracking-wider">Temperature shift</label>
                <span className="text-xs font-mono text-cyan-300">{tempShift > 0 ? '+' : ''}{tempShift} °C</span>
              </div>
              <input type="range" min={-8} max={8} step={1} value={tempShift} onChange={e => setTempShift(Number(e.target.value))} className="w-full" />
            </div>
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-[11px] text-slate-500 uppercase tracking-wider">Demand shock</label>
                <span className="text-xs font-mono text-cyan-300">{(demandShift * 100).toFixed(0)}%</span>
              </div>
              <input type="range" min={-0.5} max={0.5} step={0.05} value={demandShift} onChange={e => setDemandShift(Number(e.target.value))} className="w-full" />
            </div>
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-[11px] text-slate-500 uppercase tracking-wider">Churn rate</label>
                <span className="text-xs font-mono text-cyan-300">{(churn * 100).toFixed(0)}%</span>
              </div>
              <input type="range" min={0} max={0.6} step={0.05} value={churn} onChange={e => setChurn(Number(e.target.value))} className="w-full" />
            </div>
            <button onClick={runForecast} disabled={loading} className="w-full mt-2 text-xs text-white bg-emerald-600/80 hover:bg-emerald-600 disabled:bg-slate-700 rounded-md py-2 inline-flex items-center justify-center gap-2">
              {loading ? <><Loader2 className="w-3 h-3 animate-spin" /> Running</> : 'Run agent'}
            </button>
          </div>
        </section>

        <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
          <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-1.5"><Sparkles className="w-3.5 h-3.5 text-emerald-400" /> Top drivers (from model)</h2>
          {(!result?.drivers || result.drivers.length === 0) ? (
            <p className="text-xs text-slate-500">No driver data yet — runs after model returns explain().</p>
          ) : (
            <ul className="space-y-3">
              {result.drivers.slice(0, 6).map(d => {
                const v = d.importance ?? d.coef ?? 0;
                const mag = Math.min(100, Math.abs(v) * 100);
                const sign = v >= 0 ? '+' : '−';
                return (
                  <li key={d.feature}>
                    <div className="flex items-baseline justify-between mb-1">
                      <span className="text-xs text-slate-300 font-mono">{d.feature}</span>
                      <span className={`text-xs font-mono ${v >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{sign}{Math.abs(v).toFixed(3)}</span>
                    </div>
                    <div className="h-1.5 bg-slate-800 rounded overflow-hidden">
                      <div className={`h-full ${v >= 0 ? 'bg-emerald-500/70' : 'bg-rose-500/70'}`} style={{ width: `${mag}%` }} />
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
          <h2 className="text-sm font-semibold text-white mb-3">Provenance</h2>
          <dl className="text-xs space-y-2">
            <div><dt className="text-slate-500">Model</dt><dd className="text-slate-200 font-mono">{result?.model_used ?? '—'}</dd></div>
            <div><dt className="text-slate-500">Agent</dt><dd className="text-slate-200 font-mono">ciq-offtake-forecaster</dd></div>
            <div><dt className="text-slate-500">Train MAE</dt><dd className="text-slate-200 font-mono">{result?.model_metrics?.mae?.toFixed(2) ?? '—'}</dd></div>
            <div><dt className="text-slate-500">Train RMSE</dt><dd className="text-slate-200 font-mono">{result?.model_metrics?.rmse?.toFixed(2) ?? '—'}</dd></div>
            <div><dt className="text-slate-500">Train MAPE</dt><dd className="text-slate-200 font-mono">{result?.model_metrics?.mape?.toFixed(2) ?? '—'}%</dd></div>
            <div><dt className="text-slate-500">Live sources</dt><dd className="text-slate-200">{result?.summary?.live_sources?.join(', ') ?? '—'}</dd></div>
          </dl>
        </section>
      </div>
    </div>
  );
}
