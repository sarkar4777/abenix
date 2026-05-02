'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { TrendingUp, Users, DollarSign, Star, Loader2, RefreshCw } from 'lucide-react';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, LineChart, Line } from 'recharts';
import { fetchWithToast } from '@/stores/toastStore';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return localStorage.getItem('st_token') || ''; }

type AnalyticsTab = 'time_series' | 'segmentation' | 'revenue';

const GREENS = ['#00A651', '#16A34A', '#22C55E', '#4ADE80', '#86EFAC', '#059669', '#10B981'];

export default function DeepAnalyticsPage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [cached, setCached] = useState(false);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<AnalyticsTab>('time_series');

  async function loadDeep(refresh = false) {
    setLoading(true);
    setError('');
    const url = `${API_URL}/api/st/analytics/deep${refresh ? '?refresh=true' : ''}`;
    const json = await fetchWithToast(
      url,
      { headers: { Authorization: `Bearer ${getToken()}` } },
      'Deep Analytics failed',
    );
    if (json.data) { setCached(!!json.data._cached); setData(json.data); setError(''); }
    else if (json.error?.message) setError(json.error.message);
    setLoading(false);
  }

  // Only try loading cached result on mount (10s timeout — cache is instant, agent is slow).
  // If no cache, show empty state. User clicks "Refresh Analysis" to trigger agent.
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    (async () => {
      try {
        const res = await fetch(`${API_URL}/api/st/analytics/deep`, {
          headers: { Authorization: `Bearer ${getToken()}` },
          signal: controller.signal,
        });
        const text = await res.text();
        clearTimeout(timer);
        try {
          const json = JSON.parse(text);
          if (json.data && json.data._cached) { setCached(true); setData(json.data); setError(''); }
        } catch { /* not JSON — ignore */ }
      } catch { /* timeout or network error — show empty state */ }
    })();
    return () => { clearTimeout(timer); controller.abort(); };
  }, []);

  const seg = data?.segmentation || {};
  const originData = seg.by_origin ? Object.entries(seg.by_origin).map(([k, v]) => ({ name: k, value: v })) : [];
  const purposeData = seg.by_purpose ? Object.entries(seg.by_purpose).map(([k, v]) => ({ name: k, value: v })) : [];
  const revAttr = data?.revenue_attribution || [];
  const monthly = data?.time_series?.monthly || [];
  const satisfaction = data?.satisfaction || {};
  const ratingDist = satisfaction.rating_distribution
    ? Object.entries(satisfaction.rating_distribution).map(([k, v]) => ({ rating: `${k} star`, count: v }))
    : [];

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold">Deep Analytics</h1>
          <p className="text-sm text-green-300/40 mt-1">Time series, segmentation, revenue attribution, sentiment — via Abenix
            {cached && <span className="ml-2 text-green-500/40">(cached)</span>}
          </p>
        </div>
        <button onClick={() => loadDeep(true)} disabled={loading}
          className="px-4 py-2 rounded-lg bg-gradient-to-r from-green-600 to-green-700 text-white text-xs font-semibold hover:shadow-lg hover:shadow-green-600/25 transition-all flex items-center gap-2 disabled:opacity-50">
          {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          {loading ? 'Analyzing...' : 'Refresh Analysis'}
        </button>
      </div>
      {error && <div className="mb-6 p-4 rounded-xl border border-red-800/50 bg-red-900/20 text-sm text-red-300">{error}</div>}
      {loading && !data && (
        <div className="flex items-center justify-center py-20">
          <div className="text-center">
            <Loader2 className="w-8 h-8 animate-spin text-green-500 mx-auto mb-3" />
            <p className="text-green-300/50 text-sm">saudi-tourism-analytics agent running deep analysis...</p>
            <p className="text-[10px] text-green-400/20 mt-1">This may take 30-90 seconds on first run</p>
          </div>
        </div>
      )}

      {!loading && !data && !error && (
        <div className="rounded-2xl border border-green-800/40 bg-[#0A2818]/30 p-12 text-center">
          <TrendingUp className="w-10 h-10 text-green-600/20 mx-auto mb-4" />
          <p className="text-green-300/30 mb-2">Click "Refresh Analysis" to run deep analytics via Abenix</p>
          <p className="text-xs text-green-400/20">Uses financial_calculator and csv_analyzer to compute trends, segmentation, revenue attribution</p>
        </div>
      )}

      {/* Agent returned text instead of structured JSON */}
      {data?.text && (
        <div className="rounded-2xl border border-green-800/40 bg-[#0A2818]/50 p-6 mb-6">
          <div className="prose prose-invert prose-green max-w-none text-sm whitespace-pre-wrap" dangerouslySetInnerHTML={{ __html: data.text.replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>').replace(/\n/g, '<br/>') }} />
        </div>
      )}

      {/* Tabs — split sections so users don't see one giant scroll */}
      {data && (
        <div className="mb-5 flex items-center gap-1 border border-green-800/40 rounded-xl p-1 bg-[#0A2818]/40 w-fit">
          {[
            { key: 'time_series' as AnalyticsTab, label: 'Time Series', icon: TrendingUp },
            { key: 'segmentation' as AnalyticsTab, label: 'Segmentation', icon: Users },
            { key: 'revenue' as AnalyticsTab, label: 'Revenue Attribution', icon: DollarSign },
          ].map(t => {
            const active = tab === t.key;
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all flex items-center gap-1.5 ${
                  active ? 'bg-green-700/40 text-white border border-green-500/40' : 'text-green-300/60 hover:text-white'
                }`}
              >
                <t.icon className="w-3.5 h-3.5" /> {t.label}
              </button>
            );
          })}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* TIME SERIES tab */}
        {tab === 'time_series' && monthly.length > 0 && (
          <div className="rounded-2xl border border-green-800/40 bg-[#0A2818]/50 p-5 lg:col-span-2">
            <h3 className="text-sm font-semibold mb-4 text-green-200 flex items-center gap-2"><TrendingUp className="w-4 h-4" /> Monthly Visitor Trend</h3>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={monthly}>
                <CartesianGrid strokeDasharray="3 3" stroke="#0D3320" />
                <XAxis dataKey="month" tick={{ fill: '#4ADE80', fontSize: 10 }} />
                <YAxis tick={{ fill: '#4ADE80', fontSize: 10 }} />
                <Tooltip contentStyle={{ background: '#0A2818', border: '1px solid #166534', borderRadius: '8px', color: 'white' }} />
                <Line type="monotone" dataKey="visitors" stroke="#00A651" strokeWidth={2} dot={{ fill: '#00A651' }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* SEGMENTATION tab */}
        {tab === 'segmentation' && originData.length > 0 && (
          <div className="rounded-2xl border border-green-800/40 bg-[#0A2818]/50 p-5">
            <h3 className="text-sm font-semibold mb-4 text-green-200 flex items-center gap-2"><Users className="w-4 h-4" /> Visitor Origin</h3>
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie data={originData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={90} label={({ name, percent }: any) => `${name} ${((percent || 0) * 100).toFixed(0)}%`}>
                  {originData.map((_: any, i: number) => <Cell key={i} fill={GREENS[i % GREENS.length]} />)}
                </Pie>
                <Tooltip contentStyle={{ background: '#0A2818', border: '1px solid #166534', borderRadius: '8px', color: 'white' }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        )}

        {tab === 'segmentation' && purposeData.length > 0 && (
          <div className="rounded-2xl border border-green-800/40 bg-[#0A2818]/50 p-5">
            <h3 className="text-sm font-semibold mb-4 text-green-200 flex items-center gap-2"><Users className="w-4 h-4" /> Visitor Purpose</h3>
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie data={purposeData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={90} label={({ name, percent }: any) => `${name} ${((percent || 0) * 100).toFixed(0)}%`}>
                  {purposeData.map((_: any, i: number) => <Cell key={i} fill={GREENS[i % GREENS.length]} />)}
                </Pie>
                <Tooltip contentStyle={{ background: '#0A2818', border: '1px solid #166534', borderRadius: '8px', color: 'white' }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        )}

        {tab === 'segmentation' && ratingDist.length > 0 && (
          <div className="rounded-2xl border border-green-800/40 bg-[#0A2818]/50 p-5 lg:col-span-2">
            <h3 className="text-sm font-semibold mb-4 text-green-200 flex items-center gap-2"><Star className="w-4 h-4" /> Satisfaction Ratings</h3>
            <div className="flex items-center gap-4 mb-4">
              {satisfaction.avg_rating && <div className="text-3xl font-bold text-green-400">{satisfaction.avg_rating}/5</div>}
            </div>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={ratingDist}>
                <CartesianGrid strokeDasharray="3 3" stroke="#0D3320" />
                <XAxis dataKey="rating" tick={{ fill: '#4ADE80', fontSize: 10 }} />
                <YAxis tick={{ fill: '#4ADE80', fontSize: 10 }} />
                <Tooltip contentStyle={{ background: '#0A2818', border: '1px solid #166534', borderRadius: '8px', color: 'white' }} />
                <Bar dataKey="count" fill="#00A651" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
            {satisfaction.top_praise?.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-2">
                {satisfaction.top_praise.map((p: string) => (
                  <span key={p} className="px-2 py-1 rounded-lg bg-green-900/30 border border-green-800/30 text-xs text-green-300">{p}</span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* REVENUE tab */}
        {tab === 'revenue' && revAttr.length > 0 && (
          <div className="rounded-2xl border border-green-800/40 bg-[#0A2818]/50 p-5 lg:col-span-2">
            <h3 className="text-sm font-semibold mb-4 text-green-200 flex items-center gap-2"><DollarSign className="w-4 h-4" /> Revenue by Sector</h3>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={revAttr}>
                <CartesianGrid strokeDasharray="3 3" stroke="#0D3320" />
                <XAxis dataKey="sector" tick={{ fill: '#4ADE80', fontSize: 10 }} />
                <YAxis tick={{ fill: '#4ADE80', fontSize: 10 }} />
                <Tooltip contentStyle={{ background: '#0A2818', border: '1px solid #166534', borderRadius: '8px', color: 'white' }} />
                <Bar dataKey="revenue" fill="#16A34A" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Empty state per tab when data exists but section is empty */}
        {data && (
          (tab === 'time_series' && monthly.length === 0) ||
          (tab === 'segmentation' && originData.length === 0 && purposeData.length === 0 && ratingDist.length === 0) ||
          (tab === 'revenue' && revAttr.length === 0)
        ) && (
          <div className="rounded-2xl border border-green-800/40 bg-[#0A2818]/30 p-10 text-center lg:col-span-2">
            <p className="text-green-300/40 text-sm">No data for this view yet — re-run the agent or upload more datasets.</p>
          </div>
        )}
      </div>
    </div>
  );
}
