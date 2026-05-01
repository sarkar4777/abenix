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
  Activity, ArrowRight, Bot, CheckCircle2, ChevronDown, ChevronRight,
  Clock, Code, DollarSign, GitBranch, Loader2, Play, Search,
  Square, XCircle, Zap, FileText, Hash, ToggleLeft, Link2, List,
} from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// ─── Types ──────────────────────────────────────────────────────────────────

interface Agent {
  id: string;
  name: string;
  slug: string;
  description: string;
  category: string;
  status: string;
  mode?: string;
  input_variables?: InputVariable[];
  pipeline_config?: {
    nodes: PipelineNode[];
    edges: { source: string; target: string; id?: string }[];
  };
}

interface InputVariable {
  name: string;
  type: string;
  description: string;
  required: boolean;
  options?: string[];
  default?: string;
}

interface PipelineNode {
  id: string;
  tool_name: string;
  label?: string;
  depends_on?: string[];
  arguments?: Record<string, unknown>;
}

type NodeStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped';

interface ExecutionState {
  isRunning: boolean;
  executionId: string | null;
  nodeStatuses: Record<string, NodeStatus>;
  nodeResults: Record<string, { output?: string; error?: string; durationMs?: number }>;
  streamOutput: string;
  toolCalls: { name: string; args: string; result?: string }[];
  stats: { tokens: number; cost: number; durationMs: number };
}

// ─── Pipeline DAG Node Component ────────────────────────────────────────────

const PipelineStepNode = memo(({ data }: NodeProps) => {
  const statusColors: Record<NodeStatus, string> = {
    pending: 'border-slate-600 bg-slate-800/80',
    running: 'border-cyan-500 bg-cyan-500/10 ring-2 ring-cyan-500/30',
    completed: 'border-emerald-500 bg-emerald-500/10',
    failed: 'border-red-500 bg-red-500/10',
    skipped: 'border-slate-700 bg-slate-900/50 opacity-50',
  };
  const status: NodeStatus = data.status || 'pending';
  const StatusIcon = status === 'running' ? Loader2
    : status === 'completed' ? CheckCircle2
    : status === 'failed' ? XCircle
    : status === 'skipped' ? Square
    : Clock;

  return (
    <div className={`px-4 py-3 rounded-xl border-2 min-w-[160px] transition-all duration-300 ${statusColors[status]}`}>
      <Handle type="target" position={Position.Left} className="!w-2 !h-2 !bg-slate-500" />
      <div className="flex items-center gap-2">
        <StatusIcon className={`w-4 h-4 shrink-0 ${status === 'running' ? 'animate-spin text-cyan-400' : status === 'completed' ? 'text-emerald-400' : status === 'failed' ? 'text-red-400' : 'text-slate-500'}`} />
        <div className="min-w-0">
          <p className="text-xs font-semibold text-white truncate">{data.label}</p>
          <p className="text-[9px] text-slate-500 truncate">{data.toolName}</p>
        </div>
      </div>
      {data.durationMs != null && (
        <p className="text-[9px] text-slate-500 mt-1">{data.durationMs}ms</p>
      )}
      <Handle type="source" position={Position.Right} className="!w-2 !h-2 !bg-slate-500" />
    </div>
  );
});
PipelineStepNode.displayName = 'PipelineStepNode';

const nodeTypes = { pipelineStep: PipelineStepNode };

// ─── Helpers ────────────────────────────────────────────────────────────────

