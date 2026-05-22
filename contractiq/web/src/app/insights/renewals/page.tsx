'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Handshake, ChevronLeft, Sparkles, Loader2, Calendar,
  TrendingUp, Building2, Target, AlertCircle, CheckCircle2,
  ArrowRight, ChevronDown, ChevronUp,
} from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

interface UpcomingRenewal {
  id: string;
  title: string;
  contract_type: string;
  counterparty_a: string | null;
  counterparty_b: string | null;
  expiry_date: string | null;
  days_to_expiry: number | null;
  risk_score: number | null;
  total_capacity_mw: number | null;
}

interface RenewalPacket {
  id: string;
  contract_id: string;
  status: string;
  days_to_expiry: number | null;
  market_context: any;
  historical_pricing: any;
  counterparty_intel: any;
  term_sheet: any;
  npv_uplift: number | null;
  full_packet_markdown: string | null;
  cost_usd: number | null;
  error_message: string | null;
  created_at: string;
}

function fmtMoney(n: number | null | undefined): string {
  if (n == null) return '—';
  if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
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
        if (line.startsWith('## ')) return <h3 key={i} className="text-base font-bold text-white mt-4 mb-1">{line.slice(3)}</h3>;
        if (line.startsWith('### ')) return <h4 key={i} className="text-sm font-semibold text-white mt-3 mb-1">{line.slice(4)}</h4>;
        if (line.startsWith('- ')) return <div key={i} className="flex items-start gap-2 ml-2"><span className="text-emerald-400 mt-1.5 text-[6px]">●</span><span>{inline(line.slice(2))}</span></div>;
        if (line.startsWith('| ')) return <p key={i} className="font-mono text-xs text-slate-400">{line}</p>;
        if (line.trim() === '') return <div key={i} className="h-2" />;
        return <p key={i}>{inline(line)}</p>;
      })}
    </div>
  );
}
function inline(s: string) {
  return s.split(/(\*\*.*?\*\*)/).map((p, i) => p.startsWith('**') && p.endsWith('**') ? <strong key={i} className="text-white">{p.slice(2, -2)}</strong> : <span key={i}>{p}</span>);
}

