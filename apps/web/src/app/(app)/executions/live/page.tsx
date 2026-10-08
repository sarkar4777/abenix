'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { motion } from 'framer-motion';
import Link from 'next/link';
import {
  Activity, Radio, Cpu, Clock, DollarSign, Hash,
  Wrench, CheckCircle2, XCircle, Loader2, RefreshCw,
  ChevronRight, Zap, Play,
} from 'lucide-react';
import { usePageTitle } from '@/hooks/usePageTitle';
import { CostValue } from '@/components/shared/CostValue';
import PageHeader from '@/components/layout/PageHeader';
import { failureLabel } from '@/lib/monitor-format';
import { startedByText } from '@/lib/run-origin';

// runs that ended this long ago still show, so a run shorter than one poll is not missed
const RECENT_SECONDS = 120;

interface RecentRun {
  execution_id: string;
  agent_id: string;
  agent_name?: string | null;
  status: string;
  duration_ms?: number | null;
  completed_at?: string | null;
  failure_code?: string | null;
  trigger_kind?: string | null;
  trigger_name?: string | null;
  trigger_id?: string | null;
}

function RecentRunRow({ run }: { run: RecentRun }) {
  const ok = run.status === 'completed';
  const ago = run.completed_at ? Math.max(0, Math.round((Date.now() - new Date(run.completed_at).getTime()) / 1000)) : null;
  return (
    <li data-testid="live-recent-run" data-agent-id={run.agent_id} data-kind={run.trigger_kind || 'unknown'} data-status={run.status}>
      <Link
        href={`/executions/${run.execution_id}`}
        className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 rounded-lg hover:bg-slate-800/40 text-xs"
      >
        {ok ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" /> : <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0" />}
        <span className="text-slate-200 font-medium min-w-0 break-words">{run.agent_name || 'Agent'}</span>
        <span className={ok ? 'text-emerald-300' : 'text-red-300'}>
          {ok ? 'completed' : run.failure_code ? failureLabel(run.failure_code) : run.status}
        </span>
        {typeof run.duration_ms === 'number' && (
          <span className="text-slate-500">{run.duration_ms >= 1000 ? `${(run.duration_ms / 1000).toFixed(1)}s` : `${run.duration_ms}ms`}</span>
        )}
        <span className="text-slate-500">Started by {startedByText(run)}</span>
        {ago != null && <span className="text-slate-600 sm:ml-auto">{ago < 60 ? `${ago}s ago` : `${Math.round(ago / 60)} min ago`}</span>}
      </Link>
    </li>
  );
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface LiveExecution {
  execution_id: string;
  agent_id: string;
  agent_name?: string;
  tenant_id: string;
  status: string;
  current_step?: string;
  current_tool?: string;
  iteration?: number;
  max_iterations?: number;
  input_tokens?: number;
  output_tokens?: number;
  cost?: number;
  started_at?: string;
  duration_ms?: number;
  tool_calls?: Array<{ name: string; status: string; duration_ms?: number }>;
  node_statuses?: Record<string, string>;
  metadata?: Record<string, unknown>;
}

function LiveExecutionCard({ exec }: { exec: LiveExecution }) {
  const elapsed = exec.started_at
    ? Math.round((Date.now() - new Date(exec.started_at).getTime()) / 1000)
    : 0;
  const progress = exec.max_iterations
    ? Math.min(100, ((exec.iteration || 0) / exec.max_iterations) * 100)
    : 0;

  return (
    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 hover:border-cyan-500/30 transition-colors" data-testid="live-running-run" data-agent-id={exec.agent_id}>
      <div className="flex items-start gap-3">
        {/* Pulsing indicator */}
        <div className="relative mt-1 shrink-0">
          <div className="w-3 h-3 rounded-full bg-cyan-500 animate-pulse" />
          <div className="absolute inset-0 w-3 h-3 rounded-full bg-cyan-500/50 animate-ping" />
        </div>

        <div className="flex-1 min-w-0">
          {/* Header */}
          <div className="flex items-center gap-2 mb-2">
            <span className="text-sm font-semibold text-white truncate">
              {exec.agent_name || 'Agent'}
            </span>
            <span className="text-[10px] bg-cyan-500/10 text-cyan-400 px-2 py-0.5 rounded-full font-medium">
              RUNNING
            </span>
            <span className="text-[10px] text-slate-500 font-mono">
              {exec.execution_id.slice(0, 8)}
            </span>
          </div>

          {/* Current step */}
          {exec.current_tool && (
            <div className="flex items-center gap-2 mb-2 px-3 py-1.5 bg-slate-900/50 border border-slate-700/30 rounded-lg">
              <Wrench className="w-3.5 h-3.5 text-cyan-400 animate-spin" style={{ animationDuration: '3s' }} />
              <span className="text-xs text-cyan-300">
                Calling <span className="font-mono font-medium">{exec.current_tool}</span>
              </span>
            </div>
          )}

          {/* Progress bar */}
          {exec.max_iterations && (
            <div className="mb-2">
              <div className="flex items-center justify-between text-[10px] text-slate-500 mb-1">
                <span>Iteration {exec.iteration || 0} / {exec.max_iterations}</span>
                <span>{Math.round(progress)}%</span>
              </div>
              <div className="w-full h-1.5 bg-slate-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-cyan-500 to-purple-500 rounded-full transition-all duration-500"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          )}

          {/* Pipeline node statuses */}
          {exec.node_statuses && Object.keys(exec.node_statuses).length > 0 && (
            <div className="mb-2">
              <div className="text-[10px] text-slate-500 mb-1 flex items-center gap-1">
                <Cpu className="w-3 h-3" />
                Pipeline Nodes
              </div>
              <div className="flex flex-wrap gap-1">
                {Object.entries(exec.node_statuses).map(([nodeId, status]) => (
                  <span
                    key={nodeId}
                    className={`inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded font-mono ${
                      status === 'completed'
                        ? 'bg-emerald-500/10 text-emerald-400'
                        : status === 'running'
                          ? 'bg-cyan-500/10 text-cyan-400'
                          : status === 'failed'
                            ? 'bg-red-500/10 text-red-400'
                            : status === 'skipped'
                              ? 'bg-slate-500/10 text-slate-500'
                              : 'bg-slate-700/30 text-slate-500'
                    }`}
                  >
                    {status === 'completed' ? (
                      <CheckCircle2 className="w-2.5 h-2.5" />
                    ) : status === 'running' ? (
                      <Loader2 className="w-2.5 h-2.5 animate-spin" />
                    ) : status === 'failed' ? (
                      <XCircle className="w-2.5 h-2.5" />
                    ) : (
                      <Clock className="w-2.5 h-2.5" />
                    )}
                    {nodeId}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Stats row */}
          <div className="flex items-center gap-4 text-[10px] text-slate-500">
            <span className="flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {elapsed}s
            </span>
            {(exec.input_tokens || exec.output_tokens) && (
              <span className="flex items-center gap-1">
                <Hash className="w-3 h-3" />
                {((exec.input_tokens || 0) + (exec.output_tokens || 0)).toLocaleString()} tokens
              </span>
            )}
            {exec.cost !== undefined && exec.cost > 0 && (
              <span className="flex items-center gap-1">
                <DollarSign className="w-3 h-3" />
                <CostValue cost={exec.cost} />
              </span>
            )}
            {exec.iteration !== undefined && (
              <span className="flex items-center gap-1">
                <RefreshCw className="w-3 h-3" />
                {exec.iteration} iterations
              </span>
            )}
          </div>

          {/* Tool call history */}
          {exec.tool_calls && exec.tool_calls.length > 0 && (
            <div className="mt-2 pt-2 border-t border-slate-700/30">
              <div className="flex flex-wrap gap-1">
                {exec.tool_calls.map((tc, i) => (
                  <span
                    key={i}
                    className={`inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded ${
                      tc.status === 'completed'
                        ? 'bg-emerald-500/10 text-emerald-400'
                        : tc.status === 'running'
                          ? 'bg-cyan-500/10 text-cyan-400'
                          : 'bg-red-500/10 text-red-400'
                    }`}
                  >
                    {tc.status === 'completed' ? (
                      <CheckCircle2 className="w-2.5 h-2.5" />
                    ) : tc.status === 'running' ? (
                      <Loader2 className="w-2.5 h-2.5 animate-spin" />
                    ) : (
                      <XCircle className="w-2.5 h-2.5" />
                    )}
                    {tc.name}
                    {tc.duration_ms ? ` (${tc.duration_ms}ms)` : ''}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Link to flight recorder */}
        <Link
          href={`/executions/${exec.execution_id}`}
          className="p-2 text-slate-500 hover:text-cyan-400 hover:bg-cyan-500/10 rounded-lg transition-colors shrink-0"
          title="Open Flight Recorder"
        >
          <ChevronRight className="w-4 h-4" />
        </Link>
      </div>
    </div>
  );
}

export default function LiveDebugPage() {
  usePageTitle('Live Executions');
  const [executions, setExecutions] = useState<LiveExecution[]>([]);
  const [recent, setRecent] = useState<RecentRun[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeout = useRef<ReturnType<typeof setTimeout>>();

  const connect = useCallback(() => {
    const token = localStorage.getItem('access_token');
    if (!token) {
      setError('Not authenticated');
      return;
    }

    // SSE doesn't support auth headers natively, fall back to polling
    const poll = async () => {
      try {
        const res = await fetch(`${API_URL}/api/executions/live?recent_seconds=${RECENT_SECONDS}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) {
          setConnected(false);
          setError(res.status === 401 ? 'Your session has ended. Sign in again to keep watching.' : `The live feed is not answering (HTTP ${res.status}). Retrying every 2 seconds.`);
          return;
        }
        const json = await res.json();
        if (json.data) {
          const running: LiveExecution[] = Array.isArray(json.data) ? json.data : [];
          setExecutions(running);
          const ids = new Set(running.map((r) => r.execution_id));
          const ended: RecentRun[] = Array.isArray(json.meta?.recent) ? json.meta.recent : [];
          setRecent(ended.filter((r) => !ids.has(r.execution_id)));
          setConnected(true);
          setError(null);
        }
      } catch (err) {
        setError('Cannot reach the server. Retrying every 2 seconds.');
        setConnected(false);
      }
    };

    poll();
    const interval = setInterval(poll, 2000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const cleanup = connect();
    return () => {
      cleanup?.();
      if (reconnectTimeout.current) clearTimeout(reconnectTimeout.current);
      eventSourceRef.current?.close();
    };
  }, [connect]);

  const runningCount = executions.length;

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.3 }}>
      <PageHeader
        className="mb-6"
        title="Live Debug"
        purpose="Watch agent and pipeline runs while they happen, step by step. For anyone testing an agent or checking a trigger fired."
        icon={Radio}
        storageKey="executions-live"
        docSlug="02-runtime/04-streaming-tracing"
        meta={
          <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
            connected
              ? runningCount > 0
                ? 'bg-cyan-500/10 text-cyan-400'
                : 'bg-emerald-500/10 text-emerald-400'
              : 'bg-red-500/10 text-red-400'
          }`}>
            <Radio className={`w-3 h-3 ${connected ? 'animate-pulse' : ''}`} />
            {connected ? (runningCount > 0 ? 'Tracking' : 'Listening') : 'Disconnected'}
          </div>
        }
        primaryAction={{ label: 'Run an agent', href: '/agents', icon: Play }}
        secondaryAction={{ label: 'View History', href: '/executions' }}
        extraActions={
          <div className="flex items-center justify-center gap-2 px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg">
            <Activity className="w-4 h-4 text-cyan-400" />
            <span className="text-sm font-mono text-white">{runningCount}</span>
            <span className="text-xs text-slate-500">running</span>
          </div>
        }
        steps={[
          'Start a run from chat, a trigger or a pipeline. It shows up here within two seconds.',
          'Each card shows the current step, the tool in use, tokens and cost so far.',
          'Runs that just ended stay under Just finished for two minutes. Click one to open its full record.',
        ]}
      />

      {/* Error state */}
      {error && (
        <div role="alert" className="bg-red-500/10 border border-red-500/20 text-red-400 text-sm rounded-xl px-4 py-3 mb-4">
          {error}
        </div>
      )}

      {/* Live executions */}
      <div className="space-y-3">
        {runningCount === 0 && (
          <div className="text-center py-20 bg-slate-800/20 border border-slate-700/30 rounded-xl">
            <div className="w-16 h-16 rounded-2xl bg-slate-800/50 flex items-center justify-center mx-auto mb-4">
              <Zap className="w-8 h-8 text-slate-600" />
            </div>
            <h3 className="text-lg font-semibold text-white mb-1">No active executions</h3>
            <p className="text-sm text-slate-500 max-w-md mx-auto">
              When you run an agent or pipeline, its progress will appear here in real-time.
              Try executing an agent from the chat page or triggering a pipeline.
            </p>
            <div className="flex justify-center gap-3 mt-4">
              <Link
                href="/agents"
                className="px-4 py-2 text-sm text-cyan-400 bg-cyan-500/10 rounded-lg hover:bg-cyan-500/20 transition-colors"
              >
                Go to Agents
              </Link>
              <Link
                href="/executions"
                className="px-4 py-2 text-sm text-slate-400 bg-slate-800/50 rounded-lg hover:bg-slate-800 transition-colors"
              >
                View Past Executions
              </Link>
            </div>
          </div>
        )}

        {executions.map((exec) => (
          <LiveExecutionCard key={exec.execution_id} exec={exec} />
        ))}
      </div>

      {recent.length > 0 && (
        <section className="mt-6 bg-slate-800/20 border border-slate-700/30 rounded-xl p-3" data-testid="live-recent">
          <h2 className="text-xs font-semibold text-slate-300 px-3 pt-1 pb-2">
            Just finished <span className="font-normal text-slate-500">in the last {RECENT_SECONDS / 60} minutes</span>
          </h2>
          <ul className="space-y-0.5">
            {recent.map((r) => <RecentRunRow key={r.execution_id} run={r} />)}
          </ul>
        </section>
      )}

      {/* Auto-refresh indicator */}
      {connected && (
        <div className="flex items-center justify-center gap-2 mt-6 text-[10px] text-slate-600">
          <RefreshCw className="w-3 h-3 animate-spin" style={{ animationDuration: '2s' }} />
          Auto-refreshing every 2 seconds
        </div>
      )}
    </motion.div>
  );
}
