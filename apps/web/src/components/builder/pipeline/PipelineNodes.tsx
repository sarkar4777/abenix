'use client';

import { memo } from 'react';
import { Handle, Position, type NodeProps } from 'reactflow';
import { Zap, GitBranch, Flag, X, AlertCircle, Repeat, Bot, Activity, Merge } from 'lucide-react';

// Data interfaces

export interface PipelineStepNodeData {
  label: string;
  toolName: string;
  stepNumber: number;
  status: 'idle' | 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
  durationMs: number | null;
  error: string | null;
  configured: boolean;
  errorCount?: number;
  warningCount?: number;
  onDelete?: () => void;
}

export interface ConditionNodeData {
  label: string;
  conditionText: string;
  status: 'idle' | 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
  onDelete?: () => void;
}

export interface OutputNodeData {
  label: string;
  status: 'idle' | 'completed' | 'failed';
  onDelete?: () => void;
}

export interface ForEachStepNodeData {
  label: string;
  toolName: string;
  stepNumber: number;
  status: 'idle' | 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | 'retrying';
  durationMs: number | null;
  error: string | null;
  configured: boolean;
  itemVariable: string;
  iterationCount: number | null;
  onDelete?: () => void;
}

export interface AgentStepNodeData {
  label: string;
  toolName: string;
  stepNumber: number;
  status: 'idle' | 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
  durationMs: number | null;
  error: string | null;
  configured: boolean;
  model: string;
  toolCount: number;
  onDelete?: () => void;
}

// Helpers

const completedClasses: Record<string, string> = {
  emerald: 'border-emerald-400 shadow-emerald-500/20',
  amber: 'border-amber-400 shadow-amber-500/20',
  purple: 'border-purple-400 shadow-purple-500/20',
};

function statusBorderClasses(
  status: string,
  accentColor: 'emerald' | 'amber' | 'purple',
): string {
  switch (status) {
    case 'pending':
      return 'border-slate-500 border-dashed';
    case 'running':
      return 'border-yellow-400 animate-pulse shadow-yellow-500/30';
    case 'completed':
      return completedClasses[accentColor];
    case 'failed':
      return 'border-red-400 shadow-red-500/20';
    case 'skipped':
      return 'border-slate-600 opacity-60';
    default:
      // idle
      return 'border-slate-700';
  }
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}

// PipelineStepNode

export const PipelineStepNode = memo(function PipelineStepNode({
  data,
  selected,
}: NodeProps<PipelineStepNodeData>) {
  const errorCount = data.errorCount ?? 0;
  const warningCount = data.warningCount ?? 0;
  const borderClasses = selected
    ? 'border-emerald-400 shadow-emerald-500/30 ring-2 ring-emerald-400/20'
    : errorCount > 0
      ? 'border-red-400 shadow-red-500/20'
      : warningCount > 0
        ? 'border-amber-400 shadow-amber-500/20'
        : statusBorderClasses(data.status, 'emerald');

  return (
    <div
      className={`bg-slate-800/90 border rounded-lg p-3 min-w-[200px] shadow-md transition-all relative group ${borderClasses}`}
    >
      {/* Handles */}
      <Handle
        type="target"
        position={Position.Left}
        className="!bg-emerald-400 !w-2.5 !h-2.5 !border-2 !border-slate-900"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!bg-emerald-400 !w-2.5 !h-2.5 !border-2 !border-slate-900"
      />

      {/* Delete button — visible when selected */}
      {selected && data.onDelete && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            data.onDelete?.();
          }}
          className="absolute -top-2 -right-2 w-5 h-5 bg-red-500 hover:bg-red-400 rounded-full flex items-center justify-center shadow-lg transition-colors z-10"
        >
          <X className="w-3 h-3 text-white" />
        </button>
      )}

      {/* Validation error badge (top-left) */}
      {errorCount > 0 && (
        <div
          className="absolute -top-2 -left-2 bg-red-500 text-white text-[10px] font-bold px-1.5 py-0.5 rounded-full leading-none flex items-center gap-0.5 shadow-lg z-10"
          data-testid="pipeline-node-error-badge"
          title={`${errorCount} validation error${errorCount === 1 ? '' : 's'}`}
        >
          <AlertCircle className="w-2.5 h-2.5" />
          {errorCount}
        </div>
      )}
      {errorCount === 0 && warningCount > 0 && (
        <div
          className="absolute -top-2 -left-2 bg-amber-500 text-white text-[10px] font-bold px-1.5 py-0.5 rounded-full leading-none flex items-center gap-0.5 shadow-lg z-10"
          data-testid="pipeline-node-warning-badge"
          title={`${warningCount} validation warning${warningCount === 1 ? '' : 's'}`}
        >
          <AlertCircle className="w-2.5 h-2.5" />
          {warningCount}
        </div>
      )}

      {/* Step number badge */}
      <div className="absolute -top-2 right-4 bg-emerald-500/20 text-emerald-400 text-[10px] font-semibold px-1.5 py-0.5 rounded-full leading-none">
        #{data.stepNumber}
      </div>

      {/* Content */}
      <div className="flex items-center gap-2.5">
        <div className="w-8 h-8 rounded-md bg-emerald-500/10 flex items-center justify-center shrink-0">
          <Zap className="w-4 h-4 text-emerald-400" />
        </div>
        <div className="min-w-0">
          <p className="text-xs font-medium text-white truncate">{data.label}</p>
          <p className="text-[10px] text-slate-500 truncate">{data.toolName}</p>
        </div>
      </div>

      {/* Configuration indicator */}
      {data.configured && data.status === 'idle' && (
        <div className="mt-2 flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
          <span className="text-[10px] text-emerald-400">configured</span>
        </div>
      )}

      {/* Duration badge — shown when completed */}
      {data.status === 'completed' && data.durationMs !== null && (
        <div className="mt-2 flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
          <span className="text-[10px] text-emerald-400">
            {formatDuration(data.durationMs)}
          </span>
        </div>
      )}

      {/* Error indicator — shown when failed */}
      {data.status === 'failed' && (
        <div className="mt-2 flex items-center gap-1">
          <AlertCircle className="w-3 h-3 text-red-400" />
          <span className="text-[10px] text-red-400 truncate">
            {data.error ?? 'Step failed'}
          </span>
        </div>
      )}
    </div>
  );
});

