'use client';

/**
 * PipelineDAGPreview — Readonly pipeline DAG visualization.
 *
 * Standalone component (no builder imports) that fetches a pipeline agent's
 * config and renders it as a React Flow DAG. Used on marketplace detail,
 * agent info, and anywhere a pipeline topology needs to be shown.
 */

import { useEffect, useState, memo } from 'react';
import ReactFlow, {
  Background,
  Controls,
  Handle,
  Position,
  type Node,
  type Edge,
  type NodeProps,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { CheckCircle2, Clock, Loader2, XCircle } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// ─── Node Component ───────────────────────────────────────────────────────────

interface DAGNodeData {
  label: string;
  toolName: string;
  status?: string;
}

const DAGNode = memo(({ data }: NodeProps<DAGNodeData>) => {
  const toolColor: Record<string, string> = {
    llm_call: 'border-purple-500/40 bg-purple-900/20',
    llm_route: 'border-purple-500/40 bg-purple-900/20',
    agent_step: 'border-purple-500/40 bg-purple-900/20',
    __switch__: 'border-amber-500/40 bg-amber-900/20',
    __merge__: 'border-teal-500/40 bg-teal-900/20',
    human_approval: 'border-red-500/40 bg-red-900/20',
    web_search: 'border-cyan-500/40 bg-cyan-900/20',
    code_executor: 'border-blue-500/40 bg-blue-900/20',
    state_get: 'border-slate-500/40 bg-slate-800/40',
    state_set: 'border-slate-500/40 bg-slate-800/40',
  };
  const style = toolColor[data.toolName] || 'border-emerald-500/40 bg-emerald-900/20';

  return (
    <div className={`px-3 py-2 rounded-lg border min-w-[110px] backdrop-blur-sm ${style}`}>
      <Handle type="target" position={Position.Left} className="!w-1.5 !h-1.5 !bg-slate-500" />
      <Handle type="source" position={Position.Right} className="!w-1.5 !h-1.5 !bg-slate-500" />
      <p className="text-[10px] font-medium text-slate-200 truncate">{data.label}</p>
      <p className="text-[8px] text-slate-500 truncate">{data.toolName}</p>
    </div>
  );
});
DAGNode.displayName = 'DAGNode';

const nodeTypes = { dag: DAGNode };

// ─── Auto Layout ──────────────────────────────────────────────────────────────

function autoLayout(
  rawNodes: { id: string; tool_name: string; depends_on?: string[] }[],
  rawEdges: { source: string; target: string }[],
): { nodes: Node[]; edges: Edge[] } {
  const nodeMap = new Map(rawNodes.map(n => [n.id, n]));
  const inDegree = new Map<string, number>();
  const adj = new Map<string, string[]>();
  for (const n of rawNodes) {
    inDegree.set(n.id, 0);
    adj.set(n.id, []);
  }
  for (const e of rawEdges) {
    adj.get(e.source)?.push(e.target);
    inDegree.set(e.target, (inDegree.get(e.target) || 0) + 1);
  }

  const layers: string[][] = [];
  let queue = [...inDegree.entries()].filter(([, d]) => d === 0).map(([id]) => id);
  while (queue.length > 0) {
    layers.push([...queue]);
    const next: string[] = [];
    for (const id of queue) {
      for (const child of adj.get(id) || []) {
        const d = (inDegree.get(child) || 1) - 1;
        inDegree.set(child, d);
        if (d === 0) next.push(child);
      }
    }
    queue = next;
  }

  const X_GAP = 160;
  const Y_GAP = 60;
  const nodes: Node[] = [];
  for (let li = 0; li < layers.length; li++) {
    const layer = layers[li];
    const yStart = -(layer.length - 1) * Y_GAP / 2;
    for (let ni = 0; ni < layer.length; ni++) {
      const raw = nodeMap.get(layer[ni]);
      nodes.push({
        id: layer[ni],
        type: 'dag',
        position: { x: li * X_GAP, y: yStart + ni * Y_GAP },
        data: { label: layer[ni], toolName: raw?.tool_name || '?' },
      });
    }
  }

  const edges: Edge[] = rawEdges.map((e, i) => ({
    id: `e-${i}`,
    source: e.source,
    target: e.target,
    style: { stroke: '#475569', strokeWidth: 1.5 },
  }));

  return { nodes, edges };
}

// ─── Main Component ───────────────────────────────────────────────────────────

interface PipelineDAGPreviewProps {
  agentId: string;
  token: string;
  height?: number;
  className?: string;
}

export default function PipelineDAGPreview({ agentId, token, height = 220, className = '' }: PipelineDAGPreviewProps) {
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!agentId || !token) return;

    fetch(`${API_URL}/api/pipelines/${agentId}/config`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.json())
      .then(body => {
        const config = body.data;
        if (config?.nodes) {
          const { nodes: n, edges: e } = autoLayout(config.nodes, config.edges || []);
          setNodes(n);
          setEdges(e);
        } else {
          setError('No pipeline configuration');
        }
      })
      .catch(() => setError('Failed to load pipeline'))
      .finally(() => setLoading(false));
  }, [agentId, token]);

  if (loading) {
    return (
      <div className={`flex items-center justify-center bg-slate-900/30 rounded-xl border border-slate-700/30 ${className}`} style={{ height }}>
        <Loader2 className="w-5 h-5 text-slate-500 animate-spin" />
      </div>
    );
  }

  if (error || nodes.length === 0) {
    return null; // Don't show anything if not a pipeline or config unavailable
  }

  return (
    <div className={`bg-slate-900/30 rounded-xl border border-slate-700/30 overflow-hidden ${className}`} style={{ height }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        panOnScroll
        zoomOnScroll={false}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#1e293b" gap={20} size={1} />
      </ReactFlow>
      <div className="px-3 py-1.5 border-t border-slate-700/30 flex items-center gap-2 text-[9px] text-slate-500">
        <span>{nodes.length} nodes</span>
        <span>|</span>
        <span>{edges.length} connections</span>
        <span>|</span>
        <span>Pipeline DAG</span>
      </div>
    </div>
  );
}
