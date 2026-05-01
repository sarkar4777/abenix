'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { MapPin, Users, DollarSign, Hotel, Loader2, TrendingUp } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, LineChart, Line } from 'recharts';

import { RefreshCw } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return localStorage.getItem('st_token') || ''; }

async function safeFetch(url: string, opts?: any) {
  const res = await fetch(url, { ...opts, signal: AbortSignal.timeout(600000) });
  const text = await res.text();
  try { return JSON.parse(text); } catch { return { data: null, error: { message: text.slice(0, 200) } }; }
}

export default function RegionalPage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<any>(null);

  async function loadRegional() {
    setLoading(true);
    setError('');
    try {
      const json = await safeFetch(`${API_URL}/api/st/analytics/regional`, { headers: { Authorization: `Bearer ${getToken()}` } });
      if (json.data) setData(json.data);
      else if (json.error) setError(json.error.message);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  }

  const regions = data?.regions || [];

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold">Regional Analytics</h1>
          <p className="text-sm text-green-300/40 mt-1">Performance by KSA region — via Abenix saudi-tourism-analytics agent</p>
        </div>
        <button onClick={loadRegional} disabled={loading}
          className="px-4 py-2 rounded-lg bg-gradient-to-r from-green-600 to-green-700 text-white text-xs font-semibold hover:shadow-lg hover:shadow-green-600/25 transition-all flex items-center gap-2 disabled:opacity-50">
          {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          {loading ? 'Analyzing regions...' : 'Run Regional Analysis'}
        </button>
      </div>

      {error && <div className="mb-6 p-4 rounded-xl border border-red-800/50 bg-red-900/20 text-sm text-red-300">{error}</div>}

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="text-center">
            <Loader2 className="w-8 h-8 animate-spin text-green-500 mx-auto mb-3" />
            <p className="text-green-300/50 text-sm">saudi-tourism-analytics agent computing regional data...</p>
            <p className="text-[10px] text-green-400/20 mt-1">Processing visitor, revenue, and occupancy data by region (30-90s)</p>
          </div>
        </div>
      ) : !data ? (
        <div className="rounded-2xl border border-green-800/40 bg-[#0A2818]/30 p-12 text-center">
          <MapPin className="w-10 h-10 text-green-600/20 mx-auto mb-4" />
          <p className="text-green-300/30 mb-2">Click "Run Regional Analysis" to analyze data by KSA region</p>
          <p className="text-xs text-green-400/20">Uses financial_calculator and csv_analyzer tools to compute per-region metrics</p>
        </div>
      ) : typeof data === 'object' && data?.text ? (
        <div className="rounded-2xl border border-green-800/40 bg-[#0A2818]/50 p-6">
          <p className="text-sm text-green-200 whitespace-pre-wrap">{data.text}</p>
        </div>
      ) : (
        <>
          {/* Region Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
            {regions.map((r: any, i: number) => (
              <motion.div key={r.id || r.name} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.03 }}
                onClick={() => setSelected(selected?.id === r.id ? null : r)}
                className={`rounded-2xl border p-5 cursor-pointer transition-all ${selected?.id === r.id ? 'border-green-500 bg-green-900/30' : 'border-green-800/40 bg-[#0A2818]/50 hover:border-green-600/50'}`}>
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <MapPin className="w-4 h-4 text-green-400" />
                    <h3 className="font-semibold text-white">{r.name}</h3>
                  </div>
                  {r.yoy_growth !== undefined && (
                    <span className={`text-xs font-mono ${r.yoy_growth >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {r.yoy_growth >= 0 ? '+' : ''}{r.yoy_growth}%
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-3 gap-3 text-center">
                  <div>
                    <Users className="w-3.5 h-3.5 text-green-400/50 mx-auto mb-1" />
                    <div className="text-sm font-bold text-green-300">{typeof r.visitors === 'number' ? (r.visitors > 1000000 ? `${(r.visitors / 1000000).toFixed(1)}M` : `${(r.visitors / 1000).toFixed(0)}K`) : r.visitors || '--'}</div>
                    <div className="text-[9px] text-green-400/30">Visitors</div>
                  </div>
                  <div>
                    <DollarSign className="w-3.5 h-3.5 text-green-400/50 mx-auto mb-1" />
                    <div className="text-sm font-bold text-green-300">{typeof r.revenue === 'number' ? `${(r.revenue / 1000000000).toFixed(1)}B` : r.revenue || '--'}</div>
                    <div className="text-[9px] text-green-400/30">Revenue SAR</div>
                  </div>
                  <div>
                    <Hotel className="w-3.5 h-3.5 text-green-400/50 mx-auto mb-1" />
                    <div className="text-sm font-bold text-green-300">{r.avg_occupancy ? `${r.avg_occupancy}%` : '--'}</div>
                    <div className="text-[9px] text-green-400/30">Occupancy</div>
                  </div>
                </div>
              </motion.div>
            ))}
          </div>

          {/* Selected Region Detail */}
          {selected && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
              className="rounded-2xl border border-green-600/40 bg-[#0A2818]/70 p-6">
              <div className="flex items-center gap-2 mb-4">
                <MapPin className="w-5 h-5 text-green-400" />
                <h2 className="text-lg font-bold">{selected.name} — Detailed View</h2>
              </div>

              {selected.monthly_trend?.length > 0 && (
                <div className="mb-6">
                  <h3 className="text-sm text-green-300/50 mb-3">Monthly Visitor Trend</h3>
                  <ResponsiveContainer width="100%" height={200}>
                    <LineChart data={selected.monthly_trend}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#0D3320" />
                      <XAxis dataKey="month" tick={{ fill: '#4ADE80', fontSize: 10 }} />
                      <YAxis tick={{ fill: '#4ADE80', fontSize: 10 }} />
                      <Tooltip contentStyle={{ background: '#0A2818', border: '1px solid #166534', borderRadius: '8px', color: 'white' }} />
                      <Line type="monotone" dataKey="visitors" stroke="#00A651" strokeWidth={2} dot={{ fill: '#00A651' }} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}

              {selected.top_attractions?.length > 0 && (
                <div>
                  <h3 className="text-sm text-green-300/50 mb-2">Top Attractions</h3>
                  <div className="flex flex-wrap gap-2">
                    {selected.top_attractions.map((a: string) => (
                      <span key={a} className="px-2 py-1 rounded-lg bg-green-900/30 border border-green-800/30 text-xs text-green-300">{a}</span>
                    ))}
                  </div>
                </div>
              )}
            </motion.div>
          )}

          {/* Comparison Chart */}
          {regions.length > 0 && (
            <div className="mt-8 rounded-2xl border border-green-800/40 bg-[#0A2818]/50 p-5">
              <h3 className="text-sm font-semibold mb-4 text-green-200">Regional Comparison — Visitors</h3>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={regions}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#0D3320" />
                  <XAxis dataKey="name" tick={{ fill: '#4ADE80', fontSize: 10 }} />
                  <YAxis tick={{ fill: '#4ADE80', fontSize: 10 }} />
                  <Tooltip contentStyle={{ background: '#0A2818', border: '1px solid #166534', borderRadius: '8px', color: 'white' }} />
                  <Bar dataKey="visitors" fill="#00A651" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}
    </div>
  );
}
