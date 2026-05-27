'use client';

import { useMemo, useState } from 'react';
import { LineChart, AlertOctagon, Layers, Cpu, BarChart3, Activity } from 'lucide-react';

type Hub = 'TTF' | 'THE' | 'CEGH' | 'PSV' | 'DE-Power' | 'HU-Power' | 'PL-Power' | 'IT-Power';

const HUBS: { id: Hub; commodity: 'gas' | 'power' }[] = [
  { id: 'TTF',  commodity: 'gas' },
  { id: 'THE',  commodity: 'gas' },
  { id: 'CEGH', commodity: 'gas' },
  { id: 'PSV',  commodity: 'gas' },
  { id: 'DE-Power', commodity: 'power' },
  { id: 'HU-Power', commodity: 'power' },
  { id: 'PL-Power', commodity: 'power' },
  { id: 'IT-Power', commodity: 'power' },
];

const TENORS = ['M+1', 'M+2', 'Q+1', 'Q+2', 'Cal+1', 'Cal+2'];

interface LayerCurve { fundamental: number; econometric: number; ml: number; }
const HUB_BASE: Record<Hub, LayerCurve> = {
  TTF:      { fundamental: 34.2, econometric: 35.1, ml: 33.8 },
  THE:      { fundamental: 34.5, econometric: 35.4, ml: 34.1 },
  CEGH:     { fundamental: 34.7, econometric: 35.6, ml: 34.3 },
  PSV:      { fundamental: 35.1, econometric: 36.0, ml: 34.7 },
  'DE-Power': { fundamental: 92.5,  econometric: 95.1, ml: 91.3 },
  'HU-Power': { fundamental: 110.2, econometric: 113.0, ml: 108.7 },
  'PL-Power': { fundamental: 88.5,  econometric: 90.4, ml: 87.1 },
  'IT-Power': { fundamental: 105.6, econometric: 108.2, ml: 104.4 },
};

function buildCurve(hub: Hub, wFund: number, wEcon: number, wML: number, stress: number) {
  const base = HUB_BASE[hub];
  const wSum = wFund + wEcon + wML;
  return TENORS.map((tenor, i) => {
    const seasonal = 1 + 0.04 * Math.sin((i / TENORS.length) * Math.PI);
    const fundamental = base.fundamental * seasonal * (1 + stress * 0.15);
    const econometric = base.econometric * seasonal * (1 + stress * 0.10);
    const ml = base.ml * seasonal * (1 + stress * 0.07);
    const blended = (fundamental * wFund + econometric * wEcon + ml * wML) / wSum;
    const residual = ml - blended;
    const zScore = residual / (blended * 0.025);
    return { tenor, fundamental, econometric, ml, blended, residual, zScore };
  });
}

const STRESS_TESTS = [
  { id: 'cold-winter',     name: 'Cold winter shock',   stress: 0.8, narrative: 'Sustained sub-zero across CEE; storage withdrawal accelerates; front-month spikes.' },
  { id: 'pipeline-outage', name: 'Pipeline outage',     stress: 0.5, narrative: 'Force-majeure on a major import corridor; basis blows out for ~3 weeks.' },
  { id: 'co2-surge',       name: 'CO₂ price surge',     stress: 0.3, narrative: 'EUA price climbs > €100/t; clean-spark spreads collapse, gas-fired dispatch falls.' },
  { id: 'mild-mediterr',   name: 'Mild Mediterranean',  stress: -0.4, narrative: 'Above-average temperatures across IT/HU; storage stays full; front collapses.' },
];