export default function RenewalsPage() {
  const [upcoming, setUpcoming] = useState<UpcomingRenewal[]>([]);
  const [packets, setPackets] = useState<RenewalPacket[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    const token = getToken();
    if (!token) return;
    const [upRes, pkRes] = await Promise.all([
      fetch(`${API_URL}/api/contractiq/insights/renewals/upcoming?days=180`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${API_URL}/api/contractiq/insights/renewals`, { headers: { Authorization: `Bearer ${token}` } }),
    ]);
    setUpcoming((await upRes.json()).data || []);
    setPackets((await pkRes.json()).data || []);
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const generate = async (contractId: string) => {
    setGenerating(contractId);
    const token = getToken();
    try {
      await fetch(`${API_URL}/api/contractiq/insights/renewals/${contractId}/generate`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      await load();
    } finally {
      setGenerating(null);
    }
  };

  return (
    <div className="min-h-screen bg-[#0B0F19] p-8">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="mb-6">
          <a href="/insights" className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-emerald-400 mb-2">
            <ChevronLeft className="w-3 h-3" /> Back to Insights Hub
          </a>
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-emerald-500/20 to-teal-600/20 border border-emerald-500/30 flex items-center justify-center">
              <Handshake className="w-6 h-6 text-emerald-400" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white">Renewal Negotiation Copilot</h1>
              <p className="text-xs text-slate-400">Build a complete negotiation packet for any upcoming renewal — powered by <code className="text-emerald-300">contractiq-renewal-copilot</code></p>
            </div>
          </div>
        </div>

        {/* Upcoming renewals */}
        <div className="mb-8">
          <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
            <Calendar className="w-4 h-4 text-emerald-400" /> Upcoming Renewals (next 180 days)
          </h2>
          {loading ? (
            <div className="flex items-center justify-center h-40">
              <Loader2 className="w-6 h-6 animate-spin text-emerald-400" />
            </div>
          ) : upcoming.length === 0 ? (
            <div className="rounded-xl border border-slate-800/50 bg-slate-900/30 p-8 text-center">
              <Calendar className="w-10 h-10 text-slate-600 mx-auto mb-3" />
              <p className="text-sm text-slate-400">No contracts expiring in the next 180 days.</p>
              <p className="text-xs text-slate-500 mt-1">Upload contracts with extracted expiry dates to surface them here.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {upcoming.map((c, i) => (
                <motion.div
                  key={c.id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.04 }}
                  className="rounded-xl border border-slate-800/50 bg-slate-900/30 hover:border-emerald-500/30 transition-colors p-5"
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex-1 min-w-0">
                      <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">{c.contract_type}</p>
                      <h3 className="text-sm font-semibold text-white truncate">{c.title}</h3>
                      <p className="text-xs text-slate-400 mt-0.5">
                        {c.counterparty_a} ↔ {c.counterparty_b}
                      </p>
                    </div>
                    <span className={`shrink-0 px-2 py-1 rounded text-[10px] font-bold ${
                      (c.days_to_expiry || 0) < 30 ? 'bg-red-500/20 text-red-300' :
                      (c.days_to_expiry || 0) < 90 ? 'bg-amber-500/20 text-amber-300' :
                      'bg-emerald-500/20 text-emerald-300'
                    }`}>
                      {c.days_to_expiry}d
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-[11px] text-slate-500 mb-3">
                    {c.total_capacity_mw && <span>{c.total_capacity_mw} MW</span>}
                    {c.risk_score != null && <span>Risk {c.risk_score.toFixed(0)}/100</span>}
                    {c.expiry_date && <span>Expires {new Date(c.expiry_date).toLocaleDateString()}</span>}
                  </div>
                  <button
                    onClick={() => generate(c.id)}
                    disabled={generating === c.id}
                    className="w-full px-3 py-2 rounded-lg bg-gradient-to-r from-emerald-500 to-teal-600 text-white text-xs font-semibold hover:shadow-lg hover:shadow-emerald-500/25 transition-all flex items-center justify-center gap-2 disabled:opacity-50"
                  >
                    {generating === c.id ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Building packet...</> : <><Sparkles className="w-3.5 h-3.5" /> Build Negotiation Packet</>}
                  </button>
                </motion.div>
              ))}
            </div>
          )}
        </div>

        {/* Generated packets */}
        {packets.length > 0 && (
          <div>
            <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-emerald-400" /> Generated Packets ({packets.length})
            </h2>
            <div className="space-y-3">
              {packets.map((p) => {
                const isOpen = expanded === p.id;
                return (
                  <div key={p.id} className="rounded-xl border border-slate-800/50 bg-slate-900/30 overflow-hidden">
                    <button
                      onClick={() => setExpanded(isOpen ? null : p.id)}
                      className="w-full p-4 flex items-center justify-between hover:bg-slate-800/30 transition-colors"
                    >
                      <div className="flex items-center gap-4 text-left">
                        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                          p.status === 'completed' ? 'bg-emerald-500/10 border border-emerald-500/30' :
                          p.status === 'failed' ? 'bg-red-500/10 border border-red-500/30' :
                          'bg-amber-500/10 border border-amber-500/30'
                        }`}>
                          {p.status === 'completed' ? <CheckCircle2 className="w-4 h-4 text-emerald-400" /> :
                           p.status === 'failed' ? <AlertCircle className="w-4 h-4 text-red-400" /> :
                           <Loader2 className="w-4 h-4 text-amber-400 animate-spin" />}
                        </div>
                        <div>
                          <p className="text-sm font-medium text-white">Packet #{p.id.slice(0, 8)}</p>
                          <p className="text-[11px] text-slate-500">
                            {p.days_to_expiry}d to expiry • NPV uplift {fmtMoney(p.npv_uplift)} • {new Date(p.created_at).toLocaleDateString()}
                          </p>
                        </div>
                      </div>
                      {isOpen ? <ChevronUp className="w-4 h-4 text-slate-500" /> : <ChevronDown className="w-4 h-4 text-slate-500" />}
                    </button>
                    {isOpen && (
                      <div className="border-t border-slate-800/50 p-5 bg-slate-950/30">
                        {p.status === 'failed' ? (
                          <div className="flex items-start gap-2 text-red-300 text-sm">
                            <AlertCircle className="w-4 h-4 mt-0.5" />
                            <span>{p.error_message}</span>
                          </div>
                        ) : (
                          <div className="space-y-5">
                            {/* Three-position term sheet */}
                            {p.term_sheet && (
                              <div>
                                <h4 className="text-xs font-semibold text-emerald-300 uppercase tracking-wider mb-3 flex items-center gap-2"><Target className="w-3.5 h-3.5" /> Negotiation Positions</h4>
                                <div className="grid grid-cols-3 gap-3">
                                  {(['aggressive', 'middle', 'fallback'] as const).map(k => {
                                    const pos = p.term_sheet?.[k];
                                    if (!pos) return null;
                                    const colors = {
                                      aggressive: 'border-emerald-500/30 bg-emerald-500/5',
                                      middle:     'border-amber-500/30 bg-amber-500/5',
                                      fallback:   'border-slate-600/30 bg-slate-800/30',
                                    };
                                    return (
                                      <div key={k} className={`rounded-lg border p-3 ${colors[k]}`}>
                                        <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-2">{k}</p>
                                        <div className="space-y-1 text-xs">
                                          {Object.entries(pos).map(([key, val]: any) => (
                                            <div key={key} className="flex justify-between gap-2">
                                              <span className="text-slate-500">{key.replace(/_/g, ' ')}</span>
                                              <span className="text-white font-medium">{typeof val === 'number' && key.includes('npv') ? fmtMoney(val) : typeof val === 'number' && key.includes('probability') ? `${(val * 100).toFixed(0)}%` : String(val)}</span>
                                            </div>
                                          ))}
                                        </div>
                                      </div>
                                    );
                                  })}
                                </div>
                              </div>
                            )}

                            {/* Market context strip */}
                            {p.market_context && Object.keys(p.market_context).length > 0 && (
                              <div className="rounded-lg border border-cyan-500/20 bg-cyan-500/5 p-3">
                                <h4 className="text-xs font-semibold text-cyan-300 uppercase tracking-wider mb-2 flex items-center gap-2"><TrendingUp className="w-3.5 h-3.5" /> Market Context</h4>
                                <pre className="text-xs text-slate-300 whitespace-pre-wrap font-mono">{JSON.stringify(p.market_context, null, 2)}</pre>
                              </div>
                            )}

                            {/* Counterparty intel */}
                            {p.counterparty_intel && Object.keys(p.counterparty_intel).length > 0 && (
                              <div className="rounded-lg border border-purple-500/20 bg-purple-500/5 p-3">
                                <h4 className="text-xs font-semibold text-purple-300 uppercase tracking-wider mb-2 flex items-center gap-2"><Building2 className="w-3.5 h-3.5" /> Counterparty Intel</h4>
                                <pre className="text-xs text-slate-300 whitespace-pre-wrap font-mono">{JSON.stringify(p.counterparty_intel, null, 2)}</pre>
                              </div>
                            )}

                            {/* Full packet */}
                            {p.full_packet_markdown && (
                              <div>
                                <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Full Packet</h4>
                                <div className="rounded-lg border border-slate-700/50 bg-slate-900/50 p-4">
                                  <RichText md={p.full_packet_markdown} />
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
