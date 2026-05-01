'use client';

import { useState } from 'react';
import { motion } from 'framer-motion';
import {
  LazyAreaChart as AreaChart,
  LazyArea as Area,
  LazyXAxis as XAxis,
  LazyYAxis as YAxis,
  LazyTooltip as Tooltip,
  LazyResponsiveContainer as ResponsiveContainer,
} from '@/components/ui/LazyCharts';
import {
  DollarSign,
  Users,
  Bot,
  Clock,
  ExternalLink,
  Loader2,
  Zap,
} from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { apiFetch, API_URL } from '@/lib/api-client';
import { usePageTitle } from '@/hooks/usePageTitle';
import { SkeletonStatCard, SkeletonChartCard } from '@/components/ui/Skeleton';

interface CreatorStatus {
  is_onboarded: boolean;
  stripe_connect_id: string | null;
  charges_enabled: boolean;
  payouts_enabled: boolean;
  details_submitted: boolean;
}

interface DashboardData {
  total_revenue: number;
  total_platform_fees: number;
  creator_earnings: number;
  total_subscribers: number;
  total_agents_published: number;
  balance: {
    available: { amount: number; currency: string }[];
    pending: { amount: number; currency: string }[];
  };
  revenue_by_day: { date: string; revenue: number; count: number }[];
  top_agents: { agent_id: string; name: string; revenue: number; subscribers: number }[];
  recent_payouts: { id: string; amount_total: number; creator_amount: number; platform_fee: number; status: string; created_at: string; agent_name: string }[];
}

const PERIODS = ['7d', '30d', '90d'] as const;

