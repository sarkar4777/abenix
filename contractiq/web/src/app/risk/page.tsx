'use client';

import { useEffect, useState } from 'react';
import { Activity, Loader2, AlertTriangle, BarChart3, Network } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

type VarRun = {
  id: string;
  method: string;
  confidence: number;
  horizon_days: number;
  var_pct: number;
  var_usd: number;
  cvar_pct: number;
  cvar_usd: number;
  n_observations: number;
  source: string;
  calc_signature: string;
};

const PRESETS = [
  { name: 'Gold spot · 1d 95% VaR · $10M', source: 'lbma_gold_fix', notional: 10_000_000, confidence: 0.95, horizon: 1, method: 'filtered_historical' },
  { name: 'Gold spot · 10d 99% VaR · $10M', source: 'lbma_gold_fix', notional: 10_000_000, confidence: 0.99, horizon: 10, method: 'filtered_historical' },
  { name: 'Silver spot · 1d 95% VaR · $5M', source: 'lbma_silver_price', notional: 5_000_000, confidence: 0.95, horizon: 1, method: 'historical' },
  { name: 'Platinum · 1d 99% VaR · $5M', source: 'lppm_platinum_fix', notional: 5_000_000, confidence: 0.99, horizon: 1, method: 'filtered_historical' },
  { name: 'Palladium · 1d 95% VaR · $5M', source: 'lppm_palladium_fix', notional: 5_000_000, confidence: 0.95, horizon: 1, method: 'filtered_historical' },
];

export default function RiskPage() {
  const [runs, setRuns] = useState<VarRun[]>([]);
  const [correlations, setCorrelations] = useState<Record<string, Record<string, number>> | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = async () => {
    const token = getToken();
    if (!token) return;
    const [rs, cs] = await Promise.all([
      fetch(`${API_URL}/api/contractiq/risk/runs`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${API_URL}/api/contractiq/risk/correlations`, { headers: { Authorization: `Bearer ${token}` } }),
    ]);
    setRuns((await rs.json()).data || []);
    setCorrelations((await cs.json()).data?.matrix || null);
  };
  useEffect(() => { load(); }, []);

  const runPreset = async (p: typeof PRESETS[number]) => {
    setBusy(p.name);
    const token = getToken();
    try {
      await fetch(`${API_URL}/api/contractiq/risk/var`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: p.source, notional_usd: p.notional, confidence: p.confidence, horizon_days: p.horizon, method: p.method }),
      });
      await load();
    } finally { setBusy(null); }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <div className="max-w-7xl mx-auto p-6 lg:p-10">
        <div className="flex items-center gap-3 mb-6">
          <Activity className="w-7 h-7 text-red-300" />
          <div>
            <h1 className="text-2xl font-bold text-white">Market Risk</h1>
            <p className="text-sm text-slate-400">VaR + CVaR — parametric, historical, filtered-historical. EWMA correlation matrix. Calc-signature stamped per run.</p>
          </div>
        </div>

        <div className="mb-8">
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-3">Quick presets</div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
            {PRESETS.map(p => (
              <button
                key={p.name}
                onClick={() => runPreset(p)}
                disabled={busy === p.name}
                className="p-3 rounded-lg bg-slate-900/60 border border-slate-800/80 hover:border-red-500/40 text-left disabled:opacity-50"
              >
                <div className="text-xs font-semibold text-white">{p.name}</div>
                <div className="text-[10px] text-slate-500 mt-0.5">{p.source} · {p.method}</div>
                {busy === p.name && <Loader2 className="w-3.5 h-3.5 animate-spin text-red-300 mt-1" />}
              </button>
            ))}
          </div>
        </div>

        <div className="mb-8">
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-3 flex items-center gap-1.5">
            <BarChart3 className="w-3.5 h-3.5" /> Runs
          </div>
          {runs.length === 0 ? (
            <div className="text-center py-12 text-sm text-slate-500">No risk runs yet.</div>
          ) : (
            <div className="overflow-x-auto rounded-xl bg-slate-900/60 border border-slate-800/80">
              <table className="w-full text-xs">
                <thead className="bg-slate-900/80 text-slate-500 uppercase tracking-wide text-[10px]">
                  <tr>
                    <th className="text-left p-3">Method</th>
                    <th className="text-left p-3">Source</th>
                    <th className="text-left p-3">CI / Horizon</th>
                    <th className="text-right p-3">VaR (USD)</th>
                    <th className="text-right p-3">CVaR (USD)</th>
                    <th className="text-right p-3">Obs</th>
                    <th className="text-left p-3">Signature</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map(r => (
                    <tr key={r.id} className="border-t border-slate-800/60">
                      <td className="p-3 font-medium">{r.method}</td>
                      <td className="p-3 text-slate-400 font-mono text-[11px]">{r.source}</td>
                      <td className="p-3 text-slate-400">{(r.confidence * 100).toFixed(1)}% · {r.horizon_days}d</td>
                      <td className="p-3 text-right text-red-300 font-bold">${(r.var_usd || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                      <td className="p-3 text-right text-amber-300 font-bold">${(r.cvar_usd || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                      <td className="p-3 text-right text-slate-400">{r.n_observations}</td>
                      <td className="p-3 text-slate-500 font-mono text-[10px]">{r.calc_signature?.slice(0, 12)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {correlations && Object.keys(correlations).length > 0 && (
          <div>
            <div className="text-xs uppercase tracking-wide text-slate-500 mb-3 flex items-center gap-1.5">
              <Network className="w-3.5 h-3.5" /> EWMA correlation matrix (λ=0.94 · 120 days)
            </div>
            <div className="overflow-x-auto rounded-xl bg-slate-900/60 border border-slate-800/80 p-4">
              <table className="text-xs">
                <thead>
                  <tr>
                    <th></th>
                    {Object.keys(correlations).map(k => (
                      <th key={k} className="px-2 py-1 text-slate-500 text-[10px] uppercase">{k.split('_')[0]}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(correlations).map(([row, cols]) => (
                    <tr key={row}>
                      <td className="px-2 py-1 text-slate-500 text-[10px] uppercase">{row.split('_')[0]}</td>
                      {Object.values(cols).map((v, i) => (
                        <td key={i} className="px-2 py-1 text-center">
                          <span style={{
                            backgroundColor: v > 0
                              ? `rgba(16, 185, 129, ${Math.min(Math.abs(v), 1) * 0.5})`
                              : `rgba(239, 68, 68, ${Math.min(Math.abs(v), 1) * 0.5})`,
                            color: 'white',
                            padding: '2px 6px',
                            borderRadius: '4px',
                            fontFamily: 'monospace',
                            fontSize: '11px',
                          }}>
                            {v?.toFixed(2)}
                          </span>
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
