'use client';

import ProvenancePanel from '@/components/governance/ProvenancePanel';
import SaveAsEvalCase from '@/components/evals/SaveAsEvalCase';
import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useApi } from '@/hooks/useApi';
import {
  Activity,
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  Clock,
  CheckCircle2,
  XCircle,
  Loader2,
  Cpu,
  DollarSign,
  Zap,
  Eye,
  RotateCcw,
  Code,
  MessageSquare,
  GitBranch,
  ArrowRight,
} from 'lucide-react';
import Link from 'next/link';
import { LiveDagView } from '@/components/shared/LiveDagView';
import { FallbackBadge } from '@/components/FallbackBadge';

interface ChildExecution {
  id: string;
  agent_id: string;
  status: string;
  duration_ms?: number | null;
  created_at?: string | null;
}

interface ExecutionDetail {
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
  trace_id?: string | null;
  // a list on current rows, an object {total} on rows written before 2.5
  tool_calls?: Array<{ name: string; arguments?: Record<string, unknown>; result?: string; result_preview?: string; is_error?: boolean; duration_ms?: number; node_id?: string }> | { total?: number };
  confidence_score?: number;
  failure_code?: string | null;
  parent_execution_id?: string | null;
  // a dict keyed by node id on the wire
  node_results?: Record<string, { node_id: string; label?: string; tool_name: string; status: string; duration_ms?: number; output?: unknown; error?: string }> | Array<{ node_id: string; label?: string; tool_name: string; status: string; duration_ms?: number; output?: unknown; error?: string }>;
  execution_trace?: {
    steps?: Array<{ label?: string; node_type?: string; type?: string; tool?: string; node_id?: string; name?: string; status?: string; input?: unknown; output?: unknown; output_preview?: string; duration_ms?: number; tokens?: number; is_error?: boolean; error?: string | null }>;
    tool_calls?: Array<{ name: string; arguments: Record<string, unknown> }>;
    warnings?: string[];
    confidence_score?: number;
    pipeline_status?: string;
    execution_path?: string[];
    failed_nodes?: string[];
    skipped_nodes?: string[];
    node_results?: Record<string, { node_id: string; label?: string; tool_name: string; status: string; duration_ms?: number; output?: unknown; error?: string }> | Array<{ node_id: string; label?: string; tool_name: string; status: string; duration_ms?: number; output?: unknown; error?: string }>;
  };
  error_message?: string;
  created_at: string;
  completed_at?: string;
}

function StatusBadge({ status }: { status: string }) {
  const s = (status || '').toLowerCase();
  const styles: Record<string, string> = {
    completed: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
    failed: 'bg-red-500/10 text-red-400 border-red-500/20',
    running: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20',
  };
  return (
    <span className={`px-2 py-0.5 text-xs font-medium rounded-full border ${styles[s] || 'bg-slate-500/10 text-slate-400 border-slate-500/20'}`}>
      {s}
    </span>
  );
}

