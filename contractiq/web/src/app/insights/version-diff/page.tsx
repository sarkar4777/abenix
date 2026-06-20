'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  GitCompareArrows, ChevronLeft, Sparkles, Loader2, ArrowRight,
  TrendingUp, TrendingDown, Equal, Plus as PlusIcon, Minus,
} from 'lucide-react';
import { PageExplainer } from '@/components/PageExplainer';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

interface Diff {
  id: string;
  base_contract_id: string;
  new_contract_id: string;
  status: string;
  summary: string | null;
  changes: any[] | null;
  overall_impact: string | null;
  cost_usd: number | null;
  error_message: string | null;
  created_at: string;
}

interface Contract { id: string; title: string; }

const IMPACT_STYLES: Record<string, { bg: string; text: string; border: string; label: string }> = {
  favourable: { bg: 'bg-emerald-500/10', text: 'text-emerald-300', border: 'border-emerald-500/40', label: '↗ Favourable' },
  adverse:    { bg: 'bg-red-500/10',     text: 'text-red-300',     border: 'border-red-500/40',     label: '↘ Adverse' },
  neutral:    { bg: 'bg-slate-500/10',   text: 'text-slate-300',   border: 'border-slate-500/40',   label: '— Neutral' },
  mixed:      { bg: 'bg-amber-500/10',   text: 'text-amber-300',   border: 'border-amber-500/40',   label: '~ Mixed' },
};
const CHANGE_KIND_ICONS: Record<string, any> = {
  tightened: TrendingDown,
  loosened:  TrendingUp,
  added:     PlusIcon,
  removed:   Minus,
  unchanged: Equal,
};

