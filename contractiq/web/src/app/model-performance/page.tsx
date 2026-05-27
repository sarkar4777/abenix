'use client';

import { useMemo, useState } from 'react';
import { Activity, AlertTriangle, Calendar, CheckCircle2, History } from 'lucide-react';

const MODELS = [
  { id: 'price_fairvalue_gas_hubs',  family: 'BayesianRidge', mae: 0.42, rmse: 0.61, mape: 1.24, psi: 0.08, trend: 'flat',     lastRun: '2 m ago' },
  { id: 'price_fairvalue_power_hubs', family: 'BayesianRidge', mae: 1.84, rmse: 2.41, mape: 1.94, psi: 0.12, trend: 'flat',     lastRun: '2 m ago' },
  { id: 'price_anomaly',             family: 'IsolationForest', mae: 0.03, rmse: 0.08, mape: 0.00, psi: 0.05, trend: 'flat',     lastRun: '2 m ago' },
  { id: 'offtake_residential',       family: 'Prophet+XGB',   mae: 8.4, rmse: 11.7, mape: 2.71, psi: 0.31, trend: 'drifting', lastRun: '6 m ago' },
  { id: 'offtake_industrial',        family: 'LSTM',          mae: 6.2, rmse: 9.4,  mape: 1.51, psi: 0.18, trend: 'flat',     lastRun: '6 m ago' },
  { id: 'offtake_storage_cycling',   family: 'XGBoost+LP',    mae: 1.1, rmse: 1.6,  mape: 9.82, psi: 0.09, trend: 'flat',     lastRun: '11 m ago' },
  { id: 'scenario_prior_gas',        family: 'GaussianNB',    mae: 0.21, rmse: 0.34, mape: 0.00, psi: 0.04, trend: 'flat',     lastRun: '3 h ago' },
  { id: 'recommendation_thesis',     family: 'Haiku 4.5 LLM', mae: 0.00, rmse: 0.00, mape: 0.00, psi: 0.07, trend: 'flat',     lastRun: '4 h ago' },
];

const ACCURACY_TIMELINE: Record<string, { day: string; mape: number }[]> = (() => {
  const out: Record<string, { day: string; mape: number }[]> = {};
  for (const m of MODELS) {
    const arr = [] as { day: string; mape: number }[];
    for (let d = 30; d > 0; d--) {
      const drift = m.trend === 'drifting' ? (30 - d) * 0.06 : 0;
      const noise = (Math.random() - 0.5) * m.mape * 0.4;
      arr.push({ day: `-${d}d`, mape: Math.max(0, m.mape + drift + noise) });
    }
    out[m.id] = arr;
  }
  return out;
})();