function ConfidenceRing({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color = score >= 0.7 ? '#10b981' : score >= 0.5 ? '#f59e0b' : '#ef4444';
  const circumference = 2 * Math.PI * 20;
  const offset = circumference - (score * circumference);

  return (
    <div className="relative w-14 h-14 flex items-center justify-center">
      <svg className="w-14 h-14 -rotate-90" viewBox="0 0 48 48">
        <circle cx="24" cy="24" r="20" fill="none" stroke="#1e293b" strokeWidth="3" />
        <circle cx="24" cy="24" r="20" fill="none" stroke={color} strokeWidth="3"
          strokeDasharray={circumference} strokeDashoffset={offset}
          strokeLinecap="round" className="transition-all duration-1000" />
      </svg>
      <span className="absolute text-xs font-bold" style={{ color }}>{pct}%</span>
    </div>
  );
}

function WaterfallBar({ startPct, widthPct, color, label, durationMs }: {
  startPct: number; widthPct: number; color: string; label: string; durationMs?: number;
}) {
  return (
    <div className="relative h-7 flex items-center group">
      <div
        className="absolute h-5 rounded-sm transition-all"
        style={{
          left: `${Math.max(0, startPct)}%`,
          width: `${Math.max(1, widthPct)}%`,
          backgroundColor: color,
          opacity: 0.8,
        }}
      />
      <span className="relative z-10 text-[10px] text-white ml-1 truncate pointer-events-none"
        style={{ paddingLeft: `${Math.max(0, startPct) + 1}%` }}>
        {label}
      </span>
      {durationMs != null && (
        <span className="absolute right-1 text-[9px] text-slate-500 z-10">{durationMs}ms</span>
      )}
    </div>
  );
}

function DataPanel({ title, data, isJson }: { title: string; data: unknown; isJson?: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const content = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
  const preview = (content || '').slice(0, 200);

  return (
    <div className="bg-slate-900/50 border border-slate-700/30 rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        className="w-full flex items-center justify-between px-3 py-2 text-xs text-slate-300 hover:bg-slate-800/30"
      >
        <span className="flex items-center gap-2">
          {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          <span className="font-medium text-slate-400">{title}</span>
        </span>
        {!expanded && <span className="text-[10px] text-slate-600 truncate max-w-[200px]">{preview}</span>}
      </button>
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0 }} animate={{ height: 'auto' }} exit={{ height: 0 }}
            className="overflow-hidden"
          >
            <pre className="px-3 pb-3 text-[11px] text-slate-300 font-mono max-h-60 overflow-auto whitespace-pre-wrap">
              {content || '(empty)'}
            </pre>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// Data Lineage Graph — rich visual DAG showing tool calls, arguments, results, timing

interface LineageNode {
  id: string;
  label: string;
  type: 'input' | 'tool' | 'output';
  toolName?: string;
  durationMs?: number;
  arguments?: Record<string, unknown>;
  result?: string;
  status?: string;
  stepNumber?: number;
}

interface LineageEdge {
  from: string;
  to: string;
}

function summarizeArgs(args: Record<string, unknown> | undefined): string {
  if (!args) return '';
  const entries = Object.entries(args);
  if (entries.length === 0) return '';
  return entries.slice(0, 3).map(([k, v]) => {
    const val = typeof v === 'string' ? (v.length > 40 ? v.slice(0, 37) + '...' : v)
      : Array.isArray(v) ? `[${v.length} items]`
      : typeof v === 'object' && v ? '{...}'
      : String(v);
    return `${k}: ${val}`;
  }).join(', ') + (entries.length > 3 ? ` +${entries.length - 3} more` : '');
}

function summarizeResult(result: string | undefined): string {
  if (!result) return '';
  try {
    const parsed = JSON.parse(result);
    if (typeof parsed === 'object' && parsed !== null) {
      const keys = Object.keys(parsed);
      if (keys.length <= 4) return keys.join(', ');
      return keys.slice(0, 3).join(', ') + ` +${keys.length - 3}`;
    }
    return String(parsed).slice(0, 60);
  } catch {
    return result.slice(0, 60) + (result.length > 60 ? '...' : '');
  }
}

function LineageGraph({
  toolCalls,
  inputMessage,
  outputMessage,
  executionPath,
  nodeResults,
}: {
  toolCalls: Array<{ name: string; arguments?: Record<string, unknown>; result?: string; result_preview?: string; is_error?: boolean; duration_ms?: number; node_id?: string }>;
  inputMessage: string;
  outputMessage?: string;
  executionPath?: string[];
  nodeResults?: Array<{ node_id: string; label?: string; tool_name: string; status: string; duration_ms?: number; output?: unknown; error?: string }>;
}) {
  const [selected, setSelected] = useState<string | null>(null);

  const nodes: LineageNode[] = [];
  const edges: LineageEdge[] = [];

  nodes.push({
    id: '__input__',
    label: 'User Input',
    type: 'input',
    result: inputMessage.slice(0, 300),
  });

  if (nodeResults && nodeResults.length > 0) {
    const ordered = executionPath
      ? executionPath.map((nid) => nodeResults.find((nr) => nr.node_id === nid)).filter(Boolean)
      : nodeResults;
    let prev = '__input__';
    ordered.forEach((nr, i) => {
      if (!nr) return;
      nodes.push({
        id: nr.node_id,
        label: nr.label || nr.tool_name,
        type: 'tool',
        toolName: nr.tool_name,
        durationMs: nr.duration_ms,
        status: nr.status,
        result: nr.output ? (typeof nr.output === 'string' ? nr.output : JSON.stringify(nr.output)).slice(0, 500) : nr.error ? `error: ${nr.error}` : undefined,
        stepNumber: i + 1,
      });
      edges.push({ from: prev, to: nr.node_id });
      prev = nr.node_id;
    });
  } else {
    let prev = '__input__';
    toolCalls.forEach((tc, i) => {
      const nid = `tool_${i}`;
      nodes.push({
        id: nid,
        label: tc.name,
        type: 'tool',
        toolName: tc.name,
        durationMs: tc.duration_ms,
        arguments: tc.arguments,
        result: (tc.result ?? tc.result_preview)?.slice(0, 500),
        status: tc.is_error ? 'failed' : 'completed',
        stepNumber: i + 1,
      });
      edges.push({ from: prev, to: nid });
      prev = nid;
    });
  }

  nodes.push({
    id: '__output__',
    label: 'Final Output',
    type: 'output',
    result: outputMessage?.slice(0, 300),
  });
  edges.push({ from: nodes[nodes.length - 2]?.id || '__input__', to: '__output__' });

  const selectedNode = nodes.find((n) => n.id === selected);

  const nodeColor = (n: LineageNode) => {
    if (n.type === 'input') return 'border-cyan-500/50 bg-cyan-950/50';
    if (n.type === 'output') return 'border-purple-500/50 bg-purple-950/50';
    if (n.status === 'failed') return 'border-red-500/50 bg-red-950/50';
    return 'border-emerald-500/40 bg-emerald-950/40';
  };

  const iconColor = (n: LineageNode) => {
    if (n.type === 'input') return 'text-cyan-400';
    if (n.type === 'output') return 'text-purple-400';
    if (n.status === 'failed') return 'text-red-400';
    return 'text-emerald-400';
  };

  const totalDuration = nodes.reduce((s, n) => s + (n.durationMs || 0), 0);

  return (
    <div className="bg-slate-800/30 backdrop-blur-xl border border-slate-700/50 rounded-xl p-4" data-testid="lineage-graph">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-xs font-semibold text-slate-400 uppercase flex items-center gap-2">
          <GitBranch className="w-3.5 h-3.5 text-purple-400" />
          Data Lineage Graph
        </h3>
        <div className="flex items-center gap-3 text-[10px] text-slate-500">
          <span>{nodes.length} nodes</span>
          <span>{edges.length} edges</span>
          {totalDuration > 0 && <span>{(totalDuration / 1000).toFixed(1)}s total</span>}
        </div>
      </div>

      {/* Graph as HTML nodes (richer than SVG) */}
      <div className="flex flex-wrap gap-2 items-start" data-testid="lineage-svg">
        {nodes.map((n, i) => {
          const isSel = selected === n.id;
          const argsSummary = summarizeArgs(n.arguments);
          const resultSummary = summarizeResult(n.result);
          return (
            <div key={n.id} className="flex items-center gap-2">
              {/* Node card */}
              <div
                onClick={() => setSelected(isSel ? null : n.id)}
                className={`cursor-pointer rounded-lg border p-3 transition-all min-w-[200px] max-w-[280px] ${nodeColor(n)} ${isSel ? 'ring-2 ring-amber-500/60 shadow-lg shadow-amber-500/10' : 'hover:border-slate-500'}`}
                data-testid={`lineage-node-${n.id}`}
              >
                {/* Header */}
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-1.5">
                    {n.stepNumber && (
                      <span className="w-5 h-5 rounded bg-slate-700/80 flex items-center justify-center text-[9px] text-slate-300 font-mono">{n.stepNumber}</span>
                    )}
                    <span className={`text-xs font-semibold ${iconColor(n)}`}>{n.label}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    {n.durationMs != null && (
                      <span className="text-[9px] text-slate-500 font-mono">{n.durationMs > 1000 ? `${(n.durationMs/1000).toFixed(1)}s` : `${n.durationMs}ms`}</span>
                    )}
                    {n.status && (
                      <span className={`w-1.5 h-1.5 rounded-full ${n.status === 'completed' ? 'bg-emerald-400' : n.status === 'failed' ? 'bg-red-400' : 'bg-yellow-400'}`} />
                    )}
                  </div>
                </div>
                {/* Arguments summary */}
                {argsSummary && (
                  <p className="text-[9px] text-slate-400 truncate mb-0.5" title={argsSummary}>
                    <span className="text-slate-500">args:</span> {argsSummary}
                  </p>
                )}
                {/* Result summary */}
                {resultSummary && n.type === 'tool' && (
                  <p className="text-[9px] text-slate-500 truncate" title={resultSummary}>
                    <span className="text-slate-600">out:</span> {resultSummary}
                  </p>
                )}
                {/* Input/Output preview */}
                {n.type === 'input' && (
                  <p className="text-[9px] text-cyan-300/50 truncate">{inputMessage.slice(0, 80)}...</p>
                )}
                {n.type === 'output' && outputMessage && (
                  <p className="text-[9px] text-purple-300/50 truncate">{outputMessage.slice(0, 80)}...</p>
                )}
              </div>
              {/* Arrow to next */}
              {i < nodes.length - 1 && (
                <ArrowRight className="w-4 h-4 text-slate-600 shrink-0" />
              )}
            </div>
          );
        })}
      </div>

      {/* Expanded detail panel for selected node */}
      <AnimatePresence>
        {selectedNode && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="mt-4 border-t border-slate-700/50 pt-4" data-testid="lineage-detail">
              <div className="flex items-center gap-2 mb-3">
                <span className={`text-sm font-semibold ${iconColor(selectedNode)}`}>{selectedNode.label}</span>
                {selectedNode.stepNumber && <span className="text-[10px] text-slate-500">Step {selectedNode.stepNumber}</span>}
                {selectedNode.durationMs != null && (
                  <span className="text-[10px] text-slate-500 flex items-center gap-1">
                    <Clock className="w-3 h-3" /> {selectedNode.durationMs > 1000 ? `${(selectedNode.durationMs/1000).toFixed(1)}s` : `${selectedNode.durationMs}ms`}
                  </span>
                )}
                {selectedNode.status && (
                  <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
                    selectedNode.status === 'completed' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                    : selectedNode.status === 'failed' ? 'bg-red-500/10 text-red-400 border border-red-500/20'
                    : 'bg-slate-500/10 text-slate-400 border border-slate-500/20'
                  }`}>{selectedNode.status}</span>
                )}
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {/* Arguments */}
                {selectedNode.arguments && Object.keys(selectedNode.arguments).length > 0 && (
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase font-semibold mb-1">Arguments</p>
                    <pre className="text-[10px] text-cyan-300/70 bg-slate-900/60 rounded-lg p-3 max-h-48 overflow-y-auto whitespace-pre-wrap break-words border border-slate-700/30">
                      {JSON.stringify(selectedNode.arguments, null, 2)}
                    </pre>
                  </div>
                )}

                {/* Result / Output */}
                {selectedNode.result && (
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase font-semibold mb-1">
                      {selectedNode.type === 'input' ? 'Message' : selectedNode.type === 'output' ? 'Output' : 'Result'}
                    </p>
                    <pre className="text-[10px] text-emerald-300/70 bg-slate-900/60 rounded-lg p-3 max-h-48 overflow-y-auto whitespace-pre-wrap break-words border border-slate-700/30">
                      {(() => {
                        try { return JSON.stringify(JSON.parse(selectedNode.result!), null, 2); } catch { return selectedNode.result; }
                      })()}
                    </pre>
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default function ExecutionDetailPage() {
  const params = useParams();
  const executionId = params.id as string;
  usePageTitle('Execution Detail');

  const { data: execution, isLoading, mutate } = useApi<ExecutionDetail>(
    executionId ? `/api/executions/${executionId}` : null,
  );
  // children persist parent_execution_id, so this works after the live tree has expired
  const { data: childRuns } = useApi<ChildExecution[]>(
    executionId ? `/api/executions/${executionId}/children` : null,
  );

  // Live state for running executions
  const [liveState, setLiveState] = useState<{
    current_step?: string; current_tool?: string;
    iteration?: number; max_iterations?: number;
    node_statuses?: Record<string, string>;
  } | null>(null);

  const s = (execution?.status || '').toLowerCase();
  const isRunning = s === 'running';

  useEffect(() => {
    if (!isRunning || !executionId) return;
    const token = localStorage.getItem('access_token');
    if (!token) return;
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

    const poll = async () => {
      try {
        const res = await fetch(`${apiUrl}/api/executions/live/${executionId}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok) {
          const json = await res.json();
          if (json.data) setLiveState(json.data);
        }
      } catch { /* ignore */ }
    };
    poll();
    const interval = setInterval(poll, 2000);
    return () => { clearInterval(interval); mutate(); };
  }, [isRunning, executionId, mutate]);

  if (isLoading || !execution) {
    return (
      <div className="p-6 space-y-4">
        <div className="h-8 w-48 bg-slate-800 animate-pulse rounded" />
        <div className="h-64 bg-slate-800 animate-pulse rounded-lg" />
        <div className="h-40 bg-slate-800 animate-pulse rounded-lg" />
      </div>
    );
  }

  const totalDuration = execution.duration_ms || 1;
  const toolCalls: Array<{ name: string; arguments?: Record<string, unknown>; result?: string; result_preview?: string; is_error?: boolean; duration_ms?: number; node_id?: string }> = Array.isArray(execution.tool_calls) ? execution.tool_calls : [];
  const trace = execution.execution_trace;
  const steps = trace?.steps || [];
  // node_results is a dict keyed by node id, older rows may hold a list
  const rawNodeResults = trace?.node_results ?? execution.node_results;
  const nodeResults = Array.isArray(rawNodeResults) ? rawNodeResults : rawNodeResults ? Object.values(rawNodeResults) : [];
  const hasRealDurations = toolCalls.some((tc) => typeof tc.duration_ms === 'number');

  // Waterfall from measured durations. Rows without them get a hairline, never an invented split.
  let cumulativeMs = 0;
  const waterfallItems = toolCalls.map((tc, i) => {
    const dur = typeof tc.duration_ms === 'number' ? tc.duration_ms : 0;
    const start = cumulativeMs;
    cumulativeMs += dur;
    return {
      name: tc.name,
      startPct: (start / totalDuration) * 100,
      widthPct: Math.max((dur / totalDuration) * 100, 0.5),
      durationMs: Math.round(dur),
      measured: typeof tc.duration_ms === 'number',
      isError: Boolean(tc.is_error),
      color: tc.name.includes('llm') || tc.name.includes('agent') ? '#8b5cf6' :
             tc.name.includes('search') ? '#06b6d4' :
             tc.name.includes('memory') ? '#f59e0b' :
             tc.name.includes('human') ? '#ef4444' : '#10b981',
      arguments: tc.arguments,
      result: tc.result ?? tc.result_preview,
    };
  });

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="p-6 space-y-6 max-w-6xl"
    >
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link href="/executions" className="p-2 rounded-lg hover:bg-slate-800/50 text-slate-400 hover:text-white transition-colors">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-bold text-white">Execution Flight Recorder</h1>
            <StatusBadge status={execution.status} />
            {execution.failure_code && (
              <span className="px-2 py-0.5 text-[10px] font-mono rounded-full border border-amber-500/30 bg-amber-500/10 text-amber-300" data-testid="execution-failure-code">
                {execution.failure_code}
              </span>
            )}
          </div>
          <p className="text-xs text-slate-500 mt-0.5 font-mono flex items-center gap-2 flex-wrap">
            <span>{executionId.slice(0, 12)}... | {execution.model_used} | {new Date(execution.created_at).toLocaleString()}</span>
            <FallbackBadge
              actual_model={execution.actual_model || execution.model_used || ''}
              requested_model={execution.model_requested || ''}
              reason={execution.fallback_reason}
            />
          </p>
        </div>
        {execution.trace_id && (() => {
          const grafanaBase = (process.env.NEXT_PUBLIC_GRAFANA_URL || "http://localhost:3010").replace(/\/$/, "");
          const left = JSON.stringify({datasource:'tempo',queries:[{query:execution.trace_id,queryType:'traceql'}],range:{from:'now-1h',to:'now'}});
          return (
            <a
              href={`${grafanaBase}/explore?orgId=1&left=${encodeURIComponent(left)}`}
              target="_blank" rel="noreferrer"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-cyan-500/40 bg-cyan-500/10 text-cyan-300 text-xs font-semibold hover:bg-cyan-500/20"
              title={`Open trace ${execution.trace_id.slice(0,12)}… in Grafana Tempo`}
              data-testid="execution-view-trace"
            >
              <GitBranch className="w-3.5 h-3.5" /> View Trace
            </a>
          );
        })()}
        <Link
          href={`/agents/${execution.agent_id}/chat?prefill=${encodeURIComponent(execution.input_message || '')}`}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-600/60 bg-slate-800/40 text-slate-200 text-xs font-semibold hover:bg-slate-700/60"
          title="Open the agent with this run's input filled in"
          data-testid="execution-rerun"
        >
          <RotateCcw className="w-3.5 h-3.5" /> Re-run
        </Link>
        <SaveAsEvalCase executionId={executionId} agentId={execution.agent_id} agentName={(execution as any).agent_name} />
        {execution.confidence_score != null && (
          <ConfidenceRing score={execution.confidence_score} />
        )}
      </div>
      {execution.parent_execution_id && (
        <p className="text-xs text-slate-400 flex items-center gap-1.5">
          <GitBranch className="w-3.5 h-3.5 text-purple-400" />
          Started by
          <Link
            href={`/executions/${execution.parent_execution_id}`}
            className="font-mono text-cyan-300 hover:text-cyan-200 underline-offset-2 hover:underline"
            data-testid="execution-parent-link"
          >
            {execution.parent_execution_id.slice(0, 12)}...
          </Link>
        </p>
      )}
      {Array.isArray(childRuns) && childRuns.length > 0 && (
        <div className="bg-slate-800/30 backdrop-blur-xl border border-slate-700/50 rounded-xl p-4" data-testid="execution-children">
          <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
            <GitBranch className="w-4 h-4 text-purple-400" /> Sub-agent runs ({childRuns.length})
          </h3>
          <ul className="space-y-1.5">
            {childRuns.map((c) => (
              <li key={c.id} className="flex items-center gap-3 text-xs">
                <Link href={`/executions/${c.id}`} className="font-mono text-cyan-300 hover:text-cyan-200 hover:underline">
                  {c.id.slice(0, 12)}...
                </Link>
                <Link href={`/agents/${c.agent_id}/info`} className="text-slate-400 hover:text-white">
                  agent {c.agent_id.slice(0, 8)}
                </Link>
                <StatusBadge status={c.status} />
                {typeof c.duration_ms === 'number' && (
                  <span className="text-slate-500">{c.duration_ms >= 1000 ? `${(c.duration_ms / 1000).toFixed(1)}s` : `${c.duration_ms}ms`}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {execution.error_message && execution.status !== 'completed' && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/5 px-4 py-3 text-xs text-red-200" data-testid="execution-error">
          {execution.error_message}
        </div>
      )}
      <ProvenancePanel executionId={executionId} isPipeline={!!(execution as any).node_results && Object.keys((execution as any).node_results || {}).length > 0} />
      {trace?.warnings && trace.warnings.length > 0 && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-xs text-amber-200 space-y-1" data-testid="execution-warnings">
          {trace.warnings.map((w) => <p key={w}>{w}</p>)}
        </div>
      )}

      {/* KPI Strip */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <div className="bg-slate-800/30 backdrop-blur-xl border border-slate-700/50 rounded-lg p-3 flex items-center gap-3">
          <Clock className="w-4 h-4 text-cyan-400 shrink-0" />
          <div>
            <p className="text-[10px] text-slate-500">Duration</p>
            <p className="text-sm font-bold text-white">{totalDuration >= 1000 ? `${(totalDuration / 1000).toFixed(1)}s` : `${totalDuration}ms`}</p>
          </div>
        </div>
        <div className="bg-slate-800/30 backdrop-blur-xl border border-slate-700/50 rounded-lg p-3 flex items-center gap-3">
          <Cpu className="w-4 h-4 text-purple-400 shrink-0" />
          <div>
            <p className="text-[10px] text-slate-500">Tokens</p>
            <p className="text-sm font-bold text-white">{((execution.input_tokens || 0) + (execution.output_tokens || 0)).toLocaleString()}</p>
          </div>
        </div>
        <div className="bg-slate-800/30 backdrop-blur-xl border border-slate-700/50 rounded-lg p-3 flex items-center gap-3">
          <DollarSign className="w-4 h-4 text-emerald-400 shrink-0" />
          <div>
            <p className="text-[10px] text-slate-500">Cost</p>
            <p className="text-sm font-bold text-white">${(execution.cost || 0).toFixed(4)}</p>
          </div>
        </div>
        <div className="bg-slate-800/30 backdrop-blur-xl border border-slate-700/50 rounded-lg p-3 flex items-center gap-3">
          <Zap className="w-4 h-4 text-amber-400 shrink-0" />
          <div>
            <p className="text-[10px] text-slate-500">Tool Calls</p>
            <p className="text-sm font-bold text-white">{toolCalls.length}</p>
          </div>
        </div>
        <div className="bg-slate-800/30 backdrop-blur-xl border border-slate-700/50 rounded-lg p-3 flex items-center gap-3">
          <Activity className="w-4 h-4 text-cyan-400 shrink-0" />
          <div>
            <p className="text-[10px] text-slate-500">Confidence</p>
            <p className="text-sm font-bold text-white">{execution.confidence_score != null ? `${Math.round(execution.confidence_score * 100)}%` : '--'}</p>
          </div>
        </div>
      </div>

      {/* Live Status Banner (only when running) */}
      {isRunning && liveState ? (
        <div className="bg-cyan-500/5 border border-cyan-500/20 rounded-xl p-4 flex items-center gap-4">
          <div className="relative shrink-0">
            <div className="w-3 h-3 rounded-full bg-cyan-500 animate-pulse" />
            <div className="absolute inset-0 w-3 h-3 rounded-full bg-cyan-500/50 animate-ping" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-cyan-400">
              {liveState.current_tool ? `Calling ${liveState.current_tool}` : liveState.current_step || 'Processing...'}
            </p>
            <p className="text-[10px] text-slate-500">
              Iteration {liveState.iteration || 0} / {liveState.max_iterations || 10}
              {liveState.node_statuses && Object.keys(liveState.node_statuses).length > 0 ? (
                <> | Nodes: {Object.entries(liveState.node_statuses).map(([k, v]) => `${k}:${String(v)}`).join(', ')}</>
              ) : null}
            </p>
          </div>
          <Loader2 className="w-5 h-5 text-cyan-400 animate-spin shrink-0" />
        </div>
      ) : null}

      {/* Live DAG — SSE snapshot stream of nodes + edges. Renders for
          running executions and also replays the final graph for
          completed/failed ones, so the page is useful both live and
          after-the-fact. Mirrors the JVM SDK's LiveDagView. */}
      <div className="bg-slate-800/30 backdrop-blur-xl border border-slate-700/50 rounded-xl p-4">
        <h3 className="text-xs font-semibold text-slate-400 uppercase mb-3 flex items-center gap-2">
          <Activity className="w-3.5 h-3.5 text-cyan-400" />
          Live DAG
          <span className="text-[10px] font-normal text-slate-500 normal-case">
            — SSE snapshot stream (powered by <code className="text-cyan-400/80">forge.watch()</code>)
          </span>
        </h3>
        <LiveDagView
          executionId={executionId}
          apiUrl={process.env.NEXT_PUBLIC_API_URL || ''}
          token={typeof window !== 'undefined' ? localStorage.getItem('access_token') : null}
        />
      </div>

      {/* Waterfall + Tool Details + Pipeline */}
      <>{waterfallItems.length > 0 ? (
        <div className="bg-slate-800/30 backdrop-blur-xl border border-slate-700/50 rounded-xl p-4">
          <h3 className="text-xs font-semibold text-slate-400 uppercase mb-3 flex items-center gap-2">
            <Activity className="w-3.5 h-3.5 text-cyan-400" />
            Execution Waterfall
          </h3>
          <div className="relative">
            {/* Time ruler */}
            <div className="flex justify-between text-[9px] text-slate-600 mb-1 px-1">
              <span>0ms</span>
              <span>{Math.round(totalDuration * 0.25)}ms</span>
              <span>{Math.round(totalDuration * 0.5)}ms</span>
              <span>{Math.round(totalDuration * 0.75)}ms</span>
              <span>{totalDuration}ms</span>
            </div>
            <div className="bg-slate-900/50 rounded-lg border border-slate-700/30 overflow-hidden">
              {waterfallItems.map((item, i) => (
                <WaterfallBar
                  key={i}
                  startPct={item.startPct}
                  widthPct={item.widthPct}
                  color={item.color}
                  label={item.name}
                  durationMs={item.durationMs}
                />
              ))}
            </div>
            {/* Legend */}
            <div className="flex gap-4 mt-2 text-[9px] text-slate-500">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-purple-500" /> LLM/Agent</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-cyan-500" /> Search</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-emerald-500" /> Tool</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-amber-500" /> Memory</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-red-500" /> HITL</span>
            </div>
          </div>
        </div>
      ) : null}

      {toolCalls.length > 0 ? (
        <div className="bg-slate-800/30 backdrop-blur-xl border border-slate-700/50 rounded-xl p-4">
          <h3 className="text-xs font-semibold text-slate-400 uppercase mb-3 flex items-center gap-2">
            <Code className="w-3.5 h-3.5 text-cyan-400" />
            Tool Call Inspector ({toolCalls.length} calls)
          </h3>
          <div className="space-y-2">
            {toolCalls.map((tc, i) => (
              <div key={i} className="space-y-1" data-testid="tool-call" data-tool={tc.name}>
                <div className="flex items-center gap-2 text-xs">
                  <span className="w-5 h-5 rounded bg-slate-700 flex items-center justify-center text-[10px] text-slate-400 font-mono">{i + 1}</span>
                  <span className={`font-medium ${tc.is_error ? 'text-red-400' : 'text-cyan-400'}`}>{tc.name}</span>
                  {tc.is_error && <span className="text-[10px] px-1.5 rounded bg-red-500/10 text-red-300">error</span>}
                  {typeof tc.duration_ms === 'number' ? <span className="text-slate-600">{tc.duration_ms}ms</span> : <span className="text-slate-700">duration not recorded</span>}
                </div>
                <div className="ml-7 space-y-1">
                  <DataPanel title="Arguments" data={tc.arguments} isJson />
                  {(tc.result ?? tc.result_preview) ? (
                    <DataPanel title={tc.result ? 'Result' : 'Result (first 500 chars)'} data={tc.result ?? tc.result_preview} />
                  ) : (
                    <p className="text-[10px] text-slate-600" data-testid="tool-result-missing">No result was recorded for this call.</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {/* Pipeline Node Results */}
      {execution.execution_trace?.pipeline_status && (
        <div className="bg-slate-800/30 backdrop-blur-xl border border-slate-700/50 rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-semibold text-slate-400 uppercase flex items-center gap-2">
              <Cpu className="w-3.5 h-3.5 text-purple-400" /> Pipeline Execution
            </h3>
            <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
              execution.execution_trace.pipeline_status === 'completed'
                ? 'bg-emerald-500/10 text-emerald-400'
                : execution.execution_trace.pipeline_status === 'partial'
                  ? 'bg-amber-500/10 text-amber-400'
                  : 'bg-red-500/10 text-red-400'
            }`}>
              {execution.execution_trace.pipeline_status}
            </span>
          </div>

          {/* Execution path */}
          {execution.execution_trace.execution_path && execution.execution_trace.execution_path.length > 0 && (
            <div className="mb-3">
              <p className="text-[10px] text-slate-500 mb-1">Execution Path</p>
              <div className="flex flex-wrap items-center gap-1">
                {execution.execution_trace.execution_path.map((nodeId, i) => (
                  <span key={nodeId} className="flex items-center gap-1">
                    {i > 0 && <ChevronRight className="w-3 h-3 text-slate-600" />}
                    <span className="text-[10px] px-2 py-0.5 bg-cyan-500/10 text-cyan-400 rounded font-mono">{nodeId}</span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Skipped / Failed nodes */}
          {execution.execution_trace.skipped_nodes && execution.execution_trace.skipped_nodes.length > 0 && (
            <div className="mb-3">
              <p className="text-[10px] text-slate-500 mb-1">Skipped Nodes</p>
              <div className="flex flex-wrap gap-1">
                {execution.execution_trace.skipped_nodes.map((n) => (
                  <span key={n} className="text-[10px] px-2 py-0.5 bg-slate-700/30 text-slate-500 rounded font-mono">{n}</span>
                ))}
              </div>
            </div>
          )}
          {execution.execution_trace.failed_nodes && execution.execution_trace.failed_nodes.length > 0 && (
            <div className="mb-3">
              <p className="text-[10px] text-slate-500 mb-1">Failed Nodes</p>
              <div className="flex flex-wrap gap-1">
                {execution.execution_trace.failed_nodes.map((n) => (
                  <span key={n} className="text-[10px] px-2 py-0.5 bg-red-500/10 text-red-400 rounded font-mono">{n}</span>
                ))}
              </div>
            </div>
          )}

          {/* Node detail table */}
          {nodeResults.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-slate-700/50">
                    <th className="text-left text-[10px] text-slate-500 font-medium py-1.5">Node</th>
                    <th className="text-left text-[10px] text-slate-500 font-medium py-1.5">Tool</th>
                    <th className="text-center text-[10px] text-slate-500 font-medium py-1.5">Status</th>
                    <th className="text-right text-[10px] text-slate-500 font-medium py-1.5">Duration</th>
                  </tr>
                </thead>
                <tbody>
                  {nodeResults.map((nr) => (
                    <tr key={nr.node_id} className="border-b border-slate-700/30">
                      <td className="text-[10px] text-slate-300 py-1.5" title={nr.node_id}>{nr.label || nr.node_id}</td>
                      <td className="text-[10px] text-slate-400 py-1.5">{nr.tool_name}</td>
                      <td className="text-center py-1.5">
                        {nr.status === 'completed' ? (
                          <CheckCircle2 className="w-3 h-3 text-emerald-400 inline" />
                        ) : nr.status === 'failed' ? (
                          <XCircle className="w-3 h-3 text-red-400 inline" />
                        ) : (
                          <Clock className="w-3 h-3 text-slate-500 inline" />
                        )}
                      </td>
                      <td className="text-right text-[10px] text-slate-400 py-1.5" title={nr.error || undefined}>
                        {nr.duration_ms ? `${nr.duration_ms}ms` : '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── Data Lineage Graph ──────────────────────────────────── */}
      {(toolCalls.length > 0 || nodeResults.length > 0) && (
        <LineageGraph
          toolCalls={toolCalls}
          inputMessage={execution.input_message}
          outputMessage={execution.output_message}
          executionPath={trace?.execution_path}
          nodeResults={nodeResults}
        />
      )}

      {/* Step replay: every node in the order it ran */}
      {steps.length > 0 && (
        <div className="bg-slate-800/30 backdrop-blur-xl border border-slate-700/50 rounded-xl p-4" data-testid="execution-steps">
          <h3 className="text-xs font-semibold text-slate-400 uppercase mb-3 flex items-center gap-2">
            <RotateCcw className="w-3.5 h-3.5 text-cyan-400" /> Step replay ({steps.length} steps)
          </h3>
          <ol className="space-y-2">
            {steps.map((st, i) => {
              const failed = st.is_error || st.status === 'failed';
              const label = st.label || st.tool || st.name || st.node_id || st.node_type || st.type || 'step';
              return (
                <li key={i} className="flex items-start gap-3 text-xs" data-testid="execution-step" data-step={label}>
                  <span className="w-5 h-5 rounded bg-slate-700 flex items-center justify-center text-[10px] text-slate-400 font-mono shrink-0">{i + 1}</span>
                  <div className="flex-1 min-w-0 space-y-1">
                    <div className="flex items-center gap-2">
                      <span className={`font-medium ${failed ? 'text-red-400' : 'text-cyan-300'}`}>{label}</span>
                      {st.node_id && st.tool && <span className="text-slate-600 font-mono">{st.node_id}</span>}
                      {typeof st.duration_ms === 'number' && <span className="text-slate-600">{st.duration_ms}ms</span>}
                      {failed && <span className="text-[10px] px-1.5 rounded bg-red-500/10 text-red-300">failed</span>}
                    </div>
                    {st.input !== undefined && <DataPanel title="Input" data={st.input} isJson />}
                    {(st.output_preview || st.output !== undefined) && <DataPanel title="Output" data={st.output_preview ?? st.output} isJson={st.output_preview === undefined} />}
                    {st.error && <p className="text-[10px] text-red-300">{st.error}</p>}
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      )}

      {/* Input / Output */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-slate-800/30 backdrop-blur-xl border border-slate-700/50 rounded-xl p-4">
          <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2 flex items-center gap-2">
            <MessageSquare className="w-3.5 h-3.5 text-cyan-400" /> Input
          </h3>
          <p className="text-xs text-slate-300 whitespace-pre-wrap max-h-40 overflow-y-auto">{execution.input_message}</p>
        </div>
        <div className="bg-slate-800/30 backdrop-blur-xl border border-slate-700/50 rounded-xl p-4">
          <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2 flex items-center gap-2">
            <Eye className="w-3.5 h-3.5 text-cyan-400" /> Output
          </h3>
          <p className="text-xs text-slate-300 whitespace-pre-wrap max-h-40 overflow-y-auto">{execution.output_message || execution.error_message || '(no output)'}</p>
        </div>
      </div>

      {/* Error */}
      {execution.error_message && (
        <div className="bg-red-500/5 border border-red-500/20 rounded-xl p-4">
          <h3 className="text-xs font-semibold text-red-400 uppercase mb-2 flex items-center gap-2">
            <XCircle className="w-3.5 h-3.5" /> Error
          </h3>
          <p className="text-xs text-red-300 font-mono">{execution.error_message}</p>
        </div>
      )}

      {/* System Prompt (for debugging) */}
      {(execution as unknown as Record<string, unknown>).system_prompt && (
        <DataPanel title="System Prompt (sent to LLM)" data={(execution as unknown as Record<string, unknown>).system_prompt as string} />
      )}

      {/* Tool Config Injections */}
      {(execution as unknown as Record<string, unknown>).tool_config && (
        <DataPanel title="Tool Configuration (injected into prompt)" data={(execution as unknown as Record<string, unknown>).tool_config} isJson />
      )}

      {/* Raw Trace */}
      {trace && (
        <DataPanel title="Full Execution Trace (JSONB)" data={trace} isJson />
      )}
      </>
    </motion.div>
  );
}