export default function CreatorDashboard() {
  usePageTitle('Creator Hub');
  const [period, setPeriod] = useState<string>('30d');
  const [onboarding, setOnboarding] = useState(false);

  const { data: status, isLoading: loadingStatus, mutate: mutateStatus } =
    useApi<CreatorStatus>('/api/creator/status');
  const { data: dashboard, isLoading: loadingDash, mutate: mutateDash } =
    useApi<DashboardData>(`/api/creator/dashboard?period=${period}`);

  const loading = loadingStatus || loadingDash;

  const handleOnboard = async () => {
    setOnboarding(true);
    try {
      const res = await apiFetch<{
        onboarding_url: string;
        mode: string;
      }>('/api/creator/onboard', {
        method: 'POST',
        body: JSON.stringify({
          refresh_url: `${window.location.origin}/creator?refresh=true`,
          return_url: `${window.location.origin}/creator?onboarded=true`,
        }),
      });
      if (res.data?.onboarding_url) {
        if (res.data.mode === 'mock') {
          mutateStatus();
          mutateDash();
        } else {
          window.location.href = res.data.onboarding_url;
        }
      }
    } catch {
    } finally {
      setOnboarding(false);
    }
  };

  const handleStripeDashboard = async () => {
    try {
      const res = await apiFetch<{ url: string }>('/api/creator/login-link');
      if (res.data?.url) {
        window.open(res.data.url, '_blank');
      }
    } catch {
    }
  };

  const fmt = (n: number) => `$${n.toFixed(2)}`;
  const fmtCents = (n: number) => `$${(n / 100).toFixed(2)}`;

  if (loading) {
    return (
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        <div>
          <div className="h-7 w-32 bg-slate-800 animate-pulse rounded" />
          <div className="h-3 w-56 bg-slate-700/50 animate-pulse rounded mt-2" />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <SkeletonStatCard key={i} />
          ))}
        </div>
        <SkeletonChartCard />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <SkeletonChartCard />
          <SkeletonChartCard />
        </div>
      </div>
    );
  }

  const pendingBalance = dashboard?.balance?.pending?.[0]?.amount || 0;
  const availableBalance = dashboard?.balance?.available?.[0]?.amount || 0;

  const kpis = [
    { label: 'Total Earnings', value: fmt(dashboard?.creator_earnings || 0), icon: DollarSign, color: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/20' },
    { label: 'Subscribers', value: String(dashboard?.total_subscribers || 0), icon: Users, color: 'text-cyan-400', bg: 'bg-cyan-500/10', border: 'border-cyan-500/20' },
    { label: 'Published Agents', value: String(dashboard?.total_agents_published || 0), icon: Bot, color: 'text-purple-400', bg: 'bg-purple-500/10', border: 'border-purple-500/20' },
    { label: 'Pending Balance', value: fmtCents(pendingBalance), icon: Clock, color: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/20' },
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex-1 overflow-y-auto p-6 space-y-6"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Creator Hub</h1>
          <p className="text-sm text-slate-400 mt-1">Track your agent revenue and payouts</p>
        </div>
        <div className="flex items-center gap-2">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`px-3 py-1.5 text-xs rounded-lg transition-colors ${
                period === p
                  ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800/50'
              }`}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {status && !status.is_onboarded && (
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="relative overflow-hidden rounded-xl border border-cyan-500/20 bg-gradient-to-r from-cyan-500/10 via-purple-500/10 to-cyan-500/10 p-6"
        >
          <div className="relative z-10">
            <div className="flex items-center gap-3 mb-3">
              <img src="/logo.svg" alt="Abenix" className="w-10 h-10" />
              <div>
                <h2 className="text-lg font-semibold text-white">Start Earning from Your Agents</h2>
                <p className="text-sm text-slate-400">Connect your Stripe account to receive payouts from agent subscriptions</p>
              </div>
            </div>
            <button
              onClick={handleOnboard}
              disabled={onboarding}
              className="mt-2 px-5 py-2.5 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg hover:from-cyan-400 hover:to-purple-500 shadow-lg shadow-cyan-500/25 disabled:opacity-50 transition-all"
            >
              {onboarding ? (
                <span className="flex items-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Connecting...
                </span>
              ) : (
                'Connect with Stripe'
              )}
            </button>
          </div>
        </motion.div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {kpis.map((kpi, i) => (
          <motion.div
            key={kpi.label}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05 }}
            className={`${kpi.bg} border ${kpi.border} rounded-xl p-4`}
          >
            <div className="flex items-center justify-between mb-2">
              <kpi.icon className={`w-5 h-5 ${kpi.color}`} />
            </div>
            <p className={`text-2xl font-bold ${kpi.color}`}>{kpi.value}</p>
            <p className="text-xs text-slate-500 mt-1">{kpi.label}</p>
          </motion.div>
        ))}
      </div>

      <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
        <h3 className="text-sm font-semibold text-white mb-4">Revenue Over Time</h3>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={dashboard?.revenue_by_day || []}>
              <defs>
                <linearGradient id="revenueGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#06b6d4" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#06b6d4" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="date"
                axisLine={false}
                tickLine={false}
                tick={{ fill: '#64748b', fontSize: 11 }}
                tickFormatter={(v: string) => {
                  const d = new Date(v);
                  return `${d.getMonth() + 1}/${d.getDate()}`;
                }}
              />
              <YAxis
                axisLine={false}
                tickLine={false}
                tick={{ fill: '#64748b', fontSize: 11 }}
                tickFormatter={(v: number) => `$${v}`}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1e293b',
                  border: '1px solid #334155',
                  borderRadius: '8px',
                  color: '#f1f5f9',
                  fontSize: '12px',
                }}
                formatter={(value: unknown) => [`$${Number(value).toFixed(2)}`, 'Revenue']}
                labelFormatter={(label: unknown) => new Date(String(label)).toLocaleDateString()}
              />
              <Area
                type="monotone"
                dataKey="revenue"
                stroke="#06b6d4"
                strokeWidth={2}
                fill="url(#revenueGrad)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
          <h3 className="text-sm font-semibold text-white mb-4">Top Agents</h3>
          {dashboard?.top_agents?.length ? (
            <div className="space-y-3">
              {dashboard.top_agents.map((agent) => (
                <div
                  key={agent.agent_id}
                  className="flex items-center justify-between py-2 border-b border-slate-700/30 last:border-0"
                >
                  <div>
                    <p className="text-sm text-white font-medium">{agent.name}</p>
                    <p className="text-xs text-slate-500">{agent.subscribers} subscribers</p>
                  </div>
                  <p className="text-sm font-semibold text-emerald-400">{fmt(agent.revenue)}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-slate-500">No agent revenue yet</p>
          )}
        </div>

        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-white">Recent Payouts</h3>
            {status?.is_onboarded && (
              <button
                onClick={handleStripeDashboard}
                className="flex items-center gap-1.5 text-xs text-cyan-400 hover:text-cyan-300 transition-colors"
              >
                <ExternalLink className="w-3.5 h-3.5" />
                Stripe Dashboard
              </button>
            )}
          </div>
          {dashboard?.recent_payouts?.length ? (
            <div className="space-y-3">
              {dashboard.recent_payouts.map((p) => (
                <div
                  key={p.id}
                  className="flex items-center justify-between py-2 border-b border-slate-700/30 last:border-0"
                >
                  <div>
                    <p className="text-sm text-white">{p.agent_name}</p>
                    <p className="text-xs text-slate-500">
                      {new Date(p.created_at).toLocaleDateString()}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-semibold text-emerald-400">{fmt(p.creator_amount)}</p>
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                        p.status === 'completed'
                          ? 'bg-emerald-500/10 text-emerald-400'
                          : p.status === 'pending'
                            ? 'bg-amber-500/10 text-amber-400'
                            : 'bg-red-500/10 text-red-400'
                      }`}
                    >
                      {p.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-slate-500">No payouts yet</p>
          )}
        </div>
      </div>

      {status?.is_onboarded && (
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs text-slate-500 uppercase tracking-wider">Available Balance</p>
              <p className="text-3xl font-bold text-emerald-400 mt-1">{fmtCents(availableBalance)}</p>
            </div>
            <button
              onClick={handleStripeDashboard}
              className="px-4 py-2 bg-slate-700/50 border border-slate-600 text-slate-200 text-sm rounded-lg hover:bg-slate-700 transition-colors flex items-center gap-2"
            >
              <ExternalLink className="w-4 h-4" />
              Open Stripe Dashboard
            </button>
          </div>
        </div>
      )}
    </motion.div>
  );
}
