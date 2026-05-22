'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import {
  ShieldCheck, ShieldAlert, ShieldX, Plus, Loader2, ChevronRight,
  CheckCircle2, XCircle, AlertTriangle, Clock, FileCheck2, Building2,
  Flag, Gauge,
} from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { if (typeof window === 'undefined') return null; return localStorage.getItem('contractiq_token'); }

interface KycCheck {
  id: string;
  status: string;
  counterparty: { name: string; country_name?: string; country_iso2?: string; primary_business?: string };
  activity_trigger?: string;
  type_of_business_relationship?: string;
  aggregated_score?: number;
  type_of_check?: string;
  outcome_of_check?: string;
  local_kyc_expert_name?: string;
  signed_at?: string;
  created_at?: string;
  tool_warnings?: string[];
}

const CHECK_COLORS: Record<string, string> = {
  Simplified: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
  Standard: 'text-amber-400 bg-amber-500/10 border-amber-500/30',
  Enhanced: 'text-red-400 bg-red-500/10 border-red-500/30',
};

const OUTCOME_COLORS: Record<string, string> = {
  positive: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
  negative: 'text-red-400 bg-red-500/10 border-red-500/30',
};

export default function KycListPage() {
  const router = useRouter();
  const [checks, setChecks] = useState<KycCheck[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    try {
      const r = await fetch(`${API_URL}/api/contractiq/insights/kyc`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const j = await r.json();
      if (j.data) setChecks(j.data);
    } catch { /* silent */ }
    setLoading(false);
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const counts = {
    total: checks.length,
    running: checks.filter(c => c.status === 'running').length,
    completed: checks.filter(c => c.status === 'completed').length,
    signed: checks.filter(c => c.signed_at).length,
    enhanced: checks.filter(c => c.type_of_check === 'Enhanced').length,
  };

  if (loading) return (
    <div className="min-h-screen bg-[#0B0F19] flex items-center justify-center">
      <Loader2 className="w-8 h-8 text-emerald-400 animate-spin" />
    </div>
  );

  return (
    <div className="min-h-screen bg-[#0B0F19] p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <a href="/credit-risk" className="hover:text-slate-300">Counterparty Risk</a>
              <ChevronRight className="w-3 h-3" />
              <span>KYC Standard Checks</span>
            </div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-3 mt-1">
              <FileCheck2 className="w-7 h-7 text-cyan-400" />
              KYC Standard Check Reports
            </h1>
            <p className="text-sm text-slate-400 mt-1">
              Agent-driven KYC / AML compliance files — sanctions, PEP, UBO, adverse media, enforcement, country risk.
            </p>
          </div>
          <div className="flex gap-2">
            <a
              href="/credit-risk/kyc/new"
              className="px-4 py-2 rounded-lg bg-gradient-to-r from-cyan-500 to-emerald-600 text-white text-sm font-semibold flex items-center gap-2 hover:shadow-lg hover:shadow-cyan-500/20"
            >
              <Plus className="w-4 h-4" /> New KYC Check
            </a>
          </div>
        </div>

        {/* KPI strip */}
        <div className="grid grid-cols-5 gap-4">
          {[
            { label: 'Total Checks', value: counts.total, icon: FileCheck2, color: 'text-cyan-400' },
            { label: 'Running', value: counts.running, icon: Loader2, color: 'text-amber-400' },
            { label: 'Completed', value: counts.completed, icon: CheckCircle2, color: 'text-emerald-400' },
            { label: 'Signed Off', value: counts.signed, icon: ShieldCheck, color: 'text-emerald-300' },
            { label: 'Enhanced DD', value: counts.enhanced, icon: ShieldAlert, color: 'text-red-400' },
          ].map(kpi => (
            <div key={kpi.label} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
              <div className="flex items-center gap-2 mb-2">
                <kpi.icon className={`w-4 h-4 ${kpi.color}`} />
                <span className="text-xs text-slate-400">{kpi.label}</span>
              </div>
              <p className={`text-2xl font-bold ${kpi.color}`}>{kpi.value}</p>
            </div>
          ))}
        </div>

        {/* Check list */}
        {checks.length === 0 ? (
          <div className="text-center py-20 bg-slate-800/20 border border-slate-700/40 rounded-2xl">
            <FileCheck2 className="w-14 h-14 text-slate-700 mx-auto mb-4" />
            <p className="text-slate-400 mb-2 text-sm">No KYC checks yet</p>
            <p className="text-xs text-slate-600 mb-4">Start your first check — the agent will pull real sanctions, PEP, UBO, and adverse-media data.</p>
            <a href="/credit-risk/kyc/new" className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-cyan-500 to-emerald-600 text-white text-sm font-semibold">
              <Plus className="w-4 h-4" /> Start New Check
            </a>
          </div>
        ) : (
          <div className="space-y-2">
            {checks.map((c) => {
              const checkType = c.type_of_check || 'Pending';
              const checkColor = CHECK_COLORS[checkType] || 'text-slate-400 bg-slate-500/10 border-slate-500/30';
              const outcome = c.outcome_of_check;
              const outcomeColor = outcome ? OUTCOME_COLORS[outcome] : '';
              return (
                <motion.a
                  key={c.id}
                  href={`/credit-risk/kyc/${c.id}`}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="block bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 hover:border-cyan-500/50 transition-colors"
                >
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-cyan-500/10 to-emerald-500/10 border border-cyan-500/20 flex items-center justify-center shrink-0">
                      {c.status === 'running' && <Loader2 className="w-5 h-5 text-amber-400 animate-spin" />}
                      {c.status === 'completed' && !c.signed_at && <FileCheck2 className="w-5 h-5 text-cyan-400" />}
                      {c.signed_at && <ShieldCheck className="w-5 h-5 text-emerald-400" />}
                      {c.status === 'failed' && <XCircle className="w-5 h-5 text-red-400" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-white truncate">{c.counterparty?.name || '(no name)'}</span>
                        {c.counterparty?.country_iso2 && (
                          <span className="text-[10px] text-slate-400 flex items-center gap-1">
                            <Flag className="w-3 h-3" /> {c.counterparty.country_iso2}
                          </span>
                        )}
                        {c.counterparty?.primary_business && (
                          <span className="text-[10px] text-slate-500 truncate">• {c.counterparty.primary_business}</span>
                        )}
                      </div>
                      <div className="flex items-center gap-3 mt-1 text-xs text-slate-400">
                        {c.activity_trigger && <span>{c.activity_trigger}</span>}
                        {c.type_of_business_relationship && <span>• {c.type_of_business_relationship}</span>}
                        {c.aggregated_score != null && <span>• Score: {c.aggregated_score.toFixed(2)}</span>}
                        {c.created_at && <span>• {new Date(c.created_at).toLocaleDateString()}</span>}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`text-xs px-2 py-1 rounded-full border ${checkColor}`}>
                        {checkType}
                      </span>
                      {outcome && (
                        <span className={`text-xs px-2 py-1 rounded-full border ${outcomeColor}`}>
                          {outcome}
                        </span>
                      )}
                      {c.signed_at && (
                        <span className="text-[10px] text-emerald-400 flex items-center gap-1">
                          <CheckCircle2 className="w-3 h-3" /> signed
                        </span>
                      )}
                      <ChevronRight className="w-4 h-4 text-slate-600" />
                    </div>
                  </div>
                  {c.tool_warnings && c.tool_warnings.length > 0 && (
                    <div className="mt-2 flex items-center gap-1 text-[10px] text-amber-400/80">
                      <AlertTriangle className="w-3 h-3" /> {c.tool_warnings.length} tool warning(s)
                    </div>
                  )}
                </motion.a>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
