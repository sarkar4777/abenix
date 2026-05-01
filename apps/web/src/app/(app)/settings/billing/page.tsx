'use client';

import { useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { motion } from 'framer-motion';
import {
  CheckCircle2,
  CreditCard,
  Receipt,
  TrendingUp,
  Zap,
} from 'lucide-react';
import {
  LazyBarChart as BarChart,
  LazyBar as Bar,
  LazyXAxis as XAxis,
  LazyYAxis as YAxis,
  LazyCartesianGrid as CartesianGrid,
  LazyTooltip as Tooltip,
  LazyResponsiveContainer as ResponsiveContainer,
} from '@/components/ui/LazyCharts';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { usePageTitle } from '@/hooks/usePageTitle';

interface UsageStats {
  plan: string;
  daily_limit: number;
  today_executions: number;
  period_days: number;
  total_executions: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_tokens: number;
  total_cost: number;
  daily_executions: { date: string; count: number }[];
  by_agent: {
    agent_id: string;
    executions: number;
    tokens: number;
    cost: number;
  }[];
}


function CustomTooltip({ active, payload, label }: Record<string, unknown>) {
  if (!active || !payload || !(payload as Record<string, unknown>[]).length) return null;
  const data = (payload as { value: number }[])[0];
  return (
    <div className="bg-slate-800 border border-slate-700/50 rounded-lg px-3 py-2 shadow-xl">
      <p className="text-[11px] text-slate-400">{label as string}</p>
      <p className="text-sm text-white font-medium">{data.value} executions</p>
    </div>
  );
}

export default function BillingPage() {
  usePageTitle('Billing');
  const searchParams = useSearchParams();
  const [successBanner, setSuccessBanner] = useState(false);

  useEffect(() => {
    if (searchParams.get('success') === 'true') {
      setSuccessBanner(true);
      setTimeout(() => setSuccessBanner(false), 5000);
    }
  }, [searchParams]);

  const { data: usage, isLoading: loadingUsage } =
    useApi<UsageStats>('/api/billing/usage');
  const { data: costsData } = useApi<{
    by_agent: { agent_id: string; name: string; executions: number; total_tokens: number; cost: number }[];
  }>('/api/analytics/costs');

  const loading = loadingUsage;

  // Build agent name lookup from costs endpoint
  const agentNames: Record<string, string> = {};
  if (costsData?.by_agent) {
    for (const a of costsData.by_agent) {
      agentNames[a.agent_id] = a.name;
    }
  }

  const handleManageSubscription = async () => {
    try {
      const res = await apiFetch<{ url: string; mode: string }>(
        '/api/billing/portal',
        {
          method: 'POST',
          body: JSON.stringify({}),
        },
      );
      if (res.data?.url) {
        if (res.data.mode === 'mock') {
          // noop in mock
        } else {
          window.location.href = res.data.url;
        }
      }
    } catch {
      // skip
    }
  };

  const dailyPct =
    usage && usage.daily_limit > 0
      ? Math.min((usage.today_executions / usage.daily_limit) * 100, 100)
      : 0;

  const chartData = (usage?.daily_executions || []).map((d) => ({
    date: d.date.slice(5),
    executions: d.count,
  }));

  if (loading) {
    return (
      <div className="space-y-6 max-w-[1200px]">
        <div>
          <div className="h-7 w-36 bg-slate-800 animate-pulse rounded" />
          <div className="h-3 w-56 bg-slate-700/50 animate-pulse rounded mt-2" />
        </div>
        {/* KPI cards skeleton */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6 space-y-4">
              <div className="h-3 w-24 bg-slate-700/50 animate-pulse rounded" />
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-slate-800 animate-pulse" />
                <div className="space-y-2">
                  <div className="h-5 w-16 bg-slate-800 animate-pulse rounded" />
                  <div className="h-3 w-24 bg-slate-700/50 animate-pulse rounded" />
                </div>
              </div>
            </div>
          ))}
        </div>
        {/* Chart skeleton */}
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
          <div className="h-4 w-32 bg-slate-700/50 animate-pulse rounded mb-4" />
          <div className="h-[240px] bg-slate-800/50 animate-pulse rounded-lg" />
        </div>
        {/* Plan cards skeleton */}
        <div>
          <div className="h-4 w-28 bg-slate-700/50 animate-pulse rounded mb-4" />
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5 space-y-3">
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 rounded-lg bg-slate-800 animate-pulse" />
                  <div className="h-4 w-16 bg-slate-800 animate-pulse rounded" />
                </div>
                <div className="h-7 w-16 bg-slate-800 animate-pulse rounded" />
                <div className="space-y-1.5">
                  {Array.from({ length: 3 }).map((_, j) => (
                    <div key={j} className="h-3 w-full bg-slate-700/50 animate-pulse rounded" />
                  ))}
                </div>
                <div className="h-9 w-full bg-slate-800 animate-pulse rounded-lg" />
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="space-y-6 max-w-[1200px]"
    >
      <div>
        <h1 className="text-2xl font-bold text-white">Billing & Usage</h1>
        <p className="text-sm text-slate-500 mt-1">
          Manage your subscription and monitor usage
        </p>
      </div>

      {successBanner && (
        <div className="flex items-center gap-2 px-4 py-3 bg-emerald-500/10 border border-emerald-500/30 rounded-lg">
          <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
          <p className="text-sm text-emerald-300">
            Subscription updated successfully! Your new plan is now active.
          </p>
        </div>
      )}

      {/* Current Plan + Usage Overview */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* Current Plan */}
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
              Current Plan
            </h2>
            {usage && usage.plan !== 'free' && (
              <button
                onClick={handleManageSubscription}
                className="text-[11px] text-cyan-400 hover:text-cyan-300 transition-colors"
              >
                Manage
              </button>
            )}
          </div>
          <div className="flex items-center gap-3 mb-3">
            <div className="w-10 h-10 rounded-lg bg-cyan-500/10 flex items-center justify-center">
              <Zap className="w-5 h-5 text-cyan-400" />
            </div>
            <div>
              <p className="text-lg font-bold text-white capitalize">
                {usage?.plan || 'Free'}
              </p>
              <p className="text-xs text-slate-500">
                {usage?.daily_limit === -1
                  ? 'Unlimited executions'
                  : `${usage?.daily_limit || 50} exec/day`}
              </p>
            </div>
          </div>
        </div>

        {/* Today's Usage */}
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
          <h2 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-4">
            Today&apos;s Usage
          </h2>
          <div className="flex items-end gap-2 mb-2">
            <span className="text-2xl font-bold text-white">
              {usage?.today_executions || 0}
            </span>
            <span className="text-sm text-slate-500 pb-0.5">
              / {usage?.daily_limit === -1 ? '\u221E' : usage?.daily_limit || 50}
            </span>
          </div>
          <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${
                dailyPct >= 90
                  ? 'bg-red-400'
                  : dailyPct >= 70
                    ? 'bg-amber-400'
                    : 'bg-cyan-400'
              }`}
              style={{ width: `${usage?.daily_limit === -1 ? 0 : dailyPct}%` }}
            />
          </div>
          <p className="text-[11px] text-slate-500 mt-1">
            {usage?.daily_limit === -1
              ? 'Unlimited plan'
              : `${Math.round(dailyPct)}% used today`}
          </p>
        </div>

        {/* Period Stats */}
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
          <h2 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-4">
            30-Day Summary
          </h2>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-500">Executions</span>
              <span className="text-sm text-white font-medium">
                {usage?.total_executions?.toLocaleString() || 0}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-500">Tokens</span>
              <span className="text-sm text-white font-medium">
                {usage?.total_tokens?.toLocaleString() || 0}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-500">Cost</span>
              <span className="text-sm text-white font-medium">
                ${usage?.total_cost?.toFixed(4) || '0.00'}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Usage Chart */}
      <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-cyan-400" />
            <h2 className="text-sm font-semibold text-white">
              Daily Executions
            </h2>
          </div>
          <span className="text-xs text-slate-500">Last 30 days</span>
        </div>
        {chartData.length > 0 ? (
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis
                dataKey="date"
                tick={{ fill: '#64748b', fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: '#1e293b' }}
              />
              <YAxis
                tick={{ fill: '#64748b', fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                allowDecimals={false}
              />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(6,182,212,0.05)' }} />
              <Bar
                dataKey="executions"
                fill="#06b6d4"
                radius={[4, 4, 0, 0]}
                maxBarSize={32}
              />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex items-center justify-center h-[240px] text-sm text-slate-500">
            No execution data yet
          </div>
        )}
      </div>

      {/* Usage by Agent */}
      {usage?.by_agent && usage.by_agent.length > 0 && (
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
          <h2 className="text-sm font-semibold text-white mb-4">
            Usage by Agent
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-700/50">
                  <th className="text-left text-[11px] text-slate-500 font-medium py-2 pr-4">
                    Agent
                  </th>
                  <th className="text-right text-[11px] text-slate-500 font-medium py-2 px-4">
                    Executions
                  </th>
                  <th className="text-right text-[11px] text-slate-500 font-medium py-2 px-4">
                    Tokens
                  </th>
                  <th className="text-right text-[11px] text-slate-500 font-medium py-2 pl-4">
                    Cost
                  </th>
                </tr>
              </thead>
              <tbody>
                {usage.by_agent.map((row) => (
                  <tr
                    key={row.agent_id}
                    className="border-b border-slate-700/30"
                  >
                    <td className="text-xs text-slate-300 py-2.5 pr-4">
                      {agentNames[row.agent_id] || row.agent_id.slice(0, 8) + '...'}
                    </td>
                    <td className="text-right text-xs text-slate-300 py-2.5 px-4">
                      {row.executions.toLocaleString()}
                    </td>
                    <td className="text-right text-xs text-slate-300 py-2.5 px-4">
                      {row.tokens.toLocaleString()}
                    </td>
                    <td className="text-right text-xs text-slate-300 py-2.5 pl-4">
                      ${row.cost.toFixed(4)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Manage Subscription */}
      {usage && usage.plan !== 'free' && (
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <CreditCard className="w-5 h-5 text-slate-400" />
              <div>
                <p className="text-sm font-medium text-white">
                  Manage Subscription
                </p>
                <p className="text-xs text-slate-500">
                  Update payment method, view invoices, or cancel
                </p>
              </div>
            </div>
            <button
              onClick={handleManageSubscription}
              className="flex items-center gap-1.5 px-4 py-2 text-xs font-medium text-slate-300 bg-slate-800/50 border border-slate-700/50 rounded-lg hover:text-white hover:border-slate-600/50 transition-colors"
            >
              <Receipt className="w-3.5 h-3.5" />
              Open Billing Portal
            </button>
          </div>
        </div>
      )}
    </motion.div>
  );
}
