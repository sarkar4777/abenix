'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Telescope, ChevronLeft, Sparkles, Loader2, X, AlertTriangle,
} from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

interface Anomaly {
  id: string;
  clause_id: string;
  contract_id: string;
  anomaly_score: number;
  severity: string;
  explanation: string;
  benchmark_summary: any;
  created_at: string;
}

const SEVERITY_STYLES: Record<string, { border: string; text: string; bg: string }> = {
  critical: { border: 'border-red-500/40', text: 'text-red-300', bg: 'bg-red-500/10' },
  warning:  { border: 'border-amber-500/40', text: 'text-amber-300', bg: 'bg-amber-500/10' },
  info:     { border: 'border-cyan-500/40', text: 'text-cyan-300', bg: 'bg-cyan-500/10' },
};

export default function AnomaliesPage() {
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [toast, setToast] = useState<{ kind: 'ok' | 'warn' | 'err'; msg: string } | null>(null);

  const load = async () => {
    setLoading(true);
    const token = getToken();
    if (!token) return;
    const res = await fetch(`${API_URL}/api/contractiq/insights/anomalies`, { headers: { Authorization: `Bearer ${token}` } });
    setAnomalies((await res.json()).data || []);
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const scan = async () => {
    setScanning(true);
    setToast(null);
    const token = getToken();
    try {
      const res = await fetch(`${API_URL}/api/contractiq/insights/anomalies/scan`, {
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
          setToast({ kind: 'ok', msg: `Scan complete — ${d.anomalies_persisted ?? 0} anomalies found across ${d.scanned_clauses ?? 0} clauses.` });
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

  const dismiss = async (id: string) => {
    const token = getToken();
    await fetch(`${API_URL}/api/contractiq/insights/anomalies/${id}/dismiss`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
    setAnomalies(anomalies.filter(a => a.id !== id));
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
              <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-purple-500/20 to-fuchsia-600/20 border border-purple-500/30 flex items-center justify-center">
                <Telescope className="w-6 h-6 text-purple-400" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-white">Clause Anomaly Detector</h1>
                <p className="text-xs text-slate-400">Statistical outlier detection across your portfolio — <code className="text-purple-300">contractiq-clause-anomaly</code></p>
              </div>
            </div>
          </div>
          <button onClick={scan} disabled={scanning} className="px-4 py-2 rounded-lg bg-gradient-to-r from-purple-500 to-fuchsia-600 text-white text-sm font-semibold hover:shadow-lg hover:shadow-purple-500/25 transition-all flex items-center gap-2 disabled:opacity-50">
            {scanning ? <><Loader2 className="w-4 h-4 animate-spin" /> Scanning...</> : <><Sparkles className="w-4 h-4" /> Scan for Anomalies</>}
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
          <div className="flex items-center justify-center h-40"><Loader2 className="w-6 h-6 animate-spin text-purple-400" /></div>
        ) : anomalies.length === 0 ? (
          <div className="rounded-xl border border-slate-800/50 bg-slate-900/30 p-12 text-center">
            <Telescope className="w-12 h-12 text-purple-400/40 mx-auto mb-3" />
            <p className="text-sm text-slate-300 mb-1">No anomalies detected.</p>
            <p className="text-xs text-slate-500">Run a scan to check your portfolio for outlier clauses.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {anomalies.map((a, i) => {
              const s = SEVERITY_STYLES[a.severity] || SEVERITY_STYLES.info;
              return (
                <motion.div key={a.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }}
                  className={`rounded-xl border ${s.border} ${s.bg} p-5`}>
                  <div className="flex items-start gap-4">
                    <div className={`w-10 h-10 rounded-lg ${s.bg} border ${s.border} flex items-center justify-center shrink-0`}>
                      <AlertTriangle className={`w-5 h-5 ${s.text}`} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${s.text}`}>{a.severity}</span>
                        <span className="text-[10px] text-slate-500">Score: {(a.anomaly_score * 100).toFixed(0)}/100</span>
                        <span className="text-[10px] text-slate-500">Clause #{a.clause_id.slice(0, 8)}</span>
                      </div>
                      <p className="text-sm text-white leading-relaxed mb-2">{a.explanation}</p>
                      {a.benchmark_summary && Object.keys(a.benchmark_summary).length > 0 && (
                        <div className="mt-3 rounded-lg bg-slate-900/50 p-3 grid grid-cols-2 md:grid-cols-3 gap-2 text-[11px]">
                          {Object.entries(a.benchmark_summary).map(([k, v]: any) => (
                            <div key={k}>
                              <p className="text-slate-500 uppercase tracking-wider">{k.replace(/_/g, ' ')}</p>
                              <p className="text-white font-medium tabular-nums">{String(v)}</p>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                    <button onClick={() => dismiss(a.id)} className="p-1.5 rounded hover:bg-slate-800 text-slate-500 hover:text-white transition-colors">
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                </motion.div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
