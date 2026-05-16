'use client';


import { useCallback, useEffect, useMemo, useRef, useState, memo } from 'react';
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
import {
  Activity, AlertTriangle, ArrowRight, Bot, Brain, CheckCircle2,
  ChevronRight, Clock, Code, Cpu, DollarSign, GitBranch, Loader2,
  Merge, Play, Shield, Square, TrendingUp, XCircle, Zap,
} from 'lucide-react';

// ─── Types ────────────────────────────────────────────────────────────────────

interface Blueprint {
  id: string;
  name: string;
  slug: string;
  icon: string;
  prompt: string;
  features: string[];
  cat: string;
  description: string;
  isPipeline: boolean;
}

interface Agent {
  id: string;
  name: string;
  slug: string;
  agent_type: string;
}

interface StreamStats {
  tokens: number;
  cost: number;
  duration: number;
  model: string;
}

interface NodeStatus {
  status: 'idle' | 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
  durationMs?: number;
  output?: unknown;
  error?: string;
}

interface Props {
  agents: Agent[];
  token: string;
  addLog: (msg: string) => void;
}

// ─── Blueprint Data ───────────────────────────────────────────────────────────

const BLUEPRINTS: Blueprint[] = [
  { id: 'repo', name: 'Repo Analyzer', slug: 'repo-analyzer', icon: '</>', cat: 'Engineering', isPipeline: true, prompt: 'Analyze the architecture and security of this repository', description: 'Multi-language code analysis pipeline with GitHub API integration', features: ['Pipeline', 'GitHub API', 'Multi-Lang'] },
  { id: 'ppa', name: 'Financial PPA', slug: 'ppa-contract-analyzer', icon: '$', cat: 'Finance', isPipeline: false, prompt: 'Analyze this PPA contract: calculate LCOE and assess risk', description: 'Power purchase agreement analysis with financial modeling', features: ['13 Tools', 'Risk Analyzer'] },
  { id: 'triage', name: 'Support Triage', slug: 'email-triager', icon: '?', cat: 'Operations', isPipeline: false, prompt: 'URGENT: Application crashes on file upload >50MB. Enterprise account.', description: 'Intelligent ticket classification and priority routing', features: ['Classification', 'Routing'] },
  { id: 'energy', name: 'Energy Risk', slug: 'energy-market-analyst', icon: '\u26A1', cat: 'Energy', isPipeline: false, prompt: 'Run Monte Carlo simulation on 150MW solar portfolio with VaR at 95%', description: 'Energy market analysis with Monte Carlo risk simulation', features: ['Monte Carlo', 'Financial Calc'] },
  { id: 'migration', name: 'Migration', slug: 'migration-orchestrator', icon: '\uD83D\uDD04', cat: 'Migration', isPipeline: false, prompt: 'Plan migration of FINANCE schema from Exasol to BigQuery', description: 'Database migration orchestration with sub-agents', features: ['Sub-Agents', 'Memory', 'HITL'] },
  { id: 'iot', name: 'IoT Monitor', slug: 'iot-sensor-monitor', icon: '\uD83D\uDCE1', cat: 'IoT', isPipeline: false, prompt: 'Monitor PUMP-001 sensors for temperature anomalies', description: 'Real-time IoT sensor monitoring with anomaly detection', features: ['Redis Streams', 'Time-Series'] },
  { id: 'fraud', name: 'Fraud Detector', slug: 'fraud-detector', icon: '\uD83D\uDEE1\uFE0F', cat: 'Finance', isPipeline: false, prompt: 'Check account ACC-12345 for fraud patterns', description: 'Transaction stream analysis with risk scoring', features: ['Event Streaming', 'Risk Scoring'] },
  { id: 'hipaa', name: 'HIPAA Processor', slug: 'hipaa-document-processor', icon: '\uD83C\uDFE5', cat: 'Healthcare', isPipeline: false, prompt: 'Process patient lab report, redact all PHI', description: 'HIPAA-compliant document processing with PII redaction', features: ['PII Redaction', 'FHIR'] },
  { id: 'fin-pipeline', name: 'Financial Pipeline', slug: 'financial-analysis-pipeline', icon: '\uD83D\uDCCA', cat: 'Pipeline', isPipeline: true, prompt: 'Analyze 10-K filing: extract tables and risk factors', description: '6-node parallel pipeline for financial document analysis', features: ['Pipeline DAG', 'Parallel', '6 Nodes'] },
  { id: 'support-pipeline', name: 'Support Pipeline', slug: 'customer-support-pipeline', icon: '\uD83C\uDFAF', cat: 'Pipeline', isPipeline: true, prompt: 'Triage production API 500 errors for enterprise customer', description: 'Multi-stage support pipeline with priority scoring', features: ['Pipeline DAG', 'Priority'] },
  { id: 'smart-routing', name: 'Smart Router', slug: 'smart-routing-pipeline', icon: '\uD83D\uDD00', cat: 'Pipeline', isPipeline: true, prompt: 'Route: "I was charged twice for my subscription last month"', description: 'LLM-powered classification with switch routing to 3 tracks', features: ['LLM Route', 'Switch', 'Merge'] },
  { id: 'quality-gate', name: 'Quality Gate', slug: 'quality-gate-pipeline', icon: '\u2705', cat: 'Pipeline', isPipeline: true, prompt: 'Analyze this software license agreement for completeness. Check if it covers: liability limitation, termination clauses, IP ownership, warranty disclaimers, and data protection. Flag any missing sections.', description: 'Analysis quality routing — thorough results auto-processed, incomplete flagged for review', features: ['Quality Gate', 'Auto/Review'] },
  { id: 'error-resilient', name: 'Error Resilient', slug: 'error-resilient-pipeline', icon: '\uD83D\uDEE1\uFE0F', cat: 'Pipeline', isPipeline: true, prompt: 'Fetch and analyze the latest news about Apple Inc stock performance and market outlook for Q2 2026', description: 'Fault-tolerant pipeline with timeouts and error branches', features: ['Timeout', 'Error Branch', 'Fallback'] },
  { id: 'stateful-sync', name: 'Stateful Sync', slug: 'stateful-sync-pipeline', icon: '\uD83D\uDD04', cat: 'Pipeline', isPipeline: true, prompt: 'Run incremental data sync batch: fetch new customer records since last cursor, process and summarize the batch, update cursor for next run', description: 'Cross-run state persistence with cursor tracking', features: ['State Persist', 'Code Node'] },
];

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const CAT_COLORS: Record<string, string> = {
  Engineering: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  Finance: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  Operations: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  Energy: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
  Migration: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
  IoT: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20',
  Healthcare: 'bg-pink-500/10 text-pink-400 border-pink-500/20',
  Pipeline: 'bg-teal-500/10 text-teal-400 border-teal-500/20',
};

