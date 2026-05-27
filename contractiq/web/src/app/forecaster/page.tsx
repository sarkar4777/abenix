'use client';

import { useMemo, useState } from 'react';
import { TrendingUp, Thermometer, Factory, Users, Database, Sparkles } from 'lucide-react';

type Surface = 'residential' | 'industrial' | 'storage';

const SURFACE_META: Record<Surface, { label: string; icon: any; unit: string; model: string; horizon: string }> = {
  residential: { label: 'Residential / SME', icon: Users, unit: 'GWh/day', model: 'Prophet + XGBoost', horizon: '14 days' },
  industrial:  { label: 'Industrial baseload', icon: Factory, unit: 'GWh/day', model: 'LSTM sequence',    horizon: '14 days' },
  storage:     { label: 'Storage cycling',    icon: Database, unit: 'GWh/day', model: 'XGBoost + LP',     horizon: '90 days' },
};

function fanCurve(surface: Surface, tempShift: number, demandShift: number, churn: number) {
  const points: { t: number; p10: number; p50: number; p90: number }[] = [];
  const base = surface === 'residential' ? 320 : surface === 'industrial' ? 410 : 180;
  for (let t = 0; t < 14; t++) {
    const seasonality = surface === 'residential' ? 35 * Math.sin((t / 14) * Math.PI * 2) : 0;
    const tempEffect = -tempShift * (surface === 'residential' ? 12 : 2);
    const demandEffect = demandShift * 30;
    const churnEffect = -churn * 25;
    const p50 = base + seasonality + tempEffect + demandEffect + churnEffect + Math.sin(t * 0.7) * 10;
    const spread = surface === 'residential' ? 22 : surface === 'industrial' ? 14 : 28;
    points.push({ t, p10: p50 - spread, p50, p90: p50 + spread });
  }
  return points;
}

const DRIVERS: Record<Surface, { label: string; impact: number; sign: '+' | '-' }[]> = {
  residential: [
    { label: 'HDD next 7 days',                  impact: 38, sign: '+' },
    { label: 'Calendar (mid-week)',              impact: 22, sign: '+' },
    { label: 'Wholesale price elasticity',       impact: 14, sign: '-' },
    { label: 'Customer mix (post-acquisition)',  impact: 11, sign: '+' },
    { label: 'Retention churn drag',             impact:  8, sign: '-' },
  ],
  industrial: [
    { label: 'Sector PMI (manufacturing)',       impact: 31, sign: '+' },
    { label: 'Plant utilisation flag',           impact: 27, sign: '+' },
    { label: 'Historical baseload cluster',      impact: 18, sign: '+' },
    { label: 'Power-price elasticity',           impact: 14, sign: '-' },
    { label: 'Maintenance window',               impact:  6, sign: '-' },
  ],
  storage: [
    { label: 'Front-month vs winter spread',     impact: 41, sign: '+' },
    { label: 'Days to withdrawal window',        impact: 23, sign: '+' },
    { label: 'Injection capacity remaining',     impact: 19, sign: '+' },
    { label: 'Linepack constraint',              impact: 11, sign: '-' },
    { label: 'Cross-hub basis (TTF-THE)',        impact:  6, sign: '+' },
  ],
};

const SCENARIOS = [
  { id: 'cold-snap',     name: 'Cold-snap shock',      tempShift: -4, demandShift: 0,    churn: 0,   color: 'cyan' },
  { id: 'industrial',    name: 'Industrial pull-back', tempShift:  0, demandShift: -0.3, churn: 0,   color: 'amber' },
  { id: 'churn-event',   name: 'Retail churn event',   tempShift:  0, demandShift: 0,    churn: 0.4, color: 'rose' },
  { id: 'mild-winter',   name: 'Mild winter',          tempShift:  3, demandShift: 0,    churn: 0,   color: 'emerald' },
];

