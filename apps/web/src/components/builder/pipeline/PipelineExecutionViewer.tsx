'use client';

import { useState } from 'react';
import {
  CheckCircle,
  XCircle,
  Clock,
  Loader2,
  SkipForward,
  Play,
  X,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';

// Data interfaces

interface NodeResultData {
  output: unknown;
  durationMs: number;
  error?: string;
  status?: 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | 'retrying';
  toolName?: string;
  conditionEvaluated?: boolean;
  conditionMet?: boolean | null;
  attempt?: number;
  forEachResults?: unknown[];
}

interface PipelineExecutionViewerProps {
  isRunning: boolean;
  executionId: string | null;
  nodeStatuses: Record<
    string,
    'pending' | 'running' | 'completed' | 'failed' | 'skipped' | 'retrying'
  >;
  nodeResults: Record<string, NodeResultData>;
  executionPath: string[];
  totalDurationMs: number;
  onReset: () => void;
  onClose: () => void;
}

// Helpers

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

function formatJsonOutput(value: unknown, maxLen = 500): string {
  try {
    const raw = JSON.stringify(value, null, 2);
    if (raw.length <= maxLen) return raw;
    return raw.slice(0, maxLen) + '\u2026';
  } catch {
    return String(value);
  }
}

function statusIcon(
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | 'retrying',
): { Icon: typeof Clock; colorClass: string } {
  switch (status) {
    case 'pending':
      return { Icon: Clock, colorClass: 'text-slate-500' };
    case 'running':
      return { Icon: Loader2, colorClass: 'text-yellow-400' };
    case 'completed':
      return { Icon: CheckCircle, colorClass: 'text-emerald-400' };
    case 'failed':
      return { Icon: XCircle, colorClass: 'text-red-400' };
    case 'skipped':
      return { Icon: SkipForward, colorClass: 'text-slate-500' };
    case 'retrying':
      return { Icon: Loader2, colorClass: 'text-amber-400' };
  }
}

// Component

export default function PipelineExecutionViewer({
  isRunning,
  executionId,
  nodeStatuses,
  nodeResults,
  executionPath,
  totalDurationMs,
  onReset,
  onClose,
}: PipelineExecutionViewerProps) {
  const [expanded, setExpanded] = useState(false);
  const [expandedNode, setExpandedNode] = useState<string | null>(null);
  const [showFullOutput, setShowFullOutput] = useState<Record<string, boolean>>(
    {},
  );

  // Aggregate counts
  const completedCount = Object.values(nodeStatuses).filter(
    (s) => s === 'completed',
  ).length;
  const failedCount = Object.values(nodeStatuses).filter(
    (s) => s === 'failed',
  ).length;
  const skippedCount = Object.values(nodeStatuses).filter(
    (s) => s === 'skipped',
  ).length;
  const totalCount = Object.keys(nodeStatuses).length;

  // Determine overall pipeline status for the summary label
  const overallStatus: 'running' | 'completed' | 'failed' = isRunning
    ? 'running'
    : failedCount > 0
      ? 'failed'
      : 'completed';

  const overallLabel =
    overallStatus === 'running'
      ? 'Running pipeline...'
      : overallStatus === 'failed'
        ? 'Pipeline failed'
        : 'Pipeline completed';

  const OverallIcon =
    overallStatus === 'running'
      ? Loader2
      : overallStatus === 'failed'
        ? XCircle
        : CheckCircle;

  const overallIconColor =
    overallStatus === 'running'
      ? 'text-yellow-400'
      : overallStatus === 'failed'
        ? 'text-red-400'
        : 'text-emerald-400';

  // Build node count summary text
  const summaryParts: string[] = [];
  if (completedCount > 0)
    summaryParts.push(`${completedCount}/${totalCount} completed`);
  if (failedCount > 0) summaryParts.push(`${failedCount} failed`);
  if (skippedCount > 0) summaryParts.push(`${skippedCount} skipped`);
  const summaryText = summaryParts.join(', ') || `0/${totalCount} completed`;

  // Toggle per-node "Show more" for output
  function toggleShowFull(nodeId: string) {
    setShowFullOutput((prev) => ({ ...prev, [nodeId]: !prev[nodeId] }));
  }

  // Determine if the raw output is truncated for a given node
  function isOutputTruncated(nodeId: string): boolean {
    const result = nodeResults[nodeId];
    if (!result) return false;
    try {
      const raw = JSON.stringify(result.output, null, 2);
      return raw.length > 500;
    } catch {
      return false;
    }
  }

  return (
    <div className="fixed bottom-0 left-0 right-0 z-50 flex flex-col pointer-events-none">
      {/* ----------------------------------------------------------------- */}
      {/* Expandable Details Panel                                          */}
      {/* ----------------------------------------------------------------- */}
      {expanded && (
        <div className="pointer-events-auto bg-slate-900/95 backdrop-blur border-t border-slate-700 max-h-[50vh] overflow-y-auto">
          <div className="px-4 py-3 space-y-1">
            {executionPath.length === 0 && (
              <p className="text-xs text-slate-500">
                No execution data available.
              </p>
            )}

            {executionPath.map((nodeId) => {
              const status = nodeStatuses[nodeId] ?? 'pending';
              const result = nodeResults[nodeId];
              const { Icon, colorClass } = statusIcon(status);
              const isNodeExpanded = expandedNode === nodeId;

              return (
                <div
                  key={nodeId}
                  className="border border-slate-700/60 rounded-md overflow-hidden"
                >
                  {/* Node summary row */}
                  <button
                    type="button"
                    onClick={() =>
                      setExpandedNode(isNodeExpanded ? null : nodeId)
                    }
                    className="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-slate-800/60 transition-colors"
                  >
                    <Icon
                      className={`w-4 h-4 shrink-0 ${colorClass} ${status === 'running' ? 'animate-spin' : ''}`}
                    />
                    <span className="text-xs font-medium text-slate-200 truncate min-w-0">
                      {nodeId}
                    </span>
                    {result && (
                      <span className="text-[10px] text-slate-500 shrink-0">
                        {result.toolName}
                      </span>
                    )}
                    {result && (
                      <span className="text-[10px] text-slate-400 shrink-0 ml-auto mr-2">
                        {formatDuration(result.durationMs)}
                      </span>
                    )}
                    {isNodeExpanded ? (
                      <ChevronUp className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                    ) : (
                      <ChevronDown className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                    )}
                  </button>

                  {/* Expanded detail */}
                  {isNodeExpanded && result && (
                    <div className="px-4 py-3 border-t border-slate-700/40 space-y-3 bg-slate-800/30">
                      {/* Condition evaluation info */}
                      {result.conditionEvaluated !== undefined && (
                        <div>
                          <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1">
                            Condition
                          </p>
                          <p className="text-xs text-slate-300">
                            Evaluated:{' '}
                            {result.conditionEvaluated ? 'Yes' : 'No'}
                            {result.conditionMet !== null &&
                              result.conditionMet !== undefined && (
                                <span
                                  className={
                                    result.conditionMet
                                      ? 'text-emerald-400 ml-2'
                                      : 'text-red-400 ml-2'
                                  }
                                >
                                  {result.conditionMet
                                    ? '(met)'
                                    : '(not met)'}
                                </span>
                              )}
                          </p>
                        </div>
                      )}

                      {/* Retry attempt */}
                      {result.attempt !== undefined && result.attempt > 1 && (
                        <div>
                          <p className="text-[10px] font-semibold text-amber-400 uppercase tracking-wider mb-1">
                            Retry
                          </p>
                          <p className="text-xs text-amber-300">
                            Succeeded on attempt {result.attempt}
                          </p>
                        </div>
                      )}

                      {/* Output */}
                      <div>
                        <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1">
                          Output
                        </p>
                        <pre className="text-xs text-slate-300 bg-slate-900/60 rounded px-2 py-1.5 overflow-x-auto font-mono whitespace-pre-wrap break-all">
                          {showFullOutput[nodeId]
                            ? JSON.stringify(result.output, null, 2)
                            : formatJsonOutput(result.output)}
                        </pre>
                        {isOutputTruncated(nodeId) && (
                          <button
                            type="button"
                            onClick={() => toggleShowFull(nodeId)}
                            className="text-[10px] text-emerald-400 hover:text-emerald-300 mt-1 transition-colors"
                          >
                            {showFullOutput[nodeId]
                              ? 'Show less'
                              : 'Show more'}
                          </button>
                        )}
                      </div>

                      {/* ForEach results */}
                      {result.forEachResults && result.forEachResults.length > 0 && (
                        <div>
                          <p className="text-[10px] font-semibold text-cyan-400 uppercase tracking-wider mb-1">
                            Iterations ({result.forEachResults.length})
                          </p>
                          <div className="space-y-1 max-h-40 overflow-y-auto">
                            {result.forEachResults.map((item, idx) => (
                              <pre
                                key={idx}
                                className="text-[10px] text-slate-400 bg-slate-900/40 rounded px-2 py-1 font-mono whitespace-pre-wrap break-all"
                              >
                                [{idx}] {formatJsonOutput(item, 200)}
                              </pre>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Error */}
                      {result.error && (
                        <div>
                          <p className="text-[10px] font-semibold text-red-400 uppercase tracking-wider mb-1">
                            Error
                          </p>
                          <p className="text-xs text-red-300 bg-red-900/20 rounded px-2 py-1.5">
                            {result.error}
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ----------------------------------------------------------------- */}
      {/* Summary Bar                                                       */}
      {/* ----------------------------------------------------------------- */}
      <div className="pointer-events-auto relative bg-slate-900/95 backdrop-blur border-t border-slate-700 h-14 flex items-center px-4 gap-4">
        {/* Pulsing running indicator bar */}
        {isRunning && (
          <div className="absolute top-0 left-0 right-0 h-0.5 bg-emerald-400 animate-pulse" />
        )}

        {/* Left: overall status */}
        <div className="flex items-center gap-2 min-w-0 shrink-0">
          <OverallIcon
            className={`w-4 h-4 ${overallIconColor} ${isRunning ? 'animate-spin' : ''}`}
          />
          <span className="text-sm font-medium text-slate-200 whitespace-nowrap">
            {overallLabel}
          </span>
        </div>

        {/* Center: node count summary */}
        <div className="flex-1 text-center">
          <span className="text-xs text-slate-400">{summaryText}</span>
        </div>

        {/* Right: duration + actions */}
        <div className="flex items-center gap-3 shrink-0">
          {totalDurationMs > 0 && (
            <span className="text-xs text-slate-400 font-mono">
              {formatDuration(totalDurationMs)}
            </span>
          )}

          {/* Toggle details */}
          <button
            type="button"
            onClick={() => setExpanded((prev) => !prev)}
            className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-200 transition-colors"
            title={expanded ? 'Collapse details' : 'Expand details'}
          >
            {expanded ? (
              <ChevronDown className="w-4 h-4" />
            ) : (
              <ChevronUp className="w-4 h-4" />
            )}
          </button>

          {/* Clear Results */}
          {!isRunning && (
            <button
              type="button"
              onClick={onReset}
              className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-200 bg-slate-800 hover:bg-slate-700 rounded px-2 py-1 transition-colors"
            >
              <Play className="w-3 h-3" />
              <span>Clear Results</span>
            </button>
          )}

          {/* Close */}
          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-200 transition-colors"
            title="Close execution viewer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
