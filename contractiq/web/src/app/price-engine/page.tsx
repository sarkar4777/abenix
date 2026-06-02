'use client';

import { useEffect, useState } from 'react';
import { LineChart, AlertOctagon, Loader2, AlertTriangle } from 'lucide-react';
import { authFetch } from '../lib/authFetch';

type Hub = 'TTF' | 'NBP' | 'THE' | 'PEG' | 'PSV' | 'CEGH' | 'DE' | 'FR' | 'NL' | 'BE' | 'AT';
type Commodity = 'gas' | 'power';

const HUB_DEFS: { id: Hub; commodity: Commodity; spot_default: number }[] = [
  { id: 'TTF',  commodity: 'gas',   spot_default: 34.5 },
  { id: 'NBP',  commodity: 'gas',   spot_default: 33.8 },
  { id: 'THE',  commodity: 'gas',   spot_default: 34.7 },
  { id: 'PEG',  commodity: 'gas',   spot_default: 35.1 },
  { id: 'PSV',  commodity: 'gas',   spot_default: 35.4 },
  { id: 'CEGH', commodity: 'gas',   spot_default: 35.0 },
  { id: 'DE',   commodity: 'power', spot_default: 95.0 },
  { id: 'FR',   commodity: 'power', spot_default: 92.5 },
  { id: 'NL',   commodity: 'power', spot_default: 94.2 },
  { id: 'BE',   commodity: 'power', spot_default: 93.8 },
  { id: 'AT',   commodity: 'power', spot_default: 96.4 },
];

const GAS_FV: Record<string, number> = {
  storage_eu_pct: 62, ttf_basis_eur: 0.4, hh_eur_equiv: 13.2, brent_eur: 78,
  weather_anomaly_c: 0.5, lng_send_out_gwh: 2900,
};
const POWER_FV: Record<string, number> = {
  ttf_eur_mwh: 36, eua_eur_t: 85, residual_load_gw: 52, wind_capf: 0.22,
  solar_capf: 0.18, hydro_reservoir_pct: 60, hour_of_day_idx: 14,
};

type EngineResult = {
  hub?: string;
  model_used?: string;
  current_spot?: number;
  fair_value_eur_mwh?: number;
  sigma?: number;
  z_score?: number;
  anomaly_flag?: boolean;
  verdict?: 'rich' | 'fair' | 'cheap';
  drivers?: { feature: string; coef: number; rank: number }[];
  summary?: { live_sources?: string[]; needs_configuration?: string[]; warnings?: string[] };
  error?: string;
};