// ─── Demo DAG Node Component (Standalone) ─────────────────────────────────────

interface DemoNodeData {
  label: string;
  toolName: string;
  status: string;
  durationMs?: number;
  error?: string;
  onClick?: () => void;
}

const DemoNode = memo(({ data }: NodeProps<DemoNodeData>) => {
  const borderColor = {
    idle: 'border-slate-700',
    pending: 'border-slate-500 border-dashed',
    running: 'border-yellow-400 animate-pulse shadow-lg shadow-yellow-500/20',
    completed: 'border-emerald-400',
    failed: 'border-red-400',
    skipped: 'border-slate-600 opacity-60',
  }[data.status] || 'border-slate-700';

  const StatusIcon = {
    idle: Clock,
    pending: Clock,
    running: Loader2,
    completed: CheckCircle2,
    failed: XCircle,
    skipped: Square,
  }[data.status] || Clock;

  const iconColor = {
    idle: 'text-slate-500',
    pending: 'text-slate-400',
    running: 'text-yellow-400 animate-spin',
    completed: 'text-emerald-400',
    failed: 'text-red-400',
    skipped: 'text-slate-500',
  }[data.status] || 'text-slate-500';

  return (
    <div
      className={`px-3 py-2 rounded-lg border bg-slate-800/80 backdrop-blur-sm min-w-[120px] cursor-pointer hover:brightness-110 transition-all ${borderColor}`}
      onClick={data.onClick}
    >
      <Handle type="target" position={Position.Left} className="!w-2 !h-2 !bg-slate-500" />
      <Handle type="source" position={Position.Right} className="!w-2 !h-2 !bg-slate-500" />
      <div className="flex items-center gap-2">
        <StatusIcon className={`w-3.5 h-3.5 shrink-0 ${iconColor}`} />
        <div className="min-w-0">
          <p className="text-[11px] font-medium text-slate-200 truncate">{data.label}</p>
          <p className="text-[9px] text-slate-500 truncate">{data.toolName}</p>
        </div>
      </div>
      {data.durationMs !== undefined && data.status === 'completed' && (
        <p className="text-[9px] text-emerald-400 mt-0.5">{data.durationMs}ms</p>
      )}
      {data.error && data.status === 'failed' && (
        <p className="text-[9px] text-red-400 mt-0.5 truncate">{data.error}</p>
      )}
    </div>
  );
});
DemoNode.displayName = 'DemoNode';

