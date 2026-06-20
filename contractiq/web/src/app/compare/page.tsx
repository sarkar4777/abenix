'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import Link from 'next/link';
import {
  FileSearch, Upload, BarChart3, MessageSquare, FileText, TrendingUp,
  LogOut, ChevronLeft, ChevronRight, CheckCircle, Zap, Shield, Scale, Layers,
} from 'lucide-react';
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, Cell,
} from 'recharts';
import { PageExplainer } from '@/components/PageExplainer';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { if (typeof window === 'undefined') return null; return localStorage.getItem('contractiq_token'); }
function getUser() { if (typeof window === 'undefined') return null; try { return JSON.parse(localStorage.getItem('contractiq_user') || 'null'); } catch { return null; } }

const NAV_ITEMS = [
  { label: 'Dashboard', icon: BarChart3, href: '/dashboard' },
  { label: 'Upload Contract', icon: Upload, href: '/upload' },
  { label: 'My Contracts', icon: FileText, href: '/contracts' },
  { label: 'Compare', icon: TrendingUp, href: '/compare' },
  { label: 'Chat', icon: MessageSquare, href: '/chat' },
];

const COLORS = ['#10b981', '#f59e0b', '#8b5cf6', '#06b6d4', '#ef4444'];
const ANALYSIS_TYPES = [
  { id: 'side_by_side', label: 'Side-by-Side', icon: Layers, desc: 'Full term comparison table' },
  { id: 'risk_matrix', label: 'Risk Matrix', icon: Shield, desc: 'Risk category spider overlay' },
  { id: 'financial', label: 'Financial', icon: Scale, desc: 'Value, pricing, capacity' },
];

interface Contract { id: string; title: string; contract_type: string; status: string; counterparty_a: string; risk_score: number | null; total_capacity_mw: number | null; contract_value: number | null; effective_date: string | null; expiry_date: string | null; }
interface ContractDetail extends Contract { clauses: any[]; risk_analyses: any[]; assets: any[]; extracted_data: any[]; }

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (<div className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 shadow-xl">
    <p className="text-xs text-slate-400 mb-1">{label}</p>
    {payload.map((p: any, i: number) => (<p key={i} className="text-xs font-medium" style={{ color: p.color }}>{p.name}: {typeof p.value === 'number' ? p.value.toFixed(1) : p.value}</p>))}
  </div>);
};

