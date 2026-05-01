'use client';

import { memo } from 'react';
import { Handle, Position, type NodeProps } from 'reactflow';
import { Bot, Wrench, Database, Plug, Cpu, X, Star, Shield, Hash, Settings2 } from 'lucide-react';

export interface AgentNodeData {
  name: string;
  model: string;
  status: string;
  toolCount?: number;
  configuredToolCount?: number;
  inputParamCount?: number;
}

export interface ToolNodeData {
  name: string;
  description: string;
  configured: boolean;
  configStatus?: 'configured' | 'default';
  maxCalls?: number;
  requireApproval?: boolean;
  onDelete?: () => void;
}

export interface KnowledgeNodeData {
  name: string;
  docCount: number;
  onDelete?: () => void;
}

export interface MCPNodeData {
  name: string;
  healthy: boolean;
  toolCount: number;
  suggested?: boolean;
  onDelete?: () => void;
}

export const AgentNode = memo(function AgentNode({ data, selected }: NodeProps<AgentNodeData>) {
  return (
    <div
      className={`bg-slate-800/90 border-2 rounded-xl p-4 min-w-[220px] shadow-lg transition-all ${
        selected
          ? 'border-cyan-400 shadow-cyan-500/30 ring-2 ring-cyan-400/20'
          : 'border-cyan-500/50 shadow-cyan-500/10'
      }`}
    >
      <Handle type="target" position={Position.Left} className="!bg-cyan-400 !w-3 !h-3 !border-2 !border-slate-900" />
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-cyan-500 to-purple-600 flex items-center justify-center shrink-0">
          <Bot className="w-5 h-5 text-white" />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-white truncate">{data.name || 'New Agent'}</p>
          <div className="flex items-center gap-1.5 mt-0.5">
            <Cpu className="w-3 h-3 text-slate-500" />
            <span className="text-[10px] font-mono text-slate-400 truncate">
              {(data.model || 'claude-sonnet').replace(/-\d{8}$/, '')}
            </span>
          </div>
        </div>
      </div>
      {/* Summary badges */}
      {((data.toolCount && data.toolCount > 0) || (data.inputParamCount && data.inputParamCount > 0)) && (
        <div className="flex items-center gap-2 mt-2.5 pt-2 border-t border-slate-700/50">
          {data.toolCount !== undefined && data.toolCount > 0 && (
            <span className="text-[9px] text-slate-400 bg-slate-700/50 px-1.5 py-0.5 rounded-full">
              {data.toolCount} tools
              {data.configuredToolCount ? ` (${data.configuredToolCount} configured)` : ''}
            </span>
          )}
          {data.inputParamCount !== undefined && data.inputParamCount > 0 && (
            <span className="text-[9px] text-cyan-400/80 bg-cyan-500/10 px-1.5 py-0.5 rounded-full">
              {data.inputParamCount} input params
            </span>
          )}
        </div>
      )}
      <Handle type="source" position={Position.Right} className="!bg-cyan-400 !w-3 !h-3 !border-2 !border-slate-900" />
    </div>
  );
});