const nodeTypes = { demo: DemoNode };

// ─── Auto Layout ──────────────────────────────────────────────────────────────

function autoLayout(
  rawNodes: { id: string; tool_name: string; depends_on?: string[] }[],
  rawEdges: { source: string; target: string }[],
): { nodes: Node[]; edges: Edge[] } {
  // Topological sort into layers
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

  const X_GAP = 180;
  const Y_GAP = 70;
  const nodes: Node[] = [];
  for (let li = 0; li < layers.length; li++) {
    const layer = layers[li];
    const yStart = -(layer.length - 1) * Y_GAP / 2;
    for (let ni = 0; ni < layer.length; ni++) {
      const raw = nodeMap.get(layer[ni]);
      nodes.push({
        id: layer[ni],
        type: 'demo',
        position: { x: li * X_GAP, y: yStart + ni * Y_GAP },
        data: {
          label: layer[ni],
          toolName: raw?.tool_name || '?',
          status: 'idle',
        },
      });
    }
  }

  const edges: Edge[] = rawEdges.map((e, i) => ({
    id: `e-${i}`,
    source: e.source,
    target: e.target,
    animated: false,
    style: { stroke: '#475569', strokeWidth: 1.5 },
  }));

  return { nodes, edges };
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function BlueprintShowcase({ agents, token, addLog }: Props) {
  const [selected, setSelected] = useState<Blueprint | null>(null);
  const [rfNodes, setRfNodes] = useState<Node[]>([]);
  const [rfEdges, setRfEdges] = useState<Edge[]>([]);
  const [isExecuting, setIsExecuting] = useState(false);
  const [streamOutput, setStreamOutput] = useState('');
  const [toolCalls, setToolCalls] = useState<{ name: string; args: string; result?: string }[]>([]);
  const [streamStats, setStreamStats] = useState<StreamStats | null>(null);
  const [executionId, setExecutionId] = useState<string | null>(null);
  const [nodeStatuses, setNodeStatuses] = useState<Record<string, NodeStatus>>({});
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Find agent for a blueprint
  const getAgent = useCallback(
    (slug: string) => agents.find(a => a.slug === slug),
    [agents],
  );

  // Load pipeline config when a pipeline blueprint is selected
  useEffect(() => {
    if (!selected || !selected.isPipeline) {
      setRfNodes([]);
      setRfEdges([]);
      return;
    }
    const agent = getAgent(selected.slug);
    if (!agent) return;

    fetch(`${API_URL}/api/pipelines/${agent.id}/config`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.json())
      .then(body => {
        const config = body.data;
        if (config?.nodes) {
          const { nodes, edges } = autoLayout(config.nodes, config.edges || []);
          setRfNodes(nodes);
          setRfEdges(edges);
          // Initialize node statuses
          const statuses: Record<string, NodeStatus> = {};
          for (const n of config.nodes) {
            statuses[n.id] = { status: 'idle' };
          }
          setNodeStatuses(statuses);
        }
      })
      .catch(() => {});
  }, [selected, token, getAgent]);

  // Execute blueprint
  const executeBlueprint = useCallback(async () => {
    if (!selected) return;
    const agent = getAgent(selected.slug);
    if (!agent) {
      addLog(`Agent ${selected.slug} not found`);
      return;
    }

    setIsExecuting(true);
    setStreamOutput('');
    setToolCalls([]);
    setStreamStats(null);
    setExecutionId(null);
    setSelectedNodeId(null);

    // Reset node statuses to pending
    setNodeStatuses(prev => {
      const next = { ...prev };
      for (const key of Object.keys(next)) {
        next[key] = { status: 'pending' };
      }
      return next;
    });

    // Animate edges
    setRfEdges(prev => prev.map(e => ({ ...e, animated: true })));

    addLog(`Executing ${selected.name}...`);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch(`${API_URL}/api/agents/${agent.id}/execute`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ message: selected.prompt, stream: true }),
        signal: controller.signal,
      });

      if (!res.ok || !res.body) {
        const text = await res.text();
        addLog(`Execution failed: ${text.slice(0, 200)}`);
        setIsExecuting(false);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        let eventType = '';
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith('data: ') && eventType) {
            try {
              const data = JSON.parse(line.slice(6));

              if (eventType === 'token') {
                setStreamOutput(prev => prev + (data.text || ''));
              } else if (eventType === 'tool_call') {
                setToolCalls(prev => [...prev, { name: data.name, args: JSON.stringify(data.arguments || {}) }]);
              } else if (eventType === 'tool_result') {
                setToolCalls(prev => {
                  const copy = [...prev];
                  const last = copy.findLast(tc => tc.name === data.name);
                  if (last) last.result = typeof data.result === 'string' ? data.result.slice(0, 500) : JSON.stringify(data.result).slice(0, 500);
                  return copy;
                });
              } else if (eventType === 'node_start') {
                setNodeStatuses(prev => ({
                  ...prev,
                  [data.node_id]: { status: 'running' },
                }));
                setRfNodes(prev => prev.map(n =>
                  n.id === data.node_id
                    ? { ...n, data: { ...n.data, status: 'running' } }
                    : n
                ));
                addLog(`Node ${data.node_id} started (${data.tool_name})`);
              } else if (eventType === 'node_complete') {
                const st = data.status === 'completed' ? 'completed' : data.status === 'skipped' ? 'skipped' : 'failed';
                setNodeStatuses(prev => ({
                  ...prev,
                  [data.node_id]: { status: st, durationMs: data.duration_ms },
                }));
                setRfNodes(prev => prev.map(n =>
                  n.id === data.node_id
                    ? { ...n, data: { ...n.data, status: st, durationMs: data.duration_ms } }
                    : n
                ));
                addLog(`Node ${data.node_id} ${st} (${data.duration_ms}ms)`);
              } else if (eventType === 'done') {
                setStreamStats({
                  tokens: (data.input_tokens || 0) + (data.output_tokens || 0) + (data.total_tokens || 0),
                  cost: data.cost || 0,
                  duration: data.duration_ms || 0,
                  model: data.model || 'pipeline',
                });
                if (data.execution_id) setExecutionId(data.execution_id);
                addLog(`Execution complete (${data.duration_ms}ms)`);
              } else if (eventType === 'error') {
                addLog(`Error: ${data.message}`);
              }
            } catch { /* skip unparseable events */ }
            eventType = '';
          }
        }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        addLog('Execution cancelled');
      } else {
        addLog(`Error: ${err instanceof Error ? err.message : 'Unknown'}`);
      }
    } finally {
      setIsExecuting(false);
      setRfEdges(prev => prev.map(e => ({ ...e, animated: false })));
    }
  }, [selected, token, addLog, getAgent]);

  const stopExecution = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  // Update RF nodes with click handlers
  const nodesWithHandlers = useMemo(() =>
    rfNodes.map(n => ({
      ...n,
      data: {
        ...n.data,
        onClick: () => setSelectedNodeId(n.id),
      },
    })),
    [rfNodes],
  );

  const selectedNode = selectedNodeId ? nodeStatuses[selectedNodeId] : null;

  return (
    <div className="space-y-6">
      {/* Blueprint Grid */}
      {!selected && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {BLUEPRINTS.map(bp => {
            const agent = getAgent(bp.slug);
            return (
              <button
                key={bp.id}
                onClick={() => {
                  setSelected(bp);
                  setStreamOutput('');
                  setToolCalls([]);
                  setStreamStats(null);
                  setExecutionId(null);
                }}
                className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4 text-left hover:border-cyan-500/40 transition-all group"
              >
                <div className="flex items-start justify-between mb-2">
                  <span className="text-xl">{bp.icon}</span>
                  <span className={`text-[9px] px-2 py-0.5 rounded-full border ${CAT_COLORS[bp.cat] || 'bg-slate-700/50 text-slate-400'}`}>
                    {bp.cat}
                  </span>
                </div>
                <h3 className="text-sm font-semibold text-white group-hover:text-cyan-400 transition-colors">{bp.name}</h3>
                <p className="text-[11px] text-slate-500 mt-1 line-clamp-2">{bp.description}</p>
                <div className="flex flex-wrap gap-1 mt-2">
                  {bp.features.map(f => (
                    <span key={f} className="text-[8px] px-1.5 py-0.5 bg-cyan-500/10 text-cyan-400 rounded">{f}</span>
                  ))}
                </div>
                <div className="flex items-center justify-between mt-3">
                  <span className="text-[10px] text-slate-600">
                    {bp.isPipeline ? 'Pipeline DAG' : 'AI Agent'}
                  </span>
                  {!agent && <span className="text-[9px] text-amber-500">Not seeded</span>}
                </div>
              </button>
            );
          })}
        </div>
      )}

      {/* Execution Viewer */}
      {selected && (
        <div className="space-y-4">
          {/* Header */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <button
                onClick={() => { setSelected(null); setStreamOutput(''); setToolCalls([]); setStreamStats(null); }}
                className="text-slate-400 hover:text-white transition-colors"
              >
                <ChevronRight className="w-4 h-4 rotate-180" />
              </button>
              <span className="text-xl">{selected.icon}</span>
              <div>
                <h3 className="text-sm font-semibold text-white">{selected.name}</h3>
                <p className="text-[11px] text-slate-500">{selected.description}</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {executionId && (
                <a
                  href={`/executions/${executionId}`}
                  className="text-[10px] text-cyan-400 hover:text-cyan-300 flex items-center gap-1"
                >
                  Flight Recorder <ArrowRight className="w-3 h-3" />
                </a>
              )}
              {!isExecuting ? (
                <button
                  onClick={executeBlueprint}
                  disabled={!getAgent(selected.slug)}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-xs font-medium rounded-lg hover:opacity-90 disabled:opacity-40"
                >
                  <Play className="w-3 h-3" /> Execute
                </button>
              ) : (
                <button
                  onClick={stopExecution}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-red-500/20 text-red-400 text-xs font-medium rounded-lg hover:bg-red-500/30 border border-red-500/30"
                >
                  <Square className="w-3 h-3" /> Stop
                </button>
              )}
            </div>
          </div>

          {/* Prompt */}
          <div className="bg-slate-900/50 rounded-lg p-3 border border-slate-700/30">
            <p className="text-[10px] text-slate-500 mb-1">Prompt</p>
            <p className="text-xs text-slate-300">{selected.prompt}</p>
          </div>

          {/* Pipeline DAG (only for pipeline blueprints) */}
          {selected.isPipeline && rfNodes.length > 0 && (
            <div className="bg-slate-900/50 rounded-xl border border-slate-700/30 overflow-hidden" style={{ height: 300 }}>
              <ReactFlow
                nodes={nodesWithHandlers}
                edges={rfEdges}
                nodeTypes={nodeTypes}
                fitView
                fitViewOptions={{ padding: 0.3 }}
                panOnScroll
                zoomOnScroll={false}
                nodesDraggable={false}
                nodesConnectable={false}
                proOptions={{ hideAttribution: true }}
              >
                <Background color="#1e293b" gap={20} size={1} />
                <Controls
                  showInteractive={false}
                  position="bottom-right"
                  style={{ background: '#1e293b', borderColor: '#334155', borderRadius: 8 }}
                />
              </ReactFlow>
            </div>
          )}

          {/* Node Detail Panel */}
          {selectedNodeId && selectedNode && (
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-lg p-3">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-white font-mono">{selectedNodeId}</span>
                  <span className={`text-[9px] px-1.5 py-0.5 rounded ${
                    selectedNode.status === 'completed' ? 'bg-emerald-500/10 text-emerald-400'
                    : selectedNode.status === 'failed' ? 'bg-red-500/10 text-red-400'
                    : selectedNode.status === 'running' ? 'bg-yellow-500/10 text-yellow-400'
                    : 'bg-slate-700/50 text-slate-400'
                  }`}>{selectedNode.status}</span>
                </div>
                {selectedNode.durationMs !== undefined && (
                  <span className="text-[10px] text-slate-500">{selectedNode.durationMs}ms</span>
                )}
              </div>
              {selectedNode.error && (
                <pre className="text-[10px] text-red-300 bg-red-500/5 rounded p-2 overflow-x-auto">{selectedNode.error}</pre>
              )}
            </div>
          )}

          {/* Stats */}
          {streamStats && (
            <div className="grid grid-cols-4 gap-2">
              {[
                { icon: Cpu, label: 'Tokens', value: streamStats.tokens.toLocaleString() },
                { icon: DollarSign, label: 'Cost', value: `$${streamStats.cost.toFixed(4)}` },
                { icon: Clock, label: 'Duration', value: `${(streamStats.duration / 1000).toFixed(1)}s` },
                { icon: Brain, label: 'Model', value: streamStats.model },
              ].map(s => (
                <div key={s.label} className="bg-slate-900/50 rounded-lg p-2 text-center border border-slate-700/30">
                  <s.icon className="w-4 h-4 mx-auto mb-1 text-cyan-400" />
                  <p className="text-[10px] text-slate-500">{s.label}</p>
                  <p className="text-xs text-white font-medium">{s.value}</p>
                </div>
              ))}
            </div>
          )}

          {/* Tool Calls */}
          {toolCalls.length > 0 && (
            <div className="bg-slate-900/50 rounded-lg p-3 border border-slate-700/30">
              <p className="text-[10px] text-slate-500 mb-2">Tool Calls ({toolCalls.length})</p>
              <div className="flex flex-wrap gap-1">
                {toolCalls.map((tc, i) => (
                  <span key={i} className="text-[9px] px-2 py-0.5 bg-cyan-500/10 text-cyan-400 rounded">
                    {tc.name}{tc.result ? ' \u2713' : ''}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Streaming Output */}
          {(streamOutput || isExecuting) && (
            <div className="bg-slate-900/50 rounded-lg p-3 border border-slate-700/30">
              <p className="text-[10px] text-slate-500 mb-2">
                Output {isExecuting && <Loader2 className="w-3 h-3 inline animate-spin ml-1" />}
              </p>
              <pre className="text-[11px] text-slate-300 font-mono whitespace-pre-wrap max-h-60 overflow-y-auto">
                {streamOutput || 'Waiting for response...'}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
