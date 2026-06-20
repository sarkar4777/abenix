'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Globe, ChevronLeft, Loader2, Play, MapPin, CheckCircle2, XCircle } from 'lucide-react';
import { PageExplainer } from '@/components/PageExplainer';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

interface Contract { id: string; title: string; counterparty: string }
interface Evidence { step: number | string; step_name?: string; evidence_present?: boolean; present?: boolean; evidence_citation?: string; citation?: string; gap?: string; risk?: string }
interface Sourcing {
  id: string;
  contract_id: string;
  origin_country: string;
  origin_risk_class: string;
  mine_disclosed: boolean;
  mine_identity: string;
  refiner_disclosed: boolean;
  refiner_lbma_status: string;
  transport_route: string[];
  oecd_5_step_evidence: Evidence[];
  lbma_rgg_step_evidence: Evidence[];
  rjc_chain_of_custody: any;
  dore_integrity_protocol_applicable: boolean;
  high_risk_origin: boolean;
  russian_origin_exclusion_present: boolean;
  artisanal_source_handling: string;
  gaps_count: number;
  gaps: { item: string; severity: string; remediation: string }[];
  audit_readiness_score: number;
}

export default function SourcingPage() {
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [rows, setRows] = useState<Sourcing[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const load = async () => {
    const token = getToken();
    if (!token) return;
    const [cRes, rRes] = await Promise.all([
      fetch(`${API_URL}/api/contractiq/contracts`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${API_URL}/api/contractiq/metals/sourcing`, { headers: { Authorization: `Bearer ${token}` } }),
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
      await fetch(`${API_URL}/api/contractiq/metals/contracts/${id}/sourcing-audit`, {
        method: 'POST', headers: { Authorization: `Bearer ${token}` },
      });
      await load();
    } finally { setRunning(null); }
  };

  const byContract = new Map<string, Sourcing>();
  rows.forEach((r) => { if (!byContract.has(r.contract_id)) byContract.set(r.contract_id, r); });

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <div className="max-w-7xl mx-auto p-6 lg:p-10">
        <Link href="/metals" className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 mb-4">
          <ChevronLeft className="w-3.5 h-3.5" /> Back to metals
        </Link>
        <div className="flex items-center gap-3 mb-6">
          <Globe className="w-7 h-7 text-violet-300" />
          <div>
            <h1 className="text-2xl font-bold text-white">Responsible Sourcing</h1>
            <p className="text-sm text-slate-400">OECD 5-step · LBMA RGG · RJC Chain of Custody · origin · Doré Integrity protocol.</p>
          </div>
        </div>
        <div className="mb-4"><PageExplainer routeKey="metals-sourcing" /></div>

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
                      <div className="flex items-center gap-4 mr-3">
                        <div className="flex items-center gap-1 text-xs">
                          <MapPin className="w-3.5 h-3.5 text-slate-400" />
                          <span className="text-slate-300">{r.origin_country || 'unknown'}</span>
                          {r.origin_risk_class && (
                            <span className={`ml-1 px-1.5 rounded text-[9px] ${r.origin_risk_class === 'high' ? 'bg-red-500/20 text-red-300' : r.origin_risk_class === 'medium' ? 'bg-amber-500/20 text-amber-300' : 'bg-emerald-500/20 text-emerald-300'}`}>
                              {r.origin_risk_class}
                            </span>
                          )}
                        </div>
                        <div className="text-right">
                          <div className="text-[9px] uppercase text-slate-500">Audit readiness</div>
                          <div className={`text-sm font-bold ${r.audit_readiness_score >= 0.85 ? 'text-emerald-300' : r.audit_readiness_score >= 0.6 ? 'text-amber-300' : 'text-red-300'}`}>
                            {r.audit_readiness_score != null ? r.audit_readiness_score.toFixed(2) : 'n/a'}
                          </div>
                        </div>
                        {r.gaps_count > 0 && (
                          <div className="px-2 py-1 rounded-md text-[10px] border bg-amber-500/10 text-amber-300 border-amber-500/30">
                            {r.gaps_count} gap{r.gaps_count > 1 ? 's' : ''}
                          </div>
                        )}
                      </div>
                    )}
                    <div className="flex items-center gap-2">
                      <button onClick={() => run(c.id)} disabled={running === c.id}
                        className="px-3 py-1.5 text-xs rounded-lg bg-violet-500/20 border border-violet-500/40 text-violet-200 hover:bg-violet-500/30 disabled:opacity-50 flex items-center gap-1.5">
                        {running === c.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
                        {r ? 'Re-audit' : 'Audit'}
                      </button>
                      {r && (
                        <button onClick={() => setOpen(isOpen ? null : c.id)} className="px-3 py-1.5 text-xs rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700">
                          {isOpen ? 'Hide' : 'Detail'}
                        </button>
                      )}
                    </div>
                  </div>
                  {isOpen && r && (
                    <div className="px-4 pb-4 space-y-4">
                      {r.transport_route && r.transport_route.length > 0 && (
                        <div className="text-xs text-slate-400 flex items-center gap-2 flex-wrap">
                          <span className="text-[10px] uppercase text-slate-500">Route</span>
                          {r.transport_route.map((p, i) => (
                            <span key={i} className="flex items-center gap-1">
                              <span className="px-2 py-0.5 rounded bg-slate-800/60 border border-slate-700">{p}</span>
                              {i < r.transport_route.length - 1 && <span className="text-slate-600">→</span>}
                            </span>
                          ))}
                        </div>
                      )}
                      <div>
                        <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1.5">OECD 5-step due diligence</div>
                        <div className="grid grid-cols-1 md:grid-cols-5 gap-2">
                          {(r.oecd_5_step_evidence || []).map((e, i) => (
                            <EvidenceTile key={i} step={e.step?.toString() || (i + 1).toString()} present={!!(e.evidence_present ?? e.present)} citation={e.evidence_citation || e.citation} label={e.step_name} />
                          ))}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1.5">LBMA Responsible Gold Guidance evidence</div>
                        <div className="grid grid-cols-1 md:grid-cols-5 gap-2">
                          {(r.lbma_rgg_step_evidence || []).map((e, i) => (
                            <EvidenceTile key={i} step={e.step?.toString() || (i + 1).toString()} present={!!(e.evidence_present ?? e.present)} citation={e.evidence_citation || e.citation} label={typeof e.step === 'string' ? e.step.replace(/_/g, ' ') : undefined} />
                          ))}
                        </div>
                      </div>
                      {r.gaps && r.gaps.length > 0 && (
                        <div>
                          <div className="text-[10px] uppercase tracking-wide text-amber-300 mb-1.5">Gaps</div>
                          {r.gaps.map((g, i) => (
                            <div key={i} className="text-xs p-2 rounded bg-amber-500/5 border border-amber-500/20 mb-1">
                              <div className="text-amber-300 font-medium">{g.item}</div>
                              <div className="text-slate-400 mt-0.5">{g.remediation}</div>
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

function EvidenceTile({ step, present, citation, label }: { step: string; present: boolean; citation?: string; label?: string }) {
  const Icon = present ? CheckCircle2 : XCircle;
  return (
    <div className={`p-2 rounded-md border text-xs ${present ? 'bg-emerald-500/5 border-emerald-500/20' : 'bg-red-500/5 border-red-500/20'}`}>
      <div className="flex items-center gap-1 mb-1">
        <Icon className={`w-3 h-3 ${present ? 'text-emerald-300' : 'text-red-300'}`} />
        <span className="text-[10px] uppercase tracking-wide text-slate-500">Step {step}</span>
      </div>
      {label && <div className="text-[11px] text-slate-300">{label}</div>}
      {citation && <div className="text-[10px] text-slate-500 mt-0.5">{citation}</div>}
    </div>
  );
}