function buildDagFromConfig(pipeline: Agent['pipeline_config'], statuses: Record<string, NodeStatus>, results: Record<string, { durationMs?: number }>) {
  if (!pipeline?.nodes?.length) return { nodes: [] as Node[], edges: [] as Edge[] };

  // Topological layout
  const adj = new Map<string, string[]>();
  const inDeg = new Map<string, number>();
  for (const n of pipeline.nodes) { adj.set(n.id, []); inDeg.set(n.id, 0); }
  for (const e of (pipeline.edges || [])) {
    adj.get(e.source)?.push(e.target);
    inDeg.set(e.target, (inDeg.get(e.target) || 0) + 1);
  }
  for (const n of pipeline.nodes) {
    for (const dep of (n.depends_on || [])) {
      if (!adj.get(dep)?.includes(n.id)) {
        adj.get(dep)?.push(n.id);
        inDeg.set(n.id, (inDeg.get(n.id) || 0) + 1);
      }
    }
  }

  const layers: string[][] = [];
  let queue = [...inDeg.entries()].filter(([, d]) => d === 0).map(([id]) => id);
  while (queue.length > 0) {
    layers.push([...queue]);
    const next: string[] = [];
    for (const id of queue) {
      for (const child of (adj.get(id) || [])) {
        const d = (inDeg.get(child) || 1) - 1;
        inDeg.set(child, d);
        if (d === 0) next.push(child);
      }
    }
    queue = next;
  }

  const X_GAP = 240;
  const Y_GAP = 100;
  const posMap: Record<string, { x: number; y: number }> = {};
  for (let li = 0; li < layers.length; li++) {
    for (let ni = 0; ni < layers[li].length; ni++) {
      posMap[layers[li][ni]] = { x: 50 + li * X_GAP, y: 50 + ni * Y_GAP };
    }
  }

  const nodes: Node[] = pipeline.nodes.map((n) => ({
    id: n.id,
    type: 'pipelineStep',
    position: posMap[n.id] || { x: 50, y: 50 },
    data: {
      label: n.label || n.id.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase()),
      toolName: n.tool_name,
      status: statuses[n.id] || 'pending',
      durationMs: results[n.id]?.durationMs,
    },
  }));

  const edgeSet = new Set<string>();
  const edges: Edge[] = [];
  for (const e of (pipeline.edges || [])) {
    const key = `${e.source}-${e.target}`;
    if (!edgeSet.has(key)) {
      edgeSet.add(key);
      edges.push({ id: e.id || `e-${key}`, source: e.source, target: e.target, style: { stroke: '#10B981', strokeWidth: 2 }, animated: statuses[e.target] === 'running' || statuses[e.source] === 'running' });
    }
  }
  for (const n of pipeline.nodes) {
    for (const dep of (n.depends_on || [])) {
      const key = `${dep}-${n.id}`;
      if (!edgeSet.has(key)) {
        edgeSet.add(key);
        edges.push({ id: `e-${key}`, source: dep, target: n.id, style: { stroke: '#10B981', strokeWidth: 2 }, animated: statuses[n.id] === 'running' || statuses[dep] === 'running' });
      }
    }
  }

  return { nodes, edges };
}

// ─── Input Field Component ──────────────────────────────────────────────────

