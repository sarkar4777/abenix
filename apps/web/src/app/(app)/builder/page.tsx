'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import dynamic from 'next/dynamic';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useIsMobile } from '@/hooks/useMediaQuery';
import {
  addEdge,
  useEdgesState,
  useNodesState,
  BackgroundVariant,
  type Connection,
  type Edge,
  type Node,
  type ReactFlowInstance,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { motion } from 'framer-motion';
import { GripVertical, MousePointerClick, Save, Loader2 } from 'lucide-react';

const DynamicReactFlow = dynamic(
  () => import('reactflow').then((m) => m.default),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center h-full bg-[#0B0F19]">
        <div className="w-8 h-8 border-2 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin" />
      </div>
    ),
  },
);
const DynamicBackground = dynamic(
  () => import('reactflow').then((m) => m.Background),
  { ssr: false },
);
const DynamicControls = dynamic(
  () => import('reactflow').then((m) => m.Controls),
  { ssr: false },
);
const DynamicMiniMap = dynamic(
  () => import('reactflow').then((m) => m.MiniMap),
  { ssr: false },
);

import { nodeTypes } from '@/components/builder/nodes';
import ToolPalette from '@/components/builder/ToolPalette';
import AgentConfigPanel from '@/components/builder/AgentConfigPanel';
import BuilderTopBar, { type BuilderMode } from '@/components/builder/BuilderTopBar';
import PipelineCanvas from '@/components/builder/pipeline/PipelineCanvas';
import PipelineToolbar from '@/components/builder/pipeline/PipelineToolbar';
import StepConfigPanel from '@/components/builder/pipeline/StepConfigPanel';
import PipelineExecutionViewer from '@/components/builder/pipeline/PipelineExecutionViewer';
import { usePipelineStore } from '@/components/builder/pipeline/usePipelineStore';
import {
  deriveToolsFromSteps,
  isValidConnection as checkPipelineConnection,
  type PipelineConfig,
} from '@/components/builder/pipeline/pipelineUtils';

import { getToolDescription } from '@/lib/tool-docs';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface MCPExtensions {
  allow_user_mcp?: boolean;
  max_mcp_servers?: number;
  suggested_mcp_servers?: Array<{ registry_id: string; reason: string }>;
  allowed_tool_annotations?: string[];
}

interface ToolConfig {
  usage_instructions: string;
  parameter_defaults: Record<string, unknown>;
  max_calls: number;
  require_approval: boolean;
}

interface InputVariable {
  name: string;
  type: string;
  description: string;
  required: boolean;
  default?: string | number | boolean;
  options?: string[];
}

interface AgentConfig {
  name: string;
  description: string;
  system_prompt: string;
  category: string;
  model: string;
  temperature: number;
  max_tokens: number;
  max_iterations: number;
  timeout: number;
  mcp_extensions?: MCPExtensions;
  tool_config?: Record<string, ToolConfig>;
  input_variables?: InputVariable[];
  // Fields the YAML seed format supports but the UI used to hide.
  // Without these, YAML-authored agents could carry an icon / example
  // prompts that no UI edit could ever change.
  icon?: string;
  example_prompts?: string[];
}

const DEFAULT_CONFIG: AgentConfig = {
  name: 'New Agent',
  description: '',
  system_prompt: '',
  category: '',
  model: 'claude-sonnet-4-5-20250929',
  temperature: 0.7,
  max_tokens: 4096,
  max_iterations: 10,
  timeout: 120,
  icon: '',
  example_prompts: [],
};

function makeToolNode(
  toolId: string,
  position: { x: number; y: number },
  onDelete: () => void,
  tc?: ToolConfig,
): Node {
  const isConfigured = tc && (
    !!(tc.usage_instructions?.trim()) ||
    Object.keys(tc.parameter_defaults || {}).length > 0 ||
    (tc.max_calls && tc.max_calls > 0) ||
    tc.require_approval
  );
  return {
    id: `tool-${toolId}`,
    type: 'tool',
    position,
    data: {
      name: toolId.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase()),
      description: getToolDescription(toolId) || 'Custom tool',
      configured: !!isConfigured,
      configStatus: isConfigured ? 'configured' : 'default',
      maxCalls: tc?.max_calls || 0,
      requireApproval: tc?.require_approval || false,
      onDelete,
    },
    draggable: true,
  };
}

const EDGE_STYLE = {
  animated: true,
  style: { stroke: '#06B6D4', strokeDasharray: '5 5' },
};

function formatRegistryName(registryId: string): string {
  return registryId
    .replace(/-mcp$/, '')
    .replace(/[-_]/g, ' ')
    .replace(/\b\w/g, (c: string) => c.toUpperCase());
}

function makeMcpNode(
  registryId: string,
  position: { x: number; y: number },
  onDelete: () => void,
  suggested: boolean = false,
): Node {
  return {
    id: `mcp-${registryId}`,
    type: 'mcp',
    position,
    data: {
      name: formatRegistryName(registryId),
      healthy: true,
      toolCount: 0,
      suggested,
      onDelete,
    },
    draggable: true,
  };
}

