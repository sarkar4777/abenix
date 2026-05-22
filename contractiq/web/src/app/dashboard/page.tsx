'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import {
  FileSearch, Upload, BarChart3, MessageSquare, FileText, TrendingUp,
  LogOut, Plus, Zap, Calendar, ChevronRight, Shield,
  DollarSign, Clock,
} from 'lucide-react';
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, Legend,
} from 'recharts';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';

function getToken() {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('contractiq_token');
}
function getUser() {
  if (typeof window === 'undefined') return null;
  try { return JSON.parse(localStorage.getItem('contractiq_user') || 'null'); } catch { return null; }
}

const NAV_ITEMS = [
  { label: 'Dashboard', icon: BarChart3, href: '/dashboard' },
  { label: 'Upload Contract', icon: Upload, href: '/upload' },
  { label: 'My Contracts', icon: FileText, href: '/contracts' },
  { label: 'Compare', icon: TrendingUp, href: '/compare' },
  { label: 'Chat', icon: MessageSquare, href: '/chat' },
];

const PIE_COLORS = ['#10b981', '#f59e0b', '#8b5cf6', '#06b6d4', '#ef4444'];

interface Analytics {
  total_contracts: number;
  total_capacity_mw: number;
  avg_risk_score: number;
  total_contract_value: number;
  contracts_expiring_soon: number;
  by_type: { type: string; count: number; capacity: number }[];
  risk_by_category: { category: string; avg_score: number }[];
  contracts: {
    id: string; title: string; type: string; risk_score: number | null;
    capacity_mw: number | null; value: number | null; status: string;
    effective_date: string | null; expiry_date: string | null; counterparty: string;
  }[];
  clause_distribution: { type: string; risk_level: string; count: number }[];
  upcoming_events: { type: string; date: string; description: string; contract: string }[];
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 shadow-xl">
      <p className="text-xs text-slate-400 mb-1">{label}</p>
      {payload.map((p: any, i: number) => (
        <p key={i} className="text-xs font-medium" style={{ color: p.color }}>
          {p.name}: {typeof p.value === 'number' ? p.value.toFixed(1) : p.value}
        </p>
      ))}
    </div>
  );
};