function InputField({ variable, value, onChange }: { variable: InputVariable; value: string; onChange: (v: string) => void }) {
  const iconMap: Record<string, typeof FileText> = {
    string: FileText, number: Hash, boolean: ToggleLeft, url: Link2, file: FileText, select: List,
  };
  const Icon = iconMap[variable.type] || FileText;

  if (variable.type === 'select' && variable.options) {
    return (
      <div>
        <label className="flex items-center gap-1.5 text-xs font-medium text-slate-300 mb-1">
          <Icon className="w-3 h-3 text-slate-500" />
          {variable.name}{variable.required && <span className="text-red-400">*</span>}
        </label>
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500"
        >
          <option value="">Select...</option>
          {variable.options.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        {variable.description && <p className="text-[9px] text-slate-600 mt-0.5">{variable.description}</p>}
      </div>
    );
  }

  if (variable.type === 'boolean') {
    return (
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={value === 'true'}
          onChange={(e) => onChange(e.target.checked ? 'true' : 'false')}
          className="w-4 h-4 rounded border-slate-600 bg-slate-900 text-cyan-500 focus:ring-cyan-500"
        />
        <span className="text-xs text-slate-300">{variable.name}{variable.required && <span className="text-red-400">*</span>}</span>
        {variable.description && <span className="text-[9px] text-slate-600">— {variable.description}</span>}
      </label>
    );
  }

  return (
    <div>
      <label className="flex items-center gap-1.5 text-xs font-medium text-slate-300 mb-1">
        <Icon className="w-3 h-3 text-slate-500" />
        {variable.name}{variable.required && <span className="text-red-400">*</span>}
      </label>
      <input
        type={variable.type === 'number' ? 'number' : 'text'}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={variable.description || `Enter ${variable.name}...`}
        className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-white placeholder:text-slate-600 focus:outline-none focus:border-cyan-500"
      />
      {variable.description && <p className="text-[9px] text-slate-600 mt-0.5">{variable.description}</p>}
    </div>
  );
}

// ─── Main PlayArea Component ────────────────────────────────────────────────

export default function PlayArea() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [inputValues, setInputValues] = useState<Record<string, string>>({});
  const [freeformPrompt, setFreeformPrompt] = useState('');
  const [execution, setExecution] = useState<ExecutionState>({
    isRunning: false, executionId: null, nodeStatuses: {}, nodeResults: {},
    streamOutput: '', toolCalls: [], stats: { tokens: 0, cost: 0, durationMs: 0 },
  });
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [showPicker, setShowPicker] = useState(true);
  const outputRef = useRef<HTMLDivElement>(null);

  // Load agents — extract input_variables and pipeline_config from model_config
  // Small delay to let the parent's agent load settle (avoids concurrent 401 race)
  useEffect(() => {
    const timer = setTimeout(async () => {
      const token = localStorage.getItem('access_token');
      if (!token) { setLoading(false); return; }
      // Retry once on failure (token refresh may be in-flight)
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          const freshToken = localStorage.getItem('access_token') || token;
          const r = await fetch(`${API_URL}/api/agents?limit=100&sort=name`, {
            headers: { Authorization: `Bearer ${freshToken}` },
          });
          if (r.ok) {
            const body = await r.json();
            const raw = (body.data || []).filter((a: Record<string, unknown>) => a.status === 'active');
            const list: Agent[] = raw.map((a: Record<string, unknown>) => {
              const mc = (a.model_config || {}) as Record<string, unknown>;
              return {
                id: a.id as string,
                name: a.name as string,
                slug: a.slug as string,
                description: a.description as string,
                category: a.category as string,
                status: a.status as string,
                mode: (mc.mode as string) || undefined,
                input_variables: (mc.input_variables as InputVariable[]) || [],
                pipeline_config: (mc.pipeline_config as Agent['pipeline_config']) || undefined,
              };
            });
            setAgents(list);
            break;
          }
          if (attempt === 0) await new Promise((r) => setTimeout(r, 1500));
        } catch { /* retry */ }
      }
      setLoading(false);
    }, 1000);
    return () => clearTimeout(timer);
  }, []);

  // Filtered agents
  const filtered = useMemo(() => {
    if (!search.trim()) return agents;
    const q = search.toLowerCase();
    return agents.filter((a) => a.name.toLowerCase().includes(q) || a.category?.toLowerCase().includes(q) || a.description?.toLowerCase().includes(q));
  }, [agents, search]);

  // Select an agent — fetch full detail to get complete config
  const selectAgent = useCallback(async (agent: Agent) => {
    setShowPicker(false);
    setInputValues({});
    setFreeformPrompt('');
    setSelectedNodeId(null);
    setExecution({ isRunning: false, executionId: null, nodeStatuses: {}, nodeResults: {}, streamOutput: '', toolCalls: [], stats: { tokens: 0, cost: 0, durationMs: 0 } });

    // Fetch full agent detail for complete model_config
    const token = localStorage.getItem('access_token');
    if (token) {
      try {
        const resp = await fetch(`${API_URL}/api/agents/${agent.id}`, { headers: { Authorization: `Bearer ${token}` } });
        const body = await resp.json();
        if (body.data) {
          const mc = (body.data.model_config || {}) as Record<string, unknown>;
          const full: Agent = {
            ...agent,
            mode: (mc.mode as string) || agent.mode,
            input_variables: (mc.input_variables as InputVariable[]) || agent.input_variables || [],
            pipeline_config: (mc.pipeline_config as Agent['pipeline_config']) || agent.pipeline_config,
          };
          setSelectedAgent(full);
          return;
        }
      } catch { /* fall through to use list data */ }
    }
    setSelectedAgent(agent);
  }, []);

  const isPipeline = selectedAgent?.mode === 'pipeline' || !!selectedAgent?.pipeline_config?.nodes?.length;

  // Build DAG
  const { nodes: dagNodes, edges: dagEdges } = useMemo(() => {
    if (!isPipeline || !selectedAgent?.pipeline_config) return { nodes: [], edges: [] };
    return buildDagFromConfig(selectedAgent.pipeline_config, execution.nodeStatuses, execution.nodeResults);
  }, [selectedAgent, isPipeline, execution.nodeStatuses, execution.nodeResults]);

  // Auto-scroll output
  useEffect(() => {
    if (outputRef.current) outputRef.current.scrollTop = outputRef.current.scrollHeight;
  }, [execution.streamOutput]);

  // Execute
  const execute = useCallback(async () => {
    if (!selectedAgent) return;
    const token = localStorage.getItem('access_token');
    if (!token) return;

    // Build message from inputs
    const vars = selectedAgent.input_variables || [];
    let message = freeformPrompt;
    if (vars.length > 0) {
      const filled = vars.map((v) => `${v.name}: ${inputValues[v.name] || v.default || ''}`).join('\n');
      message = message ? `${message}\n\n${filled}` : filled;
    }
    if (!message.trim()) { message = 'Execute this agent with default settings'; }

    // Initialize execution state — set all pipeline nodes to pending in one call
    const initialStatuses: Record<string, NodeStatus> = {};
    if (isPipeline && selectedAgent.pipeline_config?.nodes) {
      for (const n of selectedAgent.pipeline_config.nodes) initialStatuses[n.id] = 'pending';
    }
    setExecution({
      isRunning: true, executionId: null, nodeStatuses: initialStatuses, nodeResults: {},
      streamOutput: '', toolCalls: [], stats: { tokens: 0, cost: 0, durationMs: 0 },
    });

    const startTime = Date.now();

    try {
      const resp = await fetch(`${API_URL}/api/agents/${selectedAgent.id}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ message, stream: true }),
      });

      if (!resp.ok || !resp.body) {
        const errBody = await resp.json().catch(() => ({ error: { message: resp.statusText } }));
        setExecution((prev) => ({
          ...prev, isRunning: false,
          streamOutput: prev.streamOutput + `\n\nError: ${errBody.error?.message || resp.statusText}`,
          stats: { ...prev.stats, durationMs: Date.now() - startTime },
        }));
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE format: "event: <type>\ndata: <json>\n\n"
        // Split on double newline to get complete SSE frames
        const frames = buffer.split('\n\n');
        buffer = frames.pop() || ''; // Keep incomplete frame in buffer

        for (const frame of frames) {
          if (!frame.trim()) continue;
          const frameLines = frame.split('\n');
          let eventType = '';
          let dataStr = '';
          for (const fl of frameLines) {
            if (fl.startsWith('event: ')) eventType = fl.slice(7).trim();
            else if (fl.startsWith('data: ')) dataStr = fl.slice(6).trim();
          }

          // Also handle flat "data: {type: ...}" format (fallback)
          if (!eventType && dataStr) {
            try {
              const parsed = JSON.parse(dataStr);
              if (parsed.type) eventType = parsed.type;
            } catch { /* not json */ }
          }

          if (!dataStr || dataStr === '[DONE]') continue;

          try {
            const evt = JSON.parse(dataStr);

            if (eventType === 'token') {
              const text = evt.text || evt.content || '';
              if (text) setExecution((prev) => ({ ...prev, streamOutput: prev.streamOutput + text }));
            } else if (eventType === 'tool_call') {
              setExecution((prev) => ({
                ...prev,
                toolCalls: [...prev.toolCalls, { name: evt.name || evt.tool, args: typeof evt.arguments === 'string' ? evt.arguments : JSON.stringify(evt.arguments || evt.input, null, 2) }],
              }));
            } else if (eventType === 'tool_result') {
              setExecution((prev) => {
                const calls = [...prev.toolCalls];
                const resultText = typeof evt.result === 'string' ? evt.result : JSON.stringify(evt.result, null, 2);
                if (calls.length > 0) calls[calls.length - 1].result = resultText;
                return { ...prev, toolCalls: calls };
              });
            } else if (eventType === 'node_start') {
              setExecution((prev) => ({
                ...prev,
                nodeStatuses: { ...prev.nodeStatuses, [evt.node_id]: 'running' },
              }));
            } else if (eventType === 'node_complete') {
              setExecution((prev) => ({
                ...prev,
                nodeStatuses: { ...prev.nodeStatuses, [evt.node_id]: evt.status === 'failed' ? 'failed' : 'completed' },
                nodeResults: { ...prev.nodeResults, [evt.node_id]: { output: evt.output, error: evt.error, durationMs: evt.duration_ms } },
              }));
            } else if (eventType === 'done') {
              setExecution((prev) => ({
                ...prev,
                executionId: evt.execution_id || prev.executionId,
                stats: {
                  tokens: (evt.total_tokens || evt.input_tokens || 0) + (evt.output_tokens || 0),
                  cost: evt.cost || 0,
                  durationMs: Date.now() - startTime,
                },
              }));
            } else if (eventType === 'error') {
              setExecution((prev) => ({
                ...prev,
                isRunning: false,
                streamOutput: prev.streamOutput + `\n\nError: ${evt.message || evt.error}`,
                stats: { ...prev.stats, durationMs: Date.now() - startTime },
              }));
            }
          } catch {
            // Ignore malformed SSE events
          }
        }
      }
    } catch (err) {
      setExecution((prev) => ({
        ...prev,
        streamOutput: prev.streamOutput + `\n\nNetwork error: ${err instanceof Error ? err.message : 'Unknown'}`,
      }));
    } finally {
      setExecution((prev) => ({
        ...prev, isRunning: false,
        stats: { ...prev.stats, durationMs: Date.now() - startTime },
      }));
    }
  }, [selectedAgent, inputValues, freeformPrompt, isPipeline]);

  // ─── Render ─────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-6 h-6 text-cyan-500 animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Agent Picker */}
      {showPicker ? (
        <div className="space-y-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search agents and pipelines..."
              className="w-full pl-10 pr-4 py-2.5 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-white placeholder:text-slate-600 focus:outline-none focus:border-cyan-500"
            />
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-2 max-h-[400px] overflow-y-auto">
            {filtered.map((agent) => (
              <button
                key={agent.id}
                onClick={() => selectAgent(agent)}
                className="text-left bg-slate-800/50 hover:bg-slate-800 border border-slate-700/50 hover:border-cyan-500/30 rounded-xl p-3 transition-all group"
              >
                <div className="flex items-center gap-2 mb-1">
                  {agent.mode === 'pipeline' || agent.pipeline_config?.nodes?.length ? (
                    <GitBranch className="w-3.5 h-3.5 text-emerald-400" />
                  ) : (
                    <Bot className="w-3.5 h-3.5 text-cyan-400" />
                  )}
                  <span className="text-xs font-semibold text-white truncate group-hover:text-cyan-400 transition-colors">{agent.name}</span>
                </div>
                <p className="text-[9px] text-slate-500 line-clamp-2">{agent.description}</p>
                <div className="flex items-center gap-2 mt-2">
                  <span className="text-[8px] px-1.5 py-0.5 bg-slate-700/50 text-slate-400 rounded">{agent.category || 'general'}</span>
                  {agent.pipeline_config?.nodes?.length && (
                    <span className="text-[8px] px-1.5 py-0.5 bg-emerald-500/10 text-emerald-400 rounded">{agent.pipeline_config.nodes.length} steps</span>
                  )}
                </div>
              </button>
            ))}
            {filtered.length === 0 && (
              <p className="col-span-full text-center text-sm text-slate-600 py-8">
                {agents.length === 0 ? 'No active agents found. Create agents in the Builder first.' : 'No agents match your search.'}
              </p>
            )}
          </div>
        </div>
      ) : selectedAgent && (
        <div className="space-y-4">
          {/* Selected agent header */}
          <div className="flex items-center gap-3">
            <button
              onClick={() => { setShowPicker(true); setSelectedAgent(null); }}
              className="text-xs text-slate-500 hover:text-cyan-400 transition-colors"
            >
              ← Back to agents
            </button>
            <div className="flex items-center gap-2 flex-1">
              {isPipeline ? <GitBranch className="w-4 h-4 text-emerald-400" /> : <Bot className="w-4 h-4 text-cyan-400" />}
              <h3 className="text-sm font-semibold text-white">{selectedAgent.name}</h3>
              <span className={`text-[9px] px-1.5 py-0.5 rounded ${isPipeline ? 'bg-emerald-500/10 text-emerald-400' : 'bg-cyan-500/10 text-cyan-400'}`}>
                {isPipeline ? 'Pipeline' : 'Agent'}
              </span>
            </div>
          </div>

          {/* Input form + Execute */}
          <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 space-y-3">
            {(selectedAgent.input_variables || []).length > 0 && (
              <div className="space-y-3">
                <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium">Input Parameters</p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {(selectedAgent.input_variables || []).map((v) => (
                    <InputField
                      key={v.name}
                      variable={v}
                      value={inputValues[v.name] || ''}
                      onChange={(val) => setInputValues((prev) => ({ ...prev, [v.name]: val }))}
                    />
                  ))}
                </div>
              </div>
            )}
            <div>
              <label className="block text-[10px] text-slate-500 uppercase tracking-wider font-medium mb-1">
                {(selectedAgent.input_variables || []).length > 0 ? 'Additional Instructions (optional)' : 'Prompt'}
              </label>
              <textarea
                value={freeformPrompt}
                onChange={(e) => setFreeformPrompt(e.target.value)}
                placeholder={isPipeline ? 'Describe what you want the pipeline to process...' : 'Enter your message to the agent...'}
                rows={3}
                className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-white placeholder:text-slate-600 focus:outline-none focus:border-cyan-500 resize-none"
              />
            </div>
            <button
              onClick={execute}
              disabled={execution.isRunning}
              className="w-full py-2.5 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg hover:opacity-90 disabled:opacity-40 flex items-center justify-center gap-2"
            >
              {execution.isRunning ? (
                <><Loader2 className="w-4 h-4 animate-spin" /> Executing...</>
              ) : (
                <><Play className="w-4 h-4" /> Execute {isPipeline ? 'Pipeline' : 'Agent'}</>
              )}
            </button>
          </div>

          {/* Pipeline DAG Visualization */}
          {isPipeline && dagNodes.length > 0 && (
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
              <div className="px-4 py-2 border-b border-slate-700/50 flex items-center gap-2">
                <GitBranch className="w-3.5 h-3.5 text-emerald-400" />
                <span className="text-xs font-semibold text-white">Pipeline DAG</span>
                {execution.isRunning && (
                  <span className="text-[9px] px-2 py-0.5 bg-cyan-500/10 text-cyan-400 rounded-full animate-pulse">Live</span>
                )}
                <span className="text-[9px] text-slate-500 ml-auto">
                  {Object.values(execution.nodeStatuses).filter((s) => s === 'completed').length}/{dagNodes.length} completed
                </span>
              </div>
              <div style={{ height: Math.max(250, Math.min(400, dagNodes.length * 80)) }}>
                <ReactFlow
                  nodes={dagNodes}
                  edges={dagEdges}
                  nodeTypes={nodeTypes}
                  onNodeClick={(_, node) => setSelectedNodeId(node.id)}
                  fitView
                  proOptions={{ hideAttribution: true }}
                  nodesDraggable={false}
                  nodesConnectable={false}
                  elementsSelectable={true}
                  zoomOnScroll={false}
                  panOnDrag={true}
                  style={{ background: '#0B0F19' }}
                >
                  <Background color="#1E293B" gap={20} size={1} />
                  <Controls showInteractive={false} className="!bg-slate-800 !border-slate-700 !rounded-lg [&>button]:!bg-slate-800 [&>button]:!border-slate-700 [&>button]:!text-slate-400" />
                </ReactFlow>
              </div>

              {/* Node output inspector */}
              {selectedNodeId && execution.nodeResults[selectedNodeId] && (
                <div className="border-t border-slate-700/50 p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold text-white">{selectedNodeId} — Output</span>
                    <button onClick={() => setSelectedNodeId(null)} className="text-xs text-slate-500 hover:text-white">×</button>
                  </div>
                  <pre className="text-[10px] font-mono text-slate-400 bg-slate-900/80 rounded-lg p-3 max-h-40 overflow-auto whitespace-pre-wrap">
                    {execution.nodeResults[selectedNodeId].error || execution.nodeResults[selectedNodeId].output || '(no output)'}
                  </pre>
                </div>
              )}
            </div>
          )}

          {/* Stats bar */}
          {(execution.isRunning || execution.stats.durationMs > 0) && (
            <div className="flex items-center gap-4 text-[10px]">
              <span className="flex items-center gap-1 text-slate-400">
                <Clock className="w-3 h-3" />
                {execution.isRunning ? 'Running...' : `${(execution.stats.durationMs / 1000).toFixed(1)}s`}
              </span>
              {execution.stats.tokens > 0 && (
                <span className="flex items-center gap-1 text-slate-400">
                  <Zap className="w-3 h-3" />
                  {execution.stats.tokens.toLocaleString()} tokens
                </span>
              )}
              {execution.stats.cost > 0 && (
                <span className="flex items-center gap-1 text-slate-400">
                  <DollarSign className="w-3 h-3" />
                  ${execution.stats.cost.toFixed(4)}
                </span>
              )}
              {execution.executionId && (
                <a
                  href={`/executions/${execution.executionId}`}
                  className="flex items-center gap-1 text-cyan-400 hover:text-cyan-300 ml-auto"
                >
                  <Activity className="w-3 h-3" />
                  Flight Recorder →
                </a>
              )}
            </div>
          )}

          {/* Stream Output */}
          {(execution.streamOutput || execution.toolCalls.length > 0) && (
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
              <div className="px-4 py-2 border-b border-slate-700/50 flex items-center gap-2">
                <Code className="w-3.5 h-3.5 text-cyan-400" />
                <span className="text-xs font-semibold text-white">Output</span>
              </div>

              {/* Tool calls */}
              {execution.toolCalls.length > 0 && (
                <div className="border-b border-slate-700/50 p-3 space-y-2">
                  <p className="text-[9px] text-slate-500 uppercase tracking-wider">Tool Calls ({execution.toolCalls.length})</p>
                  {execution.toolCalls.map((tc, i) => (
                    <details key={i} className="group">
                      <summary className="flex items-center gap-2 cursor-pointer text-xs">
                        <ChevronRight className="w-3 h-3 text-slate-500 group-open:rotate-90 transition-transform" />
                        <Zap className="w-3 h-3 text-amber-400" />
                        <span className="text-amber-400 font-mono">{tc.name}</span>
                        {tc.result && <CheckCircle2 className="w-3 h-3 text-emerald-400 ml-auto" />}
                      </summary>
                      <div className="ml-6 mt-1 space-y-1">
                        <pre className="text-[9px] font-mono text-slate-500 bg-slate-900/50 rounded p-2 max-h-24 overflow-auto">{tc.args}</pre>
                        {tc.result && (
                          <pre className="text-[9px] font-mono text-emerald-400/70 bg-slate-900/50 rounded p-2 max-h-24 overflow-auto">{tc.result}</pre>
                        )}
                      </div>
                    </details>
                  ))}
                </div>
              )}

              {/* Stream text */}
              <div ref={outputRef} className="p-4 max-h-80 overflow-y-auto">
                <pre className="text-sm text-slate-300 whitespace-pre-wrap break-words font-mono leading-relaxed">
                  {execution.streamOutput || '(waiting for output...)'}
                  {execution.isRunning && <span className="animate-pulse text-cyan-400">▊</span>}
                </pre>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
