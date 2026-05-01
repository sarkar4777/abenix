'use client';

import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { usePageTitle } from '@/hooks/usePageTitle';
import {
  Activity,
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Clock,
  DollarSign,
  TrendingDown,
  TrendingUp,
  Zap,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import {
  LazyAreaChart as AreaChart,
  LazyArea as Area,
  LazyBarChart as BarChart,
  LazyBar as Bar,
  LazyXAxis as XAxis,
  LazyYAxis as YAxis,
  LazyCartesianGrid as CartesianGrid,
  LazyTooltip as Tooltip,
  LazyResponsiveContainer as ResponsiveContainer,
} from '@/components/ui/LazyCharts';
import { useApi } from '@/hooks/useApi';
import { AnalyticsSkeleton } from '@/components/ui/Skeleton';

interface OverviewData {
  total_executions: number;
  completed: number;
  failed: number;
  success_rate: number;
  avg_response_ms: number;
  total_cost: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_tokens: number;
  cache_hit_rate: number;
  period: string;
}

interface ExecutionPoint {
  date: string;
  total: number;
  completed: number;
  failed: number;
  error_rate: number;
  avg_duration_ms: number;
}

interface ModelBreakdown {
  model: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  executions: number;
  cost: number;
}

interface DailyToken {
  date: string;
  [model: string]: string | number;
}

interface AgentCost {
  agent_id: string;
  name: string;
  icon_url: string | null;
  category: string | null;
  executions: number;
  cost: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  avg_duration_ms: number;
}

interface DailyCost {
  date: string;
  cost: number;
}

const PERIODS = [
  { label: '7d', value: '7d' },
  { label: '30d', value: '30d' },
  { label: '90d', value: '90d' },
];

const MODEL_COLORS: Record<string, string> = {
  'claude-sonnet-4-5-20250929': '#06b6d4',
  'claude-opus-4-6': '#a855f7',
  'claude-haiku-4-5-20251001': '#f59e0b',
  'gpt-4o': '#10b981',
  'gpt-4o-mini': '#3b82f6',
};

const AGENT_COLORS = ['#06b6d4', '#a855f7', '#f59e0b', '#10b981', '#3b82f6', '#ef4444', '#ec4899', '#84cc16'];

function getModelColor(model: string, idx: number): string {
  return MODEL_COLORS[model] || AGENT_COLORS[idx % AGENT_COLORS.length];
}

function ChartTooltip({ active, payload, label }: Record<string, unknown>) {
  if (!active || !payload || !(payload as Record<string, unknown>[]).length) return null;
  const items = payload as { name: string; value: number; color: string }[];
  return (
    <div className="bg-slate-800 border border-slate-700/50 rounded-lg px-3 py-2 shadow-xl">
      <p className="text-[11px] text-slate-400 mb-1">{label as string}</p>
      {items.map((item) => (
        <div key={item.name} className="flex items-center gap-2 text-xs">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: item.color }} />
          <span className="text-slate-300">{item.name}:</span>
          <span className="text-white font-medium">{typeof item.value === 'number' ? item.value.toLocaleString() : item.value}</span>
        </div>
      ))}
    </div>
  );
}

function CostTooltip({ active, payload, label }: Record<string, unknown>) {
  if (!active || !payload || !(payload as Record<string, unknown>[]).length) return null;
  const data = (payload as { value: number }[])[0];
  return (
    <div className="bg-slate-800 border border-slate-700/50 rounded-lg px-3 py-2 shadow-xl">
      <p className="text-[11px] text-slate-400">{label as string}</p>
      <p className="text-sm text-white font-medium">${data.value.toFixed(4)}</p>
    </div>
  );
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toString();
}

function formatMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${ms}ms`;
}

function formatCost(c: number): string {
  if (c >= 1) return `$${c.toFixed(2)}`;
  return `$${c.toFixed(4)}`;
}

interface TokensData {
  by_model: ModelBreakdown[];
  daily_tokens: DailyToken[];
}

interface CostsData {
  by_agent: AgentCost[];
  daily_costs: DailyCost[];
}

export default function AnalyticsPage() {
  usePageTitle('Analytics');
  const [period, setPeriod] = useState('30d');
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [selectedAgentName, setSelectedAgentName] = useState<string | null>(null);

  const agentFilter = selectedAgentId ? `&agent_id=${selectedAgentId}` : '';

  const { data: overview, isLoading: loadingOverview } = useApi<OverviewData>(
    `/api/analytics/overview?period=${period}${agentFilter}`,
  );
  const { data: executions } = useApi<ExecutionPoint[]>(
    `/api/analytics/executions?period=${period}&granularity=daily${agentFilter}`,
  );
  const { data: tokensData } = useApi<TokensData>(
    `/api/analytics/tokens?period=${period}${agentFilter}`,
  );
  const { data: costsData } = useApi<CostsData>(
    `/api/analytics/costs?period=${period}${agentFilter}`,
  );

  const byModel = tokensData?.by_model ?? [];
  const dailyTokens = tokensData?.daily_tokens ?? [];
  const byAgent = costsData?.by_agent ?? [];
  const dailyCosts = costsData?.daily_costs ?? [];
  const loading = loadingOverview;

  const modelKeys = Array.from(
    new Set(dailyTokens.flatMap((d) => Object.keys(d).filter((k) => k !== 'date')))
  );

  const execChartData = (executions ?? []).map((e) => ({
    date: e.date.slice(5),
    completed: e.completed,
    failed: e.failed,
  }));

  const errorChartData = (executions ?? []).map((e) => ({
    date: e.date.slice(5),
    error_rate: e.error_rate,
  }));

  const dailyTokenChart = dailyTokens.map((d) => ({
    ...d,
    date: typeof d.date === 'string' ? d.date.slice(5) : d.date,
  }));

  const costChartData = dailyCosts.map((d) => ({
    date: d.date.slice(5),
    cost: d.cost,
  }));

  const maxAgentCost = byAgent.length > 0 ? Math.max(...byAgent.map((a) => a.cost)) : 1;

  if (loading) {
    return <AnalyticsSkeleton />;
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="space-y-6 max-w-[1400px]"
    >
      {/* Header + Period Selector */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Analytics</h1>
          <p className="text-sm text-slate-500 mt-1">
            Track executions, token usage, costs, and performance.{' '}
            <a href="#drift-alerts" className="text-amber-400 hover:text-amber-300 underline decoration-dotted">
              Jump to Drift Alerts ↓
            </a>
          </p>
          {selectedAgentId && (
            <div className="flex items-center gap-2 mt-2">
              <span className="text-xs bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 px-2.5 py-1 rounded-full flex items-center gap-1.5">
                Filtered: {selectedAgentName || selectedAgentId.slice(0, 8)}
                <button
                  onClick={() => { setSelectedAgentId(null); setSelectedAgentName(null); }}
                  className="ml-1 text-cyan-400 hover:text-white font-bold"
                >
                  &times;
                </button>
              </span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-1 bg-slate-800/50 border border-slate-700/50 rounded-lg p-1">
          {PERIODS.map((p) => (
            <button
              key={p.value}
              onClick={() => setPeriod(p.value)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                period === p.value
                  ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        <KpiCard
          label="Total Executions"
          value={overview ? formatNumber(overview.total_executions) : '0'}
          icon={Zap}
          iconColor="text-cyan-400"
          iconBg="bg-cyan-500/10"
          sub={overview ? `${overview.completed} completed` : undefined}
        />
        <KpiCard
          label="Avg Response Time"
          value={overview ? formatMs(overview.avg_response_ms) : '0ms'}
          icon={Clock}
          iconColor="text-amber-400"
          iconBg="bg-amber-500/10"
        />
        <KpiCard
          label="Cache Hit Rate"
          value={overview ? `${overview.cache_hit_rate}%` : '0%'}
          icon={Activity}
          iconColor="text-emerald-400"
          iconBg="bg-emerald-500/10"
        />
        <KpiCard
          label="Total Cost"
          value={overview ? formatCost(overview.total_cost) : '$0'}
          icon={DollarSign}
          iconColor="text-purple-400"
          iconBg="bg-purple-500/10"
          sub={overview ? `${formatNumber(overview.total_tokens)} tokens` : undefined}
        />
        <KpiCard
          label="Success Rate"
          value={overview ? `${overview.success_rate}%` : '0%'}
          icon={overview && overview.success_rate >= 95 ? TrendingUp : TrendingDown}
          iconColor={overview && overview.success_rate >= 95 ? 'text-emerald-400' : 'text-red-400'}
          iconBg={overview && overview.success_rate >= 95 ? 'bg-emerald-500/10' : 'bg-red-500/10'}
          sub={overview && overview.failed > 0 ? `${overview.failed} failed` : undefined}
        />
      </div>

      {/* Charts Row 1: Executions + Token Usage */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Executions Over Time */}
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-cyan-400" />
              <h2 className="text-sm font-semibold text-white">Executions Over Time</h2>
            </div>
            <div className="flex items-center gap-3 text-[11px]">
              <span className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-cyan-400" />
                <span className="text-slate-400">Completed</span>
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-red-400" />
                <span className="text-slate-400">Failed</span>
              </span>
            </div>
          </div>
          {execChartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart data={execChartData}>
                <defs>
                  <linearGradient id="gradCyan" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#06b6d4" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="#06b6d4" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="gradRed" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#ef4444" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="#ef4444" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} tickLine={false} axisLine={{ stroke: '#1e293b' }} />
                <YAxis tick={{ fill: '#64748b', fontSize: 11 }} tickLine={false} axisLine={false} allowDecimals={false} />
                <Tooltip content={<ChartTooltip />} />
                <Area type="monotone" dataKey="completed" stroke="#06b6d4" fill="url(#gradCyan)" strokeWidth={2} />
                <Area type="monotone" dataKey="failed" stroke="#ef4444" fill="url(#gradRed)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <EmptyChart />
          )}
        </div>

        {/* Token Usage by Model */}
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4 text-purple-400" />
              <h2 className="text-sm font-semibold text-white">Token Usage by Model</h2>
            </div>
            <div className="flex items-center gap-3 text-[11px]">
              {byModel.slice(0, 3).map((m, i) => (
                <span key={m.model} className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: getModelColor(m.model, i) }} />
                  <span className="text-slate-400 truncate max-w-[80px]">{m.model.split('/').pop()}</span>
                </span>
              ))}
            </div>
          </div>
          {dailyTokenChart.length > 0 && modelKeys.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={dailyTokenChart}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} tickLine={false} axisLine={{ stroke: '#1e293b' }} />
                <YAxis tick={{ fill: '#64748b', fontSize: 11 }} tickLine={false} axisLine={false} tickFormatter={(v: number) => formatNumber(v)} />
                <Tooltip content={<ChartTooltip />} />
                {modelKeys.map((key, i) => (
                  <Bar
                    key={key}
                    dataKey={key}
                    stackId="tokens"
                    fill={getModelColor(key.replace(/_/g, '-').replace(/_/g, '.'), i)}
                    radius={i === modelKeys.length - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]}
                    maxBarSize={32}
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <EmptyChart />
          )}
        </div>
      </div>

      {/* Charts Row 2: Cost by Agent + Daily Costs */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Cost by Agent */}
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
          <div className="flex items-center gap-2 mb-4">
            <DollarSign className="w-4 h-4 text-amber-400" />
            <h2 className="text-sm font-semibold text-white">Cost by Agent</h2>
          </div>
          {byAgent.length > 0 ? (
            <div className="space-y-3">
              {byAgent.slice(0, 8).map((agent, i) => {
                const pct = maxAgentCost > 0 ? (agent.cost / maxAgentCost) * 100 : 0;
                return (
                  <div key={agent.agent_id}>
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-xs text-slate-300 truncate max-w-[160px]">
                          {agent.name}
                        </span>
                        {agent.category && (
                          <span className="text-[10px] text-slate-500 bg-slate-800/50 px-1.5 py-0.5 rounded">
                            {agent.category}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-3 text-[11px] shrink-0">
                        <span className="text-slate-500">{agent.executions} runs</span>
                        <span className="text-white font-medium">${agent.cost.toFixed(4)}</span>
                      </div>
                    </div>
                    <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: `${pct}%`,
                          backgroundColor: AGENT_COLORS[i % AGENT_COLORS.length],
                        }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <EmptyChart />
          )}
        </div>

        {/* Daily Cost Trend */}
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
          <div className="flex items-center gap-2 mb-4">
            <TrendingUp className="w-4 h-4 text-emerald-400" />
            <h2 className="text-sm font-semibold text-white">Daily Cost Trend</h2>
          </div>
          {costChartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart data={costChartData}>
                <defs>
                  <linearGradient id="gradPurple" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#a855f7" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="#a855f7" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} tickLine={false} axisLine={{ stroke: '#1e293b' }} />
                <YAxis tick={{ fill: '#64748b', fontSize: 11 }} tickLine={false} axisLine={false} tickFormatter={(v: number) => `$${v}`} />
                <Tooltip content={<CostTooltip />} />
                <Area type="monotone" dataKey="cost" stroke="#a855f7" fill="url(#gradPurple)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <EmptyChart />
          )}
        </div>
      </div>

      {/* Row 3: Top Agents Leaderboard + Error Rate */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Top Agents Leaderboard */}
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
          <div className="flex items-center gap-2 mb-4">
            <Zap className="w-4 h-4 text-cyan-400" />
            <h2 className="text-sm font-semibold text-white">Top Agents by Usage</h2>
          </div>
          {byAgent.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-slate-700/50">
                    <th className="text-left text-[11px] text-slate-500 font-medium py-2 pr-4">#</th>
                    <th className="text-left text-[11px] text-slate-500 font-medium py-2 pr-4">Agent</th>
                    <th className="text-right text-[11px] text-slate-500 font-medium py-2 px-3">Runs</th>
                    <th className="text-right text-[11px] text-slate-500 font-medium py-2 px-3">Tokens</th>
                    <th className="text-right text-[11px] text-slate-500 font-medium py-2 px-3">Cost</th>
                    <th className="text-right text-[11px] text-slate-500 font-medium py-2 pl-3">Avg Time</th>
                  </tr>
                </thead>
                <tbody>
                  {byAgent.slice(0, 10).map((agent, i) => (
                    <tr
                      key={agent.agent_id}
                      onClick={() => { setSelectedAgentId(agent.agent_id); setSelectedAgentName(agent.name); }}
                      className="border-b border-slate-700/30 cursor-pointer hover:bg-cyan-500/5 transition-colors"
                    >
                      <td className="py-2.5 pr-4">
                        <span className={`text-xs font-bold ${
                          i === 0 ? 'text-amber-400' : i === 1 ? 'text-slate-300' : i === 2 ? 'text-amber-600' : 'text-slate-500'
                        }`}>
                          {i + 1}
                        </span>
                      </td>
                      <td className="text-xs text-slate-300 py-2.5 pr-4 max-w-[140px] truncate">
                        {agent.name}
                      </td>
                      <td className="text-right text-xs text-slate-300 py-2.5 px-3">
                        {agent.executions.toLocaleString()}
                      </td>
                      <td className="text-right text-xs text-slate-300 py-2.5 px-3">
                        {formatNumber(agent.total_tokens)}
                      </td>
                      <td className="text-right text-xs text-white font-medium py-2.5 px-3">
                        ${agent.cost.toFixed(4)}
                      </td>
                      <td className="text-right text-xs text-slate-400 py-2.5 pl-3">
                        {formatMs(agent.avg_duration_ms)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyChart />
          )}
        </div>

        {/* Error Rate Trend */}
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
          <div className="flex items-center gap-2 mb-4">
            <TrendingDown className="w-4 h-4 text-red-400" />
            <h2 className="text-sm font-semibold text-white">Error Rate Trend</h2>
          </div>
          {errorChartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart data={errorChartData}>
                <defs>
                  <linearGradient id="gradRedError" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#ef4444" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="#ef4444" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} tickLine={false} axisLine={{ stroke: '#1e293b' }} />
                <YAxis tick={{ fill: '#64748b', fontSize: 11 }} tickLine={false} axisLine={false} tickFormatter={(v: number) => `${v}%`} domain={[0, 'auto']} />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (!active || !payload?.length) return null;
                    return (
                      <div className="bg-slate-800 border border-slate-700/50 rounded-lg px-3 py-2 shadow-xl">
                        <p className="text-[11px] text-slate-400">{label}</p>
                        <p className="text-sm text-red-400 font-medium">{(payload[0].value as number).toFixed(1)}% error rate</p>
                      </div>
                    );
                  }}
                />
                <Area type="monotone" dataKey="error_rate" stroke="#ef4444" fill="url(#gradRedError)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <EmptyChart />
          )}
        </div>
      </div>

      {/* Model Breakdown Table */}
      {byModel.length > 0 && (
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
          <div className="flex items-center gap-2 mb-4">
            <Activity className="w-4 h-4 text-purple-400" />
            <h2 className="text-sm font-semibold text-white">Token Usage by Model</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-700/50">
                  <th className="text-left text-[11px] text-slate-500 font-medium py-2 pr-4">Model</th>
                  <th className="text-right text-[11px] text-slate-500 font-medium py-2 px-4">Input Tokens</th>
                  <th className="text-right text-[11px] text-slate-500 font-medium py-2 px-4">Output Tokens</th>
                  <th className="text-right text-[11px] text-slate-500 font-medium py-2 px-4">Total</th>
                  <th className="text-right text-[11px] text-slate-500 font-medium py-2 px-4">Executions</th>
                  <th className="text-right text-[11px] text-slate-500 font-medium py-2 pl-4">Cost</th>
                </tr>
              </thead>
              <tbody>
                {byModel.map((m, i) => (
                  <tr key={m.model} className="border-b border-slate-700/30">
                    <td className="text-xs py-2.5 pr-4">
                      <div className="flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full" style={{ backgroundColor: getModelColor(m.model, i) }} />
                        <span className="text-slate-300 font-mono">{m.model}</span>
                      </div>
                    </td>
                    <td className="text-right text-xs text-slate-300 py-2.5 px-4">{formatNumber(m.input_tokens)}</td>
                    <td className="text-right text-xs text-slate-300 py-2.5 px-4">{formatNumber(m.output_tokens)}</td>
                    <td className="text-right text-xs text-white font-medium py-2.5 px-4">{formatNumber(m.total_tokens)}</td>
                    <td className="text-right text-xs text-slate-300 py-2.5 px-4">{m.executions.toLocaleString()}</td>
                    <td className="text-right text-xs text-white font-medium py-2.5 pl-4">${m.cost.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <DriftAlertsCard agentId={selectedAgentId} />
    </motion.div>
  );
}

function KpiCard({
  label,
  value,
  icon: Icon,
  iconColor,
  iconBg,
  sub,
}: {
  label: string;
  value: string;
  icon: typeof Zap;
  iconColor: string;
  iconBg: string;
  sub?: string;
}) {
  return (
    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
      <div className="flex items-center gap-2 mb-3">
        <div className={`w-8 h-8 rounded-lg ${iconBg} flex items-center justify-center`}>
          <Icon className={`w-4 h-4 ${iconColor}`} />
        </div>
        <span className="text-[11px] text-slate-500 uppercase tracking-wider font-medium">
          {label}
        </span>
      </div>
      <p className="text-2xl font-bold text-white">{value}</p>
      {sub && <p className="text-[11px] text-slate-500 mt-1">{sub}</p>}
    </div>
  );
}

function EmptyChart() {
  return (
    <div className="flex items-center justify-center h-[260px] text-sm text-slate-500">
      No data for this period
    </div>
  );
}

// ─── Drift Alerts ──────────────────────────────────────────────────────────

interface DriftAlert {
  id: string;
  agent_id: string;
  agent_name?: string | null;
  metric_name: string;
  baseline_value: number;
  current_value: number;
  deviation_pct: number;
  severity: 'warning' | 'critical';
  message: string;
  acknowledged: boolean;
  created_at: string;
}

function DriftAlertsCard({ agentId }: { agentId: string | null }) {
  const [alerts, setAlerts] = useState<DriftAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [onlyUnacked, setOnlyUnacked] = useState(true);
  const [sev, setSev] = useState<'all' | 'warning' | 'critical'>('all');
  // Tenant-wide on/off. Off means no new drift rows are recorded; existing
  // rows still display and can be acknowledged.
  const [driftEnabled, setDriftEnabled] = useState<boolean>(true);
  const [toggleLoading, setToggleLoading] = useState(false);

  const loadToggle = async () => {
    try {
      const resp = await apiFetch<{ enabled: boolean }>(`/api/analytics/drift-alerts/config`);
      setDriftEnabled(Boolean(resp.data?.enabled));
    } catch { /* older backends — leave default */ }
  };

  const flipToggle = async () => {
    setToggleLoading(true);
    const next = !driftEnabled;
    try {
      await apiFetch(`/api/analytics/drift-alerts/config`, {
        method: 'PUT',
        body: JSON.stringify({ enabled: next }),
      });
      setDriftEnabled(next);
    } catch { /* rollback UI on failure */ }
    setToggleLoading(false);
  };

  const load = async () => {
    setLoading(true);
    const qs = new URLSearchParams({ limit: '30' });
    if (agentId) qs.set('agent_id', agentId);
    if (onlyUnacked) qs.set('acknowledged', 'false');
    if (sev !== 'all') qs.set('severity', sev);
    try {
      const resp = await apiFetch<DriftAlert[]>(`/api/analytics/drift-alerts?${qs}`);
      setAlerts(resp.data ?? []);
    } catch { setAlerts([]); }
    setLoading(false);
  };

  React.useEffect(() => { loadToggle(); load(); }, [agentId, onlyUnacked, sev]); // eslint-disable-line

  const ack = async (id: string) => {
    try {
      await apiFetch(`/api/analytics/drift-alerts/${id}/acknowledge`, { method: 'POST' });
      setAlerts((xs) => xs.filter((a) => a.id !== id));
    } catch { /* ignore */ }
  };

  return (
    <div id="drift-alerts" className="mt-8 rounded-xl bg-slate-900/50 border border-slate-800/50 overflow-hidden scroll-mt-20">
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800/50">
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-400" />
          <h3 className="text-sm font-semibold text-white">Drift Alerts</h3>
          <span className="text-xs text-slate-500">(behavior deviating &gt; 2σ / 3σ from baseline)</span>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <button
            onClick={flipToggle}
            disabled={toggleLoading}
            title={driftEnabled
              ? 'Drift detection is ON — every execution updates baselines and fires alerts'
              : 'Drift detection is OFF — no new alerts will fire'}
            className={`inline-flex items-center gap-2 px-2 py-1 rounded border transition-colors ${
              driftEnabled
                ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/20'
                : 'bg-slate-800 border-slate-600 text-slate-400 hover:bg-slate-700'
            } disabled:opacity-50`}
          >
            <span className={`inline-block w-2 h-2 rounded-full ${driftEnabled ? 'bg-emerald-400' : 'bg-slate-500'}`} />
            {driftEnabled ? 'Detection ON' : 'Detection OFF'}
          </button>
          <select value={sev} onChange={(e) => setSev(e.target.value as any)}
            className="bg-slate-800/50 border border-slate-700/50 rounded px-2 py-1 text-slate-300">
            <option value="all">all</option>
            <option value="warning">warning (2σ)</option>
            <option value="critical">critical (3σ)</option>
          </select>
          <label className="flex items-center gap-1 text-slate-400">
            <input type="checkbox" checked={onlyUnacked} onChange={(e) => setOnlyUnacked(e.target.checked)} />
            un-acked only
          </label>
        </div>
      </div>
      {loading ? (
        <div className="px-5 py-6 text-sm text-slate-500">Loading…</div>
      ) : alerts.length === 0 ? (
        <div className="px-5 py-8 text-sm text-emerald-400 flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4" /> No drift alerts — every agent is behaving within baseline.
        </div>
      ) : (
        <ul className="divide-y divide-slate-800/50">
          {alerts.map((a) => (
            <li key={a.id} className="px-5 py-3 flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase ${
                    a.severity === 'critical'
                      ? 'bg-red-500/20 text-red-300 border border-red-500/30'
                      : 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                  }`}>{a.severity}</span>
                  <span className="text-xs text-white font-medium">{a.agent_name || a.agent_id.slice(0, 8)}</span>
                  <span className="text-xs text-slate-500">{a.metric_name}</span>
                  <span className="text-[11px] text-slate-600 ml-auto">{new Date(a.created_at).toLocaleString()}</span>
                </div>
                <p className="text-xs text-slate-300 truncate">{a.message}</p>
                <p className="text-[11px] text-slate-500 mt-0.5">
                  baseline {a.baseline_value.toFixed(2)} → current {a.current_value.toFixed(2)}
                  {' '}({a.deviation_pct >= 0 ? '+' : ''}{a.deviation_pct.toFixed(1)}%)
                </p>
              </div>
              {!a.acknowledged && (
                <button onClick={() => ack(a.id)}
                  className="shrink-0 text-xs px-2 py-1 rounded bg-slate-800 border border-slate-700 hover:border-emerald-500/50 text-slate-300">
                  ack
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
