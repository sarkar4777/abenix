'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ShieldCheck, ChevronLeft, Loader2, Play, CheckCircle2, XCircle, AlertCircle, Minus } from 'lucide-react';
import { PageExplainer } from '@/components/PageExplainer';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

interface Contract { id: string; title: string; counterparty: string }
interface Verdict {
  standard: string;
  standard_full_name?: string;
  verdict: 'pass' | 'fail' | 'not_applicable' | 'unclear';
  applicable: boolean;
  citation?: string;
  notes?: string;
}
interface Compliance {
  id: string;
  contract_id: string;
  overall_score: number;
  block_level_issues: number;
  clarification_requests: number;
  verdicts: Verdict[];
  superseded_references: { standard: string; found_in: string; note: string }[];
  summary: string;
  created_at: string;
}

const ICON: Record<string, any> = {
  pass: CheckCircle2,
  fail: XCircle,
  unclear: AlertCircle,
  not_applicable: Minus,
};
const COLOR: Record<string, string> = {
  pass: 'text-emerald-300',
  fail: 'text-red-300',
  unclear: 'text-amber-300',
  not_applicable: 'text-slate-500',
};

export default function MetalsCompliancePage() {
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [rows, setRows] = useState<Compliance[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState<string | null>(null);
  const [expand, setExpand] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const load = async () => {
    const token = getToken();
    if (!token) return;
    const [cRes, rRes] = await Promise.all([
      fetch(`${API_URL}/api/contractiq/contracts`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${API_URL}/api/contractiq/metals/compliance`, { headers: { Authorization: `Bearer ${token}` } }),
    ]);
    setContracts((await cRes.json()).data || []);
    setRows((await rRes.json()).data || []);
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const run = async (id: string) => {
    setRunning(id);
    setToast(null);
    const token = getToken();
    try {
      const res = await fetch(`${API_URL}/api/contractiq/metals/contracts/${id}/compliance-audit`, {
        method: 'POST', headers: { Authorization: `Bearer ${token}` },
      });
      const j = await res.json();
      setToast(j.data ? 'Audit complete' : (j.error?.message || 'Audit failed'));
      await load();
    } catch (e: any) { setToast(e.message); }
    finally { setRunning(null); }
  };

  const byContract = new Map<string, Compliance>();
  rows.forEach((r) => { if (!byContract.has(r.contract_id)) byContract.set(r.contract_id, r); });

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <div className="max-w-7xl mx-auto p-6 lg:p-10">
        <Link href="/metals" className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 mb-4">
          <ChevronLeft className="w-3.5 h-3.5" /> Back to metals
        </Link>

        <div className="flex items-center gap-3 mb-6">
          <ShieldCheck className="w-7 h-7 text-emerald-300" />
          <div>
            <h1 className="text-2xl font-bold text-white">Compliance Audit</h1>
            <p className="text-sm text-slate-400">LBMA Good Delivery + RGG · LPPM · OECD DDG · RJC · Dodd-Frank · EU 2017/821 · ISO · Swiss PMCA · HMRC · REACH · sanctions.</p>
          </div>
        </div>
        <div className="mb-4"><PageExplainer routeKey="metals-compliance" /></div>

        {toast && (
          <div className="mb-4 p-3 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-sm text-cyan-200">{toast}</div>
        )}

        {loading ? (
          <div className="flex items-center justify-center py-20"><Loader2 className="w-6 h-6 animate-spin text-slate-500" /></div>
        ) : (
          <div className="space-y-3">
            {contracts.length === 0 && (
              <div className="text-center py-16 text-sm text-slate-500">No contracts yet — upload one to start.</div>
            )}
            {contracts.map((c) => {
              const r = byContract.get(c.id);
              const isOpen = expand === c.id;
              return (
                <div key={c.id} className="rounded-xl bg-slate-900/60 border border-slate-800/80">
                  <div className="p-4 flex items-center justify-between">
                    <div className="flex-1">
                      <Link href={`/contracts/${c.id}`} className="text-sm font-semibold text-white hover:underline">{c.title}</Link>
                      <div className="text-xs text-slate-500 mt-0.5">{c.counterparty}</div>
                    </div>
                    {r && (
                      <div className="flex items-center gap-4 mr-3">
                        <Score label="Score" value={r.overall_score} />
                        <Tag label="Block-level" value={r.block_level_issues} accent={r.block_level_issues > 0 ? 'red' : 'neutral'} />
                        <Tag label="Clarify" value={r.clarification_requests} accent={r.clarification_requests > 0 ? 'amber' : 'neutral'} />
                      </div>
                    )}
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => run(c.id)}
                        disabled={running === c.id}
                        className="px-3 py-1.5 text-xs rounded-lg bg-emerald-500/20 border border-emerald-500/40 text-emerald-200 hover:bg-emerald-500/30 disabled:opacity-50 flex items-center gap-1.5"
                      >
                        {running === c.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
                        {r ? 'Re-audit' : 'Audit'}
                      </button>
                      {r && (
                        <button onClick={() => setExpand(isOpen ? null : c.id)} className="px-3 py-1.5 text-xs rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700">
                          {isOpen ? 'Hide' : 'Detail'}
                        </button>
                      )}
                    </div>
                  </div>
                  {isOpen && r && (
                    <div className="px-4 pb-4">
                      {r.summary && <div className="text-xs text-slate-300 mb-3 italic">{r.summary}</div>}
                      <div className="space-y-2">
                        {(r.verdicts || []).map((v, idx) => {
                          const Icon = ICON[v.verdict] || Minus;
                          return (
                            <div key={idx} className="p-2.5 rounded-md bg-slate-800/40 border border-slate-800 flex items-start gap-2">
                              <Icon className={`w-4 h-4 mt-0.5 ${COLOR[v.verdict]}`} />
                              <div className="flex-1">
                                <div className="text-xs font-medium text-slate-200">{v.standard_full_name || v.standard}</div>
                                {v.citation && <div className="text-[10px] text-slate-500 mt-0.5">{v.citation}</div>}
                                {v.notes && <div className="text-xs text-slate-400 mt-1 leading-relaxed">{v.notes}</div>}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                      {r.superseded_references && r.superseded_references.length > 0 && (
                        <div className="mt-4">
                          <div className="text-xs uppercase tracking-wide text-amber-300 mb-2">Superseded references</div>
                          {r.superseded_references.map((s, idx) => (
                            <div key={idx} className="text-xs text-slate-400 p-2 rounded bg-amber-500/5 border border-amber-500/20 mb-1">
                              <span className="text-amber-300 font-medium">{s.standard}</span> · {s.found_in} — {s.note}
                            </div>
                          ))}
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

function Score({ label, value }: { label: string; value: number }) {
  const tone = value >= 0.85 ? 'text-emerald-300' : value >= 0.6 ? 'text-amber-300' : 'text-red-300';
  return (
    <div className="text-right">
      <div className="text-[9px] uppercase text-slate-500 tracking-wide">{label}</div>
      <div className={`text-sm font-bold ${tone}`}>{value != null ? value.toFixed(2) : 'n/a'}</div>
    </div>
  );
}

function Tag({ label, value, accent }: { label: string; value: number; accent: string }) {
  const tone: Record<string, string> = {
    neutral: 'bg-slate-800/60 text-slate-300 border-slate-700',
    red: 'bg-red-500/10 text-red-300 border-red-500/30',
    amber: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
  };
  return (
    <div className={`px-2 py-1 rounded-md text-[10px] border ${tone[accent]}`}>
      <span className="opacity-60 mr-1">{label}</span>{value}
    </div>
  );
}