function formatValue(v: number): string {
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(0)}K`;
  return `$${v.toFixed(0)}`;
}

export default function ContractIQDashboard() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = getToken();
    if (!token) { router.replace('/'); return; }
    setUser(getUser());

    fetch(`${API_URL}/api/contractiq/analytics/portfolio`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.json())
      .then(body => { setAnalytics(body.data); setLoading(false); })
      .catch(() => setLoading(false));
  }, [router]);

  const logout = () => {
    localStorage.removeItem('contractiq_token');
    localStorage.removeItem('contractiq_refresh_token');
    localStorage.removeItem('contractiq_user');
    router.replace('/');
  };

  if (!user) return <div className="min-h-screen bg-[#0B0F19] flex items-center justify-center"><div className="w-8 h-8 border-2 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin" /></div>;

  const a = analytics;

  // Derived chart data
  const riskDistribution = a?.contracts
    ?.filter(c => c.risk_score != null)
    .map(c => ({ name: c.title.length > 20 ? c.title.slice(0, 20) + '…' : c.title, risk: c.risk_score!, type: c.type }))
    .sort((x, y) => (y.risk || 0) - (x.risk || 0)) || [];

  const typeData = a?.by_type?.map(t => ({
    name: t.type.toUpperCase(),
    value: t.count,
    capacity: t.capacity,
  })) || [];

  const radarData = a?.risk_by_category?.map(r => ({
    category: r.category.charAt(0).toUpperCase() + r.category.slice(1),
    score: r.avg_score,
    fullMark: 100,
  })) || [];

  // Clause risk aggregation
  const clauseByType: Record<string, number> = {};
  a?.clause_distribution?.forEach(c => {
    clauseByType[c.type] = (clauseByType[c.type] || 0) + c.count;
  });
  const clauseData = Object.entries(clauseByType)
    .map(([type, count]) => ({ type: type.replace(/_/g, ' '), count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 10);

  const kpis = a ? [
    { label: 'Total Contracts', value: a.total_contracts, icon: FileText, color: 'text-cyan-400', bg: 'bg-cyan-500/10' },
    { label: 'Total Capacity', value: `${a.total_capacity_mw.toFixed(0)} MW`, icon: Zap, color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
    { label: 'Portfolio Value', value: formatValue(a.total_contract_value), icon: DollarSign, color: 'text-purple-400', bg: 'bg-purple-500/10' },
    { label: 'Avg Risk Score', value: a.avg_risk_score > 0 ? a.avg_risk_score.toFixed(0) : '--', icon: Shield, color: a.avg_risk_score > 60 ? 'text-red-400' : a.avg_risk_score > 35 ? 'text-amber-400' : 'text-emerald-400', bg: a.avg_risk_score > 60 ? 'bg-red-500/10' : a.avg_risk_score > 35 ? 'bg-amber-500/10' : 'bg-emerald-500/10' },
    { label: 'Expiring <12mo', value: a.contracts_expiring_soon, icon: Clock, color: a.contracts_expiring_soon > 0 ? 'text-amber-400' : 'text-slate-400', bg: a.contracts_expiring_soon > 0 ? 'bg-amber-500/10' : 'bg-slate-500/10' },
  ] : [];

  return (
    <div className="min-h-screen bg-[#0B0F19]">
      <div className="p-6">
        <div className="max-w-7xl mx-auto space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-xl font-bold text-white">Portfolio Analytics</h1>
              <p className="text-sm text-slate-400 mt-1">Real-time intelligence across your contract portfolio</p>
            </div>
            <a href="/upload"
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-500 text-white text-sm font-medium hover:bg-emerald-400 transition-colors">
              <Plus className="w-4 h-4" /> Upload Contract
            </a>
          </div>

          {loading ? (
            <div className="flex justify-center py-20"><div className="w-8 h-8 border-2 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin" /></div>
          ) : !a || a.total_contracts === 0 ? (
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-16 text-center">
              <FileText className="w-10 h-10 text-slate-600 mx-auto mb-3" />
              <p className="text-sm text-slate-400">Upload contracts to see analytics</p>
              <a href="/upload" className="text-xs text-emerald-400 hover:underline mt-2 inline-block">Upload your first contract →</a>
            </div>
          ) : (
            <>
              {/* KPI Cards */}
              <div className="grid grid-cols-5 gap-4">
                {kpis.map((kpi, i) => (
                  <motion.div key={kpi.label} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
                    className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-[10px] text-slate-500 uppercase tracking-wider">{kpi.label}</span>
                      <div className={`w-8 h-8 rounded-lg ${kpi.bg} flex items-center justify-center`}>
                        <kpi.icon className={`w-4 h-4 ${kpi.color}`} />
                      </div>
                    </div>
                    <p className={`text-2xl font-bold ${kpi.color}`}>{kpi.value}</p>
                  </motion.div>
                ))}
              </div>

              {/* Charts Row 1 */}
              <div className="grid grid-cols-3 gap-4">
                {/* Risk by Contract */}
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.2 }}
                  className="col-span-2 bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                  <h2 className="text-sm font-semibold text-white mb-4">Risk Score by Contract</h2>
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={riskDistribution} layout="vertical" margin={{ left: 10, right: 20 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
                      <XAxis type="number" domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} />
                      <YAxis type="category" dataKey="name" width={120} tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} />
                      <Tooltip content={<CustomTooltip />} />
                      <Bar dataKey="risk" name="Risk Score" radius={[0, 4, 4, 0]}>
                        {riskDistribution.map((entry, i) => (
                          <Cell key={i} fill={entry.risk > 60 ? '#ef4444' : entry.risk > 35 ? '#f59e0b' : '#10b981'} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </motion.div>

                {/* Portfolio Composition Pie */}
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.3 }}
                  className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                  <h2 className="text-sm font-semibold text-white mb-4">Portfolio Composition</h2>
                  <ResponsiveContainer width="100%" height={220}>
                    <PieChart>
                      <Pie data={typeData} dataKey="value" nameKey="name" cx="50%" cy="50%"
                        innerRadius={50} outerRadius={75} paddingAngle={3} strokeWidth={0}>
                        {typeData.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                      </Pie>
                      <Tooltip content={<CustomTooltip />} />
                      <Legend
                        verticalAlign="bottom" height={36}
                        formatter={(value: string) => <span className="text-xs text-slate-400">{value}</span>}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </motion.div>
              </div>

              {/* Charts Row 2 */}
              <div className="grid grid-cols-2 gap-4">
                {/* Risk Radar */}
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.4 }}
                  className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                  <h2 className="text-sm font-semibold text-white mb-4">Risk Profile by Category</h2>
                  <ResponsiveContainer width="100%" height={280}>
                    <RadarChart data={radarData}>
                      <PolarGrid stroke="#1e293b" />
                      <PolarAngleAxis dataKey="category" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                      <PolarRadiusAxis angle={30} domain={[0, 100]} tick={{ fill: '#475569', fontSize: 9 }} />
                      <Radar name="Avg Risk" dataKey="score" stroke="#10b981" fill="#10b981" fillOpacity={0.2} strokeWidth={2} />
                      <Tooltip content={<CustomTooltip />} />
                    </RadarChart>
                  </ResponsiveContainer>
                </motion.div>

                {/* Clause Distribution */}
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.5 }}
                  className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                  <h2 className="text-sm font-semibold text-white mb-4">Clause Distribution</h2>
                  <ResponsiveContainer width="100%" height={280}>
                    <BarChart data={clauseData} margin={{ left: 0, right: 10 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                      <XAxis dataKey="type" tick={{ fill: '#64748b', fontSize: 9 }} angle={-30} textAnchor="end" height={60} axisLine={false} />
                      <YAxis tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} />
                      <Tooltip content={<CustomTooltip />} />
                      <Bar dataKey="count" name="Clauses" fill="#06b6d4" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </motion.div>
              </div>

              {/* Capacity by Type + Upcoming Events */}
              <div className="grid grid-cols-3 gap-4">
                {/* Capacity by Contract */}
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.6 }}
                  className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                  <h2 className="text-sm font-semibold text-white mb-4">Capacity by Contract</h2>
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={a.contracts.filter(c => c.capacity_mw).map(c => ({
                      name: c.title.length > 15 ? c.title.slice(0, 15) + '…' : c.title,
                      mw: c.capacity_mw,
                    }))}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                      <XAxis dataKey="name" tick={{ fill: '#64748b', fontSize: 9 }} axisLine={false} />
                      <YAxis tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} />
                      <Tooltip content={<CustomTooltip />} />
                      <Bar dataKey="mw" name="Capacity (MW)" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </motion.div>

                {/* Upcoming Events */}
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.7 }}
                  className="col-span-2 bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                  <div className="flex items-center justify-between mb-4">
                    <h2 className="text-sm font-semibold text-white">Key Events & Milestones</h2>
                    <Calendar className="w-4 h-4 text-slate-500" />
                  </div>
                  <div className="space-y-2 max-h-[200px] overflow-y-auto pr-2">
                    {(a.upcoming_events || []).slice(0, 8).map((ev, i) => {
                      const typeColors: Record<string, string> = {
                        milestone: 'border-emerald-500 bg-emerald-500/5',
                        deadline: 'border-red-500 bg-red-500/5',
                        review: 'border-cyan-500 bg-cyan-500/5',
                        renewal: 'border-purple-500 bg-purple-500/5',
                        termination_trigger: 'border-amber-500 bg-amber-500/5',
                      };
                      return (
                        <div key={i} className={`border-l-2 pl-3 py-1.5 rounded-r-lg ${typeColors[ev.type] || 'border-slate-600 bg-slate-800/20'}`}>
                          <div className="flex items-center justify-between">
                            <p className="text-xs text-white font-medium">{ev.description.length > 60 ? ev.description.slice(0, 60) + '…' : ev.description}</p>
                            <span className="text-[10px] text-slate-500 shrink-0 ml-2">{ev.date ? new Date(ev.date).toLocaleDateString() : ''}</span>
                          </div>
                          <p className="text-[10px] text-slate-500 mt-0.5">{ev.contract} · {ev.type.replace(/_/g, ' ')}</p>
                        </div>
                      );
                    })}
                    {(!a.upcoming_events || a.upcoming_events.length === 0) && (
                      <p className="text-xs text-slate-500 text-center py-6">No events extracted yet</p>
                    )}
                  </div>
                </motion.div>
              </div>

              {/* Recent Contracts Table */}
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.8 }}
                className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
                <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700/50">
                  <h2 className="text-sm font-semibold text-white">All Contracts</h2>
                  <a href="/contracts" className="text-xs text-emerald-400 hover:text-emerald-300 flex items-center gap-1">
                    View all <ChevronRight className="w-3 h-3" />
                  </a>
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-700/30">
                      <th className="text-left py-3 px-5 text-slate-400 font-medium text-xs">Contract</th>
                      <th className="text-left py-3 px-5 text-slate-400 font-medium text-xs">Type</th>
                      <th className="text-left py-3 px-5 text-slate-400 font-medium text-xs">Counterparty</th>
                      <th className="text-left py-3 px-5 text-slate-400 font-medium text-xs">Capacity</th>
                      <th className="text-left py-3 px-5 text-slate-400 font-medium text-xs">Status</th>
                      <th className="text-right py-3 px-5 text-slate-400 font-medium text-xs">Risk</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(a.contracts || []).map(c => (
                      <tr key={c.id} className="border-b border-slate-700/20 hover:bg-slate-700/20 cursor-pointer transition-colors"
                        onClick={() => router.push(`/contracts/${c.id}`)}>
                        <td className="py-3 px-5 text-white text-xs">{c.title}</td>
                        <td className="py-3 px-5">
                          <span className={`text-[10px] px-2 py-0.5 rounded-full ${
                            c.type === 'ppa' ? 'bg-emerald-500/10 text-emerald-400' :
                            c.type === 'gas' ? 'bg-amber-500/10 text-amber-400' : 'bg-slate-500/10 text-slate-400'
                          }`}>{c.type?.toUpperCase()}</span>
                        </td>
                        <td className="py-3 px-5 text-slate-400 text-xs">{c.counterparty || '—'}</td>
                        <td className="py-3 px-5 text-slate-400 text-xs">{c.capacity_mw ? `${c.capacity_mw} MW` : '—'}</td>
                        <td className="py-3 px-5">
                          <span className={`text-[10px] px-2 py-0.5 rounded-full ${
                            c.status === 'analyzed' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-slate-500/10 text-slate-400'
                          }`}>{c.status}</span>
                        </td>
                        <td className="py-3 px-5 text-right">
                          {c.risk_score != null ? (
                            <div className="flex items-center justify-end gap-2">
                              <div className="w-12 h-1.5 bg-slate-700/50 rounded-full overflow-hidden">
                                <div className={`h-full rounded-full ${
                                  c.risk_score > 60 ? 'bg-red-500' : c.risk_score > 35 ? 'bg-amber-500' : 'bg-emerald-500'
                                }`} style={{ width: `${c.risk_score}%` }} />
                              </div>
                              <span className={`text-xs font-mono ${
                                c.risk_score > 60 ? 'text-red-400' : c.risk_score > 35 ? 'text-amber-400' : 'text-emerald-400'
                              }`}>{c.risk_score.toFixed(0)}</span>
                            </div>
                          ) : <span className="text-xs text-slate-600">—</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </motion.div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
