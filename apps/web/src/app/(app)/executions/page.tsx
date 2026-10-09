'use client';

import { Suspense, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { motion } from 'framer-motion';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { failureLabel } from '@/lib/monitor-format';
import { ORIGIN_FILTERS, matchesFilters, startedByText } from '@/lib/run-origin';
import { CostValue } from '@/components/shared/CostValue';
import PageHeader from '@/components/layout/PageHeader';
import {
  Activity,
  ChevronDown,
  Clock,
  CheckCircle2,
  XCircle,
  Loader2,
  Play,
  Radio,
  Search,
  Shield,
  Trash2,
} from 'lucide-react';
import { readableInput } from '@/lib/readable-input';

interface ExecutionRecord {
  id: string;
  agent_id: string;
  agent_name?: string;
  status: string;
  input_message: string;
  output_message?: string;
  input_tokens?: number;
  output_tokens?: number;
  cost?: number;
  duration_ms?: number;
  model_used?: string;
  model_requested?: string;
  actual_model?: string;
  fallback_reason?: string;
  tool_calls?: Array<{ name: string; arguments: Record<string, unknown> }>;
  confidence_score?: number;
  execution_trace?: Record<string, unknown>;
  error_message?: string;
  failure_code?: string;
  created_at: string;
  completed_at?: string;
  trigger_id?: string | null;
  trigger_kind?: string | null;
  trigger_name?: string | null;
  parent_execution_id?: string | null;
}


function ConfidenceBadge({ score }: { score: number | null | undefined }) {
  if (score == null) return null;
  const pct = Math.round(score * 100);
  const color =
    score >= 0.7 ? 'text-emerald-400 bg-emerald-500/10' :
    score >= 0.5 ? 'text-amber-400 bg-amber-500/10' :
    'text-red-400 bg-red-500/10';
  return (
    <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${color}`}>
      {pct}%
    </span>
  );
}

function StatusIcon({ status }: { status: string }) {
  switch (status?.toLowerCase()) {
    case 'completed':
      return <CheckCircle2 className="w-4 h-4 text-emerald-400" />;
    case 'failed':
      return <XCircle className="w-4 h-4 text-red-400" />;
    case 'running':
      return <Loader2 className="w-4 h-4 text-cyan-400 animate-spin" />;
    default:
      return <Clock className="w-4 h-4 text-slate-500" />;
  }
}

function ExecutionRow({ exec, onDelete }: { exec: ExecutionRecord; onDelete: () => void }) {
  return (
    <div className="border border-slate-700/50 rounded-lg overflow-hidden" data-testid="execution-row" data-status={exec.status?.toLowerCase()}>
      <div className="flex items-center">
        <Link
          href={`/executions/${exec.id}`}
          className="flex-1 flex items-center gap-3 p-3 hover:bg-slate-800/30 transition-colors text-left min-w-0"
        >
          <StatusIcon status={exec.status} />
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <p className="text-sm text-white truncate max-w-full">{exec.agent_name || exec.agent_id.slice(0, 8)}</p>
              {exec.failure_code && (
                <span
                  data-testid={`execution-failure-code-${exec.failure_code}`}
                  className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-red-500/10 text-red-300 ring-1 ring-red-500/30"
                  title={exec.error_message || failureLabel(exec.failure_code)}
                >
                  {failureLabel(exec.failure_code)}
                </span>
              )}
              {exec.fallback_reason && (exec.actual_model || exec.model_used) && exec.model_requested && (exec.actual_model || exec.model_used) !== exec.model_requested && (
                <span
                  data-testid={`execution-fallback-dot-${exec.id}`}
                  className="inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 ring-1 ring-amber-500/30"
                  title={`Ran on ${exec.actual_model || exec.model_used}; fallback from ${exec.model_requested}: ${exec.fallback_reason.replace(/_/g, ' ')}`}
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                  fallback
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500 truncate">{readableInput(exec.input_message).slice(0, 80)}</p>
            <p className="text-[11px] text-slate-400 truncate mt-0.5" data-testid="execution-started-by" data-kind={exec.trigger_kind || 'unknown'}>
              <span className="text-slate-500">Started by </span>
              <span className={exec.trigger_kind ? 'text-slate-300' : 'text-slate-500'}>{startedByText(exec)}</span>
            </p>
            <p className="sm:hidden text-[11px] text-slate-600 mt-0.5">{new Date(exec.created_at).toLocaleString()}</p>
          </div>
          <div className="hidden sm:flex items-center gap-4 text-xs text-slate-400">
            {exec.duration_ms != null && <span>{(exec.duration_ms / 1000).toFixed(1)}s</span>}
            {exec.cost != null && <CostValue cost={exec.cost} testId="execution-cost" />}
            {(exec.input_tokens || 0) + (exec.output_tokens || 0) > 0 && (
              <span>{((exec.input_tokens || 0) + (exec.output_tokens || 0)).toLocaleString()} tok</span>
            )}
            <ConfidenceBadge score={exec.confidence_score} />
          </div>
          <span className="hidden sm:inline text-xs text-slate-600 shrink-0">{new Date(exec.created_at).toLocaleString()}</span>
          <ChevronDown className="w-4 h-4 text-slate-500 -rotate-90" />
        </Link>
        <button
          onClick={() => {
            if (confirm('Delete this execution?')) {
              onDelete();
            }
          }}
          className="p-1 mr-2 rounded text-slate-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"
          aria-label="Delete execution"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}

export default function ExecutionsPage() {
  return (
    <Suspense fallback={<div className="p-6"><div className="h-8 w-48 bg-slate-800 animate-pulse rounded" /></div>}>
      <ExecutionsView />
    </Suspense>
  );
}

function ExecutionsView() {
  usePageTitle('Executions');
  const params = useSearchParams();
  const router = useRouter();
  const since = params.get('since') === 'today' ? 'today' : '';
  const agentParam = params.get('agent') || '';
  const triggerParam = params.get('trigger') || '';
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState((params.get('status') || '').toLowerCase());
  const [originFilter, setOriginFilter] = useState(params.get('started_by') || '');
  const [sortBy, setSortBy] = useState('newest');
  const [page, setPage] = useState(0);
  const LIMIT = 20;

  const apiUrl = `/api/executions?search=${encodeURIComponent(search)}&status=${statusFilter}&sort=${sortBy}&limit=${LIMIT}&offset=${page * LIMIT}${since ? `&since=${since}` : ''}${agentParam ? `&agent_id=${encodeURIComponent(agentParam)}` : ''}${originFilter ? `&trigger_kind=${encodeURIComponent(originFilter)}` : ''}${triggerParam ? `&trigger_id=${encodeURIComponent(triggerParam)}` : ''}`;
  // keep the last page on screen while a filter loads, so the search box keeps focus
  const { data: executions, meta, isLoading, error, mutate } = useApi<ExecutionRecord[]>(apiUrl, { keepPreviousData: true });
  // while the next page loads, the last one stays up but only rows that fit the new filters show
  const stale = isLoading && !!executions;
  const shown = stale
    ? (executions || []).filter((e) => matchesFilters(e, { status: statusFilter, search, origin: originFilter, triggerId: triggerParam }))
    : executions || [];
  const triggerName = (executions || []).find((e) => e.trigger_id === triggerParam)?.trigger_name;
  const clearParam = (key: string) => {
    const q = new URLSearchParams(params.toString());
    q.delete(key);
    const rest = q.toString();
    router.replace(rest ? `/executions?${rest}` : '/executions');
    setPage(0);
  };
  const { data: approvals } = useApi<Array<{ execution_id: string; gate_id: string; action: string; details: string; risk_level: string }>>('/api/executions/approvals');

  const total = (meta?.total as number) || (executions || []).length;

  const stats = {
    // every run in scope, the status filter only narrows the list below
    total: (meta?.all as number) ?? total,
    completed: (meta?.completed as number) ?? (executions || []).filter((e) => e.status?.toLowerCase() === 'completed').length,
    failed: (meta?.failed as number) ?? (executions || []).filter((e) => e.status?.toLowerCase() === 'failed').length,
    avgConfidence: (executions || []).filter((e) => e.confidence_score != null).reduce((acc, e) => acc + (e.confidence_score || 0), 0) / Math.max(1, (executions || []).filter((e) => e.confidence_score != null).length),
  };

  if (isLoading && !executions && !error) {
    return (
      <div className="p-6 space-y-4">
        <div className="h-8 w-48 bg-slate-800 animate-pulse rounded" />
        <div className="grid grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => <div key={i} className="h-20 bg-slate-800 animate-pulse rounded-lg" />)}
        </div>
        {[...Array(6)].map((_, i) => <div key={i} className="h-16 bg-slate-800 animate-pulse rounded-lg" />)}
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="p-6 space-y-6 max-w-6xl"
    >
      <PageHeader
        title="Execution History"
        purpose="Every run of your agents in one list, with what started it, what it cost and how it ended. For anyone checking or debugging agents."
        icon={Activity}
        storageKey="executions"
        docSlug="02-runtime/04-streaming-tracing"
        primaryAction={{ label: 'Run an agent', href: '/agents', icon: Play }}
        secondaryAction={{ label: 'Watch live', href: '/executions/live', icon: Radio }}
        steps={[
          'Each row is one run. Open it to see the input, the answer, every tool call and the cost.',
          'Filter by status, by what started the run, or by text in the input.',
          'Failed runs show a short reason so you can spot the cause without opening them.',
        ]}
      />

      {/* KPI Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="bg-slate-800/30 backdrop-blur-xl border border-slate-700/50 rounded-lg p-4">
          <p className="text-xs text-slate-400">Total</p>
          <p className="text-2xl font-bold text-white">{stats.total}</p>
        </div>
        <div className="bg-slate-800/30 backdrop-blur-xl border border-slate-700/50 rounded-lg p-4">
          <p className="text-xs text-slate-400">Completed</p>
          <p className="text-2xl font-bold text-emerald-400">{stats.completed}</p>
        </div>
        <div className="bg-slate-800/30 backdrop-blur-xl border border-slate-700/50 rounded-lg p-4">
          <p className="text-xs text-slate-400">Failed</p>
          <p className="text-2xl font-bold text-red-400">{stats.failed}</p>
        </div>
        <div className="bg-slate-800/30 backdrop-blur-xl border border-slate-700/50 rounded-lg p-4">
          <p className="text-xs text-slate-400">Avg Confidence</p>
          {stats.avgConfidence ? (
            <p className="text-2xl font-bold text-cyan-400">{Math.round(stats.avgConfidence * 100)}%</p>
          ) : (
            <p className="text-sm text-slate-500 mt-2" data-testid="executions-no-confidence">No scored runs on this page</p>
          )}
        </div>
      </div>

      {/* Pending HITL Approvals */}
      {approvals && approvals.length > 0 && (
        <div className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-4">
          <h3 className="text-sm font-semibold text-amber-400 mb-3">Pending Approvals ({approvals.length})</h3>
          <div className="space-y-2">
            {approvals.map((a) => (
              <div key={a.gate_id} className="flex items-center justify-between bg-slate-800/50 rounded-lg p-3">
                <div>
                  <p className="text-sm text-white">{a.action}</p>
                  <p className="text-xs text-slate-400">{a.details} &middot; Risk: <span className={a.risk_level === 'critical' ? 'text-red-400' : a.risk_level === 'high' ? 'text-amber-400' : 'text-slate-400'}>{a.risk_level}</span></p>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={async () => {
                      const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
                      const token = localStorage.getItem('access_token');
                      await fetch(`${API_URL}/api/executions/${a.execution_id}/approve?gate_id=${a.gate_id}`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
                        body: JSON.stringify({ decision: 'approved', comment: '' }),
                      });
                      window.location.reload();
                    }}
                    className="px-3 py-1 text-xs bg-emerald-500/20 text-emerald-400 rounded hover:bg-emerald-500/30"
                  >Approve</button>
                  <button
                    onClick={async () => {
                      const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
                      const token = localStorage.getItem('access_token');
                      await fetch(`${API_URL}/api/executions/${a.execution_id}/approve?gate_id=${a.gate_id}`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
                        body: JSON.stringify({ decision: 'rejected', comment: '' }),
                      });
                      window.location.reload();
                    }}
                    className="px-3 py-1 text-xs bg-red-500/20 text-red-400 rounded hover:bg-red-500/30"
                  >Reject</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-3 items-center flex-wrap">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text"
            placeholder="Search executions..."
            aria-label="Search executions"
            data-testid="exec-search"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(0); }}
            className="w-full pl-9 pr-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-slate-200 focus:border-cyan-500 focus:outline-none"
          />
        </div>
        <select
          aria-label="Filter by status"
          data-testid="exec-status-filter"
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(0); }}
          className="px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-slate-200 focus:border-cyan-500 focus:outline-none"
        >
          <option value="">All Status</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
          <option value="running">Running</option>
          <option value="cancelled">Cancelled</option>
        </select>
        <select
          aria-label="Filter by what started the run"
          data-testid="exec-origin-filter"
          value={originFilter}
          onChange={(e) => { setOriginFilter(e.target.value); setPage(0); }}
          className="pl-3 pr-9 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-slate-200 focus:border-cyan-500 focus:outline-none"
        >
          <option value="">Started by: anything</option>
          {ORIGIN_FILTERS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        {triggerParam && (
          <button
            type="button"
            data-testid="exec-trigger-chip"
            onClick={() => clearParam('trigger')}
            className="px-3 py-2 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-xs text-cyan-300 hover:bg-cyan-500/20"
            title="Show runs from every trigger"
          >
            Only runs from {triggerName || 'this trigger'} &times;
          </button>
        )}
        {agentParam && (
          <button
            type="button"
            data-testid="exec-agent-chip"
            onClick={() => { router.replace(since ? '/executions?since=today' : '/executions'); setPage(0); }}
            className="px-3 py-2 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-xs text-cyan-300 hover:bg-cyan-500/20"
            title="Show every agent"
          >
            {(executions || [])[0]?.agent_name || 'One agent'} only &times;
          </button>
        )}
        {since && (
          <button
            type="button"
            data-testid="exec-since-chip"
            onClick={() => { router.replace(agentParam ? `/executions?agent=${agentParam}` : '/executions'); setPage(0); }}
            className="px-3 py-2 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-xs text-cyan-300 hover:bg-cyan-500/20"
            title="Show all dates"
          >
            Today only &times;
          </button>
        )}
        <select
          aria-label="Sort"
          data-testid="exec-sort"
          value={sortBy}
          onChange={(e) => { setSortBy(e.target.value); setPage(0); }}
          className="px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-slate-200 focus:border-cyan-500 focus:outline-none"
        >
          <option value="newest">Newest</option>
          <option value="oldest">Oldest</option>
          <option value="cost_high">Cost: High → Low</option>
          <option value="cost_low">Cost: Low → High</option>
          <option value="duration">Duration: Longest</option>
        </select>
      </div>

      {/* Execution List */}
      <div
        className={`space-y-2 transition-opacity ${stale ? 'opacity-60' : ''}`}
        data-testid="execution-list"
        aria-busy={stale}
      >
        {error ? (
          <div role="alert" data-testid="exec-error" className="text-center py-12 text-red-300 text-sm">
            Could not load executions. {error}
          </div>
        ) : shown.length === 0 && stale ? (
          <div className="text-center py-12 text-slate-500 text-sm" data-testid="exec-list-loading">
            <Loader2 className="w-5 h-5 mx-auto mb-2 animate-spin text-slate-600" />
            Loading runs for these filters
          </div>
        ) : shown.length === 0 ? (
          <div className="text-center py-12 text-slate-500">
            <Shield className="w-10 h-10 mx-auto mb-3 text-slate-700" />
            <p className="text-sm">No executions found</p>
            <p className="text-xs mt-1">
              {search || statusFilter || since || agentParam || originFilter || triggerParam ? 'Nothing matches these filters.' : 'Execute an agent to see results here'}
            </p>
            {(search || statusFilter || originFilter || triggerParam) && (
              <button
                type="button"
                data-testid="exec-clear-filters"
                onClick={() => {
                  setSearch('');
                  setStatusFilter('');
                  setOriginFilter('');
                  if (triggerParam) clearParam('trigger');
                  setPage(0);
                }}
                className="text-xs mt-2 text-cyan-300 hover:underline"
              >
                Clear filters
              </button>
            )}
          </div>
        ) : (
          shown.map((exec) => (
            <ExecutionRow
              key={exec.id}
              exec={exec}
              onDelete={() => {
                apiFetch(`/api/executions/${exec.id}`, { method: 'DELETE' }).then(() => mutate());
              }}
            />
          ))
        )}
      </div>

      {/* Pagination */}
      {shown.length > 0 && !stale && (
        <div className="flex items-center justify-between mt-4">
          <p className="text-xs text-slate-500">
            Showing {page * LIMIT + 1}&ndash;{Math.min((page + 1) * LIMIT, total)} of {total}
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-300 disabled:opacity-50"
            >
              Previous
            </button>
            <button
              onClick={() => setPage((p) => p + 1)}
              disabled={(page + 1) * LIMIT >= total}
              className="px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-300 disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </motion.div>
  );
}