export default function VersionDiffPage() {
  const [diffs, setDiffs] = useState<Diff[]>([]);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [base, setBase] = useState('');
  const [newer, setNewer] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    const token = getToken();
    if (!token) return;
    const [dRes, cRes] = await Promise.all([
      fetch(`${API_URL}/api/contractiq/insights/version-diff`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${API_URL}/api/contractiq/contracts?limit=200`, { headers: { Authorization: `Bearer ${token}` } }),
    ]);
    setDiffs((await dRes.json()).data || []);
    setContracts(((await cRes.json()).data || []).map((c: any) => ({ id: c.id, title: c.title })));
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const run = async () => {
    if (!base || !newer || base === newer) return;
    setRunning(true);
    const token = getToken();
    try {
      await fetch(`${API_URL}/api/contractiq/insights/version-diff`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ base_contract_id: base, new_contract_id: newer }),
      });
      setBase(''); setNewer('');
      await load();
    } finally {
      setRunning(false);
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
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-pink-500/20 to-rose-600/20 border border-pink-500/30 flex items-center justify-center">
              <GitCompareArrows className="w-6 h-6 text-pink-400" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white">Version Diff</h1>
              <PageExplainer routeKey="insights-version-diff" />
              <p className="text-xs text-slate-400">Semantic clause-by-clause comparison via <code className="text-pink-300">contractiq-version-diff</code></p>
            </div>
          </div>
        </div>

        {/* Run form */}
        <div className="rounded-xl border border-pink-500/30 bg-pink-500/5 p-5 mb-8">
          <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2"><Sparkles className="w-4 h-4 text-pink-400" /> Compare Two Contracts</h3>
          <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_1fr_auto] gap-3 items-end">
            <div>
              <label className="text-[10px] text-slate-400 uppercase tracking-wider mb-1 block">Base (older)</label>
              <select value={base} onChange={e => setBase(e.target.value)}
                className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:border-pink-500 focus:outline-none">
                <option value="">Select...</option>
                {contracts.map(c => <option key={c.id} value={c.id}>{c.title}</option>)}
              </select>
            </div>
            <ArrowRight className="w-5 h-5 text-pink-400 mb-2.5" />
            <div>
              <label className="text-[10px] text-slate-400 uppercase tracking-wider mb-1 block">New (newer)</label>
              <select value={newer} onChange={e => setNewer(e.target.value)}
                className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:border-pink-500 focus:outline-none">
                <option value="">Select...</option>
                {contracts.map(c => <option key={c.id} value={c.id}>{c.title}</option>)}
              </select>
            </div>
            <button onClick={run} disabled={running || !base || !newer || base === newer}
              className="px-4 py-2 rounded-lg bg-gradient-to-r from-pink-500 to-rose-600 text-white text-xs font-semibold hover:shadow-lg hover:shadow-pink-500/25 disabled:opacity-50 flex items-center gap-2">
              {running ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Running...</> : 'Run Diff'}
            </button>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center h-40"><Loader2 className="w-6 h-6 animate-spin text-pink-400" /></div>
        ) : diffs.length === 0 ? (
          <div className="rounded-xl border border-slate-800/50 bg-slate-900/30 p-12 text-center">
            <GitCompareArrows className="w-12 h-12 text-pink-400/40 mx-auto mb-3" />
            <p className="text-sm text-slate-400">No diffs run yet.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {diffs.map((d, i) => {
              const isOpen = expanded === d.id;
              const impact = IMPACT_STYLES[d.overall_impact || 'neutral'] || IMPACT_STYLES.neutral;
              return (
                <motion.div key={d.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }}
                  className="rounded-xl border border-slate-800/50 bg-slate-900/30 overflow-hidden">
                  <button onClick={() => setExpanded(isOpen ? null : d.id)} className="w-full p-4 text-left hover:bg-slate-800/30 transition-colors">
                    <div className="flex items-center justify-between gap-3 mb-2">
                      <div className="flex items-center gap-2 text-xs">
                        <span className="text-slate-400">{titleOf(d.base_contract_id)}</span>
                        <ArrowRight className="w-3.5 h-3.5 text-pink-400" />
                        <span className="text-white font-medium">{titleOf(d.new_contract_id)}</span>
                      </div>
                      <span className={`px-2 py-1 rounded text-[10px] font-bold border ${impact.border} ${impact.text} ${impact.bg}`}>
                        {impact.label}
                      </span>
                    </div>
                    {d.summary && <p className="text-sm text-slate-300 line-clamp-2">{d.summary}</p>}
                    <p className="text-[10px] text-slate-500 mt-1">{d.changes?.length || 0} changes • {new Date(d.created_at).toLocaleDateString()}</p>
                  </button>
                  {isOpen && d.changes && (
                    <div className="border-t border-slate-800/50 p-5 bg-slate-950/40 space-y-3">
                      {d.changes.map((c: any, ci: number) => {
                        const Icon = CHANGE_KIND_ICONS[c.change_kind] || Equal;
                        const kindColor = c.change_kind === 'tightened' || c.change_kind === 'removed' ? 'text-red-400' : c.change_kind === 'loosened' || c.change_kind === 'added' ? 'text-emerald-400' : 'text-slate-400';
                        const impactBadge = c.impact === 'critical' || c.impact === 'high' ? 'bg-red-500/20 text-red-300' : c.impact === 'medium' ? 'bg-amber-500/20 text-amber-300' : 'bg-slate-500/20 text-slate-300';
                        return (
                          <div key={ci} className="rounded-lg border border-slate-700/50 bg-slate-900/50 p-3">
                            <div className="flex items-center gap-2 mb-2">
                              <Icon className={`w-4 h-4 ${kindColor}`} />
                              <span className="text-xs font-mono text-slate-400 capitalize">{c.clause_type}</span>
                              <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase ${kindColor}`}>{c.change_kind}</span>
                              <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase ${impactBadge}`}>{c.impact}</span>
                            </div>
                            {c.before && <p className="text-xs text-slate-500 mb-1"><span className="text-red-400/70 font-mono">- </span>{c.before}</p>}
                            {c.after && <p className="text-xs text-slate-300 mb-1"><span className="text-emerald-400/70 font-mono">+ </span>{c.after}</p>}
                            {c.rationale && <p className="text-[11px] text-slate-400 italic mt-2">{c.rationale}</p>}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </motion.div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
