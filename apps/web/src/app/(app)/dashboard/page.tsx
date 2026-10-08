'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useAuth } from '@/contexts/AuthContext';
import { motion } from 'framer-motion';
import {
  Activity,
  ArrowRight,
  Bot,
  CheckCircle2,
  Clock,
  LayoutDashboard,
  MessageSquare,
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
import PageHeader from '@/components/layout/PageHeader';
import StartHere from '@/components/shared/StartHere';

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
  flat_rate_billing?: boolean;
}

interface Quota {
  id?: string;
  tokens_used: number;
  token_allowance: number | null;
  cost_used: number;
  cost_limit: number | null;
  usage_pct: number | null;
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
  const [health, setHealth] = useState<{ status: string } | null>(null);
  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    // Use /api/health (fast, no Neo4j) instead of /api/health/ready (slow, checks Neo4j)
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);
    fetch(`${apiUrl}/api/health`, { signal: controller.signal })
      .then(res => res.json())
      .then(data => setHealth({ status: data.status || 'ok' }))
      .catch(() => setHealth(null))
      .finally(() => clearTimeout(timeout));
  }, []);

  // Only surface what we actually checked. /api/health is a single liveness
  // probe — claiming Postgres/Redis state from it was a lie. Subsystem pills
  // can come back when we wire /api/health/ready (which probes each one).
  if (!health) {
    return [{ label: 'API gateway healthy (single check)', status: 'unknown' }];
  }
  return [{ label: 'API gateway healthy (single check)', status: 'healthy' }];
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
  const { user } = useAuth();
  const [userQuota, setUserQuota] = useState<Quota | null>(null);
  const [quotaFailed, setQuotaFailed] = useState(false);

  useEffect(() => {
    if (!user?.id) return;
    apiFetch<Quota | Quota[]>('/api/analytics/per-user').then(res => {
      // admins get the whole tenant back, pick our own row
      const mine = Array.isArray(res.data) ? res.data.find((r) => r.id === user.id) : res.data;
      if (mine) setUserQuota(mine);
      else setQuotaFailed(true);
    });
  }, [user?.id]);

  useEffect(() => {
    mutate();
  }, [dashboardUpdate, mutate]);

  const kpiCards = [
    {
      label: 'Total Agents',
      href: '/agents?tab=all',
      value: stats?.total_agents ?? 0,
      change: stats ? `${stats.active_executions} active now` : '',
      changeColor: stats && stats.active_executions > 0 ? 'text-cyan-400' : 'text-slate-500',
      icon: Bot,
      iconBg: 'bg-cyan-500/10',
      iconColor: 'text-cyan-400',
    },
    {
      label: 'Executions Today',
      href: '/executions?since=today',
      value: stats?.today_executions ?? 0,
      change: stats ? `${stats.today_failed} failed` : '',
      changeColor: stats && stats.today_failed > 0 ? 'text-red-400' : 'text-emerald-400',
      icon: Activity,
      iconBg: 'bg-purple-500/10',
      iconColor: 'text-purple-400',
    },
    {
      label: 'Success Rate',
      href: '/executions?since=today',
      // Honest rendering: no data → em-dash; zero runs today → "No runs today"; otherwise rounded %.
      value: !stats
        ? '—'
        : stats.today_executions === 0
          ? 'No runs today'
          : Math.round(stats.success_rate),
      suffix: stats && stats.today_executions > 0 ? '%' : '',
      change: stats ? `${stats.today_completed} completed` : '',
      changeColor: 'text-emerald-400',
      icon: TrendingUp,
      iconBg: 'bg-emerald-500/10',
      iconColor: 'text-emerald-400',
    },
    {
      label: 'Token Spend',
      href: '/analytics',
      value: stats?.today_cost ?? 0,
      prefix: '$',
      note: stats?.flat_rate_billing ? 'Claude subscription, flat rate with no per-token charge' : undefined,
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
        <PageHeader
          title="Dashboard"
          icon={LayoutDashboard}
          storageKey="dashboard"
          purpose="Your home page. See what your agents did today and what to do next. For everyone in the workspace."
          primaryAction={{ label: 'Build an agent', href: '/builder', icon: Plus, testId: 'dashboard-new-agent' }}
          secondaryAction={{ label: 'Open chat', href: '/chat', icon: MessageSquare }}
          meta={stats && stats.active_executions > 0 ? (
            <Link href="/executions?status=running" className="flex items-center gap-2 px-3 py-1 rounded-lg bg-cyan-500/10 border border-cyan-500/20">
              <RefreshCw className="w-3.5 h-3.5 text-cyan-400 animate-spin" />
              <span className="text-xs text-cyan-400 font-medium">{stats.active_executions} running</span>
            </Link>
          ) : null}
          steps={[
            'Follow Start here below. It ticks itself off as you go and only shows steps for your role.',
            'The cards show the runs, failures and spend for today. Click any of them to see the runs behind the number.',
            'Quick actions jump straight to building, uploading documents or connecting tools.',
          ]}
          docSlug="08-howto/07-finding-your-way-around"
        />
      </motion.div>

      <motion.div variants={item}>
        <StartHere />
      </motion.div>

      <motion.div variants={item} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {kpiCards.map((kpi) => (
          <Link
            key={kpi.label}
            href={kpi.href}
            data-testid={`kpi-${kpi.label.toLowerCase().replace(/\s+/g, '-')}`}
            className="block bg-slate-800/30 border border-cyan-500/20 rounded-xl p-5 hover:border-cyan-500/40 transition-colors"
          >
            <div className="flex items-start justify-between mb-3">
              <div className={`w-10 h-10 rounded-lg ${kpi.iconBg} flex items-center justify-center`}>
                <kpi.icon className={`w-5 h-5 ${kpi.iconColor}`} />
              </div>
              <span className={`text-xs ${kpi.changeColor}`}>{kpi.change}</span>
            </div>
            <p className="text-2xl font-bold text-white">
              {typeof kpi.value === 'number' ? (
                <CountUp target={kpi.value} prefix={kpi.prefix} suffix={kpi.suffix} />
              ) : (
                <span>{kpi.prefix ?? ''}{kpi.value}{kpi.suffix ?? ''}</span>
              )}
            </p>
            <p className="text-xs text-slate-500 mt-1">{kpi.label}</p>
            {kpi.note && <p className="text-[11px] text-violet-300/80 mt-1" data-testid="kpi-cost-note">{kpi.note}</p>}
          </Link>
        ))}
        {/* User token usage card */}
        <div className="bg-slate-800/30 border border-cyan-500/20 rounded-xl p-4" data-testid="kpi-your-usage">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-slate-500 uppercase">Your Token Usage this month</span>
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
                {!userQuota.token_allowance && ' · no limit set'}
                {stats?.flat_rate_billing && <span className="text-violet-300/80" data-testid="your-usage-subscription"> · Claude subscription</span>}
              </p>
            </>
          ) : quotaFailed ? (
            <p className="text-sm text-slate-500">Usage not available</p>
          ) : (
            <div className="h-6 w-20 bg-slate-800 animate-pulse rounded" aria-label="Loading usage" />
          )}
        </div>
      </motion.div>

      <div className="grid lg:grid-cols-3 gap-6">
        <motion.div variants={item} className="lg:col-span-2 bg-slate-800/30 border border-cyan-500/20 rounded-xl overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-cyan-500/20">
            <h2 className="text-sm font-semibold text-white">Live Activity</h2>
            <a href="/executions" className="text-xs text-cyan-400 hover:text-cyan-300 flex items-center gap-1 transition-colors">
              View all <ArrowRight className="w-3 h-3" />
            </a>
          </div>
          <div className="p-5 grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Link href="/executions?status=running" data-testid="live-active-now" className="block bg-slate-900/50 rounded-lg p-4 border border-cyan-500/20 hover:border-cyan-500/40 transition-colors">
              <p className="text-xs text-slate-500 mb-1">Active Now</p>
              <p className="text-xl font-bold text-cyan-400">
                {stats?.active_executions ?? 0}
              </p>
            </Link>
            <Link href="/executions?since=today&status=completed" data-testid="live-completed-today" className="block bg-slate-900/50 rounded-lg p-4 border border-cyan-500/20 hover:border-cyan-500/40 transition-colors">
              <p className="text-xs text-slate-500 mb-1">Completed Today</p>
              <p className="text-xl font-bold text-emerald-400">
                {stats?.today_completed ?? 0}
              </p>
            </Link>
            <Link href="/executions?since=today&status=failed" data-testid="live-failed-today" className="block bg-slate-900/50 rounded-lg p-4 border border-cyan-500/20 hover:border-cyan-500/40 transition-colors">
              <p className="text-xs text-slate-500 mb-1">Failed Today</p>
              <p className="text-xl font-bold text-red-400">
                {stats?.today_failed ?? 0}
              </p>
            </Link>
          </div>
        </motion.div>

        <div className="space-y-6">
          <motion.div variants={item} className="bg-slate-800/30 border border-cyan-500/20 rounded-xl p-5">
            <h2 className="text-sm font-semibold text-white mb-4">Quick Actions</h2>
            <div className="grid grid-cols-2 gap-3">
              {QUICK_ACTIONS.map((action) => (
                <a
                  key={action.label}
                  href={action.href}
                  className="flex flex-col items-center gap-2 p-3 rounded-lg bg-slate-800/50 border border-cyan-500/20 hover:border-cyan-500/40 transition-colors group"
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

          <motion.div variants={item} className="bg-slate-800/30 border border-cyan-500/20 rounded-xl p-5">
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