// ConditionNode

export const ConditionNode = memo(function ConditionNode({
  data,
  selected,
}: NodeProps<ConditionNodeData>) {
  const borderClasses = selected
    ? 'border-amber-400 shadow-amber-500/30 ring-2 ring-amber-400/20'
    : statusBorderClasses(data.status, 'amber');

  return (
    <div
      className={`bg-slate-800/90 border rounded-lg p-3 min-w-[160px] shadow-md transition-all relative group ${borderClasses}`}
    >
      {/* Target handle (left) */}
      <Handle
        type="target"
        position={Position.Left}
        className="!bg-amber-400 !w-2.5 !h-2.5 !border-2 !border-slate-900"
      />

      {/* Source handle — true path (right) */}
      <Handle
        type="source"
        position={Position.Right}
        id="true"
        className="!bg-amber-400 !w-2.5 !h-2.5 !border-2 !border-slate-900"
      />

      {/* Source handle — false path (bottom) */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="false"
        className="!bg-amber-400 !w-2.5 !h-2.5 !border-2 !border-slate-900"
      />

      {/* Delete button */}
      {selected && data.onDelete && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            data.onDelete?.();
          }}
          className="absolute -top-2 -right-2 w-5 h-5 bg-red-500 hover:bg-red-400 rounded-full flex items-center justify-center shadow-lg transition-colors z-10"
        >
          <X className="w-3 h-3 text-white" />
        </button>
      )}

      {/* Content */}
      <div className="flex items-center gap-2.5">
        <div className="w-8 h-8 rounded-md bg-amber-500/10 flex items-center justify-center shrink-0">
          <GitBranch className="w-4 h-4 text-amber-400" />
        </div>
        <div className="min-w-0">
          <p className="text-xs font-medium text-white truncate">{data.label}</p>
          <p className="text-[10px] text-slate-500 truncate font-mono">
            {data.conditionText}
          </p>
        </div>
      </div>

      {/* Branch labels */}
      <div className="mt-2 flex items-center justify-between text-[9px] px-0.5">
        <span className="text-emerald-400">true &rarr;</span>
        <span className="text-red-400">false &darr;</span>
      </div>
    </div>
  );
});

// OutputNode

export const OutputNode = memo(function OutputNode({
  data,
  selected,
}: NodeProps<OutputNodeData>) {
  const borderClasses = selected
    ? 'border-purple-400 shadow-purple-500/30 ring-2 ring-purple-400/20'
    : statusBorderClasses(data.status, 'purple');

  return (
    <div
      className={`bg-slate-800/90 border rounded-lg p-3 min-w-[120px] shadow-md transition-all relative group ${borderClasses}`}
    >
      {/* Target handle only — terminal node */}
      <Handle
        type="target"
        position={Position.Left}
        className="!bg-purple-400 !w-2.5 !h-2.5 !border-2 !border-slate-900"
      />

      {/* Delete button */}
      {selected && data.onDelete && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            data.onDelete?.();
          }}
          className="absolute -top-2 -right-2 w-5 h-5 bg-red-500 hover:bg-red-400 rounded-full flex items-center justify-center shadow-lg transition-colors z-10"
        >
          <X className="w-3 h-3 text-white" />
        </button>
      )}

      {/* Content */}
      <div className="flex items-center gap-2.5">
        <div className="w-8 h-8 rounded-md bg-purple-500/10 flex items-center justify-center shrink-0">
          <Flag className="w-4 h-4 text-purple-400" />
        </div>
        <div className="min-w-0">
          <p className="text-xs font-medium text-white truncate">{data.label}</p>
          {data.status === 'completed' && (
            <p className="text-[10px] text-emerald-400">done</p>
          )}
          {data.status === 'failed' && (
            <p className="text-[10px] text-red-400">failed</p>
          )}
        </div>
      </div>
    </div>
  );
});

