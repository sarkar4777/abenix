'use client';

import { useEffect, useState, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import {
  FileCheck2, ChevronRight, Loader2, AlertTriangle, CheckCircle2, XCircle,
  Building2, Flag, ShieldCheck, ShieldAlert, DollarSign,
  Users, Globe, MessageSquare, PenLine, Printer, Clock, Briefcase,
  Info, Gauge, Target, Scale, ExternalLink, Activity, MapPin, Zap, Trash2,
} from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { if (typeof window === 'undefined') return null; return localStorage.getItem('contractiq_token'); }

type Risk = 'L' | 'M' | 'H';
type Outcome = 'ok' | 'fail' | 'n-a';

interface CheckItem {
  name: string; label: string; outcome: Outcome; risk: Risk;
  comment?: string; evidence_urls?: string[];
  reviewed_by?: string; reviewed_at?: string;
}

interface KycData {
  id: string;
  status: string;
  profit_centre?: string;
  activity_trigger?: string;
  type_of_business_relationship?: string;
  start_date_of_check?: string;
  counterparty?: any;
  sanctions_applicable?: boolean;
  indicator_i?: any;
  indicator_ii?: any;
  indicator_iii?: any;
  aggregated_score?: number;
  type_of_check?: string;
  basic_compliance?: any;
  intermediate_checks?: CheckItem[];
  shareholder_structure_summary?: string;
  ubos?: any[];
  discovery_gaps?: any[];
  summary_of_compliance_risk_assessment?: string;
  general_comments?: string;
  legal_consulted?: boolean;
  legal_opinion_summary?: string;
  outcome_of_check?: string;
  top_recommendations?: string[];
  narrative?: string;
  supporting_docs_location?: string;
  local_kyc_expert_name?: string;
  signed_at?: string;
  tool_warnings?: string[];
  cost_usd?: number;
  duration_ms?: number;
  created_at?: string;
  updated_at?: string;
  error_message?: string;
}

const RISK_STYLE: Record<string, { text: string; bg: string; border: string; dot: string }> = {
  L: { text: 'text-emerald-300', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', dot: 'bg-emerald-400' },
  M: { text: 'text-amber-300', bg: 'bg-amber-500/10', border: 'border-amber-500/30', dot: 'bg-amber-400' },
  H: { text: 'text-red-300', bg: 'bg-red-500/10', border: 'border-red-500/30', dot: 'bg-red-400' },
};

const CHECK_TYPE_STYLE: Record<string, { text: string; bg: string; border: string; icon: any }> = {
  Simplified: { text: 'text-emerald-300', bg: 'bg-emerald-500/10', border: 'border-emerald-500/40', icon: ShieldCheck },
  Standard: { text: 'text-amber-300', bg: 'bg-amber-500/10', border: 'border-amber-500/40', icon: ShieldAlert },
  Enhanced: { text: 'text-red-300', bg: 'bg-red-500/10', border: 'border-red-500/40', icon: AlertTriangle },
};

const OUTCOME_STYLE: Record<string, { text: string; label: string; dot: string }> = {
  ok: { text: 'text-emerald-300', label: 'OK', dot: 'bg-emerald-400' },
  fail: { text: 'text-red-300', label: 'NOT OK', dot: 'bg-red-400' },
  'n-a': { text: 'text-slate-400', label: 'N/A', dot: 'bg-slate-500' },
};

function RiskToggle({ value, onChange, disabled }: { value: Risk; onChange: (r: Risk) => void; disabled?: boolean }) {
  return (
    <div className="flex items-center gap-1">
      {(['L', 'M', 'H'] as Risk[]).map(r => {
        const s = RISK_STYLE[r];
        const selected = value === r;
        return (
          <button
            key={r}
            disabled={disabled}
            onClick={() => onChange(r)}
            className={`w-7 h-7 rounded border text-[11px] font-semibold transition ${
              selected ? `${s.bg} ${s.border} ${s.text} shadow-sm` : 'border-slate-700 text-slate-500 hover:border-slate-600'
            } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
            data-testid={`risk-${r}`}
          >
            {r}
          </button>
        );
      })}
    </div>
  );
}

function OutcomeSelect({ value, onChange, disabled }: { value: Outcome; onChange: (o: Outcome) => void; disabled?: boolean }) {
  return (
    <select
      disabled={disabled}
      value={value}
      onChange={e => onChange(e.target.value as Outcome)}
      className="text-[11px] bg-slate-900 border border-slate-700 rounded px-2 py-1 text-white focus:border-emerald-500/60 focus:outline-none disabled:opacity-50"
    >
      <option value="ok">OK</option>
      <option value="fail">NOT OK</option>
      <option value="n-a">N/A</option>
    </select>
  );
}

// Key/value row with a left "label" column and a right value. Skips rows where
// value is empty (removes the "—" placeholder for uninferable fields).
function KVRow({ label, value, highlight = false, children }: {
  label: string; value?: any; highlight?: boolean; children?: React.ReactNode;
}) {
  const display = children ?? value;
  if (display === null || display === undefined || display === '' || display === '—') return null;
  return (
    <div className="grid grid-cols-[220px_1fr] border-b border-slate-800 last:border-b-0">
      <div className="bg-slate-900/40 px-4 py-2.5 text-[11px] font-medium text-slate-400 uppercase tracking-wide">{label}</div>
      <div className={`px-4 py-2.5 text-sm ${highlight ? 'text-white font-semibold' : 'text-slate-200'}`}>{display}</div>
    </div>
  );
}

export default function KycDetailPage() {
  const router = useRouter();
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<KycData | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [signingOff, setSigningOff] = useState(false);
  const [signOffForm, setSignOffForm] = useState({
    outcome_of_check: 'positive',
    general_comments: '',
    legal_consulted: false,
    legal_opinion_summary: '',
    supporting_docs_location: '',
    local_kyc_expert_name: '',
  });

  const fetchData = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    try {
      const r = await fetch(`${API_URL}/api/contractiq/insights/kyc/${id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const j = await r.json();
      if (j.data) {
        setData(j.data);
        setSignOffForm(f => ({
          ...f,
          outcome_of_check: j.data.outcome_of_check || 'positive',
          general_comments: j.data.general_comments || '',
          legal_consulted: j.data.legal_consulted || false,
          legal_opinion_summary: j.data.legal_opinion_summary || '',
          supporting_docs_location: j.data.supporting_docs_location || '',
          local_kyc_expert_name: j.data.local_kyc_expert_name || '',
        }));
      }
    } catch { /* silent */ }
    setLoading(false);
  }, [id]);

  useEffect(() => { fetchData(); }, [fetchData]);

  useEffect(() => {
    if (data?.status === 'running') {
      const t = setInterval(fetchData, 5000);
      return () => clearInterval(t);
    }
  }, [data?.status, fetchData]);

  const updateItem = async (itemName: string, updates: Partial<CheckItem>) => {
    setSaving(itemName);
    try {
      const r = await fetch(`${API_URL}/api/contractiq/insights/kyc/${id}/review-item`, {
        method: 'PUT',
        headers: { Authorization: `Bearer ${getToken()}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_name: itemName, ...updates }),
      });
      const j = await r.json();
      if (j.data) setData(j.data);
    } catch { /* silent */ }
    setSaving(null);
  };

  const signOff = async () => {
    setSigningOff(true);
    try {
      const r = await fetch(`${API_URL}/api/contractiq/insights/kyc/${id}/sign-off`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${getToken()}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(signOffForm),
      });
      const j = await r.json();
      if (j.data) setData(j.data);
    } catch { /* silent */ }
    setSigningOff(false);
  };

  const print = () => window.print();

  if (loading) return (
    <div className="min-h-screen bg-[#0B0F19] flex items-center justify-center">
      <Loader2 className="w-8 h-8 text-emerald-400 animate-spin" />
    </div>
  );
  if (!data) return (
    <div className="min-h-screen bg-[#0B0F19] flex items-center justify-center text-slate-400">
      KYC check not found
    </div>
  );

  const cp = data.counterparty || {};
  const checks = data.intermediate_checks || [];
  const checkType = data.type_of_check || 'Standard';
  const typeStyle = CHECK_TYPE_STYLE[checkType] || CHECK_TYPE_STYLE.Standard;
  const TypeIcon = typeStyle.icon;
  const isSigned = !!data.signed_at;
  const outcome = data.outcome_of_check;

  // Risk distribution across intermediate checks
  const riskCounts = checks.reduce((acc: Record<string, number>, c) => {
    acc[c.risk] = (acc[c.risk] || 0) + 1;
    return acc;
  }, { L: 0, M: 0, H: 0 });

  return (
    <div className="min-h-screen bg-[#0B0F19] print:bg-white">
      <div className="max-w-6xl mx-auto p-6 space-y-5">
        {/* Breadcrumbs + actions */}
        <div className="flex items-center justify-between print:hidden">
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <a href="/credit-risk" className="hover:text-slate-300">Counterparty Risk</a>
            <ChevronRight className="w-3 h-3" />
            <a href="/credit-risk/kyc" className="hover:text-slate-300">KYC Standard Checks</a>
            <ChevronRight className="w-3 h-3" />
            <span className="text-slate-400 truncate max-w-[400px]">{cp.name}</span>
          </div>
          <div className="flex gap-2">
            <button onClick={print} className="px-3 py-1.5 rounded-lg bg-slate-800/50 border border-slate-700 text-xs text-slate-300 flex items-center gap-1.5 hover:bg-slate-700">
              <Printer className="w-3 h-3" /> Print / PDF
            </button>
            <button
              onClick={async () => {
                if (!confirm(`Delete KYC check for "${cp.name}"? This cannot be undone.`)) return;
                try {
                  const r = await fetch(`${API_URL}/api/contractiq/insights/kyc/${id}`, {
                    method: 'DELETE',
                    headers: { Authorization: `Bearer ${getToken()}` },
                  });
                  const j = await r.json();
                  if (j.data?.deleted) router.replace('/credit-risk/kyc');
                } catch { /* silent */ }
              }}
              className="px-3 py-1.5 rounded-lg bg-slate-800/50 border border-red-500/30 text-xs text-red-400 flex items-center gap-1.5 hover:bg-red-500/10"
              data-testid="kyc-delete"
            >
              <Trash2 className="w-3 h-3" /> Delete
            </button>
          </div>
        </div>

        {/* Running state */}
        {data.status === 'running' && (
          <div className="bg-cyan-500/5 border border-cyan-500/30 rounded-xl p-6 flex items-center gap-4">
            <Loader2 className="w-6 h-6 text-cyan-400 animate-spin" />
            <div>
              <p className="text-sm text-cyan-300 font-medium">Agent is running…</p>
              <p className="text-xs text-slate-400 mt-0.5">Screening sanctions, PEP, UBO, adverse media, enforcement, country risk.</p>
            </div>
          </div>
        )}

        {data.status === 'failed' && (
          <div className="bg-red-500/5 border border-red-500/30 rounded-xl p-4 flex items-start gap-3">
            <XCircle className="w-5 h-5 text-red-400 mt-0.5" />
            <div>
              <p className="text-sm text-red-300 font-medium">KYC check failed</p>
              <p className="text-xs text-slate-400 mt-0.5">{data.error_message || 'Unknown error'}</p>
            </div>
          </div>
        )}

        {data.status !== 'running' && data.status !== 'failed' && (
          <>
            {/* Hero header card */}
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              className="relative overflow-hidden rounded-2xl border border-slate-800 bg-gradient-to-br from-slate-900 via-slate-900 to-slate-900/50"
            >
              {/* Accent bar */}
              <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-emerald-500 via-cyan-500 to-emerald-500" />
              <div className="p-6">
                <div className="flex items-start gap-4">
                  <div className="w-14 h-14 rounded-xl bg-gradient-to-br from-emerald-500/20 to-cyan-500/20 border border-emerald-500/30 flex items-center justify-center shrink-0">
                    <FileCheck2 className="w-7 h-7 text-emerald-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-[10px] uppercase tracking-[0.15em] text-slate-500 mb-1">KYC Standard Check Report</p>
                    <h1 className="text-2xl font-bold text-white mb-2 truncate">{cp.name}</h1>
                    <div className="flex flex-wrap items-center gap-3 text-xs">
                      {cp.country_name && (
                        <span className="flex items-center gap-1 text-slate-300"><Flag className="w-3 h-3 text-emerald-400" /> {cp.country_name} ({cp.country_iso2})</span>
                      )}
                      {cp.primary_business && (
                        <span className="flex items-center gap-1 text-slate-300"><Briefcase className="w-3 h-3 text-cyan-400" /> {cp.primary_business}</span>
                      )}
                      {data.profit_centre && (
                        <span className="flex items-center gap-1 text-slate-300"><Building2 className="w-3 h-3 text-slate-500" /> {data.profit_centre}</span>
                      )}
                      {data.start_date_of_check && (
                        <span className="flex items-center gap-1 text-slate-400"><Clock className="w-3 h-3" /> {new Date(data.start_date_of_check).toLocaleDateString()}</span>
                      )}
                    </div>
                  </div>
                  <div className={`px-3 py-2 rounded-lg border ${typeStyle.bg} ${typeStyle.border} shrink-0`}>
                    <div className="flex items-center gap-2">
                      <TypeIcon className={`w-4 h-4 ${typeStyle.text}`} />
                      <div>
                        <p className="text-[9px] uppercase tracking-wider text-slate-500">Check Type</p>
                        <p className={`text-sm font-semibold ${typeStyle.text}`}>{checkType}</p>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Activity pills */}
                <div className="flex flex-wrap gap-2 mt-4">
                  {data.activity_trigger && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800/60 border border-slate-700 text-slate-300">
                      Activity: {data.activity_trigger}
                    </span>
                  )}
                  {data.type_of_business_relationship && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800/60 border border-slate-700 text-slate-300">
                      Relationship: {data.type_of_business_relationship}
                    </span>
                  )}
                  <span className={`text-[10px] px-2 py-0.5 rounded-full border ${
                    data.sanctions_applicable ? 'bg-red-500/10 border-red-500/30 text-red-300' : 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                  }`}>
                    Country sanctions: {data.sanctions_applicable ? 'applicable — Special Check' : 'clear — Standard Check'}
                  </span>
                  {isSigned && outcome && (
                    <span className={`text-[10px] px-2 py-0.5 rounded-full border ${
                      outcome === 'positive' ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300' : 'bg-red-500/10 border-red-500/30 text-red-300'
                    }`}>
                      Outcome: {outcome}
                    </span>
                  )}
                </div>
              </div>
            </motion.div>

            {/* Scoring row */}
            <div className="grid grid-cols-4 gap-3">
              {[
                {
                  key: 'i', label: 'Indicator I',
                  sub: data.indicator_i?.title || 'Country CPI',
                  score: data.indicator_i?.score,
                  value: data.indicator_i?.value,
                  suffix: data.indicator_i?.value != null ? ` (rank ${data.indicator_i.value})` : '',
                  rationale: data.indicator_i?.rationale,
                },
                {
                  key: 'ii', label: 'Indicator II',
                  sub: data.indicator_ii?.title || 'Annual Notional',
                  score: data.indicator_ii?.score,
                  value: data.indicator_ii?.value_usd,
                  suffix: data.indicator_ii?.value_usd != null ? ` ($${(data.indicator_ii.value_usd / 1e6).toFixed(1)}M)` : '',
                  rationale: data.indicator_ii?.rationale,
                },
                {
                  key: 'iii', label: 'Indicator III',
                  sub: data.indicator_iii?.title || 'Industry',
                  score: data.indicator_iii?.score,
                  value: data.indicator_iii?.value,
                  suffix: '',
                  rationale: data.indicator_iii?.rationale,
                },
              ].map(ind => (
                <div key={ind.key} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                  <p className="text-[10px] uppercase tracking-wider text-slate-500">{ind.label}</p>
                  <p className="text-xs text-slate-400 mt-0.5 truncate">{ind.sub}{ind.suffix}</p>
                  <p className="text-2xl font-bold text-white mt-2">{ind.score != null ? Number(ind.score).toFixed(2) : '—'}</p>
                  {ind.rationale && <p className="text-[10px] text-slate-500 mt-1 line-clamp-2">{ind.rationale}</p>}
                </div>
              ))}
              <div className={`rounded-xl p-4 border ${typeStyle.bg} ${typeStyle.border}`}>
                <p className="text-[10px] uppercase tracking-wider text-slate-500">Aggregated Score</p>
                <p className="text-xs text-slate-400 mt-0.5">Sum of Indicators</p>
                <p className="text-2xl font-bold text-white mt-2">{data.aggregated_score != null ? Number(data.aggregated_score).toFixed(2) : '—'}</p>
                <p className={`text-[10px] mt-1 ${typeStyle.text}`}>
                  → {checkType} Due Diligence
                </p>
              </div>
            </div>

            {/* Identity card */}
            <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
              <header className="px-4 py-3 border-b border-slate-700/50 flex items-center gap-2">
                <Building2 className="w-4 h-4 text-cyan-400" />
                <h2 className="text-sm font-semibold text-white">Counterparty Identity</h2>
              </header>
              <div className="text-xs">
                <KVRow label="Legal Name" value={cp.name} highlight />
                <KVRow label="Address" value={cp.address} />
                <KVRow label="Primary Business" value={cp.primary_business} />
                <KVRow label="Business Description" value={cp.description} />
                <KVRow label="Legal Form" value={cp.legal_form} />
                <KVRow label="Registration Number" value={cp.registration_number} />
                <KVRow label="LEI" value={cp.lei} />
                <KVRow label="Incorporation Date" value={cp.incorporation_date} />
                <KVRow label="Entity Status">
                  {cp.status && (
                    <span className={`inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full border ${
                      cp.status === 'active' ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                      : cp.status === 'dissolved' ? 'bg-red-500/10 border-red-500/30 text-red-300'
                      : 'bg-slate-700/30 border-slate-700 text-slate-300'
                    }`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${
                        cp.status === 'active' ? 'bg-emerald-400' : cp.status === 'dissolved' ? 'bg-red-400' : 'bg-slate-400'
                      }`} />
                      {cp.status}
                    </span>
                  )}
                </KVRow>
              </div>
            </section>

            {/* Basic compliance */}
            {data.basic_compliance?.verification_of_legal_existence && (
              <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
                <header className="px-4 py-3 border-b border-slate-700/50 flex items-center gap-2">
                  <Scale className="w-4 h-4 text-cyan-400" />
                  <h2 className="text-sm font-semibold text-white">Basic Compliance Check</h2>
                </header>
                <div className="p-4 flex items-start gap-3">
                  {(() => {
                    const o = data.basic_compliance.verification_of_legal_existence.outcome || 'n-a';
                    const style = OUTCOME_STYLE[o];
                    return (
                      <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border bg-slate-900/30 ${style.text}`}>
                        <span className={`w-2 h-2 rounded-full ${style.dot}`} />
                        <span className="text-xs font-semibold">{style.label}</span>
                      </div>
                    );
                  })()}
                  <div className="flex-1 text-sm text-slate-300">
                    <p className="font-medium text-white mb-1">Verification of Legal Existence</p>
                    <p className="text-xs text-slate-400">{data.basic_compliance.verification_of_legal_existence.comment || 'No comment provided.'}</p>
                    {(data.basic_compliance.verification_of_legal_existence.evidence_urls || []).length > 0 && (
                      <div className="flex flex-wrap gap-2 mt-2">
                        {data.basic_compliance.verification_of_legal_existence.evidence_urls.map((u: string, i: number) => (
                          <a key={i} href={u} target="_blank" rel="noopener noreferrer" className="text-[10px] text-cyan-400 hover:text-cyan-300 flex items-center gap-1">
                            <ExternalLink className="w-3 h-3" /> Evidence {i + 1}
                          </a>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </section>
            )}

            {/* Intermediate checks — the 10-row standard-template table, dark-styled */}
            <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
              <header className="px-4 py-3 border-b border-slate-700/50 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <ShieldCheck className="w-4 h-4 text-cyan-400" />
                  <h2 className="text-sm font-semibold text-white">Intermediate Compliance Checks</h2>
                </div>
                <div className="flex items-center gap-3 text-[10px]">
                  <span className="flex items-center gap-1 text-slate-500">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" /> {riskCounts.L} Low
                  </span>
                  <span className="flex items-center gap-1 text-slate-500">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400" /> {riskCounts.M} Medium
                  </span>
                  <span className="flex items-center gap-1 text-slate-500">
                    <span className="w-1.5 h-1.5 rounded-full bg-red-400" /> {riskCounts.H} High
                  </span>
                </div>
              </header>
              <div className="divide-y divide-slate-800/60">
                {checks.map(c => {
                  const outStyle = OUTCOME_STYLE[c.outcome] || OUTCOME_STYLE['n-a'];
                  return (
                    <div key={c.name} className="grid grid-cols-[1fr_140px_120px] gap-4 px-4 py-3 items-start">
                      <div>
                        <p className="text-sm text-white font-medium">{c.label}</p>
                        <input
                          defaultValue={c.comment || ''}
                          disabled={isSigned}
                          onBlur={(e) => {
                            if (e.target.value !== (c.comment || '')) {
                              updateItem(c.name, { comment: e.target.value });
                            }
                          }}
                          placeholder={isSigned ? '' : 'Add comment…'}
                          className="mt-1 w-full bg-transparent border-0 border-b border-slate-800 focus:border-emerald-500/50 outline-none text-xs text-slate-300 placeholder-slate-600 pb-1 print:pointer-events-none disabled:opacity-80"
                        />
                        {(c.evidence_urls || []).length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-1.5">
                            {c.evidence_urls!.slice(0, 4).map((u, j) => (
                              <a key={j} href={u} target="_blank" rel="noopener noreferrer" className="text-[10px] text-cyan-400 hover:text-cyan-300 flex items-center gap-1">
                                <ExternalLink className="w-2.5 h-2.5" /> ev{j + 1}
                              </a>
                            ))}
                          </div>
                        )}
                        {c.reviewed_at && (
                          <p className="text-[9px] text-slate-600 mt-1 flex items-center gap-1">
                            <PenLine className="w-2.5 h-2.5" /> Reviewed {new Date(c.reviewed_at).toLocaleString()}
                          </p>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <OutcomeSelect value={c.outcome} onChange={o => updateItem(c.name, { outcome: o })} disabled={isSigned} />
                        <span className={`flex items-center gap-1 text-[10px] ${outStyle.text}`}>
                          <span className={`w-1.5 h-1.5 rounded-full ${outStyle.dot}`} />
                        </span>
                      </div>
                      <div>
                        <RiskToggle value={c.risk} onChange={r => updateItem(c.name, { risk: r })} disabled={isSigned} />
                        {saving === c.name && (
                          <p className="text-[9px] text-cyan-500 mt-1">saving…</p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>

            {/* Shareholder / UBO block */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
                <header className="px-4 py-3 border-b border-slate-700/50 flex items-center gap-2">
                  <GitBranchIcon />
                  <h2 className="text-sm font-semibold text-white">Shareholder Structure</h2>
                </header>
                <div className="p-4 text-sm text-slate-300 whitespace-pre-line min-h-[80px]">
                  {data.shareholder_structure_summary || <span className="text-slate-500 italic text-xs">No shareholder structure data collected automatically. Request shareholder register copy from counterparty.</span>}
                </div>
              </section>
              <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
                <header className="px-4 py-3 border-b border-slate-700/50 flex items-center gap-2">
                  <Users className="w-4 h-4 text-cyan-400" />
                  <h2 className="text-sm font-semibold text-white">UBOs ≥ 20%</h2>
                  {data.ubos && data.ubos.length > 0 && (
                    <span className="text-[10px] text-slate-500">{data.ubos.length}</span>
                  )}
                </header>
                <div className="p-4 min-h-[80px]">
                  {(data.ubos || []).length === 0 ? (
                    <p className="text-xs text-slate-500 italic">No UBOs auto-identified. Request KYC questionnaire + certified shareholder register copy.</p>
                  ) : (
                    <ul className="space-y-2">
                      {(data.ubos || []).map((u: any, i: number) => (
                        <li key={i} className="flex items-center gap-2 text-xs">
                          <div className="w-6 h-6 rounded-full bg-gradient-to-br from-emerald-500/20 to-cyan-500/20 border border-emerald-500/30 flex items-center justify-center text-[10px] font-semibold text-emerald-300">
                            {(u.name || '?').charAt(0).toUpperCase()}
                          </div>
                          <div className="flex-1">
                            <p className="text-white font-medium">{u.name}</p>
                            <p className="text-[10px] text-slate-500">
                              {u.effective_pct != null && `${u.effective_pct}% • `}
                              {u.nationality && `${u.nationality} • `}
                              {u.source && `${u.source}`}
                            </p>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </section>
            </div>

            {/* Discovery gaps */}
            {(data.discovery_gaps || []).length > 0 && (
              <section className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-4">
                <div className="flex items-center gap-2 mb-3">
                  <AlertTriangle className="w-4 h-4 text-amber-400" />
                  <h2 className="text-sm font-semibold text-amber-200">Discovery Gaps — manual verification required</h2>
                </div>
                <ul className="space-y-1.5">
                  {(data.discovery_gaps || []).map((g: any, i: number) => (
                    <li key={i} className="text-xs text-amber-100/80 flex items-start gap-2">
                      <span className="text-amber-400 mt-0.5">•</span>
                      <span><strong className="text-amber-200">{g.node}</strong>: {g.reason}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* Narrative */}
            {data.narrative && (
              <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
                <header className="px-4 py-3 border-b border-slate-700/50 flex items-center gap-2">
                  <MessageSquare className="w-4 h-4 text-cyan-400" />
                  <h2 className="text-sm font-semibold text-white">Agent Narrative</h2>
                </header>
                <div className="p-4 space-y-3">
                  <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-line">{data.narrative}</p>
                  {(data.top_recommendations || []).length > 0 && (
                    <div className="pt-3 border-t border-slate-800">
                      <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Top Recommendations</p>
                      <ul className="space-y-1.5">
                        {data.top_recommendations?.map((r, i) => (
                          <li key={i} className="flex items-start gap-2 text-sm text-slate-300">
                            <Target className="w-3 h-3 text-emerald-400 mt-1 shrink-0" />
                            <span>{r}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </section>
            )}

            {/* Tool warnings expandable */}
            {data.tool_warnings && data.tool_warnings.length > 0 && (
              <details className="bg-slate-800/20 border border-slate-800 rounded-xl p-3 text-[11px] print:hidden">
                <summary className="cursor-pointer text-slate-400 hover:text-slate-300 flex items-center gap-2">
                  <Info className="w-3 h-3" /> {data.tool_warnings.length} tool warning(s) during scan
                </summary>
                <ul className="mt-2 space-y-0.5 pl-5">
                  {data.tool_warnings.map((w, i) => <li key={i} className="text-slate-500">• {w}</li>)}
                </ul>
              </details>
            )}

            {/* Sign-off state */}
            {isSigned ? (
              <section className="bg-emerald-500/5 border border-emerald-500/30 rounded-xl p-4 flex items-center gap-3">
                <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                <div className="flex-1">
                  <p className="text-sm text-emerald-200 font-semibold">Signed off by {data.local_kyc_expert_name}</p>
                  <p className="text-[11px] text-slate-400 mt-0.5">
                    {new Date(data.signed_at!).toLocaleString()} · Outcome: <strong className={outcome === 'positive' ? 'text-emerald-300' : 'text-red-300'}>{outcome}</strong>
                    {data.supporting_docs_location && <> · Docs: <span className="text-slate-300">{data.supporting_docs_location}</span></>}
                  </p>
                </div>
              </section>
            ) : data.status === 'completed' && (
              <motion.section
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="bg-slate-800/30 border border-cyan-500/30 rounded-xl overflow-hidden print:hidden"
              >
                <header className="px-4 py-3 border-b border-cyan-500/20 bg-cyan-500/5 flex items-center gap-2">
                  <PenLine className="w-4 h-4 text-cyan-400" />
                  <h2 className="text-sm font-semibold text-white">Sign-off</h2>
                </header>
                <div className="p-4 grid grid-cols-2 gap-4">
                  <label className="block text-xs text-slate-400">
                    Outcome of Check
                    <select
                      value={signOffForm.outcome_of_check}
                      onChange={e => setSignOffForm(f => ({ ...f, outcome_of_check: e.target.value }))}
                      className="mt-1 w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-emerald-500/60 focus:outline-none"
                    >
                      <option value="positive">Positive — Enter / Continue</option>
                      <option value="negative">Negative — Do not enter / Terminate</option>
                    </select>
                  </label>
                  <label className="block text-xs text-slate-400">
                    Local KYC Expert Name
                    <input
                      value={signOffForm.local_kyc_expert_name}
                      onChange={e => setSignOffForm(f => ({ ...f, local_kyc_expert_name: e.target.value }))}
                      placeholder="Defaults to logged-in user"
                      className="mt-1 w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-600 focus:border-emerald-500/60 focus:outline-none"
                    />
                  </label>
                  <label className="block text-xs text-slate-400">
                    Supporting Docs Location
                    <input
                      value={signOffForm.supporting_docs_location}
                      onChange={e => setSignOffForm(f => ({ ...f, supporting_docs_location: e.target.value }))}
                      placeholder="SharePoint / Docusign URL"
                      className="mt-1 w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-600 focus:border-emerald-500/60 focus:outline-none"
                    />
                  </label>
                  <label className="flex items-end gap-2 text-xs text-slate-400 pb-2">
                    <input
                      type="checkbox"
                      checked={signOffForm.legal_consulted}
                      onChange={e => setSignOffForm(f => ({ ...f, legal_consulted: e.target.checked }))}
                      className="rounded border-slate-600 w-4 h-4 accent-emerald-500"
                    />
                    Legal was consulted
                  </label>
                  <label className="col-span-2 block text-xs text-slate-400">
                    General Comments
                    <textarea
                      value={signOffForm.general_comments}
                      onChange={e => setSignOffForm(f => ({ ...f, general_comments: e.target.value }))}
                      rows={2}
                      className="mt-1 w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-emerald-500/60 focus:outline-none"
                    />
                  </label>
                  {signOffForm.legal_consulted && (
                    <label className="col-span-2 block text-xs text-slate-400">
                      Legal Opinion Summary
                      <textarea
                        value={signOffForm.legal_opinion_summary}
                        onChange={e => setSignOffForm(f => ({ ...f, legal_opinion_summary: e.target.value }))}
                        rows={2}
                        className="mt-1 w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-emerald-500/60 focus:outline-none"
                      />
                    </label>
                  )}
                  <div className="col-span-2 flex justify-end">
                    <button
                      onClick={signOff}
                      disabled={signingOff}
                      data-testid="kyc-sign-off"
                      className="px-5 py-2 rounded-lg bg-gradient-to-r from-emerald-500 to-cyan-600 text-white font-semibold text-sm flex items-center gap-2 hover:shadow-lg hover:shadow-emerald-500/20 disabled:opacity-50"
                    >
                      {signingOff ? <><Loader2 className="w-4 h-4 animate-spin" /> Signing…</> : <><PenLine className="w-4 h-4" /> Sign Off</>}
                    </button>
                  </div>
                </div>
              </motion.section>
            )}

            {/* Meta footer */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-slate-600 pt-1">
              {data.created_at && <span>Created: {new Date(data.created_at).toLocaleString()}</span>}
              {data.cost_usd != null && <span>Agent cost: ${data.cost_usd.toFixed(4)}</span>}
              {data.duration_ms != null && <span>Duration: {(data.duration_ms / 1000).toFixed(1)}s</span>}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// Small GitBranch icon with the cyan color — avoids importing an extra lib.
function GitBranchIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-cyan-400">
      <line x1="6" y1="3" x2="6" y2="15" />
      <circle cx="18" cy="6" r="3" />
      <circle cx="6" cy="18" r="3" />
      <path d="M18 9a9 9 0 0 1-9 9" />
    </svg>
  );
}