export default function ComparePage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [step, setStep] = useState(1);
  const [analysisType, setAnalysisType] = useState('side_by_side');
  const [details, setDetails] = useState<Record<string, ContractDetail>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = getToken();
    if (!token) { router.replace('/'); return; }
    setUser(getUser());
    fetch(`${API_URL}/api/contractiq/contracts?limit=100&sort=newest`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json()).then(body => { setContracts(body.data || []); setLoading(false); }).catch(() => setLoading(false));
  }, [router]);

  const toggleSelect = (id: string) => {
    setSelected(prev => prev.includes(id) ? prev.filter(x => x !== id) : prev.length < 5 ? [...prev, id] : prev);
  };

  const loadDetails = async () => {
    const token = getToken();
    const results: Record<string, ContractDetail> = {};
    await Promise.all(selected.map(async (id) => {
      try {
        const res = await fetch(`${API_URL}/api/contractiq/contracts/${id}`, { headers: { Authorization: `Bearer ${token}` } });
        const body = await res.json();
        if (body.data) results[id] = body.data;
      } catch { /* skip */ }
    }));
    setDetails(results);
  };

  const goToResults = async () => {
    setLoading(true);
    await loadDetails();
    setLoading(false);
    setStep(3);
  };

  const logout = () => { localStorage.removeItem('contractiq_token'); localStorage.removeItem('contractiq_refresh_token'); localStorage.removeItem('contractiq_user'); router.replace('/'); };
  const selectedContracts = contracts.filter(c => selected.includes(c.id));

  if (!user) return <div className="min-h-screen bg-[#0B0F19] flex items-center justify-center"><div className="w-8 h-8 border-2 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin" /></div>;

  // Build chart data for results
  const riskRadarData = (() => {
    const categories = ['market', 'credit', 'operational', 'regulatory', 'legal', 'technology'];
    return categories.map(cat => {
      const entry: any = { category: cat.charAt(0).toUpperCase() + cat.slice(1) };
      selected.forEach((id, i) => {
        const d = details[id];
        const risk = d?.risk_analyses?.find((r: any) => r.category === cat);
        entry[d?.title || `Contract ${i + 1}`] = risk?.score || 0;
      });
      return entry;
    });
  })();

  return (
    <div className="min-h-screen bg-[#0B0F19]">
      <div className="p-6">
        <div className="max-w-6xl mx-auto space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-xl font-bold text-white">Contract Comparison</h1>
              <p className="text-sm text-slate-400 mt-1">Compare 2-5 contracts side by side</p>
            </div>
            <div className="flex gap-2">
              {[1, 2, 3].map(s => (
                <div key={s} className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold ${step >= s ? 'bg-emerald-500 text-white' : 'bg-slate-800 text-slate-500'}`}>{s}</div>
              ))}
            </div>
          </div>

          <PageExplainer routeKey="compare" />

          {!loading && contracts.filter(c => c.status === 'analyzed').length < 2 && step === 1 && (
            <div className="bg-slate-800/20 border border-slate-700/40 rounded-2xl p-12 text-center">
              <Upload className="w-14 h-14 text-slate-700 mx-auto mb-3" />
              <p className="text-base font-semibold text-white mb-1">You do not have any contracts yet</p>
              <p className="text-sm text-slate-400 mb-5">Upload at least 2 to use Compare.</p>
              <Link href="/upload" className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-500 text-white text-sm font-medium hover:bg-emerald-400 transition-colors">
                <Upload className="w-4 h-4" /> Upload your first contract
              </Link>
            </div>
          )}

          {/* Step 1: Select Contracts */}
          {step === 1 && contracts.filter(c => c.status === 'analyzed').length >= 2 && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
              <p className="text-xs text-slate-400">Select 2-5 contracts to compare ({selected.length} selected)</p>
              <div className="grid grid-cols-2 gap-3">
                {contracts.filter(c => c.status === 'analyzed').map(c => (
                  <div key={c.id} onClick={() => toggleSelect(c.id)}
                    className={`bg-slate-800/30 border rounded-xl p-4 cursor-pointer transition-all ${selected.includes(c.id) ? 'border-emerald-500/50 bg-emerald-500/5' : 'border-slate-700/50 hover:border-slate-600'}`}>
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <div className={`w-5 h-5 rounded border flex items-center justify-center ${selected.includes(c.id) ? 'bg-emerald-500 border-emerald-500' : 'border-slate-600'}`}>
                          {selected.includes(c.id) && <CheckCircle className="w-3 h-3 text-white" />}
                        </div>
                        <span className="text-sm font-medium text-white">{c.title}</span>
                      </div>
                      <span className={`text-[10px] px-2 py-0.5 rounded-full ${c.contract_type === 'ppa' ? 'bg-emerald-500/10 text-emerald-400' : c.contract_type === 'gas' ? 'bg-amber-500/10 text-amber-400' : 'bg-slate-500/10 text-slate-400'}`}>{c.contract_type?.toUpperCase()}</span>
                    </div>
                    <div className="flex items-center gap-4 text-xs text-slate-400">
                      <span>{c.counterparty_a || '—'}</span>
                      {c.total_capacity_mw && <span className="text-emerald-400">{c.total_capacity_mw} MW</span>}
                      {c.risk_score != null && <span className={c.risk_score > 60 ? 'text-red-400' : c.risk_score > 35 ? 'text-amber-400' : 'text-emerald-400'}>Risk: {c.risk_score.toFixed(0)}</span>}
                    </div>
                  </div>
                ))}
              </div>
              <button onClick={() => setStep(2)} disabled={selected.length < 2}
                className="w-full py-3 rounded-lg bg-emerald-500 text-white font-medium text-sm hover:bg-emerald-400 disabled:opacity-30 transition-colors flex items-center justify-center gap-2">
                Continue <ChevronRight className="w-4 h-4" />
              </button>
            </motion.div>
          )}

          {/* Step 2: Choose Analysis Type */}
          {step === 2 && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
              <button onClick={() => setStep(1)} className="flex items-center gap-1 text-xs text-slate-400 hover:text-white"><ChevronLeft className="w-3 h-3" /> Back</button>
              <p className="text-xs text-slate-400">Choose analysis type for {selected.length} contracts</p>
              <div className="grid grid-cols-3 gap-4">
                {ANALYSIS_TYPES.map(at => (
                  <div key={at.id} onClick={() => setAnalysisType(at.id)}
                    className={`bg-slate-800/30 border rounded-xl p-6 cursor-pointer transition-all text-center ${analysisType === at.id ? 'border-emerald-500/50 bg-emerald-500/5' : 'border-slate-700/50 hover:border-slate-600'}`}>
                    <at.icon className={`w-8 h-8 mx-auto mb-3 ${analysisType === at.id ? 'text-emerald-400' : 'text-slate-500'}`} />
                    <p className="text-sm font-medium text-white">{at.label}</p>
                    <p className="text-[10px] text-slate-500 mt-1">{at.desc}</p>
                  </div>
                ))}
              </div>
              <button onClick={goToResults} disabled={loading}
                className="w-full py-3 rounded-lg bg-emerald-500 text-white font-medium text-sm hover:bg-emerald-400 disabled:opacity-30 transition-colors flex items-center justify-center gap-2">
                {loading ? 'Loading...' : 'Compare'} <ChevronRight className="w-4 h-4" />
              </button>
            </motion.div>
          )}

          {/* Step 3: Results */}
          {step === 3 && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
              <button onClick={() => setStep(2)} className="flex items-center gap-1 text-xs text-slate-400 hover:text-white"><ChevronLeft className="w-3 h-3" /> Back</button>

              {/* Selected contracts badges */}
              <div className="flex gap-2 flex-wrap">
                {selectedContracts.map((c, i) => (
                  <span key={c.id} className="text-xs px-3 py-1 rounded-full border" style={{ borderColor: COLORS[i], color: COLORS[i] }}>
                    {c.title}
                  </span>
                ))}
              </div>

              {/* Side-by-Side */}
              {analysisType === 'side_by_side' && (
                <div className="space-y-4">
                  <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-slate-700/30">
                          <th className="text-left py-3 px-4 text-slate-400 font-medium w-40">Field</th>
                          {selectedContracts.map((c, i) => (
                            <th key={c.id} className="text-left py-3 px-4 font-medium" style={{ color: COLORS[i] }}>{c.title.slice(0, 25)}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {[
                          { label: 'Type', fn: (c: Contract) => c.contract_type?.toUpperCase() },
                          { label: 'Counterparty', fn: (c: Contract) => c.counterparty_a || '—' },
                          { label: 'Capacity', fn: (c: Contract) => c.total_capacity_mw ? `${c.total_capacity_mw} MW` : '—' },
                          { label: 'Value', fn: (c: Contract) => c.contract_value ? `$${(c.contract_value / 1e6).toFixed(1)}M` : '—' },
                          { label: 'Risk Score', fn: (c: Contract) => c.risk_score != null ? c.risk_score.toFixed(0) + '/100' : '—' },
                          { label: 'Effective', fn: (c: Contract) => c.effective_date ? new Date(c.effective_date).toLocaleDateString() : '—' },
                          { label: 'Expiry', fn: (c: Contract) => c.expiry_date ? new Date(c.expiry_date).toLocaleDateString() : '—' },
                          { label: 'Clauses', fn: (c: Contract) => details[c.id]?.clauses?.length?.toString() || '—' },
                          { label: 'Assets', fn: (c: Contract) => details[c.id]?.assets?.length?.toString() || '—' },
                        ].map(row => (
                          <tr key={row.label} className="border-b border-slate-700/20 hover:bg-slate-700/10">
                            <td className="py-2.5 px-4 text-slate-400 font-medium">{row.label}</td>
                            {selectedContracts.map(c => (
                              <td key={c.id} className="py-2.5 px-4 text-white">{row.fn(c)}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {/* Capacity & Risk comparison bars */}
                  <div className="grid grid-cols-2 gap-4">
                    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                      <h3 className="text-sm font-semibold text-white mb-3">Capacity Comparison</h3>
                      <ResponsiveContainer width="100%" height={200}>
                        <BarChart data={selectedContracts.map((c, i) => ({ name: c.title.slice(0, 15), mw: c.total_capacity_mw || 0, fill: COLORS[i] }))}>
                          <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 9 }} axisLine={false} /><YAxis tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} /><Tooltip content={<CustomTooltip />} />
                          <Bar dataKey="mw" name="MW" radius={[4, 4, 0, 0]}>{selectedContracts.map((_, i) => <Cell key={i} fill={COLORS[i]} />)}</Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                      <h3 className="text-sm font-semibold text-white mb-3">Risk Score Comparison</h3>
                      <ResponsiveContainer width="100%" height={200}>
                        <BarChart data={selectedContracts.map((c, i) => ({ name: c.title.slice(0, 15), risk: c.risk_score || 0, fill: COLORS[i] }))}>
                          <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 9 }} axisLine={false} /><YAxis domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} /><Tooltip content={<CustomTooltip />} />
                          <Bar dataKey="risk" name="Risk" radius={[4, 4, 0, 0]}>{selectedContracts.map((_, i) => <Cell key={i} fill={COLORS[i]} />)}</Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                </div>
              )}

              {/* Risk Matrix */}
              {analysisType === 'risk_matrix' && (
                <div className="space-y-4">
                  {/* Risk score cards */}
                  <div className="grid grid-cols-5 gap-3">
                    {selectedContracts.map((c, i) => (
                      <div key={c.id} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 text-center">
                        <div className={`text-2xl font-bold ${(c.risk_score || 0) > 60 ? 'text-red-400' : (c.risk_score || 0) > 35 ? 'text-amber-400' : 'text-emerald-400'}`}>{c.risk_score?.toFixed(0) || '—'}</div>
                        <p className="text-[10px] text-slate-500 mt-1" style={{ color: COLORS[i] }}>{c.title.slice(0, 20)}</p>
                      </div>
                    ))}
                  </div>

                  {/* Overlaid Radar */}
                  <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                    <h3 className="text-sm font-semibold text-white mb-3">Risk Category Comparison</h3>
                    <ResponsiveContainer width="100%" height={350}>
                      <RadarChart data={riskRadarData}>
                        <PolarGrid stroke="#1e293b" />
                        <PolarAngleAxis dataKey="category" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                        <PolarRadiusAxis angle={30} domain={[0, 100]} tick={{ fill: '#475569', fontSize: 9 }} />
                        {selectedContracts.map((c, i) => {
                          const d = details[c.id];
                          const key = d?.title || `Contract ${i + 1}`;
                          return <Radar key={c.id} name={key} dataKey={key} stroke={COLORS[i]} fill={COLORS[i]} fillOpacity={0.1} strokeWidth={2} />;
                        })}
                        <Tooltip content={<CustomTooltip />} />
                        <Legend formatter={(v: string) => <span className="text-xs text-slate-400">{v.slice(0, 25)}</span>} />
                      </RadarChart>
                    </ResponsiveContainer>
                  </div>

                  {/* Risk category breakdown */}
                  <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                    <h3 className="text-sm font-semibold text-white mb-3">Risk Scores by Category</h3>
                    <ResponsiveContainer width="100%" height={250}>
                      <BarChart data={riskRadarData}>
                        <XAxis dataKey="category" tick={{ fill: '#94a3b8', fontSize: 10 }} axisLine={false} />
                        <YAxis domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} />
                        <Tooltip content={<CustomTooltip />} />
                        {selectedContracts.map((c, i) => {
                          const d = details[c.id];
                          const key = d?.title || `Contract ${i + 1}`;
                          return <Bar key={c.id} dataKey={key} fill={COLORS[i]} radius={[2, 2, 0, 0]} />;
                        })}
                        <Legend formatter={(v: string) => <span className="text-xs text-slate-400">{v.slice(0, 25)}</span>} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}

              {/* Financial */}
              {analysisType === 'financial' && (
                <div className="space-y-4">
                  <div className="grid grid-cols-3 gap-3">
                    {[
                      { label: 'Total Capacity', value: `${selectedContracts.reduce((s, c) => s + (c.total_capacity_mw || 0), 0).toFixed(0)} MW` },
                      { label: 'Total Value', value: `$${(selectedContracts.reduce((s, c) => s + (c.contract_value || 0), 0) / 1e6).toFixed(1)}M` },
                      { label: 'Avg Risk', value: `${(selectedContracts.reduce((s, c) => s + (c.risk_score || 0), 0) / selectedContracts.length).toFixed(0)}/100` },
                    ].map(s => (
                      <div key={s.label} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 text-center">
                        <p className="text-2xl font-bold text-cyan-400">{s.value}</p>
                        <p className="text-[10px] text-slate-500 uppercase mt-1">{s.label}</p>
                      </div>
                    ))}
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                      <h3 className="text-sm font-semibold text-white mb-3">Contract Value</h3>
                      <ResponsiveContainer width="100%" height={200}>
                        <BarChart data={selectedContracts.map((c, i) => ({ name: c.title.slice(0, 15), value: (c.contract_value || 0) / 1e6 }))}>
                          <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 9 }} axisLine={false} /><YAxis tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} /><Tooltip content={<CustomTooltip />} />
                          <Bar dataKey="value" name="Value ($M)" radius={[4, 4, 0, 0]}>{selectedContracts.map((_, i) => <Cell key={i} fill={COLORS[i]} />)}</Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                      <h3 className="text-sm font-semibold text-white mb-3">Capacity (MW)</h3>
                      <ResponsiveContainer width="100%" height={200}>
                        <BarChart data={selectedContracts.map((c, i) => ({ name: c.title.slice(0, 15), mw: c.total_capacity_mw || 0 }))}>
                          <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 9 }} axisLine={false} /><YAxis tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} /><Tooltip content={<CustomTooltip />} />
                          <Bar dataKey="mw" name="MW" radius={[4, 4, 0, 0]}>{selectedContracts.map((_, i) => <Cell key={i} fill={COLORS[i]} />)}</Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </div>

                  {/* Extracted commercial terms comparison */}
                  <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
                    <div className="px-4 py-3 border-b border-slate-700/30"><h3 className="text-sm font-semibold text-white">Commercial Terms</h3></div>
                    <table className="w-full text-xs">
                      <thead><tr className="border-b border-slate-700/30">
                        <th className="text-left py-2 px-4 text-slate-400 font-medium">Term</th>
                        {selectedContracts.map((c, i) => (<th key={c.id} className="text-left py-2 px-4 font-medium" style={{ color: COLORS[i] }}>{c.title.slice(0, 20)}</th>))}
                      </tr></thead>
                      <tbody>
                        {(() => {
                          const allFields = new Set<string>();
                          selectedContracts.forEach(c => (details[c.id]?.extracted_data || []).filter((d: any) => d.section === 'commercial_terms').forEach((d: any) => allFields.add(d.field_name)));
                          return Array.from(allFields).slice(0, 15).map(field => (
                            <tr key={field} className="border-b border-slate-700/20">
                              <td className="py-2 px-4 text-slate-400">{field.replace(/_/g, ' ')}</td>
                              {selectedContracts.map(c => {
                                const val = (details[c.id]?.extracted_data || []).find((d: any) => d.field_name === field);
                                return <td key={c.id} className="py-2 px-4 text-white">{val?.field_value?.slice(0, 40) || '—'}</td>;
                              })}
                            </tr>
                          ));
                        })()}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </motion.div>
          )}
        </div>
      </div>
    </div>
  );
}