// ForEachStepNode

export const ForEachStepNode = memo(function ForEachStepNode({
  data,
  selected,
}: NodeProps<ForEachStepNodeData>) {
  const borderClasses = selected
    ? 'border-cyan-400 shadow-cyan-500/30 ring-2 ring-cyan-400/20'
    : statusBorderClasses(data.status, 'emerald');

  return (
    <div
      className={`bg-slate-800/90 border rounded-lg p-3 min-w-[200px] shadow-md transition-all relative group ${borderClasses}`}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!bg-cyan-400 !w-2.5 !h-2.5 !border-2 !border-slate-900"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!bg-cyan-400 !w-2.5 !h-2.5 !border-2 !border-slate-900"
      />

      {selected && data.onDelete && (
        <button
          onClick={(e) => { e.stopPropagation(); data.onDelete?.(); }}
          className="absolute -top-2 -right-2 w-5 h-5 bg-red-500 hover:bg-red-400 rounded-full flex items-center justify-center shadow-lg transition-colors z-10"
        >
          <X className="w-3 h-3 text-white" />
        </button>
      )}

      <div className="absolute -top-2 right-4 bg-cyan-500/20 text-cyan-400 text-[10px] font-semibold px-1.5 py-0.5 rounded-full leading-none">
        #{data.stepNumber}
      </div>

      <div className="flex items-center gap-2.5">
        <div className="w-8 h-8 rounded-md bg-cyan-500/10 flex items-center justify-center shrink-0">
          <Repeat className="w-4 h-4 text-cyan-400" />
        </div>
        <div className="min-w-0">
          <p className="text-xs font-medium text-white truncate">{data.label}</p>
          <p className="text-[10px] text-slate-500 truncate">{data.toolName}</p>
        </div>
      </div>

      {/* Iteration info */}
      <div className="mt-2 flex items-center gap-2">
        <span className="text-[10px] text-cyan-400 font-mono">
          {data.itemVariable || 'current_item'}
        </span>
        {data.iterationCount !== null && (
          <span className="text-[10px] text-slate-500">
            ({data.iterationCount} items)
          </span>
        )}
      </div>

      {data.status === 'completed' && data.durationMs !== null && (
        <div className="mt-1 flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
          <span className="text-[10px] text-cyan-400">
            {formatDuration(data.durationMs)}
          </span>
        </div>
      )}

      {data.status === 'failed' && (
        <div className="mt-1 flex items-center gap-1">
          <AlertCircle className="w-3 h-3 text-red-400" />
          <span className="text-[10px] text-red-400 truncate">
            {data.error ?? 'Step failed'}
          </span>
        </div>
      )}
    </div>
  );
});

// AgentStepNode

export const AgentStepNode = memo(function AgentStepNode({
  data,
  selected,
}: NodeProps<AgentStepNodeData>) {
  const borderClasses = selected
    ? 'border-cyan-400 shadow-cyan-500/30 ring-2 ring-cyan-400/20'
    : statusBorderClasses(data.status, 'emerald');

  return (
    <div
      className={`bg-slate-800/90 border rounded-lg p-3 min-w-[200px] shadow-md transition-all relative group ${borderClasses}`}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!bg-cyan-400 !w-2.5 !h-2.5 !border-2 !border-slate-900"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!bg-cyan-400 !w-2.5 !h-2.5 !border-2 !border-slate-900"
      />

      {selected && data.onDelete && (
        <button
          onClick={(e) => { e.stopPropagation(); data.onDelete?.(); }}
          className="absolute -top-2 -right-2 w-5 h-5 bg-red-500 hover:bg-red-400 rounded-full flex items-center justify-center shadow-lg transition-colors z-10"
        >
          <X className="w-3 h-3 text-white" />
        </button>
      )}

      <div className="absolute -top-2 right-4 bg-cyan-500/20 text-cyan-400 text-[10px] font-semibold px-1.5 py-0.5 rounded-full leading-none">
        #{data.stepNumber}
      </div>

      <div className="flex items-center gap-2.5">
        <div className="w-8 h-8 rounded-md bg-cyan-500/10 flex items-center justify-center shrink-0">
          <Bot className="w-4 h-4 text-cyan-400" />
        </div>
        <div className="min-w-0">
          <p className="text-xs font-medium text-white truncate">{data.label}</p>
          <p className="text-[10px] text-slate-500 truncate">Agent Step</p>
        </div>
      </div>

      {/* Agent info */}
      <div className="mt-2 flex items-center gap-2">
        <span className="text-[10px] text-cyan-400/80">{data.model || 'claude-sonnet-4-5'}</span>
        {data.toolCount > 0 && (
          <span className="text-[10px] text-slate-500">{data.toolCount} tools</span>
        )}
      </div>

      {data.status === 'completed' && data.durationMs !== null && (
        <div className="mt-1 flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
          <span className="text-[10px] text-cyan-400">
            {formatDuration(data.durationMs)}
          </span>
        </div>
      )}

      {data.status === 'failed' && (
        <div className="mt-1 flex items-center gap-1">
          <AlertCircle className="w-3 h-3 text-red-400" />
          <span className="text-[10px] text-red-400 truncate">
            {data.error ?? 'Step failed'}
          </span>
        </div>
      )}
    </div>
  );
});