export default function ForecasterPage() {
  const [surface, setSurface] = useState<Surface>('residential');
  const [tempShift, setTempShift] = useState(0);
  const [demandShift, setDemandShift] = useState(0);
  const [churn, setChurn] = useState(0);

  const curve = useMemo(() => fanCurve(surface, tempShift, demandShift, churn), [surface, tempShift, demandShift, churn]);
  const meta = SURFACE_META[surface];

  const yMin = Math.min(...curve.map(p => p.p10)) - 20;
  const yMax = Math.max(...curve.map(p => p.p90)) + 20;
  const w = 920;
  const h = 280;
  const xs = (t: number) => 40 + (t / 13) * (w - 60);
  const ys = (v: number) => h - 30 - ((v - yMin) / (yMax - yMin)) * (h - 60);

  const fanPath = curve.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xs(p.t)} ${ys(p.p90)}`).join(' ')
    + ' ' + curve.slice().reverse().map(p => `L ${xs(p.t)} ${ys(p.p10)}`).join(' ') + ' Z';
  const medianPath = curve.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xs(p.t)} ${ys(p.p50)}`).join(' ');

  return (
    <div className="min-h-screen text-slate-200 p-8 max-w-[1400px] mx-auto">
      <header className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <TrendingUp className="w-7 h-7 text-emerald-400" />
          <h1 className="text-3xl font-bold text-white">Predictive Offtake Forecaster</h1>
        </div>
        <p className="text-slate-400 max-w-3xl">
          ML demand models for residential, industrial, and storage offtake surfaces — hourly to annual horizons, with
          live what-if sliders and cited drivers.
        </p>
      </header>

      <div className="grid grid-cols-3 gap-3 mb-6">
        {(Object.keys(SURFACE_META) as Surface[]).map(s => {
          const m = SURFACE_META[s];
          const Ic = m.icon;
          const active = surface === s;
          return (
            <button
              key={s}
              onClick={() => setSurface(s)}
              className={`rounded-xl border p-4 text-left transition-all ${
                active ? 'border-emerald-500/50 bg-emerald-500/10' : 'border-slate-800 bg-slate-900/40 hover:bg-slate-800/40'
              }`}
            >
              <div className="flex items-center gap-2 mb-1.5">
                <Ic className={`w-5 h-5 ${active ? 'text-emerald-400' : 'text-slate-500'}`} />
                <span className={`text-sm font-semibold ${active ? 'text-white' : 'text-slate-300'}`}>{m.label}</span>
              </div>
              <p className="text-[11px] text-slate-500"><span className="text-slate-400 font-mono">{m.model}</span> · horizon {m.horizon} · {m.unit}</p>
            </button>
          );
        })}
      </div>

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-6 mb-6">
        <div className="flex items-baseline justify-between mb-3">
          <h2 className="text-lg font-semibold text-white">14-day fan chart</h2>
          <p className="text-xs text-slate-500">P10 / P50 / P90 · {meta.unit}</p>
        </div>
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
          {curve.map(p => (
            <circle key={p.t} cx={xs(p.t)} cy={ys(p.p50)} r="2.5" fill="#0B0F19" stroke="#10b981" strokeWidth="2" />
          ))}
          {[0, 7, 13].map(t => (
            <text key={t} x={xs(t)} y={h - 8} textAnchor="middle" fill="#64748b" fontSize="10">
              {t === 0 ? 'today' : `+${t}d`}
            </text>
          ))}
          <text x="36" y="30" textAnchor="end" fill="#64748b" fontSize="10">{yMax.toFixed(0)}</text>
          <text x="36" y={h - 30} textAnchor="end" fill="#64748b" fontSize="10">{yMin.toFixed(0)}</text>
        </svg>
      </section>

      <div className="grid grid-cols-3 gap-6">
        <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
          <h2 className="text-sm font-semibold text-white mb-4">Live what-if</h2>
          <div className="space-y-5">
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-[11px] text-slate-500 uppercase tracking-wider flex items-center gap-1.5"><Thermometer className="w-3 h-3" /> Temperature shift</label>
                <span className="text-xs font-mono text-cyan-300">{tempShift > 0 ? '+' : ''}{tempShift} °C</span>
              </div>
              <input type="range" min={-8} max={8} step={1} value={tempShift} onChange={e => setTempShift(Number(e.target.value))} className="w-full" />
            </div>
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-[11px] text-slate-500 uppercase tracking-wider flex items-center gap-1.5"><Factory className="w-3 h-3" /> Demand shock</label>
                <span className="text-xs font-mono text-cyan-300">{(demandShift * 100).toFixed(0)}%</span>
              </div>
              <input type="range" min={-0.5} max={0.5} step={0.05} value={demandShift} onChange={e => setDemandShift(Number(e.target.value))} className="w-full" />
            </div>
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-[11px] text-slate-500 uppercase tracking-wider flex items-center gap-1.5"><Users className="w-3 h-3" /> Churn rate</label>
                <span className="text-xs font-mono text-cyan-300">{(churn * 100).toFixed(0)}%</span>
              </div>
              <input type="range" min={0} max={0.6} step={0.05} value={churn} onChange={e => setChurn(Number(e.target.value))} className="w-full" />
            </div>
            <button onClick={() => { setTempShift(0); setDemandShift(0); setChurn(0); }} className="w-full mt-2 text-xs text-slate-400 hover:text-white border border-slate-800 rounded-md py-2">Reset</button>
          </div>
        </section>

        <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
          <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-1.5"><Sparkles className="w-3.5 h-3.5 text-emerald-400" /> Top drivers (SHAP)</h2>
          <ul className="space-y-3">
            {DRIVERS[surface].map(d => (
              <li key={d.label}>
                <div className="flex items-baseline justify-between mb-1">
                  <span className="text-xs text-slate-300">{d.label}</span>
                  <span className={`text-xs font-mono ${d.sign === '+' ? 'text-emerald-400' : 'text-rose-400'}`}>{d.sign}{d.impact}</span>
                </div>
                <div className="h-1.5 bg-slate-800 rounded overflow-hidden">
                  <div className={`h-full ${d.sign === '+' ? 'bg-emerald-500/70' : 'bg-rose-500/70'}`} style={{ width: `${d.impact * 2}%` }} />
                </div>
              </li>
            ))}
          </ul>
        </section>

        <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
          <h2 className="text-sm font-semibold text-white mb-3">Pre-baked scenarios</h2>
          <div className="space-y-2">
            {SCENARIOS.map(s => (
              <button
                key={s.id}
                onClick={() => { setTempShift(s.tempShift); setDemandShift(s.demandShift); setChurn(s.churn); }}
                className="w-full text-left p-3 rounded-md border border-slate-800 bg-slate-950/40 hover:bg-slate-800/40 transition-colors group"
              >
                <p className="text-xs font-semibold text-white">{s.name}</p>
                <p className="text-[10px] text-slate-500 mt-0.5 font-mono">ΔT {s.tempShift > 0 ? '+' : ''}{s.tempShift} · ΔD {(s.demandShift * 100).toFixed(0)}% · Churn {(s.churn * 100).toFixed(0)}%</p>
              </button>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