export default function PriceEnginePage() {
  const [hub, setHub] = useState<Hub>('TTF');
  const [wFund, setWFund] = useState(40);
  const [wEcon, setWEcon] = useState(35);
  const [wML, setWML] = useState(25);
  const [stress, setStress] = useState(0);

  const curve = useMemo(() => buildCurve(hub, wFund, wEcon, wML, stress), [hub, wFund, wEcon, wML, stress]);
  const unit = hub.endsWith('Power') ? '€/MWh' : '€/MWh';
  const yMax = Math.max(...curve.flatMap(p => [p.fundamental, p.econometric, p.ml, p.blended])) * 1.05;
  const yMin = Math.min(...curve.flatMap(p => [p.fundamental, p.econometric, p.ml, p.blended])) * 0.95;
  const w = 920, h = 280;
  const xs = (i: number) => 50 + (i / (TENORS.length - 1)) * (w - 70);
  const ys = (v: number) => h - 30 - ((v - yMin) / (yMax - yMin)) * (h - 60);

  const layerPath = (key: 'fundamental' | 'econometric' | 'ml' | 'blended') =>
    curve.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xs(i)} ${ys(p[key])}`).join(' ');

  const flagged = curve.filter(p => Math.abs(p.zScore) > 2);

  return (
    <div className="min-h-screen text-slate-200 p-8 max-w-[1400px] mx-auto">
      <header className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <LineChart className="w-7 h-7 text-violet-400" />
          <h1 className="text-3xl font-bold text-white">Dynamic Forward Price Engine</h1>
        </div>
        <p className="text-slate-400 max-w-3xl">
          Three-layer hybrid — fundamental balance, econometric (cointegration + GARCH), and ML (BayesianRidge fair-value).
          Blend per hub. Residuals from the median feed an IsolationForest anomaly score → mispricing signal.
        </p>
      </header>

      <div className="flex flex-wrap gap-2 mb-4">
        {HUBS.map(h => (
          <button
            key={h.id}
            onClick={() => setHub(h.id)}
            className={`px-3 py-1.5 rounded-md text-xs border transition-colors ${
              hub === h.id
                ? 'bg-violet-500/15 text-violet-200 border-violet-500/40'
                : 'bg-slate-900/40 text-slate-400 border-slate-800 hover:bg-slate-800/60 hover:text-white'
            }`}
          >
            {h.id} <span className="text-[9px] text-slate-500 ml-1">{h.commodity}</span>
          </button>
        ))}
      </div>

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-6 mb-6">
        <div className="flex items-baseline justify-between mb-3">
          <h2 className="text-lg font-semibold text-white">{hub} forward curve — three layers + blend</h2>
          <p className="text-xs text-slate-500">{unit}</p>
        </div>
        <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-auto">
          {[0, 0.25, 0.5, 0.75, 1].map(g => {
            const y = 30 + g * (h - 60);
            return <line key={g} x1="50" x2={w - 20} y1={y} y2={y} stroke="#1e293b" strokeDasharray="2 4" strokeWidth="0.5" />;
          })}
          <path d={layerPath('fundamental')} stroke="#06b6d4" strokeWidth="1.5" fill="none" strokeDasharray="4 3" />
          <path d={layerPath('econometric')} stroke="#a78bfa" strokeWidth="1.5" fill="none" strokeDasharray="4 3" />
          <path d={layerPath('ml')}          stroke="#f59e0b" strokeWidth="1.5" fill="none" strokeDasharray="4 3" />
          <path d={layerPath('blended')}     stroke="#10b981" strokeWidth="3" fill="none" />
          {curve.map((p, i) => (
            <circle key={p.tenor} cx={xs(i)} cy={ys(p.blended)} r="3" fill="#0B0F19" stroke="#10b981" strokeWidth="2" />
          ))}
          {curve.map((p, i) => (
            <text key={p.tenor + 'l'} x={xs(i)} y={h - 8} textAnchor="middle" fill="#64748b" fontSize="10">{p.tenor}</text>
          ))}
        </svg>
        <div className="flex items-center gap-4 mt-3 text-[11px]">
          <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 bg-cyan-400 inline-block"></span><span className="text-slate-400">Fundamental</span></span>
          <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 bg-violet-400 inline-block"></span><span className="text-slate-400">Econometric</span></span>
          <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 bg-amber-400 inline-block"></span><span className="text-slate-400">ML fair-value</span></span>
          <span className="flex items-center gap-1.5"><span className="w-4 h-0.5 bg-emerald-500 inline-block"></span><span className="text-slate-300 font-semibold">Blended</span></span>
        </div>
      </section>

      <div className="grid grid-cols-12 gap-6">
        <section className="col-span-4 rounded-xl border border-slate-800 bg-slate-900/40 p-6">
          <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-1.5"><Layers className="w-3.5 h-3.5 text-violet-400" /> Layer weights</h2>
          {[
            { label: 'Fundamental', value: wFund, set: setWFund, color: 'cyan' },
            { label: 'Econometric', value: wEcon, set: setWEcon, color: 'violet' },
            { label: 'ML fair-value', value: wML, set: setWML, color: 'amber' },
          ].map(L => (
            <div key={L.label} className="mb-4 last:mb-0">
              <div className="flex justify-between mb-1">
                <span className="text-[11px] text-slate-500 uppercase tracking-wider">{L.label}</span>
                <span className="text-xs font-mono text-slate-300">{L.value}%</span>
              </div>
              <input type="range" min={0} max={100} value={L.value} onChange={e => L.set(Number(e.target.value))} className="w-full" />
            </div>
          ))}
          <p className="text-[10px] text-slate-600 mt-2">Total {wFund + wEcon + wML}% — renormalised internally.</p>
        </section>

        <section className="col-span-4 rounded-xl border border-slate-800 bg-slate-900/40 p-6">
          <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-1.5"><Cpu className="w-3.5 h-3.5 text-emerald-400" /> Stress test</h2>
          <div className="space-y-2 mb-4">
            {STRESS_TESTS.map(s => (
              <button
                key={s.id}
                onClick={() => setStress(s.stress)}
                className={`w-full text-left p-2.5 rounded-md border text-xs transition-colors ${
                  Math.abs(stress - s.stress) < 0.01
                    ? 'bg-emerald-500/15 border-emerald-500/50 text-emerald-100'
                    : 'bg-slate-950/40 border-slate-800 hover:bg-slate-800/40 text-slate-300'
                }`}
              >
                <p className="font-semibold">{s.name}</p>
                <p className="text-[10px] text-slate-500 mt-0.5">{s.narrative}</p>
              </button>
            ))}
          </div>
          <div className="mt-3 pt-3 border-t border-slate-800">
            <div className="flex justify-between mb-1">
              <span className="text-[11px] text-slate-500 uppercase tracking-wider">Custom stress</span>
              <span className="text-xs font-mono text-slate-300">{stress >= 0 ? '+' : ''}{(stress * 100).toFixed(0)}%</span>
            </div>
            <input type="range" min={-1} max={1} step={0.05} value={stress} onChange={e => setStress(Number(e.target.value))} className="w-full" />
          </div>
        </section>

        <section className="col-span-4 rounded-xl border border-slate-800 bg-slate-900/40 p-6">
          <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-1.5">
            <AlertOctagon className="w-3.5 h-3.5 text-rose-400" /> Mispricing flags
          </h2>
          {flagged.length === 0 ? (
            <p className="text-xs text-slate-500">No tenor with |z| &gt; 2 — layers agree to within ±2σ.</p>
          ) : (
            <ul className="space-y-2 text-xs">
              {flagged.map(p => (
                <li key={p.tenor} className="rounded-md border border-rose-500/20 bg-rose-500/5 p-2.5">
                  <p className="text-rose-300 font-semibold">{hub} {p.tenor}</p>
                  <p className="text-slate-400 mt-0.5">
                    ML fair-value {p.ml.toFixed(2)} vs blended {p.blended.toFixed(2)} → z {p.zScore.toFixed(2)}σ
                  </p>
                  <button className="mt-2 text-[10px] uppercase tracking-wider bg-rose-500/15 text-rose-300 px-2 py-1 rounded border border-rose-500/30 hover:bg-rose-500/25">
                    → Route to Approvals
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section className="mt-6 rounded-xl border border-slate-800 bg-slate-900/40 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-900/80 text-[10px] text-slate-500 uppercase tracking-wider">
            <tr>
              <th className="text-left px-4 py-2.5">Tenor</th>
              <th className="text-right px-4 py-2.5">Fundamental</th>
              <th className="text-right px-4 py-2.5">Econometric</th>
              <th className="text-right px-4 py-2.5">ML fair-value</th>
              <th className="text-right px-4 py-2.5">Blended</th>
              <th className="text-right px-4 py-2.5">Residual</th>
              <th className="text-right px-4 py-2.5">|z|</th>
            </tr>
          </thead>
          <tbody>
            {curve.map(p => (
              <tr key={p.tenor} className={`border-t border-slate-800/60 ${Math.abs(p.zScore) > 2 ? 'bg-rose-500/5' : ''}`}>
                <td className="px-4 py-2.5 text-white font-medium">{p.tenor}</td>
                <td className="px-4 py-2.5 text-right font-mono text-xs text-cyan-300">{p.fundamental.toFixed(2)}</td>
                <td className="px-4 py-2.5 text-right font-mono text-xs text-violet-300">{p.econometric.toFixed(2)}</td>
                <td className="px-4 py-2.5 text-right font-mono text-xs text-amber-300">{p.ml.toFixed(2)}</td>
                <td className="px-4 py-2.5 text-right font-mono text-xs text-emerald-300 font-semibold">{p.blended.toFixed(2)}</td>
                <td className="px-4 py-2.5 text-right font-mono text-xs text-slate-400">{p.residual > 0 ? '+' : ''}{p.residual.toFixed(2)}</td>
                <td className={`px-4 py-2.5 text-right font-mono text-xs ${Math.abs(p.zScore) > 2 ? 'text-rose-300 font-semibold' : 'text-slate-500'}`}>{Math.abs(p.zScore).toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
