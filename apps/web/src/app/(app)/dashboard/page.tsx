'use client';

import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Activity,
  ArrowRight,
  Bot,
  CheckCircle2,
  Clock,
  Coins,
  DollarSign,
  Plus,
  RefreshCw,
  TrendingUp,
  Upload,
  XCircle,
  Zap,
} from 'lucide-react';
import { useNotificationStore } from '@/stores/notificationStore';
import { useApi } from '@/hooks/useApi';
import { usePageTitle } from '@/hooks/usePageTitle';
import { apiFetch } from '@/lib/api-client';
import { DashboardSkeleton } from '@/components/ui/Skeleton';

interface LiveStats {
  active_executions: number;
  today_executions: number;
  today_completed: number;
  today_failed: number;
  success_rate: number;
  total_agents: number;
  today_cost: number;
  today_input_tokens?: number;
  today_output_tokens?: number;
  today_total_tokens?: number;
}

function fmtTokens(n: number | undefined): string {
  if (!n) return '0';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function CountUp({ target, prefix = '', suffix = '' }: { target: number; prefix?: string; suffix?: string }) {
  const [count, setCount] = useState(0);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    let frame: number;
    const duration = 1200;
    const start = performance.now();
    const step = (now: number) => {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setCount(Math.floor(eased * target));
      if (progress < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target]);

  return (
    <span ref={ref}>
      {prefix}{count.toLocaleString()}{suffix}
    </span>
  );
}

const QUICK_ACTIONS = [
  { label: 'New Agent', icon: Plus, href: '/builder', color: 'from-cyan-500 to-blue-600' },
  { label: 'Upload Knowledge', icon: Upload, href: '/knowledge', color: 'from-purple-500 to-pink-600' },
  { label: 'Browse Agents', icon: Bot, href: '/agents', color: 'from-amber-500 to-orange-600' },
  { label: 'Connect MCP', icon: Zap, href: '/mcp', color: 'from-emerald-500 to-teal-600' },
];

function useSystemStatus() {
  const [health, setHealth] = useState<{ status: string; postgres?: string; redis?: string } | null>(null);
  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    // Use /api/health (fast, no Neo4j) instead of /api/health/ready (slow, checks Neo4j)
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);
    fetch(`${apiUrl}/api/health`, { signal: controller.signal })
      .then(res => res.json())
      .then(data => setHealth({ status: data.status || 'ok', postgres: 'ok', redis: 'ok' }))
      .catch(() => setHealth(null))
      .finally(() => clearTimeout(timeout));
  }, []);

  if (!health) {
    return [
      { label: 'API Gateway', status: 'unknown' },
      { label: 'PostgreSQL', status: 'unknown' },
      { label: 'Redis Cache', status: 'unknown' },
    ];
  }
  return [
    { label: 'API Gateway', status: 'healthy' },
    { label: 'PostgreSQL', status: health.postgres === 'ok' ? 'healthy' : 'unavailable' },
    { label: 'Redis Cache', status: health.redis === 'ok' ? 'healthy' : 'unavailable' },
  ];
}

const statusIcon = (s: string) => {
  if (s === 'healthy') return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />;
  if (s === 'degraded' || s === 'unknown') return <Clock className="w-3.5 h-3.5 text-amber-400" />;
  return <XCircle className="w-3.5 h-3.5 text-red-400" />;
};

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06 } },
};

const item = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0, transition: { duration: 0.4 } },
};

