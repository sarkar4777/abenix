'use client';

import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'next/navigation';
import { Gauge, Loader2, Play, ChevronLeft, TrendingDown, TrendingUp } from 'lucide-react';
import Link from 'next/link';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

type Scenario = { id: string; name: string; perturbations: Record<string, number | boolean> };
type Run = {
  id: string;
  scenario_name: string;
  perturbations: Record<string, any>;
  base_value_usd: number;
  scenario_value_usd: number;
  delta_usd: number;
  delta_pct: number;
  decomposition?: Array<{ driver: string; shock: string; delta_usd: number; rationale: string }>;
  narrative?: string;
  calc_signature?: string;
  created_at: string;
};

const ACCENT: Record<string, string> = {
  ppa: 'cyan', vppa: 'emerald', tolling: 'amber', gas: 'orange', metals: 'amber',
};

export default function WhatIfPage() {
  const { contractId } = useParams<{ contractId: string }>();
  const [contract, setContract] = useState<any>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [running, setRunning] = useState<string | null>(null);
  const [custom, setCustom] = useState<Record<string, string>>({});

  const load = async () => {
    const token = getToken();
    if (!token) return;
    const [c, s, r] = await Promise.all([
      fetch(`${API_URL}/api/contractiq/contracts/${contractId}`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${API_URL}/api/contractiq/whatif/scenarios`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${API_URL}/api/contractiq/whatif/contracts/${contractId}/runs`, { headers: { Authorization: `Bearer ${token}` } }),
    ]);
    const cj = await c.json();
    const sj = await s.json();
    const rj = await r.json();
    setContract(cj.data);
    const t = cj.data?.contract_type || 'ppa';
    const scenLibrary = (sj.data && (sj.data[t] || [])) as Scenario[];
    setScenarios(scenLibrary);
    setRuns(rj.data || []);
  };
  useEffect(() => { load(); }, [contractId]);

  const runScenario = async (scenarioName: string, perturbations: Record<string, any>) => {
    setRunning(scenarioName);
    const token = getToken();
    try {
      await fetch(`${API_URL}/api/contractiq/whatif/contracts/${contractId}/run`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario_name: scenarioName, perturbations, contract_type: contract?.contract_type }),
      });
      await load();
    } finally { setRunning(null); }
  };

  const runCustom = async () => {
    const parsed: Record<string, any> = {};
    for (const [k, v] of Object.entries(custom)) {
      if (v === '') continue;
      const n = Number(v);
      parsed[k] = Number.isFinite(n) ? n : v;
    }
    if (Object.keys(parsed).length === 0) return;
    await runScenario('Custom what-if', parsed);
    setCustom({});
  };

  const accent = ACCENT[contract?.contract_type] || 'cyan';
  const driverKeys = useMemo(() => {
    const s = new Set<string>();
    scenarios.forEach(sc => Object.keys(sc.perturbations).forEach(k => s.add(k)));
    return Array.from(s);
  }, [scenarios]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <div className="max-w-7xl mx-auto p-6 lg:p-10">
        <Link href={`/contracts/${contractId}`} className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 mb-4">
          <ChevronLeft className="w-3.5 h-3.5" /> Back to contract
        </Link>
        <div className="flex items-center gap-3 mb-6">
          <Gauge className={`w-7 h-7 text-${accent}-300`} />
          <div>
            <h1 className="text-2xl font-bold text-white">What-If Analysis</h1>
            <p className="text-sm text-slate-400">
              Type-aware scenarios for <span className={`text-${accent}-300 uppercase`}>{contract?.contract_type}</span>{contract?.asset_class && <> · {contract.asset_class}</>} contracts.
              Perturb a driver, watch the value re-price, get a per-driver decomposition.
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80">
            <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-2">Pre-built scenarios</div>
            <div className="space-y-1.5">
              {scenarios.map(s => (
                <button
                  key={s.id}
                  onClick={() => runScenario(s.name, s.perturbations)}
                  disabled={running === s.name}
                  className="w-full text-left px-3 py-2 rounded-md bg-slate-800/40 hover:bg-slate-800/80 border border-slate-800 flex items-center justify-between"
                >
                  <span className="text-xs">{s.name}</span>
                  {running === s.name ? <Loader2 className="w-3.5 h-3.5 animate-spin text-slate-500" /> : <Play className="w-3.5 h-3.5 text-slate-500" />}
                </button>
              ))}
            </div>
          </div>

          <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80">
            <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-2">Custom what-if</div>
            <div className="space-y-2">
              {driverKeys.map(k => (
                <div key={k} className="flex items-center justify-between gap-2">
                  <label className="text-xs text-slate-400 font-mono">{k}</label>
                  <input
                    value={custom[k] || ''}
                    onChange={e => setCustom({ ...custom, [k]: e.target.value })}
                    placeholder="value"
                    className="px-2 py-1 text-xs rounded bg-slate-800/60 border border-slate-700 text-slate-200 w-32"
                  />
                </div>
              ))}
              <button
                onClick={runCustom}
                disabled={running === 'Custom what-if'}
                className={`mt-3 w-full px-3 py-2 text-xs rounded-md bg-${accent}-500/20 border border-${accent}-500/40 text-${accent}-200 hover:bg-${accent}-500/30 disabled:opacity-50 flex items-center justify-center gap-1.5`}
              >
                {running === 'Custom what-if' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
                Run custom
              </button>
            </div>
          </div>
        </div>

        <div className="text-xs uppercase tracking-wide text-slate-500 mb-3">Scenarios run ({runs.length})</div>
        <div className="space-y-3">
          {runs.length === 0 && (
            <div className="text-center py-12 text-sm text-slate-500">No scenarios yet. Click one above to run.</div>
          )}
          {runs.map(r => (
            <div key={r.id} className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <div className="text-sm font-semibold text-white">{r.scenario_name}</div>
                  <div className="text-[10px] text-slate-500 mt-0.5">sig {r.calc_signature?.slice(0, 8)} · {new Date(r.created_at).toLocaleString()}</div>
                </div>
                <div className="text-right">
                  <div className="text-[10px] uppercase text-slate-500">Delta</div>
                  <div className={`text-lg font-bold flex items-center gap-1 ${r.delta_usd >= 0 ? 'text-emerald-300' : 'text-red-300'}`}>
                    {r.delta_usd >= 0 ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
                    {formatUsd(r.delta_usd)} ({r.delta_pct?.toFixed(2)}%)
                  </div>
                </div>
              </div>
              {r.narrative && <p className="text-xs text-slate-300 italic mb-2">{r.narrative}</p>}
              {r.decomposition && r.decomposition.length > 0 && (
                <table className="w-full text-xs">
                  <thead className="text-[10px] uppercase text-slate-500">
                    <tr>
                      <th className="text-left py-1">Driver</th>
                      <th className="text-left py-1">Shock</th>
                      <th className="text-right py-1">Delta USD</th>
                      <th className="text-left py-1 pl-3">Rationale</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.decomposition.map((d, i) => (
                      <tr key={i} className="border-t border-slate-800/40">
                        <td className="py-1 font-medium">{d.driver}</td>
                        <td className="py-1 text-slate-400">{d.shock}</td>
                        <td className={`py-1 text-right ${d.delta_usd >= 0 ? 'text-emerald-300' : 'text-red-300'}`}>{formatUsd(d.delta_usd)}</td>
                        <td className="py-1 text-slate-400 pl-3">{d.rationale}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function formatUsd(v: number): string {
  if (!v) return '$0';
  const sign = v < 0 ? '-' : '';
  const a = Math.abs(v);
  if (a >= 1_000_000) return `${sign}$${(a / 1_000_000).toFixed(2)}M`;
  if (a >= 1_000) return `${sign}$${(a / 1_000).toFixed(1)}k`;
  return `${sign}$${a.toFixed(0)}`;
}
