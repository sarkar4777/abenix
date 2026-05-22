'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  AlertOctagon, ChevronLeft, Sparkles, Loader2, Clock,
  CheckCircle2, XCircle, FileText, AlertCircle,
} from 'lucide-react';


const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

interface FMNotice {
  id: string;
  contract_id: string;
  trigger_type: string;
  trigger_description: string;
  severity: string;
  applicable_clauses: any[];
  financial_impact_usd: number | null;
  draft_notice: string | null;
  deadline_to_notify: string | null;
  status: string;
  created_at: string;
}

function fmtMoney(n: number | null | undefined): string {
  if (n == null) return '—';
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (Math.abs(n) >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

const SEVERITY_STYLES: Record<string, string> = {
  critical: 'bg-red-500/20 text-red-300 border-red-500/40',
  warning:  'bg-amber-500/20 text-amber-300 border-amber-500/40',
  info:     'bg-cyan-500/20 text-cyan-300 border-cyan-500/40',
};

export default function ForceMajeurePage() {
  const [notices, setNotices] = useState<FMNotice[]>([]);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [toast, setToast] = useState<{ kind: 'ok' | 'warn' | 'err'; msg: string } | null>(null);

  const load = async () => {
    setLoading(true);
    const token = getToken();
    if (!token) return;
    const res = await fetch(`${API_URL}/api/contractiq/insights/force-majeure/notices`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    setNotices((await res.json()).data || []);
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const runScan = async () => {
    setScanning(true);
    setToast(null);
    const token = getToken();
    try {
      const res = await fetch(`${API_URL}/api/contractiq/insights/force-majeure/scan`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const body = await res.json();
      if (!res.ok || body?.error) {
        setToast({ kind: 'err', msg: body?.error?.message || `Scan failed (${res.status})` });
      } else {
        const d = body?.data || {};
        if (d.warning) {
          setToast({ kind: 'warn', msg: d.scan_summary || `Warning: ${d.warning}` });
        } else {
          setToast({ kind: 'ok', msg: `Scan complete — ${d.notices_created ?? 0} notices created.` });
        }
      }
      await load();
    } catch (e: any) {
      setToast({ kind: 'err', msg: `Network error: ${e?.message || 'unknown'}` });
    } finally {
      setScanning(false);
      setTimeout(() => setToast(null), 8000);
    }
  };

  const updateStatus = async (id: string, status: string) => {
    const token = getToken();
    await fetch(`${API_URL}/api/contractiq/insights/force-majeure/notices/${id}/review`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    });
    await load();
  };

  return (
    <div className="min-h-screen bg-[#0B0F19] p-8">
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <a href="/insights" className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-emerald-400 mb-2">
              <ChevronLeft className="w-3 h-3" /> Back to Insights Hub
            </a>
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-red-500/20 to-pink-600/20 border border-red-500/30 flex items-center justify-center">
                <AlertOctagon className="w-6 h-6 text-red-400" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-white">Force Majeure Monitor</h1>
                <p className="text-xs text-slate-400">Auto-detect FM triggers and draft notices via <code className="text-red-300">contractiq-force-majeure-monitor</code></p>
              </div>
            </div>
          </div>
          <button
            onClick={runScan}
            disabled={scanning}
            className="px-4 py-2 rounded-lg bg-gradient-to-r from-red-500 to-pink-600 text-white text-sm font-semibold hover:shadow-lg hover:shadow-red-500/25 transition-all flex items-center gap-2 disabled:opacity-50"
          >
            {scanning ? <><Loader2 className="w-4 h-4 animate-spin" /> Scanning...</> : <><Sparkles className="w-4 h-4" /> Run FM Scan</>}
          </button>
        </div>
        {toast && (
          <div className={`mb-4 rounded-lg border px-3 py-2 text-xs ${
            toast.kind === 'ok' ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300' :
            toast.kind === 'warn' ? 'border-amber-500/40 bg-amber-500/10 text-amber-300' :
            'border-red-500/40 bg-red-500/10 text-red-300'
          }`}>{toast.msg}</div>
        )}

        {loading ? (
          <div className="flex items-center justify-center h-64"><Loader2 className="w-8 h-8 animate-spin text-red-400" /></div>
        ) : notices.length === 0 ? (
          <div className="rounded-xl border border-slate-800/50 bg-slate-900/30 p-12 text-center">
            <CheckCircle2 className="w-12 h-12 text-emerald-400/40 mx-auto mb-3" />
            <p className="text-sm text-slate-300 mb-1">No force majeure triggers detected.</p>
            <p className="text-xs text-slate-500">Run a scan to check current market and grid conditions against your contracts' FM clauses.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {notices.map((n, idx) => {
              const isOpen = expanded === n.id;
              return (
                <motion.div
                  key={n.id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: idx * 0.04 }}
                  className="rounded-xl border border-slate-800/50 bg-slate-900/30 overflow-hidden"
                >
                  <button onClick={() => setExpanded(isOpen ? null : n.id)} className="w-full p-4 flex items-start gap-4 hover:bg-slate-800/30 transition-colors text-left">
                    <span className={`px-2 py-1 rounded text-[10px] font-bold uppercase border ${SEVERITY_STYLES[n.severity] || SEVERITY_STYLES.info}`}>
                      {n.severity}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-white capitalize">{n.trigger_type.replace(/_/g, ' ')}</p>
                      <p className="text-xs text-slate-400 mt-0.5 line-clamp-2">{n.trigger_description}</p>
                      <div className="flex items-center gap-3 mt-2 text-[11px] text-slate-500">
                        {n.financial_impact_usd != null && <span>Impact: {fmtMoney(n.financial_impact_usd)}</span>}
                        {n.deadline_to_notify && <span className="flex items-center gap-1"><Clock className="w-3 h-3" /> {new Date(n.deadline_to_notify).toLocaleDateString()}</span>}
                        <span className={`px-1.5 py-0.5 rounded text-[9px] ${
                          n.status === 'sent' ? 'bg-emerald-500/20 text-emerald-300' :
                          n.status === 'dismissed' ? 'bg-slate-500/20 text-slate-400' :
                          'bg-amber-500/20 text-amber-300'
                        }`}>{n.status.replace(/_/g, ' ')}</span>
                      </div>
                    </div>
                  </button>
                  {isOpen && (
                    <div className="border-t border-slate-800/50 p-5 bg-slate-950/40">
                      {n.applicable_clauses && n.applicable_clauses.length > 0 && (
                        <div className="mb-4">
                          <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Applicable Clauses</h4>
                          <div className="space-y-2">
                            {n.applicable_clauses.map((c: any, i: number) => (
                              <div key={i} className="rounded-lg border border-slate-700/50 bg-slate-900/50 p-3">
                                <p className="text-xs font-mono text-emerald-300 mb-1">Clause {c.clause_number} — {c.title}</p>
                                {c.excerpt && <p className="text-xs text-slate-400 italic">"{c.excerpt}"</p>}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                      {n.draft_notice && (
                        <div className="mb-4">
                          <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-2"><FileText className="w-3.5 h-3.5" /> Draft Notice</h4>
                          <pre className="rounded-lg border border-slate-700/50 bg-slate-950/80 p-4 text-xs text-slate-300 whitespace-pre-wrap font-mono leading-relaxed max-h-96 overflow-y-auto">{n.draft_notice}</pre>
                        </div>
                      )}
                      <div className="flex items-center gap-2 pt-3 border-t border-slate-800/50">
                        <button onClick={() => updateStatus(n.id, 'sent')} className="px-3 py-1.5 rounded-lg bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 text-xs font-semibold hover:bg-emerald-500/30 transition-colors flex items-center gap-1.5">
                          <CheckCircle2 className="w-3.5 h-3.5" /> Mark Sent
                        </button>
                        <button onClick={() => updateStatus(n.id, 'dismissed')} className="px-3 py-1.5 rounded-lg bg-slate-700/30 border border-slate-600/40 text-slate-400 text-xs font-semibold hover:bg-slate-700/50 transition-colors flex items-center gap-1.5">
                          <XCircle className="w-3.5 h-3.5" /> Dismiss
                        </button>
                      </div>
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