export default function PriceEnginePage() {
  const [hubId, setHubId] = useState<Hub>('TTF');
  const [stress, setStress] = useState(0);
  const [result, setResult] = useState<EngineResult | null>(null);
  const [loading, setLoading] = useState(false);

  const hubDef = HUB_DEFS.find(h => h.id === hubId)!;

  const run = async () => {
    setLoading(true);
    try {
      const isGas = hubDef.commodity === 'gas';
      const baseFv = isGas ? { ...GAS_FV } : { ...POWER_FV };
      if (isGas) baseFv.weather_anomaly_c = (baseFv.weather_anomaly_c ?? 0) + stress * 4;
      else baseFv.residual_load_gw = (baseFv.residual_load_gw ?? 0) * (1 + stress * 0.2);
      const currentSpot = hubDef.spot_default * (1 + stress * 0.06);

      const res = await authFetch('/api/contractiq/price-engine/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          hub: hubId,
          commodity: hubDef.commodity,
          feature_vector: baseFv,
          current_spot: currentSpot,
        }),
      });
      setResult(await res.json());
    } catch (e: any) {
      setResult({ error: String(e), summary: { warnings: [String(e)] } });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { run(); }, [hubId]);

  const needsConfig = (result?.summary?.needs_configuration ?? []).length > 0;
  const warnings = result?.summary?.warnings ?? [];
  const verdictColor = result?.verdict === 'rich' ? 'text-rose-300' : result?.verdict === 'cheap' ? 'text-emerald-300' : 'text-slate-300';

  return (
    <div className="min-h-screen text-slate-200 p-8 max-w-[1400px] mx-auto">
      <header className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <LineChart className="w-7 h-7 text-violet-400" />
          <h1 className="text-3xl font-bold text-white">Dynamic Forward Price Engine</h1>
        </div>
        <p className="text-slate-400 max-w-3xl">
          Calls <span className="font-mono text-violet-300">{hubDef.commodity === 'gas' ? 'price_fairvalue_gas_hubs' : 'price_fairvalue_power_hubs'}</span>
          {' '}(BayesianRidge + IsolationForest residual) via the <span className="font-mono">ciq-price-engine</span> agent. z-score and verdict are computed from the model's sigma; no values are invented.
        </p>
      </header>

      <div className="flex flex-wrap gap-2 mb-6">
        {HUB_DEFS.map(h => (
          <button
            key={h.id}
            onClick={() => setHubId(h.id)}
            className={`px-3 py-1.5 rounded-md text-xs border transition-colors ${
              hubId === h.id ? 'bg-violet-500/15 text-violet-200 border-violet-500/40' : 'bg-slate-900/40 text-slate-400 border-slate-800 hover:bg-slate-800/60 hover:text-white'
            }`}
          >
            {h.id} <span className="text-[9px] text-slate-500 ml-1">{h.commodity}</span>
          </button>
        ))}
      </div>

      {needsConfig && (
        <div className="rounded-lg border border-amber-700/50 bg-amber-900/20 p-4 mb-6 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
          <div className="text-sm">
            <p className="font-semibold text-amber-200">Fair-value model not registered for this tenant</p>
            <p className="text-amber-300/80 text-xs mt-1">Expected: <span className="font-mono">{result?.summary?.needs_configuration?.join(', ')}</span>. Run the ml-model seed.</p>
          </div>
        </div>
      )}
      {warnings.length > 0 && !needsConfig && (
        <div className="rounded-lg border border-amber-700/40 bg-amber-900/15 p-3 mb-6 text-xs text-amber-300/90">
          {warnings.map((w, i) => <div key={i}>• {w}</div>)}
        </div>
      )}

      <div className="grid grid-cols-12 gap-6 mb-6">
        <section className="col-span-8 rounded-xl border border-slate-800 bg-slate-900/40 p-6">
          <h2 className="text-lg font-semibold text-white mb-4">{hubId} fair-value vs spot</h2>
          {loading && <div className="h-48 flex items-center justify-center text-slate-500"><Loader2 className="w-5 h-5 animate-spin mr-2" /> Running ciq-price-engine...</div>}
          {!loading && result && (
            <div className="grid grid-cols-4 gap-4">
              <Stat label="Spot"        value={result.current_spot?.toFixed(2)} unit="€/MWh" color="text-slate-200" />
              <Stat label="Fair value"  value={result.fair_value_eur_mwh?.toFixed(2)} unit="€/MWh" color="text-violet-300" />
              <Stat label="σ"           value={result.sigma?.toFixed(2)} unit="€/MWh" color="text-cyan-300" />
              <Stat label="z-score"     value={result.z_score?.toFixed(2)} unit="σ" color={Math.abs(result.z_score ?? 0) >= 2 ? 'text-rose-300' : 'text-emerald-300'} />
              <div className="col-span-4 mt-2">
                <p className="text-xs text-slate-500">Verdict</p>
                <p className={`text-2xl font-bold uppercase ${verdictColor}`}>{result.verdict ?? '—'}</p>
                {result.anomaly_flag && (
                  <p className="text-xs text-rose-300 mt-1 flex items-center gap-1.5"><AlertOctagon className="w-3.5 h-3.5" /> IsolationForest flagged this residual.</p>
                )}
              </div>
            </div>
          )}
        </section>

        <section className="col-span-4 rounded-xl border border-slate-800 bg-slate-900/40 p-6">
          <h2 className="text-sm font-semibold text-white mb-4">Stress test</h2>
          <div className="space-y-3">
            <div>
              <div className="flex justify-between mb-1">
                <span className="text-[11px] text-slate-500 uppercase tracking-wider">Shock</span>
                <span className="text-xs font-mono text-slate-300">{stress >= 0 ? '+' : ''}{(stress * 100).toFixed(0)}%</span>
              </div>
              <input type="range" min={-1} max={1} step={0.05} value={stress} onChange={e => setStress(Number(e.target.value))} className="w-full" />
            </div>
            <button onClick={run} disabled={loading} className="w-full px-3 py-2 text-xs bg-violet-600/80 hover:bg-violet-600 disabled:bg-slate-700 text-white rounded-md inline-flex items-center justify-center gap-2">
              {loading ? <><Loader2 className="w-3 h-3 animate-spin" /> Running</> : 'Re-run agent'}
            </button>
          </div>
        </section>
      </div>

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
        <h2 className="text-sm font-semibold text-white mb-3">Driver coefficients</h2>
        {(!result?.drivers || result.drivers.length === 0) ? (
          <p className="text-xs text-slate-500">No driver data yet.</p>
        ) : (
          <ul className="space-y-3">
            {result.drivers.slice(0, 8).map(d => {
              const v = d.coef;
              const mag = Math.min(100, Math.abs(v) * 30);
              return (
                <li key={d.feature}>
                  <div className="flex items-baseline justify-between mb-1">
                    <span className="text-xs text-slate-300 font-mono">{d.feature}</span>
                    <span className={`text-xs font-mono ${v >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{v >= 0 ? '+' : '−'}{Math.abs(v).toFixed(3)}</span>
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
    </div>
  );
}

function Stat({ label, value, unit, color }: { label: string; value?: string; unit: string; color: string }) {
  return (
    <div>
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`text-2xl font-bold font-mono ${color}`}>{value ?? '—'}</p>
      <p className="text-[10px] text-slate-600">{unit}</p>
    </div>
  );
}