const MOBILE_MODELS = [
  { value: 'claude-sonnet-4-5-20250929', label: 'Claude Sonnet 4.5' },
  { value: 'claude-haiku-3-5-20241022', label: 'Claude Haiku 3.5' },
  { value: 'gpt-4o', label: 'GPT-4o' },
  { value: 'gpt-4o-mini', label: 'GPT-4o Mini' },
  { value: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash' },
];

const MOBILE_TOOLS = [
  { id: 'calculator', name: 'Calculator' },
  { id: 'current_time', name: 'Current Time' },
  { id: 'web_search', name: 'Web Search' },
  { id: 'file_reader', name: 'File Reader' },
  { id: 'llm_call', name: 'LLM Call' },
  { id: 'email_sender', name: 'Email Sender' },
  { id: 'data_merger', name: 'Data Merger' },
];

export default function BuilderPage() {
  usePageTitle('Agent Builder');
  const router = useRouter();
  const searchParams = useSearchParams();
  const agentParam = searchParams.get('agent');
  const isMobile = useIsMobile();

  const [agentId, setAgentId] = useState<string | null>(agentParam);
  const [config, setConfig] = useState<AgentConfig>(DEFAULT_CONFIG);
  const [selectedTools, setSelectedTools] = useState<string[]>([]);
  const [loading, setLoading] = useState(!!agentParam);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [mcpExtensions, setMcpExtensions] = useState<MCPExtensions | undefined>(undefined);
  const [builderMode, setBuilderMode] = useState<BuilderMode>('agent');
  const [showExecutionViewer, setShowExecutionViewer] = useState(false);

  // Pipeline store
  const pipelineStore = usePipelineStore();

  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  const reactFlowRef = useRef<ReactFlowInstance | null>(null);
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout>>();

  // Delete a node and its edges + clean up tool_config
  const deleteNode = useCallback(
    (nodeId: string) => {
      const toolId = nodeId.replace('tool-', '');
      setNodes((nds) => nds.filter((n) => n.id !== nodeId));
      setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
      setSelectedTools((prev) => prev.filter((t) => t !== toolId));
      setSelectedNodeId((prev) => (prev === nodeId ? null : prev));
      // Clean up any tool_config for the deleted tool
      setConfig((prev) => {
        if (prev.tool_config && prev.tool_config[toolId]) {
          const next = { ...prev.tool_config };
          delete next[toolId];
          return { ...prev, tool_config: next };
        }
        return prev;
      });
      setDirty(true);
    },
    [setNodes, setEdges],
  );

  // Build nodes for initial load / agent fetch
  const buildInitialNodes = useCallback(
    (cfg: AgentConfig, tools: string[]): Node[] => {
      const tc = cfg.tool_config || {};
      const configuredCount = Object.values(tc).filter((c) =>
        !!(c.usage_instructions?.trim()) || Object.keys(c.parameter_defaults || {}).length > 0 || (c.max_calls && c.max_calls > 0) || c.require_approval
      ).length;

      const agentNode: Node = {
        id: 'agent',
        type: 'agent',
        position: { x: 250, y: 200 },
        data: {
          name: cfg.name,
          model: cfg.model,
          status: 'draft',
          toolCount: tools.length,
          configuredToolCount: configuredCount,
          inputParamCount: cfg.input_variables?.length || 0,
        },
        draggable: true,
      };

      const toolNodes: Node[] = tools.map((tool, i) =>
        makeToolNode(tool, { x: 550, y: 80 + i * 110 }, () => deleteNode(`tool-${tool}`), tc[tool]),
      );

      return [agentNode, ...toolNodes];
    },
    [deleteNode],
  );

  const buildInitialEdges = useCallback((tools: string[]): Edge[] => {
    return tools.map((tool) => ({
      id: `edge-agent-${tool}`,
      source: 'agent',
      target: `tool-${tool}`,
      ...EDGE_STYLE,
    }));
  }, []);

  // Sync the agent's selected tools into the pipeline store so backend
  // validation knows which tools are available for use in pipeline nodes.
  useEffect(() => {
    usePipelineStore.getState().setAgentTools(selectedTools);
  }, [selectedTools]);

  // Sync the agent's declared input_variables into the pipeline store
  // so `{{context.<var>}}` templates don't get flagged as unknown.
  useEffect(() => {
    const keys = (config.input_variables || [])
      .map((v) => v.name.trim())
      .filter((n) => n.length > 0);
    usePipelineStore.getState().setAgentContextKeys(keys);
  }, [config.input_variables]);

  // Load agent or init empty
  useEffect(() => {
    if (!agentParam) {
      setNodes(buildInitialNodes(DEFAULT_CONFIG, []));
      setEdges([]);
      setLoading(false);
      return;
    }

    const token = localStorage.getItem('access_token');
    if (!token) return;

    fetch(`${API_URL}/api/agents/${agentParam}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.json())
      .then((json) => {
        if (!json.data) return;
        const a = json.data;
        const mc = a.model_config || {};
        const tools = mc.tools || [];
        const loadedMcpExtensions: MCPExtensions | undefined =
          mc.mcp_extensions || a.mcp_extensions || undefined;
        const loaded: AgentConfig = {
          name: a.name,
          description: a.description || '',
          system_prompt: a.system_prompt || '',
          category: a.category || '',
          model: mc.model || DEFAULT_CONFIG.model,
          temperature: mc.temperature ?? DEFAULT_CONFIG.temperature,
          max_tokens: mc.max_tokens ?? DEFAULT_CONFIG.max_tokens,
          max_iterations: 10,
          timeout: 120,
          mcp_extensions: loadedMcpExtensions,
          input_variables: mc.input_variables || [],
          tool_config: mc.tool_config || {},
          icon: a.icon_url || mc.icon || '',
          example_prompts: mc.example_prompts || [],
        };
        setConfig(loaded);
        setMcpExtensions(loadedMcpExtensions);
        setSelectedTools(tools);

        // Detect pipeline mode
        if (mc.mode === 'pipeline' && mc.pipeline_config) {
          setBuilderMode('pipeline');
          pipelineStore.deserialize(mc.pipeline_config as PipelineConfig);
        } else {
          setBuilderMode('agent');
          setNodes(buildInitialNodes(loaded, tools));
          setEdges(buildInitialEdges(tools));
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [agentParam, setNodes, setEdges, buildInitialNodes, buildInitialEdges]);

  // Update agent config & reflect in nodes
  const updateConfig = useCallback(
    (updates: Partial<AgentConfig>) => {
      setConfig((prev) => {
        const next = { ...prev, ...updates };
        const tc = next.tool_config || {};
        const configuredCount = Object.values(tc).filter((c) =>
          !!(c.usage_instructions?.trim()) || Object.keys(c.parameter_defaults || {}).length > 0 || (c.max_calls && c.max_calls > 0) || c.require_approval
        ).length;

        setNodes((nds) =>
          nds.map((n) => {
            if (n.id === 'agent') {
              return {
                ...n,
                data: {
                  ...n.data,
                  name: next.name,
                  model: next.model,
                  toolCount: nds.filter((nd) => nd.type === 'tool').length,
                  configuredToolCount: configuredCount,
                  inputParamCount: next.input_variables?.length || 0,
                },
              };
            }
            // Update tool node status from tool_config
            if (n.type === 'tool') {
              const toolId = n.id.replace('tool-', '');
              const toolCfg = tc[toolId];
              const isConfigured = toolCfg && (
                !!(toolCfg.usage_instructions?.trim()) ||
                Object.keys(toolCfg.parameter_defaults || {}).length > 0 ||
                (toolCfg.max_calls && toolCfg.max_calls > 0) ||
                toolCfg.require_approval
              );
              return {
                ...n,
                data: {
                  ...n.data,
                  configured: !!isConfigured,
                  configStatus: isConfigured ? 'configured' : 'default',
                  maxCalls: toolCfg?.max_calls || 0,
                  requireApproval: toolCfg?.require_approval || false,
                },
              };
            }
            return n;
          }),
        );
        return next;
      });
      setDirty(true);
    },
    [setNodes],
  );

  // Toggle tool from palette (click to add/remove)
  const toggleTool = useCallback(
    (toolId: string) => {
      setSelectedTools((prev) => {
        if (prev.includes(toolId)) {
          const nodeId = `tool-${toolId}`;
          setNodes((nds) => nds.filter((n) => n.id !== nodeId));
          setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
          setSelectedNodeId((cur) => (cur === nodeId ? null : cur));
          return prev.filter((t) => t !== toolId);
        } else {
          const existingToolCount = prev.length;
          const position = { x: 550, y: 80 + existingToolCount * 110 };
          const newNode = makeToolNode(toolId, position, () => deleteNode(`tool-${toolId}`));
          const newEdge: Edge = {
            id: `edge-agent-${toolId}`,
            source: 'agent',
            target: `tool-${toolId}`,
            ...EDGE_STYLE,
          };
          setNodes((nds) => [...nds, newNode]);
          setEdges((eds) => [...eds, newEdge]);
          return [...prev, toolId];
        }
      });
      setDirty(true);
    },
    [setNodes, setEdges, deleteNode],
  );

  // Drag-and-drop from palette onto canvas
  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const toolJson = e.dataTransfer.getData('application/abenix-tool');
      if (!toolJson || !reactFlowRef.current) return;

      const tool = JSON.parse(toolJson) as { id: string; name: string; description: string };
      if (selectedTools.includes(tool.id)) return;

      const position = reactFlowRef.current.screenToFlowPosition({
        x: e.clientX,
        y: e.clientY,
      });

      const newNode = makeToolNode(tool.id, position, () => deleteNode(`tool-${tool.id}`));
      const newEdge: Edge = {
        id: `edge-agent-${tool.id}`,
        source: 'agent',
        target: `tool-${tool.id}`,
        ...EDGE_STYLE,
      };

      setNodes((nds) => [...nds, newNode]);
      setEdges((eds) => [...eds, newEdge]);
      setSelectedTools((prev) => [...prev, tool.id]);
      setDirty(true);
    },
    [selectedTools, setNodes, setEdges, deleteNode],
  );

  // Manual edge connections by dragging between handles
  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges((eds) =>
        addEdge(
          {
            ...connection,
            animated: true,
            style: { stroke: '#06B6D4', strokeDasharray: '5 5' },
          },
          eds,
        ),
      );
      setDirty(true);
    },
    [setEdges],
  );

  // Node selection
  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNodeId(node.id);
  }, []);

  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null);
  }, []);

  const clearSelection = useCallback(() => {
    setSelectedNodeId(null);
    setNodes((nds) => nds.map((n) => ({ ...n, selected: false })));
  }, [setNodes]);

  // MCP nodes derived from canvas
  const mcpNodes = useMemo(
    () =>
      nodes
        .filter((n) => n.type === 'mcp')
        .map((n) => ({
          id: n.id,
          name: n.data.name as string,
          url: n.data.url as string | undefined,
        })),
    [nodes],
  );

  // Add MCP connection via external page
  const handleAddMcpConnection = useCallback(() => {
    window.open('/mcp', '_blank');
  }, []);

  // Connect a suggested MCP server (adds node to canvas)
  const handleConnectMcp = useCallback(
    (registryId: string) => {
      const nodeId = `mcp-${registryId}`;
      // Don't add if already exists
      if (nodes.some((n) => n.id === nodeId)) return;

      const mcpCount = nodes.filter((n) => n.type === 'mcp').length;
      const position = { x: 550, y: 80 + (selectedTools.length + mcpCount) * 110 };

      const newNode = makeMcpNode(registryId, position, () => deleteNode(nodeId), true);
      const newEdge: Edge = {
        id: `edge-agent-${registryId}`,
        source: 'agent',
        target: nodeId,
        ...EDGE_STYLE,
      };

      setNodes((nds) => [...nds, newNode]);
      setEdges((eds) => [...eds, newEdge]);
      setDirty(true);
    },
    [nodes, selectedTools.length, setNodes, setEdges, deleteNode],
  );

  // Disconnect an MCP server (removes node from canvas)
  const handleDisconnectMcp = useCallback(
    (nodeId: string) => {
      setNodes((nds) => nds.filter((n) => n.id !== nodeId));
      setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
      setSelectedNodeId((prev) => (prev === nodeId ? null : prev));
      setDirty(true);
    },
    [setNodes, setEdges],
  );

  // Keyboard delete (but protect agent node)
  const onNodesDelete = useCallback(
    (deletedNodes: Node[]) => {
      for (const node of deletedNodes) {
        if (node.id === 'agent') continue;
        const toolId = node.id.replace('tool-', '');
        setSelectedTools((prev) => prev.filter((t) => t !== toolId));
      }
      setSelectedNodeId(null);
      setDirty(true);
    },
    [],
  );

  // Run pipeline
  const runPipeline = useCallback(async () => {
    if (!agentId) return;
    setShowExecutionViewer(true);
    await pipelineStore.executeAndTrack(agentId);
  }, [agentId, pipelineStore]);

  // Save
  const save = useCallback(async () => {
    const token = localStorage.getItem('access_token');
    if (!token) return;

    setSaving(true);

    // Build model_config depending on mode
    const modelConfig: Record<string, unknown> = {
      model: config.model,
      temperature: config.temperature,
      max_tokens: config.max_tokens,
    };

    if (builderMode === 'pipeline') {
      modelConfig.mode = 'pipeline';
      modelConfig.pipeline_config = pipelineStore.serialize();
      modelConfig.tools = deriveToolsFromSteps(pipelineStore.steps);
    } else {
      modelConfig.tools = selectedTools;
    }

    // Save input variables if defined
    if (config.input_variables && config.input_variables.length > 0) {
      modelConfig.input_variables = config.input_variables.filter((v) => v.name.trim() !== '');
    }

    // Example prompts — what the YAML seeds call `example_prompts`. Stored
    // inside model_config so the info page / marketplace card can pick
    // them up the same way they'd appear for a YAML-seeded agent.
    if (config.example_prompts && config.example_prompts.length > 0) {
      const cleaned = config.example_prompts.map((p) => (p || '').trim()).filter(Boolean);
      if (cleaned.length > 0) {
        modelConfig.example_prompts = cleaned;
      }
    }

    // Save tool config if any tools are configured
    if (config.tool_config && Object.keys(config.tool_config).length > 0) {
      // Only persist configs that have actual values set
      const filtered: Record<string, unknown> = {};
      for (const [toolId, tc] of Object.entries(config.tool_config)) {
        if (tc.usage_instructions?.trim() || Object.keys(tc.parameter_defaults || {}).length > 0 || tc.max_calls > 0 || tc.require_approval) {
          filtered[toolId] = tc;
        }
      }
      if (Object.keys(filtered).length > 0) {
        modelConfig.tool_config = filtered;
      }
    }

    const payload: Record<string, unknown> = {
      name: config.name,
      description: config.description,
      system_prompt: config.system_prompt,
      model_config: modelConfig,
      category: config.category || null,
    };
    // The icon lives as a top-level column (icon_url) on the agents
    // table, not inside model_config — the API accepts either name.
    if (config.icon && config.icon.trim()) {
      payload.icon_url = config.icon.trim();
    }

    try {
      if (agentId) {
        await fetch(`${API_URL}/api/agents/${agentId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify(payload),
        });
      } else {
        const res = await fetch(`${API_URL}/api/agents`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify(payload),
        });
        const json = await res.json();
        if (json.data?.id) {
          setAgentId(json.data.id);
          router.replace(`/builder?agent=${json.data.id}`);
        }
      }
      setDirty(false);
    } catch {
    } finally {
      setSaving(false);
    }
  }, [agentId, config, selectedTools, router, builderMode, pipelineStore]);

  // Combined dirty state (agent mode dirty or pipeline store dirty)
  const isDirty = dirty || pipelineStore.dirty;

  // Auto-save debounce
  useEffect(() => {
    if (!isDirty || !agentId) return;
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    saveTimeoutRef.current = setTimeout(() => {
      save();
    }, 500);
    return () => {
      if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    };
  }, [isDirty, agentId, save]);

  // AI Builder — apply generated config to canvas without page reload
  const applyAIConfig = useCallback((aiConfig: Record<string, unknown>) => {
    const mc = (aiConfig.model_config || aiConfig) as Record<string, unknown>;
    const tools = (mc.tools || aiConfig.tools || []) as string[];
    const mode = (mc.mode || aiConfig.mode || 'agent') as string;

    // Build the complete new config FIRST
    const fullConfig: AgentConfig = {
      ...DEFAULT_CONFIG,
      name: (aiConfig.name as string) || 'AI Generated Agent',
      description: (aiConfig.description as string) || '',
      system_prompt: (aiConfig.system_prompt as string) || '',
      model: (mc.model as string) || 'claude-sonnet-4-5-20250929',
      temperature: (mc.temperature as number) || 0.7,
      max_tokens: 4096,
      input_variables: (mc.input_variables || aiConfig.input_variables || []) as AgentConfig['input_variables'],
      category: (aiConfig.category as string) || 'engineering',
      tool_config: {},
    };

    // Apply all state updates
    setConfig(fullConfig);
    setSelectedTools(tools);

    if (mode === 'pipeline') {
      const pipelineConfig = (mc.pipeline_config || aiConfig.pipeline_config) as PipelineConfig | undefined;
      if (pipelineConfig) {
        setBuilderMode('pipeline');
        // Ensure nodes have edges from depends_on
        const nodes = pipelineConfig.nodes || [];
        if (!pipelineConfig.edges || pipelineConfig.edges.length === 0) {
          const edges: { source: string; target: string; id?: string }[] = [];
          for (const n of nodes) {
            for (const dep of (n.depends_on || [])) {
              edges.push({ source: dep, target: n.id, id: `edge-${dep}-${n.id}` });
            }
          }
          (pipelineConfig as unknown as Record<string, unknown>).edges = edges;
        }
        pipelineStore.deserialize(pipelineConfig);
      }
    } else {
      setBuilderMode('agent');
      // Delay node creation to ensure React has re-rendered the canvas
      setTimeout(() => {
        setNodes(buildInitialNodes(fullConfig, tools));
        setEdges(buildInitialEdges(tools));
        setDirty(true);
      }, 100);
      return; // Don't set dirty here — setTimeout will do it
    }

    setDirty(true);
  }, [setNodes, setEdges, buildInitialNodes, buildInitialEdges, pipelineStore]);

  // Publish
  const publish = useCallback(async () => {
    if (!agentId) {
      await save();
    }
    const currentId = agentId || (await getCreatedId());
    if (!currentId) return;

    const token = localStorage.getItem('access_token');
    if (!token) return;

    await fetch(`${API_URL}/api/agents/${currentId}/publish`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
    router.push(`/agents/${currentId}/chat`);
  }, [agentId, save, router]);

  async function getCreatedId(): Promise<string | null> {
    return agentId;
  }

  // Derived state
  const selectedNode = useMemo(
    () => nodes.find((n) => n.id === selectedNodeId) || null,
    [nodes, selectedNodeId],
  );

  const hasToolNodes = nodes.some((n) => n.type === 'tool');

  const miniMapNodeColor = useCallback((n: Node) => {
    if (n.type === 'agent') return '#06B6D4';
    if (n.type === 'tool') return '#22D3EE';
    if (n.type === 'knowledge') return '#A855F7';
    if (n.type === 'mcp') return '#F59E0B';
    return '#64748B';
  }, []);

  const flowStyle = useMemo(() => ({ background: '#0B0F19' }), []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin" />
      </div>
    );
  }

  // --- Mobile builder fallback ---
  if (isMobile) {
    return (
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.3 }}
        className="-m-3 flex flex-col h-[calc(100vh-3.5rem-1.75rem)]"
      >
        <BuilderTopBar
          agentId={agentId}
          name={config.name}
          onNameChange={(name) => updateConfig({ name })}
          onSave={save}
          onPublish={publish}
          saving={saving}
          dirty={isDirty}
          builderMode={builderMode}
          onModeChange={setBuilderMode}
          onRunPipeline={runPipeline}
          pipelineRunning={pipelineStore.execution.isRunning}
          onAIBuild={applyAIConfig}
          validationErrorCount={pipelineStore.validation.errors.length}
          validationWarningCount={pipelineStore.validation.warnings.length}
          isValidating={pipelineStore.validation.isValidating}
          hasPipelineSteps={pipelineStore.steps.length > 0}
        />
        <div className="flex-1 overflow-y-auto p-4 space-y-5">
          {/* Agent Name */}
          <div>
            <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider mb-1.5">
              Agent Name
            </label>
            <input
              type="text"
              value={config.name}
              onChange={(e) => updateConfig({ name: e.target.value })}
              className="w-full px-3 py-2.5 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500 transition-colors"
            />
          </div>

          {/* Model */}
          <div>
            <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider mb-1.5">
              Model
            </label>
            <select
              value={config.model}
              onChange={(e) => updateConfig({ model: e.target.value })}
              className="w-full px-3 py-2.5 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500 appearance-none transition-colors"
            >
              {MOBILE_MODELS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </div>

          {/* Tools */}
          <div>
            <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider mb-1.5">
              Tools
            </label>
            <div className="space-y-2">
              {MOBILE_TOOLS.map((tool) => (
                <label
                  key={tool.id}
                  className="flex items-center gap-3 p-2.5 rounded-lg bg-slate-800/30 border border-slate-700/50 cursor-pointer hover:border-slate-600 transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={selectedTools.includes(tool.id)}
                    onChange={() => toggleTool(tool.id)}
                    className="w-4 h-4 rounded border-slate-600 bg-slate-800 text-cyan-500 focus:ring-cyan-500 focus:ring-offset-0"
                  />
                  <span className="text-sm text-slate-200">{tool.name}</span>
                  <span className="text-xs text-slate-500 ml-auto">
                    {getToolDescription(tool.id)}
                  </span>
                </label>
              ))}
            </div>
          </div>

          {/* System Prompt */}
          <div>
            <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider mb-1.5">
              System Prompt
            </label>
            <textarea
              value={config.system_prompt}
              onChange={(e) => updateConfig({ system_prompt: e.target.value })}
              rows={6}
              placeholder="Enter system prompt..."
              className="w-full px-3 py-2.5 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 resize-none focus:outline-none focus:border-cyan-500 transition-colors"
            />
          </div>

          {/* Save button */}
          <button
            onClick={save}
            disabled={saving}
            className="w-full py-2.5 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg hover:from-cyan-400 hover:to-purple-500 shadow-lg shadow-cyan-500/25 disabled:opacity-50 transition-all flex items-center justify-center gap-2"
          >
            {saving ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Saving...
              </>
            ) : (
              <>
                <Save className="w-4 h-4" />
                Save Agent
              </>
            )}
          </button>
        </div>
      </motion.div>
    );
  }

  // --- Desktop builder with ReactFlow canvas ---
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
      className="-m-6 flex flex-col h-[calc(100vh-3.5rem-1.75rem)]"
    >
      <BuilderTopBar
        agentId={agentId}
        name={config.name}
        onNameChange={(name) => updateConfig({ name })}
        onSave={save}
        onPublish={publish}
        saving={saving}
        dirty={isDirty}
        builderMode={builderMode}
        onModeChange={setBuilderMode}
        onRunPipeline={runPipeline}
        pipelineRunning={pipelineStore.execution.isRunning}
        onAIBuild={applyAIConfig}
        getDraftForValidate={() => {
          if (builderMode === 'pipeline') {
            const serialized = pipelineStore.serialize();
            return {
              nodes: (serialized?.nodes as unknown[]) || [],
              tools: deriveToolsFromSteps(pipelineStore.steps),
              context_keys: (config.input_variables || [])
                .filter((v) => v.name.trim() !== '')
                .map((v) => v.name),
              purpose: config.description || config.name || '',
            };
          }
          // Agent mode: no DAG to validate. Return an empty payload so the
          // dialog shows the "nothing to validate yet" hint.
          return { nodes: [], tools: selectedTools, context_keys: [], purpose: config.description || '' };
        }}
      />
      <div className="flex-1 flex min-h-0">
        {builderMode === 'agent' ? (
          <>
            <ToolPalette selectedTools={selectedTools} onToggleTool={toggleTool} />
            <div className="flex-1 min-w-0 relative h-full">
              <DynamicReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onNodeClick={onNodeClick}
                onPaneClick={onPaneClick}
                onNodesDelete={onNodesDelete}
                onDragOver={onDragOver}
                onDrop={onDrop}
                onInit={(instance) => {
                  reactFlowRef.current = instance;
                }}
                nodeTypes={nodeTypes}
                deleteKeyCode={['Backspace', 'Delete']}
                style={flowStyle}
                fitView
                proOptions={{ hideAttribution: true }}
                connectionLineStyle={{ stroke: '#06B6D4', strokeWidth: 2 }}
              >
                <DynamicBackground variant={BackgroundVariant.Dots} color="#1E293B" gap={20} size={1} />
                <DynamicControls
                  className="!bg-slate-800 !border-slate-700 !rounded-lg !shadow-lg [&>button]:!bg-slate-800 [&>button]:!border-slate-700 [&>button]:!text-slate-400 [&>button:hover]:!bg-slate-700"
                />
                <DynamicMiniMap
                  nodeColor={miniMapNodeColor}
                  maskColor="rgba(11, 15, 25, 0.7)"
                  className="!bg-slate-900 !border-slate-800 !rounded-lg"
                />
              </DynamicReactFlow>

              {/* Empty state hint when no tools added yet */}
              {!hasToolNodes && (
                <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                  <div className="text-center mt-32">
                    <div className="flex items-center justify-center gap-3 mb-2">
                      <GripVertical className="w-4 h-4 text-slate-600" />
                      <MousePointerClick className="w-4 h-4 text-slate-600" />
                    </div>
                    <p className="text-sm text-slate-600">
                      Drag tools from the palette or click to add them
                    </p>
                    <p className="text-xs text-slate-700 mt-1">
                      Connect nodes by dragging between their handles
                    </p>
                  </div>
                </div>
              )}
            </div>
            <AgentConfigPanel
              config={config as Parameters<typeof AgentConfigPanel>[0]['config']}
              onChange={updateConfig as Parameters<typeof AgentConfigPanel>[0]['onChange']}
              selectedNode={selectedNode}
              onClearSelection={clearSelection}
              mcpExtensions={mcpExtensions || config.mcp_extensions}
              mcpNodes={mcpNodes}
              onConnectMcp={handleConnectMcp}
              onAddMcpConnection={handleAddMcpConnection}
              onDisconnectMcp={handleDisconnectMcp}
            />
          </>
        ) : (
          <PipelineModeContent
            showExecutionViewer={showExecutionViewer}
            setShowExecutionViewer={setShowExecutionViewer}
          />
        )}
      </div>
    </motion.div>
  );
}