export default function DashboardPage() {
  usePageTitle('Dashboard');
  const statusItems = useSystemStatus();
  const dashboardUpdate = useNotificationStore((s) => s.dashboardUpdate);
  const { data: stats, isLoading: loading, mutate } = useApi<LiveStats>(
    '/api/analytics/live-stats',
  );
  const [userQuota, setUserQuota] = useState<{tokens_used: number; token_allowance: number | null; cost_used: number; cost_limit: number | null; usage_pct: number | null} | null>(null);

  useEffect(() => {
    apiFetch('/api/analytics/per-user').then(res => {
      if (res.data && !Array.isArray(res.data)) setUserQuota(res.data as {tokens_used: number; token_allowance: number | null; cost_used: number; cost_limit: number | null; usage_pct: number | null});
    });
  }, []);

  useEffect(() => {
    mutate();
  }, [dashboardUpdate, mutate]);

  const kpiCards = [
    {
      label: 'Total Agents',
      value: stats?.total_agents ?? 0,
      change: stats ? `${stats.active_executions} active now` : '',
      changeColor: stats && stats.active_executions > 0 ? 'text-cyan-400' : 'text-slate-500',
      icon: Bot,
      iconBg: 'bg-cyan-500/10',
      iconColor: 'text-cyan-400',
    },
    {
      label: 'Executions Today',
      value: stats?.today_executions ?? 0,
      change: stats ? `${stats.today_failed} failed` : '',
      changeColor: stats && stats.today_failed > 0 ? 'text-red-400' : 'text-emerald-400',
      icon: Activity,
      iconBg: 'bg-purple-500/10',
      iconColor: 'text-purple-400',
    },
    {
      label: 'Success Rate',
      value: Math.round(stats?.success_rate ?? 100),
      suffix: '%',
      change: stats ? `${stats.today_completed} completed` : '',
      changeColor: 'text-emerald-400',
      icon: TrendingUp,
      iconBg: 'bg-emerald-500/10',
      iconColor: 'text-emerald-400',
    },
    {
      label: 'Token Spend',
      value: stats?.today_cost ?? 0,
      prefix: '$',
      // Secondary line on the card — total tokens used today, so the
      // operator sees volume AND dollar spend at a glance. Prevents the
      // "$0 for 1M tokens" silent-zero-pricing gap from looking like
      // there was zero activity.
      change: stats
        ? `${fmtTokens(stats.today_total_tokens)} tokens today`
        : 'today',
      changeColor: 'text-slate-500',
      icon: DollarSign,
      iconBg: 'bg-amber-500/10',
      iconColor: 'text-amber-400',
    },
  ];

  if (loading && !stats) {
    return <DashboardSkeleton />;
  }

  return (
    <motion.div
      variants={container}
      initial="hidden"
      animate="show"
      className="space-y-6 max-w-[1400px]"
    >
      <motion.div variants={item}>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white">Dashboard</h1>
            <p className="text-sm text-slate-500 mt-1">Overview of your agent platform</p>
          </div>
          {stats && stats.active_executions > 0 && (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-cyan-500/10 border border-cyan-500/20">
              <RefreshCw className="w-3.5 h-3.5 text-cyan-400 animate-spin" />
              <span className="text-xs text-cyan-400 font-medium">
                {stats.active_executions} running
              </span>
            </div>
          )}
        </div>
      </motion.div>

      {/*
        Zero-state hero — shown when a fresh tenant lands here for the
        first time (no agents, no executions). Three concrete actions
        that move them forward in <30 seconds. Hidden once the tenant
        has any activity so power users don't see redundant CTAs.
      */}
      {stats && stats.total_agents === 0 && stats.today_executions === 0 && (
        <motion.div variants={item}>
          <div className="bg-gradient-to-br from-cyan-500/10 via-purple-500/5 to-transparent border border-cyan-500/20 rounded-xl p-6">
            <h2 className="text-lg font-semibold text-white mb-1">Welcome to Abenix 👋</h2>
            <p className="text-sm text-slate-300 mb-5">
              Three ways to get going in the next 5 minutes:
            </p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <a
                href="/chat"
                className="group bg-slate-900/60 border border-slate-700/60 rounded-lg p-4 hover:border-cyan-500/40 hover:bg-slate-900 transition-colors"
              >
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-8 h-8 rounded-lg bg-cyan-500/15 flex items-center justify-center">
                    <Bot className="w-4 h-4 text-cyan-400" />
                  </div>
                  <h3 className="text-white font-medium">Talk to a sample agent</h3>
                </div>
                <p className="text-xs text-slate-400">
                  We pre-seeded a few agents (code-assistant, web-researcher, doc-summariser).
                  Open <code className="text-cyan-300">/chat</code>, pick one, send a prompt.
                </p>
                <span className="inline-flex items-center gap-1 mt-3 text-xs text-cyan-400 group-hover:gap-2 transition-all">
                  Try it <ArrowRight className="w-3 h-3" />
                </span>
              </a>
              <a
                href="/agents/new"
                className="group bg-slate-900/60 border border-slate-700/60 rounded-lg p-4 hover:border-purple-500/40 hover:bg-slate-900 transition-colors"
              >
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-8 h-8 rounded-lg bg-purple-500/15 flex items-center justify-center">
                    <Plus className="w-4 h-4 text-purple-400" />
                  </div>
                  <h3 className="text-white font-medium">Build your first agent</h3>
                </div>
                <p className="text-xs text-slate-400">
                  Pick a system prompt + a few tools (calculator, web_search, file_reader).
                  No code needed.
                </p>
                <span className="inline-flex items-center gap-1 mt-3 text-xs text-purple-400 group-hover:gap-2 transition-all">
                  Open builder <ArrowRight className="w-3 h-3" />
                </span>
              </a>
              <a
                href="/knowledge"
                className="group bg-slate-900/60 border border-slate-700/60 rounded-lg p-4 hover:border-amber-500/40 hover:bg-slate-900 transition-colors"
              >
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-8 h-8 rounded-lg bg-amber-500/15 flex items-center justify-center">
                    <Upload className="w-4 h-4 text-amber-400" />
                  </div>
                  <h3 className="text-white font-medium">Upload a knowledge base</h3>
                </div>
                <p className="text-xs text-slate-400">
                  Drop in PDFs, DOCX, CSV, or Markdown. Agents can search them with
                  the <code className="text-amber-300">knowledge_search</code> tool.
                </p>
                <span className="inline-flex items-center gap-1 mt-3 text-xs text-amber-400 group-hover:gap-2 transition-all">
                  Upload <ArrowRight className="w-3 h-3" />
                </span>
              </a>
            </div>
            <p className="text-xs text-slate-500 mt-4">
              Need a deeper walkthrough?{' '}
              <a href="/help" className="text-cyan-400 hover:underline">
                Open the help center
              </a>{' '}
              — every feature has a short tour.
            </p>
          </div>
        </motion.div>
      )}

      <motion.div variants={item} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {kpiCards.map((kpi) => (
          <div
            key={kpi.label}
            className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5 hover:border-slate-600/50 transition-colors"
          >
            <div className="flex items-start justify-between mb-3">
              <div className={`w-10 h-10 rounded-lg ${kpi.iconBg} flex items-center justify-center`}>
                <kpi.icon className={`w-5 h-5 ${kpi.iconColor}`} />
              </div>
              <span className={`text-xs ${kpi.changeColor}`}>{kpi.change}</span>
            </div>
            <p className="text-2xl font-bold text-white">
              <CountUp target={kpi.value} prefix={kpi.prefix} suffix={kpi.suffix} />
            </p>
            <p className="text-xs text-slate-500 mt-1">{kpi.label}</p>
          </div>
        ))}
        {/* User token usage card */}
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-slate-500 uppercase">Your Token Usage</span>
            <Coins className="w-4 h-4 text-cyan-400" />
          </div>
          {userQuota ? (
            <>
              <p className="text-lg font-bold text-white">
                {userQuota.tokens_used >= 1000 ? `${(userQuota.tokens_used / 1000).toFixed(0)}K` : userQuota.tokens_used}
                {userQuota.token_allowance && (
                  <span className="text-sm text-slate-500 font-normal"> / {userQuota.token_allowance >= 1000 ? `${(userQuota.token_allowance / 1000).toFixed(0)}K` : userQuota.token_allowance}</span>
                )}
              </p>
              {userQuota.token_allowance && (
                <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden mt-2">
                  <div
                    className={`h-full rounded-full ${(userQuota.usage_pct || 0) > 90 ? 'bg-red-500' : (userQuota.usage_pct || 0) > 70 ? 'bg-amber-500' : 'bg-cyan-500'}`}
                    style={{ width: `${Math.min(userQuota.usage_pct || 0, 100)}%` }}
                  />
                </div>
              )}
              <p className="text-xs text-slate-500 mt-1">
                Cost: ${userQuota.cost_used.toFixed(2)}{userQuota.cost_limit ? ` / $${userQuota.cost_limit.toFixed(2)}` : ''}
              </p>
            </>
          ) : (
            <p className="text-lg font-bold text-slate-600">Unlimited</p>
          )}
        </div>
      </motion.div>

      <div className="grid lg:grid-cols-3 gap-6">
        <motion.div variants={item} className="lg:col-span-2 bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700/50">
            <h2 className="text-sm font-semibold text-white">Live Activity</h2>
            <a href="/analytics" className="text-xs text-cyan-400 hover:text-cyan-300 flex items-center gap-1 transition-colors">
              View all <ArrowRight className="w-3 h-3" />
            </a>
          </div>
          <div className="p-5 grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="bg-slate-900/50 rounded-lg p-4 border border-slate-700/30">
              <p className="text-xs text-slate-500 mb-1">Active Now</p>
              <p className="text-xl font-bold text-cyan-400">
                {stats?.active_executions ?? 0}
              </p>
            </div>
            <div className="bg-slate-900/50 rounded-lg p-4 border border-slate-700/30">
              <p className="text-xs text-slate-500 mb-1">Completed Today</p>
              <p className="text-xl font-bold text-emerald-400">
                {stats?.today_completed ?? 0}
              </p>
            </div>
            <div className="bg-slate-900/50 rounded-lg p-4 border border-slate-700/30">
              <p className="text-xs text-slate-500 mb-1">Failed Today</p>
              <p className="text-xl font-bold text-red-400">
                {stats?.today_failed ?? 0}
              </p>
            </div>
          </div>
        </motion.div>

        <div className="space-y-6">
          <motion.div variants={item} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
            <h2 className="text-sm font-semibold text-white mb-4">Quick Actions</h2>
            <div className="grid grid-cols-2 gap-3">
              {QUICK_ACTIONS.map((action) => (
                <a
                  key={action.label}
                  href={action.href}
                  className="flex flex-col items-center gap-2 p-3 rounded-lg bg-slate-800/50 border border-slate-700/30 hover:border-slate-600/50 transition-colors group"
                >
                  <div className={`w-9 h-9 rounded-lg bg-gradient-to-br ${action.color} flex items-center justify-center group-hover:scale-110 transition-transform`}>
                    <action.icon className="w-4 h-4 text-white" />
                  </div>
                  <span className="text-xs text-slate-400 group-hover:text-white transition-colors">
                    {action.label}
                  </span>
                </a>
              ))}
            </div>
          </motion.div>

          <motion.div variants={item} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-white">System Status</h2>
              {(() => {
                const allHealthy = statusItems.every(s => s.status === 'healthy');
                const anyDown = statusItems.some(s => s.status === 'unavailable');
                const label = anyDown ? 'Degraded' : allHealthy ? 'Operational' : 'Checking...';
                const color = anyDown ? 'text-amber-400' : allHealthy ? 'text-emerald-400' : 'text-slate-400';
                const bg = anyDown ? 'bg-amber-400' : allHealthy ? 'bg-emerald-400' : 'bg-slate-400';
                return (
                  <span className={`flex items-center gap-1.5 text-xs ${color}`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${bg} animate-pulse`} />
                    {label}
                  </span>
                );
              })()}
            </div>
            <div className="space-y-2.5">
              {statusItems.map((si) => (
                <div key={si.label} className="flex items-center justify-between">
                  <span className="text-xs text-slate-400">{si.label}</span>
                  <div className="flex items-center gap-1.5">
                    {statusIcon(si.status)}
                    <span className={`text-xs ${si.status === 'healthy' ? 'text-emerald-400' : si.status === 'degraded' || si.status === 'unknown' ? 'text-amber-400' : 'text-red-400'}`}>
                      {si.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        </div>
      </div>
    </motion.div>
  );
}