// SwitchNode — multi-branch routing node

interface SwitchNodeData {
  label: string;
  caseCount?: number;
  status?: string;
  onDelete?: () => void;
}

const SwitchNode = memo(({ data }: NodeProps<SwitchNodeData>) => {
  return (
    <div
      className={`relative min-w-[140px] rounded-xl border p-3 shadow-lg backdrop-blur-xl transition-all
        border-purple-500/30 bg-purple-900/20`}
    >
      <Handle type="target" position={Position.Left} className="!w-2.5 !h-2.5 !bg-purple-500 !border-purple-400" />
      <Handle type="source" position={Position.Right} id="default" className="!w-2.5 !h-2.5 !bg-purple-500 !border-purple-400" />
      <Handle type="source" position={Position.Bottom} id="case-0" className="!w-2.5 !h-2.5 !bg-cyan-500 !border-cyan-400" />

      {data.onDelete && (
        <button onClick={data.onDelete} className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-slate-700 border border-slate-600 flex items-center justify-center hover:bg-red-600/80 transition-colors z-10">
          <X className="w-2.5 h-2.5 text-slate-300" />
        </button>
      )}

      <div className="flex items-center gap-2">
        <div className="w-7 h-7 rounded-lg bg-purple-500/20 flex items-center justify-center">
          <Activity className="w-4 h-4 text-purple-400" />
        </div>
        <div>
          <p className="text-xs font-semibold text-slate-100 truncate max-w-[100px]">{data.label}</p>
          <p className="text-[9px] text-purple-400">
            Switch{data.caseCount ? ` (${data.caseCount} cases)` : ''}
          </p>
        </div>
      </div>
    </div>
  );
});
SwitchNode.displayName = 'SwitchNode';

// MergeNode — combine outputs from multiple branches

interface MergeNodeData {
  label: string;
  mode?: string;
  status?: string;
  onDelete?: () => void;
}

const MergeNode = memo(({ data }: NodeProps<MergeNodeData>) => {
  return (
    <div
      className={`relative min-w-[140px] rounded-xl border p-3 shadow-lg backdrop-blur-xl transition-all
        border-teal-500/30 bg-teal-900/20`}
    >
      <Handle type="target" position={Position.Left} className="!w-2.5 !h-2.5 !bg-teal-500 !border-teal-400" />
      <Handle type="source" position={Position.Right} className="!w-2.5 !h-2.5 !bg-teal-500 !border-teal-400" />

      {data.onDelete && (
        <button onClick={data.onDelete} className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-slate-700 border border-slate-600 flex items-center justify-center hover:bg-red-600/80 transition-colors z-10">
          <X className="w-2.5 h-2.5 text-slate-300" />
        </button>
      )}

      <div className="flex items-center gap-2">
        <div className="w-7 h-7 rounded-lg bg-teal-500/20 flex items-center justify-center">
          <Merge className="w-4 h-4 text-teal-400" />
        </div>
        <div>
          <p className="text-xs font-semibold text-slate-100 truncate max-w-[100px]">{data.label}</p>
          <p className="text-[9px] text-teal-400">
            Merge{data.mode ? ` (${data.mode})` : ''}
          </p>
        </div>
      </div>
    </div>
  );
});
MergeNode.displayName = 'MergeNode';

// Node type registry for React Flow

export const pipelineNodeTypes = {
  pipelineStep: PipelineStepNode,
  condition: ConditionNode,
  output: OutputNode,
  forEachStep: ForEachStepNode,
  agentStep: AgentStepNode,
  switchNode: SwitchNode,
  mergeNode: MergeNode,
};