export const ToolNode = memo(function ToolNode({ data, selected }: NodeProps<ToolNodeData>) {
  const isConfigured = data.configStatus === 'configured';
  const borderColor = selected
    ? 'border-cyan-400 shadow-cyan-500/20 ring-2 ring-cyan-400/20'
    : isConfigured
      ? 'border-emerald-500/40'
      : 'border-slate-700';

  return (
    <div
      className={`bg-slate-800/90 border rounded-lg p-3 min-w-[180px] shadow-md transition-all relative group ${borderColor}`}
    >
      <Handle type="target" position={Position.Left} className="!bg-cyan-400 !w-2.5 !h-2.5 !border-2 !border-slate-900" />
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
      <div className="flex items-center gap-2.5">
        <div className={`w-8 h-8 rounded-md flex items-center justify-center shrink-0 ${
          isConfigured ? 'bg-emerald-500/10' : 'bg-cyan-500/10'
        }`}>
          <Wrench className={`w-4 h-4 ${isConfigured ? 'text-emerald-400' : 'text-cyan-400'}`} />
        </div>
        <div className="min-w-0">
          <p className="text-xs font-medium text-white truncate">{data.name}</p>
          <p className="text-[10px] text-slate-500 truncate">{data.description}</p>
        </div>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <div className="flex items-center gap-1">
          <span className={`w-1.5 h-1.5 rounded-full ${isConfigured ? 'bg-emerald-400' : 'bg-slate-500'}`} />
          <span className={`text-[10px] ${isConfigured ? 'text-emerald-400' : 'text-slate-500'}`}>
            {isConfigured ? 'configured' : 'default'}
          </span>
        </div>
        {data.maxCalls && data.maxCalls > 0 ? (
          <span className="flex items-center gap-0.5 text-[9px] text-amber-400/80 bg-amber-500/10 px-1.5 py-0.5 rounded-full">
            <Hash className="w-2.5 h-2.5" />
            {data.maxCalls}
          </span>
        ) : null}
        {data.requireApproval ? (
          <span className="flex items-center gap-0.5 text-[9px] text-purple-400/80 bg-purple-500/10 px-1.5 py-0.5 rounded-full">
            <Shield className="w-2.5 h-2.5" />
            HITL
          </span>
        ) : null}
        {!isConfigured && (
          <span className="ml-auto flex items-center gap-0.5 text-[9px] text-slate-600">
            <Settings2 className="w-2.5 h-2.5" />
            click to configure
          </span>
        )}
      </div>
      <Handle type="source" position={Position.Right} className="!bg-cyan-400 !w-2.5 !h-2.5 !border-2 !border-slate-900" />
    </div>
  );
});

export const KnowledgeNode = memo(function KnowledgeNode({ data, selected }: NodeProps<KnowledgeNodeData>) {
  return (
    <div
      className={`bg-slate-800/90 border rounded-lg p-3 min-w-[160px] shadow-md transition-all relative ${
        selected
          ? 'border-purple-400 shadow-purple-500/20 ring-2 ring-purple-400/20'
          : 'border-slate-700'
      }`}
    >
      <Handle type="target" position={Position.Left} className="!bg-purple-400 !w-2.5 !h-2.5 !border-2 !border-slate-900" />
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
      <div className="flex items-center gap-2.5">
        <div className="w-8 h-8 rounded-md bg-purple-500/10 flex items-center justify-center shrink-0">
          <Database className="w-4 h-4 text-purple-400" />
        </div>
        <div className="min-w-0">
          <p className="text-xs font-medium text-white truncate">{data.name}</p>
          <p className="text-[10px] text-slate-500">{data.docCount} documents</p>
        </div>
      </div>
    </div>
  );
});

export const MCPNode = memo(function MCPNode({ data, selected }: NodeProps<MCPNodeData>) {
  return (
    <div
      className={`bg-slate-800/90 border rounded-lg p-3 min-w-[160px] shadow-md transition-all relative ${
        selected
          ? 'border-amber-400 shadow-amber-500/20 ring-2 ring-amber-400/20'
          : 'border-slate-700'
      }`}
    >
      <Handle type="target" position={Position.Left} className="!bg-amber-400 !w-2.5 !h-2.5 !border-2 !border-slate-900" />
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
      {data.suggested && (
        <div className="absolute -top-1.5 -left-1.5 w-5 h-5 bg-amber-500 rounded-full flex items-center justify-center shadow-md z-10" title="Suggested server">
          <Star className="w-3 h-3 text-white fill-white" />
        </div>
      )}
      <div className="flex items-center gap-2.5">
        <div className="w-8 h-8 rounded-md bg-amber-500/10 flex items-center justify-center shrink-0">
          <Plug className="w-4 h-4 text-amber-400" />
        </div>
        <div className="min-w-0">
          <p className="text-xs font-medium text-white truncate">{data.name}</p>
          <p className="text-[10px] text-slate-500">{data.toolCount} tools</p>
        </div>
      </div>
      <div className="mt-2 flex items-center gap-1">
        <span className={`w-1.5 h-1.5 rounded-full ${data.healthy ? 'bg-emerald-400' : 'bg-red-400'}`} />
        <span className={`text-[10px] ${data.healthy ? 'text-emerald-400' : 'text-red-400'}`}>
          {data.healthy ? 'connected' : 'disconnected'}
        </span>
      </div>
    </div>
  );
});

export const nodeTypes = {
  agent: AgentNode,
  tool: ToolNode,
  knowledge: KnowledgeNode,
  mcp: MCPNode,
};
