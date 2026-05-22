'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Receipt, ChevronLeft, Sparkles, Loader2, FileText,
  AlertCircle, CheckCircle2, TrendingUp, TrendingDown,
} from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

interface Recon {
  id: string;
  contract_id: string | null;
  invoice_filename: string | null;
  invoice_period: string | null;
  invoice_amount: number | null;
  expected_amount: number | null;
  variance_amount: number | null;
  variance_pct: number | null;
  line_items: any[] | null;
  discrepancies: any[] | null;
  dispute_letter: string | null;
  status: string;
  cost_usd: number | null;
  created_at: string;
}

interface Contract { id: string; title: string; }

function fmtMoney(n: number | null | undefined): string {
  if (n == null) return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n);
}

export default function ReconciliationPage() {
  const [recons, setRecons] = useState<Recon[]>([]);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  // Form
  const [contractId, setContractId] = useState('');
  const [period, setPeriod] = useState('');
  const [amount, setAmount] = useState('');
  const [file, setFile] = useState<File | null>(null);

  const load = async () => {
    setLoading(true);
    const token = getToken();
    if (!token) return;
    const [rRes, cRes] = await Promise.all([
      fetch(`${API_URL}/api/contractiq/insights/reconciliation`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${API_URL}/api/contractiq/contracts?limit=100`, { headers: { Authorization: `Bearer ${token}` } }),
    ]);
    setRecons((await rRes.json()).data || []);
    setContracts(((await cRes.json()).data || []).map((c: any) => ({ id: c.id, title: c.title })));
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!contractId || !amount) return;
    setSubmitting(true);
    const token = getToken();
    try {
      const fd = new FormData();
      fd.append('contract_id', contractId);
      fd.append('invoice_period', period);
      fd.append('invoice_amount', amount);
      if (file) fd.append('file', file);
      await fetch(`${API_URL}/api/contractiq/insights/reconciliation/upload`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      setContractId(''); setPeriod(''); setAmount(''); setFile(null);
      await load();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#0B0F19] p-8">
      <div className="max-w-5xl mx-auto">
        <div className="mb-6">
          <a href="/insights" className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-emerald-400 mb-2">
            <ChevronLeft className="w-3 h-3" /> Back to Insights Hub
          </a>
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-cyan-500/20 to-blue-600/20 border border-cyan-500/30 flex items-center justify-center">
              <Receipt className="w-6 h-6 text-cyan-400" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white">Settlement Reconciliation</h1>
              <p className="text-xs text-slate-400">Verify counterparty invoice math against contract pricing — <code className="text-cyan-300">contractiq-settlement-reconciler</code></p>
            </div>
          </div>
        </div>

        {/* Upload form */}
        <form onSubmit={submit} className="rounded-xl border border-cyan-500/30 bg-cyan-500/5 p-5 mb-8">
          <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2"><Sparkles className="w-4 h-4 text-cyan-400" /> Reconcile an Invoice</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
            <div>
              <label className="text-[10px] text-slate-400 uppercase tracking-wider mb-1 block">Contract</label>
              <select value={contractId} onChange={e => setContractId(e.target.value)} required
                className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:border-cyan-500 focus:outline-none">
                <option value="">Select contract...</option>
                {contracts.map(c => <option key={c.id} value={c.id}>{c.title}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-slate-400 uppercase tracking-wider mb-1 block">Period</label>
              <input type="text" value={period} onChange={e => setPeriod(e.target.value)} placeholder="2026-03"
                className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-600 focus:border-cyan-500 focus:outline-none" />
            </div>
            <div>
              <label className="text-[10px] text-slate-400 uppercase tracking-wider mb-1 block">Invoice Amount (USD)</label>
              <input type="number" step="0.01" value={amount} onChange={e => setAmount(e.target.value)} required placeholder="1245000"
                className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-600 focus:border-cyan-500 focus:outline-none" />
            </div>
          </div>
          <div className="flex items-center justify-between">
            <label className="text-xs text-slate-400 cursor-pointer hover:text-cyan-300">
              <input type="file" onChange={e => setFile(e.target.files?.[0] || null)} className="hidden" />
              {file ? `📎 ${file.name}` : '📎 Attach invoice (optional, .txt)'}
            </label>
            <button type="submit" disabled={submitting || !contractId || !amount}
              className="px-4 py-2 rounded-lg bg-gradient-to-r from-cyan-500 to-blue-600 text-white text-xs font-semibold disabled:opacity-50 flex items-center gap-2">
              {submitting ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Reconciling...</> : <><Sparkles className="w-3.5 h-3.5" /> Reconcile</>}
            </button>
          </div>
        </form>

        {/* Results */}
        {loading ? (
          <div className="flex items-center justify-center h-40"><Loader2 className="w-6 h-6 animate-spin text-cyan-400" /></div>
        ) : recons.length === 0 ? (
          <div className="rounded-xl border border-slate-800/50 bg-slate-900/30 p-8 text-center">
            <Receipt className="w-10 h-10 text-slate-600 mx-auto mb-3" />
            <p className="text-sm text-slate-400">No reconciliations yet.</p>
          </div>
        ) : (
          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-slate-300 mb-2">Recent Reconciliations ({recons.length})</h3>
            {recons.map(r => {
              const isOpen = expanded === r.id;
              const variance = r.variance_amount || 0;
              const isOverbill = variance > 0;
              return (
                <div key={r.id} className="rounded-xl border border-slate-800/50 bg-slate-900/30 overflow-hidden">
                  <button onClick={() => setExpanded(isOpen ? null : r.id)} className="w-full p-4 hover:bg-slate-800/30 transition-colors text-left">
                    <div className="flex items-center gap-4">
                      <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                        Math.abs(r.variance_pct || 0) > 1 ? 'bg-red-500/10 border border-red-500/30' : 'bg-emerald-500/10 border border-emerald-500/30'
                      }`}>
                        {Math.abs(r.variance_pct || 0) > 1 ? <AlertCircle className="w-5 h-5 text-red-400" /> : <CheckCircle2 className="w-5 h-5 text-emerald-400" />}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold text-white">{r.invoice_period || 'Unknown period'}</p>
                        <p className="text-xs text-slate-400">{r.invoice_filename || 'No file attached'} • {new Date(r.created_at).toLocaleDateString()}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-sm text-white tabular-nums">{fmtMoney(r.invoice_amount)}</p>
                        {r.variance_amount != null && (
                          <p className={`text-[11px] tabular-nums flex items-center gap-1 justify-end ${isOverbill ? 'text-red-400' : 'text-emerald-400'}`}>
                            {isOverbill ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                            {fmtMoney(Math.abs(variance))} ({(r.variance_pct || 0).toFixed(1)}%)
                          </p>
                        )}
                      </div>
                    </div>
                  </button>
                  {isOpen && (
                    <div className="border-t border-slate-800/50 p-5 bg-slate-950/40 space-y-4">
                      {/* Comparison */}
                      <div className="grid grid-cols-3 gap-3">
                        <div className="rounded-lg bg-slate-800/30 p-3">
                          <p className="text-[10px] text-slate-500 uppercase tracking-wider">Invoiced</p>
                          <p className="text-lg font-bold text-white tabular-nums">{fmtMoney(r.invoice_amount)}</p>
                        </div>
                        <div className="rounded-lg bg-slate-800/30 p-3">
                          <p className="text-[10px] text-slate-500 uppercase tracking-wider">Expected</p>
                          <p className="text-lg font-bold text-white tabular-nums">{fmtMoney(r.expected_amount)}</p>
                        </div>
                        <div className={`rounded-lg p-3 ${isOverbill ? 'bg-red-500/10 border border-red-500/30' : 'bg-emerald-500/10 border border-emerald-500/30'}`}>
                          <p className="text-[10px] text-slate-500 uppercase tracking-wider">Variance</p>
                          <p className={`text-lg font-bold tabular-nums ${isOverbill ? 'text-red-400' : 'text-emerald-400'}`}>{fmtMoney(r.variance_amount)}</p>
                        </div>
                      </div>

                      {/* Line items */}
                      {r.line_items && r.line_items.length > 0 && (
                        <div>
                          <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Line Items</h4>
                          <div className="space-y-2">
                            {r.line_items.map((li: any, i: number) => (
                              <div key={i} className="rounded-lg border border-slate-700/50 bg-slate-900/50 p-3">
                                <p className="text-xs text-white mb-1">{li.description}</p>
                                <div className="grid grid-cols-3 gap-2 text-[11px] text-slate-400 mb-1">
                                  <span>Invoiced: <span className="text-white tabular-nums">{fmtMoney(li.invoice)}</span></span>
                                  <span>Expected: <span className="text-white tabular-nums">{fmtMoney(li.expected)}</span></span>
                                  <span className={Math.abs(li.variance_pct || 0) > 1 ? 'text-red-400' : 'text-emerald-400'}>
                                    Δ {fmtMoney(li.variance)} ({(li.variance_pct || 0).toFixed(1)}%)
                                  </span>
                                </div>
                                {li.explanation && <p className="text-[11px] text-slate-500 italic">{li.explanation}</p>}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Dispute letter */}
                      {r.dispute_letter && (
                        <div>
                          <h4 className="text-xs font-semibold text-amber-300 uppercase tracking-wider mb-2 flex items-center gap-2"><FileText className="w-3.5 h-3.5" /> Draft Dispute Letter</h4>
                          <pre className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-xs text-slate-300 whitespace-pre-wrap font-mono leading-relaxed max-h-72 overflow-y-auto">{r.dispute_letter}</pre>
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
