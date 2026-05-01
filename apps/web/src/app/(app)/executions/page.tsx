'use client';

import { useState } from 'react';
import { motion } from 'framer-motion';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import {
  Activity,
  ChevronDown,
  ChevronUp,
  Clock,
  CheckCircle2,
  XCircle,
  Loader2,
  Search,
  Shield,
  Trash2,
} from 'lucide-react';

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
  tool_calls?: Array<{ name: string; arguments: Record<string, unknown> }>;
  confidence_score?: number;
  execution_trace?: Record<string, unknown>;
  error_message?: string;
  failure_code?: string;
  created_at: string;
  completed_at?: string;
}

function ConfidenceBadge({ score }: { score: number | null | undefined }) {
  if (score == null) return <span className="text-xs text-slate-600">--</span>;
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
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border border-slate-700/50 rounded-lg overflow-hidden">
      <div className="flex items-center">
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex-1 flex items-center gap-3 p-3 hover:bg-slate-800/30 transition-colors text-left min-w-0"
        >
          <StatusIcon status={exec.status} />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <p className="text-sm text-white truncate">{exec.agent_name || exec.agent_id.slice(0, 8)}</p>
              {exec.failure_code && (
                <span
                  data-testid={`execution-failure-code-${exec.failure_code}`}
                  className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-red-500/10 text-red-300 ring-1 ring-red-500/30"
                  title={exec.error_message || exec.failure_code}
                >
                  {exec.failure_code}
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500 truncate">{exec.input_message?.slice(0, 80)}</p>
          </div>
          <div className="hidden sm:flex items-center gap-4 text-xs text-slate-400">
            {exec.duration_ms != null && <span>{(exec.duration_ms / 1000).toFixed(1)}s</span>}
            {exec.cost != null && <span>${exec.cost.toFixed(4)}</span>}
            {(exec.input_tokens || 0) + (exec.output_tokens || 0) > 0 && (
              <span>{((exec.input_tokens || 0) + (exec.output_tokens || 0)).toLocaleString()} tok</span>
            )}
            <ConfidenceBadge score={exec.confidence_score} />
          </div>
          <span className="text-xs text-slate-600">{new Date(exec.created_at).toLocaleString()}</span>
          {expanded ? <ChevronUp className="w-4 h-4 text-slate-500" /> : <ChevronDown className="w-4 h-4 text-slate-500" />}
        </button>
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

      {expanded && (
        <div className="border-t border-slate-700/50 p-4 bg-slate-900/40 space-y-3">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div><span className="text-slate-500">Status</span><br /><span className="text-white">{exec.status}</span></div>
            <div><span className="text-slate-500">Model</span><br /><span className="text-white">{exec.model_used || '--'}</span></div>
            <div><span className="text-slate-500">Duration</span><br /><span className="text-white">{exec.duration_ms ? `${exec.duration_ms}ms` : '--'}</span></div>
            <div><span className="text-slate-500">Confidence</span><br /><ConfidenceBadge score={exec.confidence_score} /></div>
          </div>

          {exec.input_message && (
            <div>
              <p className="text-xs font-medium text-slate-400 mb-1">Input</p>
              <p className="text-xs text-slate-300 bg-slate-800/50 rounded p-2 max-h-24 overflow-y-auto">{exec.input_message}</p>
            </div>
          )}

          {exec.output_message && (
            <div>
              <p className="text-xs font-medium text-slate-400 mb-1">Output</p>
              <p className="text-xs text-slate-300 bg-slate-800/50 rounded p-2 max-h-40 overflow-y-auto whitespace-pre-wrap">{exec.output_message.slice(0, 2000)}</p>
            </div>
          )}

          {exec.tool_calls && exec.tool_calls.length > 0 && (
            <div>
              <p className="text-xs font-medium text-slate-400 mb-1">Tool Calls ({exec.tool_calls.length})</p>
              <div className="flex flex-wrap gap-1">
                {exec.tool_calls.map((tc, i) => (
                  <span key={i} className="text-[10px] px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                    {tc.name}
                  </span>
                ))}
              </div>
            </div>
          )}

          {exec.error_message && (
            <div>
              <p className="text-xs font-medium text-red-400 mb-1">Error</p>
              <p className="text-xs text-red-300 bg-red-500/10 rounded p-2">{exec.error_message}</p>
            </div>
          )}
          <a href={`/executions/${exec.id}`} className="inline-flex items-center gap-1 text-xs text-cyan-400 hover:text-cyan-300 mt-2">
            Open Flight Recorder &rarr;
          </a>
        </div>
      )}
    </div>
  );
}

export default function ExecutionsPage() {
  usePageTitle('Executions');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [sortBy, setSortBy] = useState('newest');
  const [page, setPage] = useState(0);
  const LIMIT = 20;

  const apiUrl = `/api/executions?search=${encodeURIComponent(search)}&status=${statusFilter}&sort=${sortBy}&limit=${LIMIT}&offset=${page * LIMIT}`;
  const { data: executions, meta, isLoading, mutate } = useApi<ExecutionRecord[]>(apiUrl);
  const { data: approvals } = useApi<Array<{ execution_id: string; gate_id: string; action: string; details: string; risk_level: string }>>('/api/executions/approvals');

  const total = (meta?.total as number) || (executions || []).length;

  const stats = {
    total,
    completed: (meta?.completed as number) ?? (executions || []).filter((e) => e.status?.toLowerCase() === 'completed').length,
    failed: (meta?.failed as number) ?? (executions || []).filter((e) => e.status?.toLowerCase() === 'failed').length,
    avgConfidence: (executions || []).filter((e) => e.confidence_score != null).reduce((acc, e) => acc + (e.confidence_score || 0), 0) / Math.max(1, (executions || []).filter((e) => e.confidence_score != null).length),
  };

  if (isLoading) {
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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Activity className="w-5 h-5 text-cyan-400" />
            Execution History
          </h1>
          <p className="text-sm text-slate-400 mt-1">View past agent executions, tool calls, and confidence scores</p>
        </div>
      </div>

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
          <p className="text-2xl font-bold text-cyan-400">{stats.avgConfidence ? `${Math.round(stats.avgConfidence * 100)}%` : '--'}</p>
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
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(0); }}
            className="w-full pl-9 pr-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-slate-200 focus:border-cyan-500 focus:outline-none"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(0); }}
          className="px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-slate-200 focus:border-cyan-500 focus:outline-none"
        >
          <option value="">All Status</option>
          <option value="COMPLETED">Completed</option>
          <option value="FAILED">Failed</option>
          <option value="RUNNING">Running</option>
        </select>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
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
      <div className="space-y-2">
        {(executions || []).length === 0 ? (
          <div className="text-center py-12 text-slate-500">
            <Shield className="w-10 h-10 mx-auto mb-3 text-slate-700" />
            <p className="text-sm">No executions found</p>
            <p className="text-xs mt-1">Execute an agent to see results here</p>
          </div>
        ) : (
          (executions || []).map((exec) => (
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
      {(executions || []).length > 0 && (
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