// PipelineModeContent — Bridges pipeline store ↔ ReactFlow

function PipelineModeContent({
  showExecutionViewer,
  setShowExecutionViewer,
}: {
  showExecutionViewer: boolean;
  setShowExecutionViewer: (v: boolean) => void;
}) {
  const pipelineStore = usePipelineStore();
  const reactFlowRef = useRef<ReactFlowInstance | null>(null);

  // Convert pipeline steps → ReactFlow nodes
  const pipelineNodes: Node[] = useMemo(() => {
    const LOGIC_NODE_TYPES: Record<string, string> = {
      '__switch__': 'switchNode',
      '__merge__': 'mergeNode',
      'condition': 'condition',
      'output': 'output',
      'for_each': 'forEachStep',
    };
    return pipelineStore.steps.map((step, idx) => {
      const errorCount = pipelineStore.validation.errors.filter(
        (e) => e.node_id === step.id,
      ).length;
      const warningCount = pipelineStore.validation.warnings.filter(
        (w) => w.node_id === step.id,
      ).length;
      const nodeType = LOGIC_NODE_TYPES[step.toolName] || 'pipelineStep';
      return {
        id: step.id,
        type: nodeType,
        position: step.position,
        selected: step.id === pipelineStore.selectedStepId,
        data: {
          label: step.label,
          toolName: step.toolName,
          stepNumber: idx + 1,
          configured: Object.keys(step.arguments).length > 0,
          status: pipelineStore.execution.nodeStatuses[step.id] || undefined,
          durationMs: pipelineStore.execution.nodeResults[step.id]?.durationMs,
          errorCount,
          warningCount,
          caseCount: step.switchConfig?.cases?.length,
          mode: step.mergeConfig?.mode,
          conditionText: step.condition
            ? `${step.condition.field} ${step.condition.operator} ${step.condition.value}`
            : undefined,
          onDelete: () => pipelineStore.removeStep(step.id),
        },
        draggable: true,
      };
    });
  }, [
    pipelineStore.steps,
    pipelineStore.selectedStepId,
    pipelineStore.execution,
    pipelineStore.validation,
  ]);

  // Convert pipeline edges → ReactFlow edges
  const pipelineEdges: Edge[] = useMemo(() => {
    return pipelineStore.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: 'pipeline',
      data: {
        label: edge.sourceField || undefined,
        animated: pipelineStore.execution.isRunning,
        onDelete: () => pipelineStore.disconnectSteps(edge.id),
      },
    }));
  }, [pipelineStore.edges, pipelineStore.execution.isRunning, pipelineStore.disconnectSteps]);

  const [rfNodes, setRfNodes, onNodesChange] = useNodesState(pipelineNodes);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState(pipelineEdges);

  // Sync store → ReactFlow state when store changes
  useEffect(() => {
    setRfNodes(pipelineNodes);
    // Auto-fit view when nodes are loaded from config
    if (pipelineNodes.length > 0 && reactFlowRef.current) {
      setTimeout(() => reactFlowRef.current?.fitView({ padding: 0.2 }), 100);
    }
  }, [pipelineNodes, setRfNodes]);

  useEffect(() => {
    setRfEdges(pipelineEdges);
  }, [pipelineEdges, setRfEdges]);

  // Sync position changes from ReactFlow → store
  const handleNodesChange = useCallback(
    (changes: Parameters<typeof onNodesChange>[0]) => {
      onNodesChange(changes);
      // Update store positions for drag events
      for (const change of changes) {
        if (change.type === 'position' && change.position && !change.dragging) {
          pipelineStore.updateStep(change.id, { position: change.position });
        }
      }
    },
    [onNodesChange, pipelineStore],
  );

  // Handle new connections
  const handleConnect = useCallback(
    (connection: Connection) => {
      if (connection.source && connection.target) {
        pipelineStore.connectSteps(connection.source, connection.target);
      }
    },
    [pipelineStore],
  );

  // Node click → select
  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      pipelineStore.setSelectedStep(node.id);
    },
    [pipelineStore],
  );

  // Pane click → deselect
  const handlePaneClick = useCallback(() => {
    pipelineStore.setSelectedStep(null);
  }, [pipelineStore]);

  // Delete nodes
  const handleNodesDelete = useCallback(
    (deleted: Node[]) => {
      for (const node of deleted) {
        pipelineStore.removeStep(node.id);
      }
    },
    [pipelineStore],
  );

  // Drag over (accept drops)
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  }, []);

  // Drop from PipelineToolbar
  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const stepJson = e.dataTransfer.getData('application/abenix-pipeline-step');
      if (!stepJson || !reactFlowRef.current) return;

      const step = JSON.parse(stepJson) as { toolId: string; name: string; isLogic?: boolean };
      const position = reactFlowRef.current.screenToFlowPosition({
        x: e.clientX,
        y: e.clientY,
      });

      pipelineStore.addStep(step.toolId, step.name, position);
    },
    [pipelineStore],
  );

  // Validate connections (prevent cycles)
  const handleIsValidConnection = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return false;
      return checkPipelineConnection(connection.source, connection.target, pipelineStore.steps);
    },
    [pipelineStore.steps],
  );

  return (
    <>
      <PipelineToolbar />
      <div className="flex-1 min-w-0 relative h-full">
        <PipelineCanvas
          nodes={rfNodes}
          edges={rfEdges}
          onNodesChange={handleNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={handleConnect}
          onNodeClick={handleNodeClick}
          onPaneClick={handlePaneClick}
          onNodesDelete={handleNodesDelete}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
          onInit={(instance) => {
            reactFlowRef.current = instance;
            // Fit view after initialization with loaded nodes
            setTimeout(() => instance.fitView({ padding: 0.2 }), 200);
          }}
          isValidConnection={handleIsValidConnection}
        />

        {/* Pipeline execution viewer */}
        {showExecutionViewer && (
          <PipelineExecutionViewer
            isRunning={pipelineStore.execution.isRunning}
            executionId={pipelineStore.execution.executionId}
            nodeStatuses={pipelineStore.execution.nodeStatuses}
            nodeResults={pipelineStore.execution.nodeResults}
            executionPath={pipelineStore.execution.executionPath}
            totalDurationMs={pipelineStore.execution.totalDurationMs}
            onReset={() => {
              pipelineStore.resetExecution();
              setShowExecutionViewer(false);
            }}
            onClose={() => setShowExecutionViewer(false)}
          />
        )}
      </div>
      <StepConfigPanel
        step={pipelineStore.steps.find((s) => s.id === pipelineStore.selectedStepId) || null}
        allSteps={pipelineStore.steps}
        onUpdate={(id, updates) => pipelineStore.updateStep(id, updates)}
        onClose={() => pipelineStore.setSelectedStep(null)}
      />
    </>
  );
}
