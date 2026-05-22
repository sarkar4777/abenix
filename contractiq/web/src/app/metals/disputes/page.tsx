'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { AlertTriangle, ChevronLeft, Loader2, Play } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

interface Contract { id: string; title: string; counterparty: string; contract_value_usd: number | null }
interface Dimension { dimension: string; score: number; rationale: string; expected_exposure_usd: number; recommendation: string }
interface Dispute {
  id: string;
  contract_id: string;
  aggregate_score: number;
  tier: string;
  expected_loss_usd: number;
  expected_loss_pct_of_notional: number;
  dimensions: Dimension[];
  top_recommendations: string[];
}

export default function MetalsDisputesPage() {
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [rows, setRows] = useState<Dispute[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const load = async () => {
    const token = getToken();
    if (!token) return;
    const [cRes, rRes] = await Promise.all([
      fetch(`${API_URL}/api/contractiq/contracts`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${API_URL}/api/contractiq/metals/disputes`, { headers: { Authorization: `Bearer ${token}` } }),
    ]);
    setContracts((await cRes.json()).data || []);
    setRows((await rRes.json()).data || []);
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const run = async (id: string) => {
    setRunning(id);
    const token = getToken();
    try {
      await fetch(`${API_URL}/api/contractiq/metals/contracts/${id}/dispute-risk`, {
        method: 'POST', headers: { Authorization: `Bearer ${token}` },
      });
      await load();
    } finally { setRunning(null); }
  };

  const byContract = new Map<string, Dispute>();
  rows.forEach((r) => { if (!byContract.has(r.contract_id)) byContract.set(r.contract_id, r); });
  const tierColor: Record<string, string> = {
    low: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30',
    elevated: 'text-amber-300 bg-amber-500/10 border-amber-500/30',
    high: 'text-red-300 bg-red-500/10 border-red-500/30',
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <div className="max-w-7xl mx-auto p-6 lg:p-10">
        <Link href="/metals" className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 mb-4">
          <ChevronLeft className="w-3.5 h-3.5" /> Back to metals
        </Link>
        <div className="flex items-center gap-3 mb-6">
          <AlertTriangle className="w-7 h-7 text-red-300" />
          <div>
            <h1 className="text-2xl font-bold text-white">Dispute Risk Scorer</h1>
            <p className="text-sm text-slate-400">Assay × weight × brand × late-delivery × sanctioned-origin → expected $ exposure.</p>
          </div>
        </div>

        {loading ? <Loader2 className="w-6 h-6 animate-spin text-slate-500 mx-auto block mt-20" /> : (
          <div className="space-y-3">
            {contracts.map((c) => {
              const r = byContract.get(c.id);
              const isOpen = open === c.id;
              return (
                <div key={c.id} className="rounded-xl bg-slate-900/60 border border-slate-800/80">
                  <div className="p-4 flex items-center justify-between">
                    <div className="flex-1">
                      <div className="text-sm font-semibold text-white">{c.title}</div>
                      <div className="text-xs text-slate-500 mt-0.5">{c.counterparty}</div>
                    </div>
                    {r && (
                      <div className="flex items-center gap-3 mr-3">
                        <div className={`px-2 py-1 rounded-md text-[10px] border uppercase ${tierColor[r.tier] || 'text-slate-300 bg-slate-800 border-slate-700'}`}>{r.tier}</div>
                        <div className="text-right">
                          <div className="text-[9px] uppercase text-slate-500">Expected loss</div>
                          <div className="text-sm font-bold text-red-300">{formatUsd(r.expected_loss_usd)}</div>
                          {r.expected_loss_pct_of_notional != null && (
                            <div className="text-[9px] text-slate-500">{r.expected_loss_pct_of_notional.toFixed(2)}% of notional</div>
                          )}
                        </div>
                      </div>
                    )}
                    <div className="flex items-center gap-2">
                      <button onClick={() => run(c.id)} disabled={running === c.id}
                        className="px-3 py-1.5 text-xs rounded-lg bg-red-500/20 border border-red-500/40 text-red-200 hover:bg-red-500/30 disabled:opacity-50 flex items-center gap-1.5">
                        {running === c.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
                        {r ? 'Re-score' : 'Score'}
                      </button>
                      {r && (
                        <button onClick={() => setOpen(isOpen ? null : c.id)} className="px-3 py-1.5 text-xs rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700">
                          {isOpen ? 'Hide' : 'Detail'}
                        </button>
                      )}
                    </div>
                  </div>
                  {isOpen && r && (
                    <div className="px-4 pb-4 space-y-2">
                      {(r.dimensions || []).map((d, idx) => (
                        <div key={idx} className="p-3 rounded-md bg-slate-800/40 border border-slate-800">
                          <div className="flex items-center justify-between mb-1.5">
                            <div className="text-xs font-medium text-slate-200">{d.dimension}</div>
                            <div className="flex items-center gap-3 text-xs">
                              <span className="text-slate-400">score {d.score.toFixed(2)}</span>
                              <span className="text-red-300">{formatUsd(d.expected_exposure_usd)}</span>
                            </div>
                          </div>
                          <div className="text-xs text-slate-400 leading-relaxed">{d.rationale}</div>
                          {d.recommendation && (
                            <div className="mt-1.5 text-xs text-cyan-300/80">Recommend: {d.recommendation}</div>
                          )}
                        </div>
                      ))}
                      {r.top_recommendations && r.top_recommendations.length > 0 && (
                        <div className="p-3 rounded-md bg-cyan-500/5 border border-cyan-500/20">
                          <div className="text-[10px] uppercase tracking-wide text-cyan-300 mb-1">Top recommendations</div>
                          <ul className="text-xs text-slate-300 space-y-1">
                            {r.top_recommendations.map((t, i) => <li key={i}>• {t}</li>)}
                          </ul>
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

function formatUsd(v: number): string {
  if (!v) return '$0';
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}k`;
  return `$${v.toFixed(0)}`;
}
