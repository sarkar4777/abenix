'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  ShieldCheck, ChevronLeft, Sparkles, Loader2, Star, Award,
} from 'lucide-react';
import { PageExplainer } from '@/components/PageExplainer';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

interface Hedge {
  id: string;
  contract_id: string;
  status: string;
  exposure_type: string | null;
  notional_amount: number | null;
  notional_currency: string | null;
  tenor_months: number | null;
  structures: any[] | null;
  recommended_structure: string | null;
  rationale: string | null;
  created_at: string;
}

interface Contract { id: string; title: string; }

function fmtMoney(n: number | null | undefined): string {
  if (n == null) return '—';
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (Math.abs(n) >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

function RichText({ md }: { md: string }) {
  if (!md) return null;
  const lines = md.split('\n');
  return (
    <div className="space-y-2 text-sm text-slate-300 leading-relaxed">
      {lines.map((line, i) => {
        if (line.startsWith('## ')) return <h3 key={i} className="text-base font-bold text-white mt-3 mb-1">{line.slice(3)}</h3>;
        if (line.startsWith('### ')) return <h4 key={i} className="text-sm font-semibold text-white mt-2 mb-1">{line.slice(4)}</h4>;
        if (line.startsWith('- ')) return <div key={i} className="flex items-start gap-2 ml-2"><span className="text-emerald-400 mt-1.5 text-[6px]">●</span><span>{line.slice(2)}</span></div>;
        if (line.trim() === '') return <div key={i} className="h-1" />;
        return <p key={i}>{line}</p>;
      })}
    </div>
  );
}

export default function HedgePage() {
  const [hedges, setHedges] = useState<Hedge[]>([]);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [contractId, setContractId] = useState('');
  const [tolerance, setTolerance] = useState<'low' | 'medium' | 'high'>('medium');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [toast, setToast] = useState<{ kind: 'ok' | 'warn' | 'err'; msg: string } | null>(null);

  useEffect(() => {
    if (!running) return;
    const start = Date.now();
    setElapsed(0);
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(t);
  }, [running]);

  const load = async () => {
    setLoading(true);
    const token = getToken();
    if (!token) return;
    const [hRes, cRes] = await Promise.all([
      fetch(`${API_URL}/api/contractiq/insights/hedge`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${API_URL}/api/contractiq/contracts?limit=200`, { headers: { Authorization: `Bearer ${token}` } }),
    ]);
    setHedges((await hRes.json()).data || []);
    setContracts(((await cRes.json()).data || []).map((c: any) => ({ id: c.id, title: c.title })));
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const run = async () => {
    if (!contractId) return;
    setRunning(true);
    setToast(null);
    const token = getToken();
    try {
      const res = await fetch(`${API_URL}/api/contractiq/insights/hedge/${contractId}/recommend`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ risk_tolerance: tolerance }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok || body?.error) {
        setToast({ kind: 'err', msg: body?.error?.message || body?.error_message || `Recommend failed (${res.status})` });
      } else {
        const d = body?.data || body || {};
        const cost = d.cost_usd ?? d.cost ?? null;
        if (d.error_message) {
          setToast({ kind: 'warn', msg: `${d.error_message}${cost != null ? ` · $${Number(cost).toFixed(4)}` : ''}` });
        } else {
          setToast({ kind: 'ok', msg: `Recommendation ready${cost != null ? ` · $${Number(cost).toFixed(4)}` : ''}` });
        }
      }
      await load();
    } catch (e: any) {
      setToast({ kind: 'err', msg: `Network error: ${e?.message || 'unknown'}` });
    } finally {
      setRunning(false);
      setTimeout(() => setToast(null), 8000);
    }
  };

  const titleOf = (id: string) => contracts.find(c => c.id === id)?.title || id.slice(0, 8);

  return (
    <div className="min-h-screen bg-[#0B0F19] p-8">
      <div className="max-w-5xl mx-auto">
        <div className="mb-6">
          <a href="/insights" className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-emerald-400 mb-2">
            <ChevronLeft className="w-3 h-3" /> Back to Insights Hub
          </a>
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-teal-500/20 to-emerald-600/20 border border-teal-500/30 flex items-center justify-center">
              <ShieldCheck className="w-6 h-6 text-teal-400" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white">Hedge Advisor</h1>
              <PageExplainer routeKey="insights-hedge" />
              <p className="text-xs text-slate-400">Right-sized hedge structures via <code className="text-teal-300">contractiq-hedge-advisor</code></p>
            </div>
          </div>
        </div>

        {/* Form */}
        <div className="rounded-xl border border-teal-500/30 bg-teal-500/5 p-5 mb-8">
          <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2"><Sparkles className="w-4 h-4 text-teal-400" /> Recommend Hedge</h3>
          <div className="grid grid-cols-1 md:grid-cols-[2fr_1fr_auto] gap-3 items-end">
            <div>
              <label className="text-[10px] text-slate-400 uppercase tracking-wider mb-1 block">Contract</label>
              <select value={contractId} onChange={e => setContractId(e.target.value)}
                className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:border-teal-500 focus:outline-none">
                <option value="">Select...</option>
                {contracts.map(c => <option key={c.id} value={c.id}>{c.title}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-slate-400 uppercase tracking-wider mb-1 block">Risk Tolerance</label>
              <select value={tolerance} onChange={e => setTolerance(e.target.value as any)}
                className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:border-teal-500 focus:outline-none">
                <option value="low">Low (max hedge)</option>
                <option value="medium">Medium</option>
                <option value="high">High (min hedge)</option>
              </select>
            </div>
            <button onClick={run} disabled={running || !contractId}
              className="px-4 py-2 rounded-lg bg-gradient-to-r from-teal-500 to-emerald-600 text-white text-xs font-semibold hover:shadow-lg hover:shadow-teal-500/25 disabled:opacity-50 flex items-center gap-2">
              {running ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Agent running... {elapsed}s</> : 'Recommend'}
            </button>
          </div>
          {running && (
            <p className="text-[11px] text-slate-400 mt-2">
              Hedge advisor prices 3-5 structures via <code className="text-teal-300">financial_calculator</code>. Typical run 15-40s. Watch the live activity rail for tool calls.
            </p>
          )}
          {toast && !running && (
            <div className={`mt-3 rounded-lg border px-3 py-2 text-xs ${
              toast.kind === 'ok' ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300' :
              toast.kind === 'warn' ? 'border-amber-500/40 bg-amber-500/10 text-amber-300' :
              'border-red-500/40 bg-red-500/10 text-red-300'
            }`}>{toast.msg}</div>
          )}
        </div>

        {loading ? (
          <div className="flex items-center justify-center h-40"><Loader2 className="w-6 h-6 animate-spin text-teal-400" /></div>
        ) : hedges.length === 0 ? (
          <div className="rounded-xl border border-slate-800/50 bg-slate-900/30 p-12 text-center">
            <ShieldCheck className="w-12 h-12 text-teal-400/40 mx-auto mb-3" />
            <p className="text-sm text-slate-400">No hedge recommendations yet.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {hedges.map(h => {
              const isOpen = expanded === h.id;
              return (
                <div key={h.id} className="rounded-xl border border-slate-800/50 bg-slate-900/30 overflow-hidden">
                  <button onClick={() => setExpanded(isOpen ? null : h.id)} className="w-full p-4 hover:bg-slate-800/30 transition-colors text-left">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-sm font-semibold text-white">{titleOf(h.contract_id)}</p>
                        <p className="text-[11px] text-slate-500">{h.exposure_type || 'unknown'} exposure • {fmtMoney(h.notional_amount)} {h.notional_currency} • {h.tenor_months}mo</p>
                      </div>
                      {h.recommended_structure && (
                        <div className="text-right">
                          <p className="text-[10px] text-slate-500 uppercase">Recommended</p>
                          <p className="text-sm font-bold text-teal-300 capitalize">{h.recommended_structure}</p>
                        </div>
                      )}
                    </div>
                  </button>
                  {isOpen && h.structures && (
                    <div className="border-t border-slate-800/50 p-5 bg-slate-950/40 space-y-4">
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                        {h.structures.map((s: any, i: number) => {
                          const isRec = s.type === h.recommended_structure || s.name?.toLowerCase().includes(h.recommended_structure || '');
                          return (
                            <div key={i} className={`rounded-lg border p-4 ${isRec ? 'border-teal-500/40 bg-teal-500/10' : 'border-slate-700/50 bg-slate-900/50'}`}>
                              {isRec && <div className="flex items-center gap-1 mb-2 text-[10px] text-teal-300 font-bold uppercase"><Star className="w-3 h-3 fill-teal-400 text-teal-400" /> Recommended</div>}
                              <h4 className="text-sm font-semibold text-white mb-2">{s.name}</h4>
                              <div className="space-y-1 text-[11px] mb-3">
                                <div className="flex justify-between"><span className="text-slate-500">Type</span><span className="text-slate-300 capitalize">{s.type}</span></div>
                                <div className="flex justify-between"><span className="text-slate-500">Premium</span><span className="text-white tabular-nums">{fmtMoney(s.premium_usd)}</span></div>
                                <div className="flex justify-between"><span className="text-slate-500">Cost %</span><span className="text-white tabular-nums">{s.cost_pct?.toFixed(2)}%</span></div>
                                <div className="flex justify-between"><span className="text-slate-500">Residual Risk</span><span className="text-amber-300">{s.residual_risk}</span></div>
                              </div>
                              {s.description && <p className="text-[10px] text-slate-400 leading-relaxed">{s.description}</p>}
                              {s.pros_cons && <p className="text-[10px] text-slate-500 italic mt-2">{s.pros_cons}</p>}
                            </div>
                          );
                        })}
                      </div>
                      {h.rationale && (
                        <div className="rounded-lg border border-slate-700/50 bg-slate-900/50 p-4">
                          <h4 className="text-xs font-semibold text-teal-300 uppercase tracking-wider mb-2 flex items-center gap-2"><Award className="w-3.5 h-3.5" /> Rationale</h4>
                          <RichText md={h.rationale} />
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
