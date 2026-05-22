'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Radar, ChevronLeft, Loader2, Play, ShieldAlert, Calendar } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

interface Refiner {
  id: string;
  refiner: string;
  lbma_gold: string;
  lbma_silver: string;
  lppm_platinum: string;
  lppm_palladium: string;
  ofac_sdn: boolean;
  next_audit_date: string;
  last_audit_findings: string;
  user_contracts: number;
  last_alert: any;
  last_scanned_at: string;
}

const STATUS: Record<string, string> = {
  active:       'text-emerald-300 bg-emerald-500/10 border-emerald-500/30',
  suspended:    'text-amber-300  bg-amber-500/10  border-amber-500/30',
  delisted:     'text-red-300    bg-red-500/10    border-red-500/30',
  not_listed:   'text-slate-500  bg-slate-800/60  border-slate-700',
  unknown:      'text-slate-500  bg-slate-800/60  border-slate-700',
};

export default function RefinersPage() {
  const [rows, setRows] = useState<Refiner[]>([]);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [alerts, setAlerts] = useState<any[]>([]);

  const load = async () => {
    const token = getToken();
    if (!token) return;
    const res = await fetch(`${API_URL}/api/contractiq/metals/refiner-watch`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    setRows((await res.json()).data || []);
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const scan = async () => {
    setScanning(true);
    setToast(null);
    const token = getToken();
    try {
      const res = await fetch(`${API_URL}/api/contractiq/metals/refiner-watch/scan`, {
        method: 'POST', headers: { Authorization: `Bearer ${token}` },
      });
      const j = await res.json();
      setAlerts(j.data?.alerts || []);
      setToast(j.data?.summary || (j.error?.message || 'Scan complete'));
      await load();
    } catch (e: any) {
      setToast(e.message || 'Scan failed');
    } finally { setScanning(false); }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <div className="max-w-7xl mx-auto p-6 lg:p-10">
        <Link href="/metals" className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 mb-4">
          <ChevronLeft className="w-3.5 h-3.5" /> Back to metals
        </Link>

        <div className="flex items-start justify-between mb-6">
          <div className="flex items-center gap-3">
            <Radar className="w-7 h-7 text-orange-300" />
            <div>
              <h1 className="text-2xl font-bold text-white">Refiner Watch</h1>
              <p className="text-sm text-slate-400">Counterparty Good Delivery list status · audit dates · OFAC SDN.</p>
            </div>
          </div>
          <button onClick={scan} disabled={scanning}
            className="px-4 py-2 text-sm rounded-lg bg-orange-500/20 border border-orange-500/40 text-orange-200 hover:bg-orange-500/30 disabled:opacity-50 flex items-center gap-1.5">
            {scanning ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            {scanning ? 'Scanning...' : 'Run scan'}
          </button>
        </div>

        {toast && (
          <div className="mb-4 p-3 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-sm text-cyan-200">{toast}</div>
        )}

        {alerts.length > 0 && (
          <div className="mb-6 space-y-2">
            {alerts.map((a, i) => (
              <div key={i} className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 flex items-start gap-2">
                <ShieldAlert className="w-4 h-4 text-red-300 mt-0.5" />
                <div className="flex-1">
                  <div className="text-sm font-semibold text-red-200">{a.refiner} — {a.alert_kind}</div>
                  <div className="text-xs text-slate-400 mt-0.5">
                    {a.list_affected} · {a.previous_status} → {a.current_status} · effective {a.effective_date}
                  </div>
                  {a.recommended_action && (
                    <div className="text-xs text-cyan-300 mt-1">Action: {a.recommended_action}</div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {loading ? <Loader2 className="w-6 h-6 animate-spin text-slate-500 mx-auto block mt-20" /> : rows.length === 0 ? (
          <div className="text-center py-16 text-sm text-slate-500">
            No refiners tracked yet. Click <span className="text-orange-300">Run scan</span> to discover refiners from your contracts.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-xl bg-slate-900/60 border border-slate-800/80">
            <table className="w-full text-xs">
              <thead className="bg-slate-900/80 text-slate-500 uppercase tracking-wide text-[10px]">
                <tr>
                  <th className="text-left p-3">Refiner</th>
                  <th className="text-left p-3">LBMA Gold</th>
                  <th className="text-left p-3">LBMA Silver</th>
                  <th className="text-left p-3">LPPM Pt</th>
                  <th className="text-left p-3">LPPM Pd</th>
                  <th className="text-left p-3">OFAC</th>
                  <th className="text-left p-3">Next audit</th>
                  <th className="text-right p-3">Contracts</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="border-t border-slate-800/60">
                    <td className="p-3 font-medium text-white">{r.refiner}</td>
                    <td className="p-3"><StatusPill v={r.lbma_gold} /></td>
                    <td className="p-3"><StatusPill v={r.lbma_silver} /></td>
                    <td className="p-3"><StatusPill v={r.lppm_platinum} /></td>
                    <td className="p-3"><StatusPill v={r.lppm_palladium} /></td>
                    <td className="p-3">{r.ofac_sdn ? <span className="text-red-300">listed</span> : <span className="text-slate-500">clean</span>}</td>
                    <td className="p-3 text-slate-400 flex items-center gap-1">
                      {r.next_audit_date && <Calendar className="w-3 h-3" />}
                      {r.next_audit_date || '—'}
                    </td>
                    <td className="p-3 text-right">{r.user_contracts}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function StatusPill({ v }: { v: string | null | undefined }) {
  const key = v || 'unknown';
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] border ${STATUS[key] || STATUS.unknown}`}>{key}</span>
  );
}