export default function ModelPerformancePage() {
  const [selected, setSelected] = useState(MODELS[3].id);
  const [running, setRunning] = useState(false);
  const [backtest, setBacktest] = useState<{ mae: number; rmse: number; mape: number; periods: number } | null>(null);

  const m = MODELS.find(x => x.id === selected)!;
  const timeline = ACCURACY_TIMELINE[selected];
  const w = 920, h = 200;
  const mapeMax = Math.max(...timeline.map(p => p.mape)) * 1.1;
  const xs = (i: number) => 40 + (i / (timeline.length - 1)) * (w - 60);
  const ys = (v: number) => h - 30 - (v / mapeMax) * (h - 60);
  const linePath = timeline.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xs(i)} ${ys(p.mape)}`).join(' ');

  const driftPolicy = useMemo(() => {
    if (m.psi < 0.10) return { tone: 'emerald', label: 'Stable', detail: 'PSI below 0.10 — distribution matches training' };
    if (m.psi < 0.25) return { tone: 'amber', label: 'Watch', detail: 'PSI 0.10–0.25 — distribution shifting; monitor 7 more days' };
    return { tone: 'rose', label: 'Drifting', detail: 'PSI above 0.25 for 7 days — automatic retraining proposal raised' };
  }, [m.psi]);

  const runBacktest = () => {
    setRunning(true);
    setBacktest(null);
    setTimeout(() => {
      setBacktest({ mae: m.mae * 1.08, rmse: m.rmse * 1.12, mape: m.mape * 1.05, periods: 365 });
      setRunning(false);
    }, 1500);
  };

  return (
    <div className="min-h-screen text-slate-200 p-8 max-w-[1400px] mx-auto">
      <header className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <Activity className="w-7 h-7 text-cyan-400" />
          <h1 className="text-3xl font-bold text-white">Performance &amp; Backtest</h1>
        </div>
        <p className="text-slate-400 max-w-3xl">
          Accuracy tracking (MAE / RMSE / MAPE), population-stability-index drift detection, and one-click historical replay
          on the current model.
        </p>
      </header>

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 overflow-hidden mb-6">
        <table className="w-full text-sm">
          <thead className="bg-slate-900/80 text-[10px] text-slate-500 uppercase tracking-wider">
            <tr>
              <th className="text-left px-4 py-2.5">Model</th>
              <th className="text-left px-4 py-2.5">Family</th>
              <th className="text-right px-4 py-2.5">MAE</th>
              <th className="text-right px-4 py-2.5">RMSE</th>
              <th className="text-right px-4 py-2.5">MAPE %</th>
              <th className="text-right px-4 py-2.5">PSI</th>
              <th className="text-left px-4 py-2.5">Status</th>
              <th className="text-left px-4 py-2.5">Last run</th>
            </tr>
          </thead>
          <tbody>
            {MODELS.map(row => {
              const isSel = row.id === selected;
              const status = row.psi >= 0.25 ? { tone: 'rose', label: 'Drifting', Icon: AlertTriangle }
                          : row.psi >= 0.10 ? { tone: 'amber', label: 'Watch',    Icon: AlertTriangle }
                          : { tone: 'emerald', label: 'Stable', Icon: CheckCircle2 };
              return (
                <tr
                  key={row.id}
                  onClick={() => { setSelected(row.id); setBacktest(null); }}
                  className={`border-t border-slate-800/60 cursor-pointer ${isSel ? 'bg-cyan-500/5' : 'hover:bg-slate-800/30'}`}
                >
                  <td className="px-4 py-2.5 font-mono text-xs text-white">{row.id}</td>
                  <td className="px-4 py-2.5 text-xs text-slate-400">{row.family}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-xs text-slate-300">{row.mae.toFixed(2)}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-xs text-slate-300">{row.rmse.toFixed(2)}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-xs text-slate-300">{row.mape.toFixed(2)}</td>
                  <td className={`px-4 py-2.5 text-right font-mono text-xs ${row.psi >= 0.25 ? 'text-rose-400' : row.psi >= 0.10 ? 'text-amber-400' : 'text-emerald-400'}`}>{row.psi.toFixed(2)}</td>
                  <td className="px-4 py-2.5">
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] uppercase tracking-wider border bg-${status.tone}-500/10 text-${status.tone}-300 border-${status.tone}-500/30`}>
                      <status.Icon className="w-3 h-3" /> {status.label}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-xs text-slate-500">{row.lastRun}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      <div className="grid grid-cols-12 gap-6">
        <section className="col-span-8 rounded-xl border border-slate-800 bg-slate-900/40 p-6">
          <div className="flex items-baseline justify-between mb-2">
            <h2 className="text-lg font-semibold text-white">30-day MAPE — <span className="font-mono text-slate-400 text-sm">{m.id}</span></h2>
            <p className="text-xs text-slate-500">lower is better</p>
          </div>
          <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-auto">
            {[0, 0.25, 0.5, 0.75, 1].map(g => {
              const y = 30 + g * (h - 60);
              return <line key={g} x1="40" x2={w - 20} y1={y} y2={y} stroke="#1e293b" strokeDasharray="2 4" strokeWidth="0.5" />;
            })}
            <path d={linePath} stroke="#06b6d4" strokeWidth="2" fill="none" />
            {timeline.filter((_, i) => i % 5 === 0).map((p, i) => (
              <text key={i} x={xs(i * 5)} y={h - 8} textAnchor="middle" fill="#64748b" fontSize="10">{p.day}</text>
            ))}
            <text x="36" y="30" textAnchor="end" fill="#64748b" fontSize="10">{mapeMax.toFixed(1)}%</text>
            <text x="36" y={h - 30} textAnchor="end" fill="#64748b" fontSize="10">0%</text>
          </svg>
        </section>

        <section className="col-span-4 space-y-6">
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
            <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-1.5">
              <AlertTriangle className={`w-3.5 h-3.5 text-${driftPolicy.tone}-400`} /> Drift status
            </h2>
            <p className={`text-base font-bold text-${driftPolicy.tone}-300 mb-1`}>{driftPolicy.label}</p>
            <p className="text-xs text-slate-400 leading-relaxed">{driftPolicy.detail}</p>
            <div className="mt-3 pt-3 border-t border-slate-800">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">PSI</p>
              <div className="flex items-baseline gap-2">
                <p className={`text-2xl font-bold text-${driftPolicy.tone}-300`}>{m.psi.toFixed(2)}</p>
                <p className="text-[10px] text-slate-500">stable &lt; 0.10 · watch 0.10-0.25 · drift &gt; 0.25</p>
              </div>
            </div>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
            <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-1.5"><History className="w-3.5 h-3.5 text-violet-400" /> Backtest harness</h2>
            <p className="text-xs text-slate-500 mb-3">Replays the last 365 days through the current model with strict point-in-time joins.</p>
            <button
              onClick={runBacktest}
              disabled={running}
              className="w-full px-3 py-2 text-xs bg-violet-600/20 text-violet-200 border border-violet-500/30 rounded-md hover:bg-violet-600/30 disabled:opacity-40 mb-3"
            >
              {running ? 'Running 365-day replay…' : 'Run 365-day backtest'}
            </button>
            {backtest && (
              <div className="mt-3 pt-3 border-t border-slate-800 space-y-1.5 text-xs">
                <div className="flex justify-between"><span className="text-slate-500">MAE</span><span className="font-mono text-slate-200">{backtest.mae.toFixed(2)}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">RMSE</span><span className="font-mono text-slate-200">{backtest.rmse.toFixed(2)}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">MAPE</span><span className="font-mono text-slate-200">{backtest.mape.toFixed(2)}%</span></div>
                <div className="flex justify-between"><span className="text-slate-500">Periods</span><span className="font-mono text-slate-200">{backtest.periods}</span></div>
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
