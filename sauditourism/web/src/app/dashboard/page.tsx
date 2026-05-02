'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { BarChart3, Users, DollarSign, Hotel, Star, Loader2, AlertCircle, Database, RefreshCw } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, LineChart, Line, CartesianGrid } from 'recharts';
import { fetchWithToast, toastError, toastSuccess } from '@/stores/toastStore';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return localStorage.getItem('st_token') || ''; }

const GREENS = ['#00A651', '#16A34A', '#22C55E', '#4ADE80', '#86EFAC', '#059669', '#10B981', '#34D399'];

const ANALYTICS_CACHE_KEY = 'st_dashboard_cache_v1';
const ANALYTICS_TTL_MS = 60 * 60 * 1000; // 1 hour

export default function DashboardPage() {
  const [data, setData] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);
  const [datasets, setDatasets] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [error, setError] = useState('');

  const headers = { Authorization: `Bearer ${getToken()}` };

  // Load instant data (no agent needed)
  async function loadBasicData() {
    const [statsRes, dsRes] = await Promise.all([
      fetchWithToast(`${API_URL}/api/st/datasets/stats`, { headers }, 'Failed to load dataset stats'),
      fetchWithToast(`${API_URL}/api/st/datasets`, { headers }, 'Failed to load datasets'),
    ]);
    if (statsRes.data) setStats(statsRes.data);
    if (dsRes.data) setDatasets(dsRes.data);
  }

  // Load full analytics via Abenix (takes 30-90s)
  async function loadAnalytics(opts: { background?: boolean } = {}) {
    if (!opts.background) setLoading(true);
    setError('');
    const json = await fetchWithToast(
      `${API_URL}/api/st/analytics/dashboard`,
      { headers },
      'AI Analytics failed',
    );
    if (json.data) {
      setData(json.data);
      try {
        localStorage.setItem(ANALYTICS_CACHE_KEY, JSON.stringify({ at: Date.now(), data: json.data }));
      } catch { }
    } else if (json.error?.message) {
      setError(json.error.message);
    }
    if (!opts.background) setLoading(false);
  }

  async function seedData() {
    setSeeding(true);
    const json = await fetchWithToast(
      `${API_URL}/api/st/datasets/seed`,
      { method: 'POST', headers },
      'Seed test data failed',
    );
    if (json.data) {
      const seeded = (json.data.seeded || []).filter((s: any) => s.status === 'seeded').length;
      toastSuccess(`Seeded ${seeded} dataset(s)`, seeded === 0 ? 'All test datasets already loaded' : undefined);
    }
    await loadBasicData();
    setSeeding(false);
  }

  // Auto-load: instant data first, then hydrate from cache, then refresh stale.
  useEffect(() => {
    loadBasicData();
    try {
      const raw = localStorage.getItem(ANALYTICS_CACHE_KEY);
      if (raw) {
        const { at, data: cached } = JSON.parse(raw);
        if (cached) setData(cached);
        if (Date.now() - (at || 0) > ANALYTICS_TTL_MS) {
          // Stale — kick off a background refresh (no spinner over the cards)
          loadAnalytics({ background: true });
        }
      } else {
        // No cache yet — trigger a one-shot background fetch so KPIs appear without a click
        loadAnalytics({ background: true });
      }
    } catch { }
  }, []);

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold">Tourism Dashboard</h1>
          <p className="text-sm text-green-300/40 mt-1">Kingdom of Saudi Arabia &middot; Real-time analytics</p>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={seedData} disabled={seeding}
            className="px-4 py-2 rounded-lg bg-green-700/30 border border-green-600/30 text-green-300 text-xs hover:bg-green-700/50 transition-all flex items-center gap-2 disabled:opacity-50">
            {seeding ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Database className="w-3.5 h-3.5" />}
            {seeding ? 'Seeding...' : 'Seed Test Data'}
          </button>
          <button onClick={() => loadAnalytics()} disabled={loading}
            className="px-4 py-2 rounded-lg bg-gradient-to-r from-green-600 to-green-700 text-white text-xs font-semibold hover:shadow-lg hover:shadow-green-600/25 transition-all flex items-center gap-2 disabled:opacity-50">
            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            {loading ? 'Analyzing via Abenix...' : 'Run AI Analytics'}
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-6 p-4 rounded-xl border border-red-800/50 bg-red-900/20 flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-red-400 shrink-0" />
          <p className="text-sm text-red-300 flex-1">{error}</p>
        </div>
      )}

      {/* Dataset Overview (instant, no agent) */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {[
          { label: 'Datasets Uploaded', value: stats?.total_datasets ?? '--', icon: Database, color: 'text-green-400' },
          { label: 'Total Data Rows', value: stats?.total_rows ? stats.total_rows.toLocaleString() : '--', icon: BarChart3, color: 'text-emerald-400' },
          { label: 'Analyzed', value: stats?.by_status?.analyzed ?? '--', icon: Star, color: 'text-green-300' },
          { label: 'Dataset Types', value: stats?.by_type ? Object.keys(stats.by_type).length : '--', icon: Users, color: 'text-green-400' },
        ].map((kpi, i) => (
          <motion.div key={kpi.label} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
            className="rounded-2xl border border-green-800/40 bg-[#0A2818]/50 p-5">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs text-green-300/40">{kpi.label}</span>
              <kpi.icon className={`w-4 h-4 ${kpi.color}`} />
            </div>
            <div className={`text-3xl font-bold ${kpi.color}`}>{kpi.value}</div>
          </motion.div>
        ))}
      </div>

      {/* Datasets list (instant) */}
      {datasets.length > 0 && !data && (
        <div className="mb-6 rounded-2xl border border-green-800/40 bg-[#0A2818]/50 p-5">
          <h3 className="text-sm font-semibold mb-3 text-green-200">Your Datasets</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {datasets.map((d: any) => (
              <div key={d.id} className="rounded-xl bg-green-900/20 border border-green-800/30 p-3">
                <p className="text-sm text-white font-medium">{d.title}</p>
                <div className="flex items-center gap-2 text-[10px] text-green-400/30 mt-1">
                  <span className="px-1.5 py-0.5 rounded bg-green-500/20 text-green-300 border border-green-500/30">{d.dataset_type}</span>
                  <span>{d.status}</span>
                  {d.row_count && <span>{d.row_count} rows</span>}
                </div>
              </div>
            ))}
          </div>
          {!loading && !data && (
            <div className="mt-4 p-4 rounded-xl border border-green-600/20 bg-green-900/10 text-center">
              <p className="text-sm text-green-300/50 mb-2">Click "Run AI Analytics" to analyze your datasets with the Abenix analytics agent</p>
              <p className="text-[10px] text-green-400/20">Uses: saudi-tourism-analytics agent with financial_calculator, csv_analyzer, scenario_planner tools</p>
            </div>
          )}
        </div>
      )}

      {/* No data prompt */}
      {(!stats || stats.total_datasets === 0) && (
        <div className="rounded-2xl border border-green-800/40 bg-[#0A2818]/30 p-12 text-center">
          <Database className="w-10 h-10 text-green-600/20 mx-auto mb-4" />
          <p className="text-green-300/30 mb-2">No datasets uploaded yet</p>
          <p className="text-xs text-green-400/20 mb-4">Click "Seed Test Data" to load sample KSA tourism datasets</p>
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="flex items-center justify-center py-12">
          <div className="text-center">
            <Loader2 className="w-8 h-8 animate-spin text-green-500 mx-auto mb-3" />
            <p className="text-green-300/50 text-sm">saudi-tourism-analytics agent is analyzing your data...</p>
            <p className="text-[10px] text-green-400/20 mt-1">This uses financial_calculator and csv_analyzer tools (30-90 seconds)</p>
          </div>
        </div>
      )}

      {/* Agent analytics results */}
      {data && (
        <>
          {/* AI KPI Cards */}
          {data.kpis && (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
              {[
                { label: 'Total Visitors', value: data.kpis.total_visitors ? `${(data.kpis.total_visitors / 1000000).toFixed(1)}M` : '--', icon: Users, color: 'text-green-400' },
                { label: 'Revenue (SAR)', value: data.kpis.total_revenue_sar ? `${(data.kpis.total_revenue_sar / 1000000000).toFixed(1)}B` : '--', icon: DollarSign, color: 'text-emerald-400' },
                { label: 'Hotel Occupancy', value: data.kpis.avg_hotel_occupancy ? `${data.kpis.avg_hotel_occupancy}%` : '--', icon: Hotel, color: 'text-green-300' },
                { label: 'Satisfaction', value: data.kpis.avg_satisfaction ? `${data.kpis.avg_satisfaction}/5` : '--', icon: Star, color: 'text-green-400' },
              ].map((kpi, i) => (
                <motion.div key={kpi.label} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
                  className="rounded-2xl border border-green-600/40 bg-green-900/30 p-5">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs text-green-300/50">{kpi.label}</span>
                    <kpi.icon className={`w-4 h-4 ${kpi.color}`} />
                  </div>
                  <div className={`text-3xl font-bold ${kpi.color}`}>{kpi.value}</div>
                </motion.div>
              ))}
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {data.monthly_arrivals?.length > 0 && (
              <div className="rounded-2xl border border-green-800/40 bg-[#0A2818]/50 p-5">
                <h3 className="text-sm font-semibold mb-4 text-green-200">Monthly Visitor Arrivals</h3>
                <ResponsiveContainer width="100%" height={250}>
                  <BarChart data={data.monthly_arrivals}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#0D3320" />
                    <XAxis dataKey="month" tick={{ fill: '#4ADE80', fontSize: 10 }} />
                    <YAxis tick={{ fill: '#4ADE80', fontSize: 10 }} />
                    <Tooltip contentStyle={{ background: '#0A2818', border: '1px solid #166534', borderRadius: '8px', color: 'white' }} />
                    <Bar dataKey="visitors" fill="#00A651" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {data.revenue_by_sector?.length > 0 && (
              <div className="rounded-2xl border border-green-800/40 bg-[#0A2818]/50 p-5">
                <h3 className="text-sm font-semibold mb-4 text-green-200">Revenue by Sector</h3>
                <ResponsiveContainer width="100%" height={250}>
                  <PieChart>
                    <Pie data={data.revenue_by_sector} dataKey="revenue" nameKey="sector" cx="50%" cy="50%" outerRadius={90} label={({ sector }: any) => sector}>
                      {data.revenue_by_sector.map((_: any, i: number) => <Cell key={i} fill={GREENS[i % GREENS.length]} />)}
                    </Pie>
                    <Tooltip contentStyle={{ background: '#0A2818', border: '1px solid #166534', borderRadius: '8px', color: 'white' }} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            )}

            {data.region_visitors?.length > 0 && (
              <div className="rounded-2xl border border-green-800/40 bg-[#0A2818]/50 p-5">
                <h3 className="text-sm font-semibold mb-4 text-green-200">Visitors by Region</h3>
                <ResponsiveContainer width="100%" height={250}>
                  <BarChart data={data.region_visitors} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" stroke="#0D3320" />
                    <XAxis type="number" tick={{ fill: '#4ADE80', fontSize: 10 }} />
                    <YAxis dataKey="region" type="category" tick={{ fill: '#4ADE80', fontSize: 10 }} width={80} />
                    <Tooltip contentStyle={{ background: '#0A2818', border: '1px solid #166534', borderRadius: '8px', color: 'white' }} />
                    <Bar dataKey="visitors" fill="#16A34A" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {data.purpose_breakdown?.length > 0 && (
              <div className="rounded-2xl border border-green-800/40 bg-[#0A2818]/50 p-5">
                <h3 className="text-sm font-semibold mb-4 text-green-200">Visitor Purpose</h3>
                <ResponsiveContainer width="100%" height={250}>
                  <PieChart>
                    <Pie data={data.purpose_breakdown} dataKey="visitors" nameKey="purpose" cx="50%" cy="50%" outerRadius={90} label={({ purpose }: any) => purpose}>
                      {data.purpose_breakdown.map((_: any, i: number) => <Cell key={i} fill={GREENS[i % GREENS.length]} />)}
                    </Pie>
                    <Tooltip contentStyle={{ background: '#0A2818', border: '1px solid #166534', borderRadius: '8px', color: 'white' }} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          {/* If agent returned text instead of JSON */}
          {data.text && (
            <div className="mt-6 rounded-2xl border border-green-800/40 bg-[#0A2818]/50 p-6">
              <h3 className="text-sm font-semibold mb-3 text-green-200">AI Analytics Summary</h3>
              <div className="text-sm text-green-200/60 whitespace-pre-wrap leading-relaxed"
                dangerouslySetInnerHTML={{ __html: data.text.replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>').replace(/\n/g, '<br/>') }} />
            </div>
          )}
        </>
      )}
    </div>
  );
}
