'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Activity, ChevronLeft, Sparkles, Loader2, Target, AlertTriangle,
} from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Tooltip, ReferenceLine,
} from 'recharts';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

interface StressTest {
  id: string;
  contract_id: string | null;
  scope: string;
  name: string;
  iterations: number;
  status: string;
  base_npv: number | null;
  p5_npv: number | null;
  p50_npv: number | null;
  p95_npv: number | null;
  var_95: number | null;
  expected_shortfall: number | null;
  distribution: any[] | null;
  worst_scenarios: any[] | null;
  summary_markdown: string | null;
  created_at: string;
}

interface Contract { id: string; title: string; }

function fmtMoney(n: number | null | undefined): string {
  if (n == null) return '—';
  if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  if (Math.abs(n) >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

export default function StressTestPage() {
  const [tests, setTests] = useState<StressTest[]>([]);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [contractId, setContractId] = useState('');
  const [scope, setScope] = useState<'single' | 'portfolio'>('single');
  const [iterations, setIterations] = useState(1000);
  const [powerShock, setPowerShock] = useState(30);
  const [fxShock, setFxShock] = useState(15);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    const token = getToken();
    if (!token) return;
    const [tRes, cRes] = await Promise.all([
      fetch(`${API_URL}/api/contractiq/insights/stress-test`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${API_URL}/api/contractiq/contracts?limit=200`, { headers: { Authorization: `Bearer ${token}` } }),
    ]);
    setTests((await tRes.json()).data || []);
    setContracts(((await cRes.json()).data || []).map((c: any) => ({ id: c.id, title: c.title })));
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const run = async () => {
    setRunning(true);
    const token = getToken();
    try {
      await fetch(`${API_URL}/api/contractiq/insights/stress-test`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scope,
          contract_id: scope === 'single' ? contractId : null,
          iterations,
          name: scope === 'portfolio' ? 'Portfolio stress test' : `Stress: ${contracts.find(c => c.id === contractId)?.title || 'contract'}`,
          scenario_params: {
            power_price_shock_pct: [-powerShock, powerShock],
            fx_shock_pct: [-fxShock, fxShock],
          },
        }),
      });
      await load();
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#0B0F19] p-8">
      <div className="max-w-6xl mx-auto">
        <div className="mb-6">
          <a href="/insights" className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-emerald-400 mb-2">
            <ChevronLeft className="w-3 h-3" /> Back to Insights Hub
          </a>
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-orange-500/20 to-red-600/20 border border-orange-500/30 flex items-center justify-center">
              <Activity className="w-6 h-6 text-orange-400" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white">Stress Test Simulator</h1>
              <p className="text-xs text-slate-400">Monte Carlo P&L distribution under market shocks via <code className="text-orange-300">contractiq-stress-test</code></p>
            </div>
          </div>
        </div>

        {/* Run form */}
        <div className="rounded-xl border border-orange-500/30 bg-orange-500/5 p-5 mb-8">
          <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2"><Sparkles className="w-4 h-4 text-orange-400" /> Configure Stress Test</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
            <div>
              <label className="text-[10px] text-slate-400 uppercase tracking-wider mb-1 block">Scope</label>
              <select value={scope} onChange={e => setScope(e.target.value as any)}
                className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:border-orange-500 focus:outline-none">
                <option value="single">Single contract</option>
                <option value="portfolio">Entire portfolio</option>
              </select>
            </div>
            {scope === 'single' && (
              <div className="md:col-span-2">
                <label className="text-[10px] text-slate-400 uppercase tracking-wider mb-1 block">Contract</label>
                <select value={contractId} onChange={e => setContractId(e.target.value)}
                  className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:border-orange-500 focus:outline-none">
                  <option value="">Select...</option>
                  {contracts.map(c => <option key={c.id} value={c.id}>{c.title}</option>)}
                </select>
              </div>
            )}
          </div>
          <div className="grid grid-cols-3 gap-3 mb-4">
            <div>
              <label className="text-[10px] text-slate-400 uppercase tracking-wider mb-1 block">Iterations: {iterations}</label>
              <input type="range" min="100" max="10000" step="100" value={iterations} onChange={e => setIterations(parseInt(e.target.value))} className="w-full accent-orange-500" />
            </div>
            <div>
              <label className="text-[10px] text-slate-400 uppercase tracking-wider mb-1 block">Power shock: ±{powerShock}%</label>
              <input type="range" min="5" max="50" value={powerShock} onChange={e => setPowerShock(parseInt(e.target.value))} className="w-full accent-orange-500" />
            </div>
            <div>
              <label className="text-[10px] text-slate-400 uppercase tracking-wider mb-1 block">FX shock: ±{fxShock}%</label>
              <input type="range" min="2" max="30" value={fxShock} onChange={e => setFxShock(parseInt(e.target.value))} className="w-full accent-orange-500" />
            </div>
          </div>
          <button onClick={run} disabled={running || (scope === 'single' && !contractId)}
            className="w-full px-4 py-2.5 rounded-lg bg-gradient-to-r from-orange-500 to-red-600 text-white text-sm font-semibold hover:shadow-lg hover:shadow-orange-500/25 disabled:opacity-50 flex items-center justify-center gap-2">
            {running ? <><Loader2 className="w-4 h-4 animate-spin" /> Running Monte Carlo...</> : <><Sparkles className="w-4 h-4" /> Run Stress Test</>}
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center h-40"><Loader2 className="w-6 h-6 animate-spin text-orange-400" /></div>
        ) : tests.length === 0 ? (
          <div className="rounded-xl border border-slate-800/50 bg-slate-900/30 p-12 text-center">
            <Activity className="w-12 h-12 text-orange-400/40 mx-auto mb-3" />
            <p className="text-sm text-slate-400">No stress tests run yet.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {tests.map((t) => {
              const isOpen = expanded === t.id;
              return (
                <div key={t.id} className="rounded-xl border border-slate-800/50 bg-slate-900/30 overflow-hidden">
                  <button onClick={() => setExpanded(isOpen ? null : t.id)} className="w-full p-4 hover:bg-slate-800/30 transition-colors text-left">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-sm font-semibold text-white">{t.name}</p>
                        <p className="text-[11px] text-slate-500">{t.iterations} iterations • {new Date(t.created_at).toLocaleString()}</p>
                      </div>
                      <div className="flex items-center gap-4 text-right">
                        <div>
                          <p className="text-[10px] text-slate-500 uppercase">Base NPV</p>
                          <p className="text-sm font-bold text-white tabular-nums">{fmtMoney(t.base_npv)}</p>
                        </div>
                        <div>
                          <p className="text-[10px] text-slate-500 uppercase">VaR 95</p>
                          <p className="text-sm font-bold text-red-400 tabular-nums">{fmtMoney(t.var_95)}</p>
                        </div>
                      </div>
                    </div>
                  </button>
                  {isOpen && (
                    <div className="border-t border-slate-800/50 p-5 bg-slate-950/40 space-y-5">
                      {/* KPI grid */}
                      <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
                        {[
                          { label: 'Base', value: t.base_npv, color: 'text-white' },
                          { label: 'P5', value: t.p5_npv, color: 'text-red-400' },
                          { label: 'P50', value: t.p50_npv, color: 'text-amber-400' },
                          { label: 'P95', value: t.p95_npv, color: 'text-emerald-400' },
                          { label: 'VaR 95', value: t.var_95, color: 'text-red-400' },
                          { label: 'ES', value: t.expected_shortfall, color: 'text-red-400' },
                        ].map((k) => (
                          <div key={k.label} className="rounded-lg bg-slate-800/30 p-3">
                            <p className="text-[10px] text-slate-500 uppercase tracking-wider">{k.label}</p>
                            <p className={`text-base font-bold tabular-nums ${k.color}`}>{fmtMoney(k.value)}</p>
                          </div>
                        ))}
                      </div>

                      {/* Distribution chart */}
                      {t.distribution && t.distribution.length > 0 && (
                        <div className="rounded-lg border border-slate-700/50 bg-slate-900/50 p-4">
                          <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">P&L Distribution</h4>
                          <ResponsiveContainer width="100%" height={220}>
                            <BarChart data={t.distribution.map((d: any) => ({
                              name: fmtMoney((d.bin_low + d.bin_high) / 2),
                              count: d.count,
                            }))}>
                              <XAxis dataKey="name" stroke="#475569" tick={{ fontSize: 10 }} />
                              <YAxis stroke="#475569" tick={{ fontSize: 10 }} />
                              <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 11 }} />
                              {t.base_npv != null && <ReferenceLine y={0} stroke="#f97316" />}
                              <Bar dataKey="count" fill="#f97316" />
                            </BarChart>
                          </ResponsiveContainer>
                        </div>
                      )}

                      {/* Worst scenarios */}
                      {t.worst_scenarios && t.worst_scenarios.length > 0 && (
                        <div>
                          <h4 className="text-xs font-semibold text-red-300 uppercase tracking-wider mb-2 flex items-center gap-2">
                            <AlertTriangle className="w-3.5 h-3.5" /> Worst Scenarios
                          </h4>
                          <div className="space-y-1">
                            {t.worst_scenarios.slice(0, 5).map((s: any, i: number) => (
                              <div key={i} className="flex items-center gap-3 text-xs p-2 rounded bg-red-500/5 border border-red-500/20">
                                <span className="text-slate-500 font-mono">#{s.iteration}</span>
                                <span className="text-red-300 font-bold tabular-nums">{fmtMoney(s.npv)}</span>
                                <span className="text-slate-400 flex-1">{s.drivers}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Summary markdown */}
                      {t.summary_markdown && (
                        <div className="rounded-lg border border-slate-700/50 bg-slate-900/50 p-4">
                          <pre className="text-xs text-slate-300 whitespace-pre-wrap leading-relaxed">{t.summary_markdown}</pre>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
