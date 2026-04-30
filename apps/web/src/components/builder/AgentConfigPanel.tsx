'use client';

import { useCallback, useState, type ChangeEvent } from 'react';
import {
  Wrench, Database, Plug, ArrowLeft, Plus, Star, Unplug,
  Shield, Hash, MessageSquareText, Trash2, CheckCircle2, AlertCircle,
  Sparkles,
} from 'lucide-react';
import type { Node } from 'reactflow';
import { getToolDoc } from '@/lib/tool-docs';
import {
  ToolConfigFields,
  AgentStepConfig,
  LLMCallConfig,
  LLMRouteConfig,
  CodeExecutorConfig,
  MLModelConfig,
  HttpClientConfig,
  CodeAssetConfig,
  SandboxedJobConfig,
} from './tool-configs';

interface InputVariable {
  name: string;
  type: 'string' | 'number' | 'boolean' | 'file' | 'url' | 'select' | 'connection_string';
  description: string;
  required: boolean;
  default?: string | number | boolean;
  placeholder?: string;
  options?: string[];  // For select type
}

export interface ToolConfig {
  usage_instructions: string;
  parameter_defaults: Record<string, unknown>;
  max_calls: number;
  require_approval: boolean;
}

export function isToolConfigured(tc?: ToolConfig): boolean {
  if (!tc) return false;
  return !!(tc.usage_instructions.trim() || Object.keys(tc.parameter_defaults).length > 0 || tc.max_calls > 0 || tc.require_approval);
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
  input_variables?: InputVariable[];
  tool_config?: Record<string, ToolConfig>;
  // Parity with YAML seed fields that used to be UI-invisible.
  icon?: string;
  example_prompts?: string[];
}

interface MCPExtensions {
  allow_user_mcp?: boolean;
  max_mcp_servers?: number;
  suggested_mcp_servers?: Array<{ registry_id: string; reason: string }>;
  allowed_tool_annotations?: string[];
}

interface MCPNodeInfo {
  id: string;
  name: string;
  url?: string;
}

interface AgentConfigPanelProps {
  config: AgentConfig;
  onChange: (updates: Partial<AgentConfig>) => void;
  selectedNode?: Node | null;
  onClearSelection?: () => void;
  mcpExtensions?: MCPExtensions;
  mcpNodes?: MCPNodeInfo[];
  onConnectMcp?: (registryId: string) => void;
  onAddMcpConnection?: () => void;
  onDisconnectMcp?: (nodeId: string) => void;
}

const MODELS = [
  { value: 'claude-sonnet-4-5-20250929', label: 'Claude Sonnet 4.5' },
  { value: 'claude-haiku-3-5-20241022', label: 'Claude Haiku 3.5' },
  { value: 'gpt-4o', label: 'GPT-4o' },
  { value: 'gpt-4o-mini', label: 'GPT-4o Mini' },
  { value: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash' },
];

const CATEGORIES = [
  'productivity', 'development', 'research', 'creative',
  'customer-support', 'data-analysis', 'education',
  'compliance', 'kyc-aml', 'finance', 'energy', 'legal',
  'other',
];

type Tab = 'general' | 'model' | 'prompt' | 'advanced' | 'mcp';

function formatRegistryId(registryId: string): string {
  return registryId
    .replace(/-mcp$/, '')
    .replace(/[-_]/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

const DEFAULT_TOOL_CONFIG: ToolConfig = {
  usage_instructions: '',
  parameter_defaults: {},
  max_calls: 0,
  require_approval: false,
};

// Specialized config components for specific tools
const SPECIALIZED_CONFIGS: Record<string, React.ComponentType<{ values: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void }>> = {
  agent_step: AgentStepConfig,
  llm_call: LLMCallConfig,
  llm_route: LLMRouteConfig,
  code_executor: CodeExecutorConfig,
  ml_model: MLModelConfig,
  http_client: HttpClientConfig,
  // New in this PR — replace the empty-pane + free-text-UUID experience
  // with proper dropdowns, schema previews, and empty-state CTAs.
  code_asset: CodeAssetConfig,
  sandboxed_job: SandboxedJobConfig,
};

function ToolConfigPanel({
  node,
  toolConfig,
  onToolConfigChange,
  onBack,
}: {
  node: Node;
  toolConfig: ToolConfig;
  onToolConfigChange: (tc: ToolConfig) => void;
  onBack: () => void;
}) {
  const data = node.data;
  const toolId = node.id.replace('tool-', '');
  const configured = isToolConfigured(toolConfig);
  const toolDoc = getToolDoc(toolId);
  const SpecializedConfig = SPECIALIZED_CONFIGS[toolId];

  // Manage parameter_defaults as the source of truth for tool-specific fields
  const handleParamChange = useCallback((newValues: Record<string, unknown>) => {
    onToolConfigChange({ ...toolConfig, parameter_defaults: newValues });
  }, [toolConfig, onToolConfigChange]);

  return (
    <div className="w-[320px] border-l border-slate-800 bg-[#0F172A] flex flex-col shrink-0 overflow-hidden">
      <div className="border-b border-slate-800/50 p-3">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors mb-3"
        >
          <ArrowLeft className="w-3 h-3" />
          Back to Agent Config
        </button>
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-cyan-500/10 flex items-center justify-center shrink-0">
            <Wrench className="w-5 h-5 text-cyan-400" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-white truncate">{data.name}</p>
            <p className="text-[10px] text-slate-500">{toolId}</p>
          </div>
          <div className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium ${
            configured
              ? 'bg-emerald-500/10 text-emerald-400'
              : 'bg-slate-700/50 text-slate-500'
          }`}>
            {configured ? <CheckCircle2 className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
            {configured ? 'Configured' : 'Default'}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Description */}
        <div>
          <label className="block text-xs text-slate-400 mb-1">Description</label>
          <p className="px-3 py-2 bg-slate-800/30 border border-slate-700/30 rounded-lg text-xs text-slate-300">
            {toolDoc?.description || data.description || 'No description available'}
          </p>
        </div>

        {/* ──── Schema-driven or Specialized Parameters ──── */}
        {SpecializedConfig ? (
          <div className="border-t border-slate-700/50 pt-4">
            <p className="text-[9px] text-slate-500 uppercase tracking-wider font-medium mb-3">Configuration</p>
            <SpecializedConfig
              values={toolConfig.parameter_defaults}
              onChange={handleParamChange}
            />
          </div>
        ) : toolDoc && toolDoc.parameters.length > 0 ? (
          <div className="border-t border-slate-700/50 pt-4">
            <p className="text-[9px] text-slate-500 uppercase tracking-wider font-medium mb-3">Parameters</p>
            <ToolConfigFields
              params={toolDoc.parameters}
              values={toolConfig.parameter_defaults}
              onChange={handleParamChange}
            />
          </div>
        ) : null}

        {/* ──── Cross-cutting Concerns ──── */}
        <div className="border-t border-slate-700/50 pt-4 space-y-4">
          <p className="text-[9px] text-slate-500 uppercase tracking-wider font-medium">Execution Settings</p>

          {/* Usage Instructions */}
          <div>
            <label className="flex items-center gap-1.5 text-xs text-slate-400 mb-1.5">
              <MessageSquareText className="w-3 h-3" />
              Usage Instructions
            </label>
            <textarea
              value={toolConfig.usage_instructions}
              onChange={(e) => onToolConfigChange({ ...toolConfig, usage_instructions: e.target.value })}
              placeholder="e.g. Use this tool when the user asks about calculations. Always validate inputs first."
              rows={3}
              className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-600 resize-none focus:outline-none focus:border-cyan-500 leading-relaxed"
            />
            <p className="text-[9px] text-slate-600 mt-1">
              Injected into the system prompt to guide the LLM on when and how to use this tool.
            </p>
          </div>

          {/* Max Calls */}
          <div>
            <label className="flex items-center gap-1.5 text-xs text-slate-400 mb-1.5">
              <Hash className="w-3 h-3" />
              Max Calls per Execution
            </label>
            <input
              type="number"
              value={toolConfig.max_calls || ''}
              onChange={(e) => onToolConfigChange({ ...toolConfig, max_calls: parseInt(e.target.value) || 0 })}
              placeholder="0 = unlimited"
              min={0}
              max={100}
              className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
            />
          </div>

          {/* HITL Approval */}
          <button
            type="button"
            onClick={() => onToolConfigChange({ ...toolConfig, require_approval: !toolConfig.require_approval })}
            className="w-full flex items-center gap-3 cursor-pointer group text-left"
          >
            <div className={`w-9 h-5 rounded-full transition-colors relative shrink-0 ${
              toolConfig.require_approval ? 'bg-cyan-500' : 'bg-slate-700'
            }`}>
              <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${
                toolConfig.require_approval ? 'translate-x-4' : 'translate-x-0.5'
              }`} />
            </div>
            <div>
              <span className="flex items-center gap-1.5 text-xs text-slate-300 group-hover:text-white">
                <Shield className="w-3 h-3" />
                Require HITL Approval
              </span>
              <p className="text-[9px] text-slate-600">Pause execution and wait for human approval before calling this tool</p>
            </div>
          </button>
        </div>

        {/* Reset */}
        {configured && (
          <button
            onClick={() => onToolConfigChange({ ...DEFAULT_TOOL_CONFIG })}
            className="w-full py-2 text-xs text-slate-500 hover:text-red-400 border border-slate-700/50 rounded-lg hover:border-red-500/30 transition-colors"
          >
            Reset to Defaults
          </button>
        )}

        <div className="pt-2 border-t border-slate-800">
          <p className="text-[10px] text-slate-600">
            Configuration is saved with the agent and injected into the system prompt at execution time.
            Via SDK: <code className="bg-slate-800 px-1 rounded">tool_config.{toolId}</code>
          </p>
        </div>
      </div>
    </div>
  );
}

function NodePropertiesPanel({
  node,
  onBack,
  toolConfig,
  onToolConfigChange,
}: {
  node: Node;
  onBack: () => void;
  toolConfig?: ToolConfig;
  onToolConfigChange?: (tc: ToolConfig) => void;
}) {
  const type = node.type;
  const data = node.data;

  // Tool nodes get the full configuration panel
  if (type === 'tool' && toolConfig && onToolConfigChange) {
    return (
      <ToolConfigPanel
        node={node}
        toolConfig={toolConfig}
        onToolConfigChange={onToolConfigChange}
        onBack={onBack}
      />
    );
  }

  const iconMap: Record<string, { icon: typeof Wrench; color: string; bg: string }> = {
    tool: { icon: Wrench, color: 'text-cyan-400', bg: 'bg-cyan-500/10' },
    knowledge: { icon: Database, color: 'text-purple-400', bg: 'bg-purple-500/10' },
    mcp: { icon: Plug, color: 'text-amber-400', bg: 'bg-amber-500/10' },
  };

  const nodeStyle = iconMap[type || ''] || iconMap.tool;
  const Icon = nodeStyle.icon;

  return (
    <div className="w-[320px] border-l border-slate-800 bg-[#0F172A] flex flex-col shrink-0 overflow-hidden">
      <div className="border-b border-slate-800/50 p-3">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors mb-3"
        >
          <ArrowLeft className="w-3 h-3" />
          Back to Agent Config
        </button>
        <div className="flex items-center gap-3">
          <div className={`w-10 h-10 rounded-lg ${nodeStyle.bg} flex items-center justify-center shrink-0`}>
            <Icon className={`w-5 h-5 ${nodeStyle.color}`} />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-white truncate">{data.name}</p>
            <p className="text-[10px] text-slate-500 uppercase tracking-wider">{type} node</p>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {type === 'knowledge' && (
          <>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Knowledge Base</label>
              <p className="px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white">
                {data.name}
              </p>
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Documents</label>
              <p className="px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-slate-300">
                {data.docCount} documents indexed
              </p>
            </div>
          </>
        )}

        {type === 'mcp' && (
          <>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">MCP Server</label>
              <p className="px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white">
                {data.name}
              </p>
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Available Tools</label>
              <p className="px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-slate-300">
                {data.toolCount} tools
              </p>
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Connection</label>
              <div className="flex items-center gap-2 px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg">
                <span className={`w-2 h-2 rounded-full ${data.healthy ? 'bg-emerald-400' : 'bg-red-400'}`} />
                <span className={`text-sm ${data.healthy ? 'text-emerald-400' : 'text-red-400'}`}>
                  {data.healthy ? 'Connected' : 'Disconnected'}
                </span>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// Tool category labels for description generation
const TOOL_CATEGORIES: Record<string, string> = {
  calculator: 'mathematical computation',
  web_search: 'internet research',
  file_reader: 'document processing',
  code_executor: 'code execution',
  database_query: 'database access',
  database_writer: 'data persistence',
  email_sender: 'email communication',
  http_client: 'API integration',
  github_tool: 'GitHub integration',
  memory_store: 'persistent memory',
  memory_recall: 'memory retrieval',
  human_approval: 'human-in-the-loop approval',
  agent_step: 'sub-agent delegation',
  structured_analyzer: 'structured data extraction',
  risk_analyzer: 'risk analysis',
  financial_calculator: 'financial modeling',
  llm_call: 'LLM sub-calls',
  data_merger: 'data merging',
  json_transformer: 'data transformation',
  cloud_storage: 'cloud storage',
  image_analyzer: 'image analysis',
  schema_validator: 'schema validation',
};

function _autoGenerateDescription(config: AgentConfig): string {
  const name = config.name && config.name !== 'New Agent' ? config.name : '';
  const prompt = config.system_prompt || '';
  const tools = (config as unknown as Record<string, unknown>).tools as string[] | undefined;
  const inputVars = config.input_variables || [];

  // Extract role from system prompt (first sentence)
  const firstSentence = prompt.split(/[.!?\n]/).filter(s => s.trim().length > 10)[0]?.trim() || '';
  const roleMatch = firstSentence.match(/you are (?:a |an )?(.+)/i);
  const role = roleMatch?.[1]?.replace(/\.$/, '') || '';

  // Build capability list from tools
  const capabilities = (tools || [])
    .map(t => TOOL_CATEGORIES[t])
    .filter(Boolean)
    .slice(0, 5);

  // Build input parameter info
  const inputInfo = inputVars.length > 0
    ? ` Accepts ${inputVars.length} input parameter${inputVars.length > 1 ? 's' : ''}: ${inputVars.map(v => v.name).join(', ')}.`
    : '';

  // Construct description
  let desc = '';
  if (name && role) {
    desc = `${name} — ${role}. `;
  } else if (name) {
    desc = `${name} — an AI agent that processes your requests using specialized tools. `;
  } else {
    desc = 'An AI agent that processes your requests using specialized tools. ';
  }

  if (capabilities.length > 0) {
    desc += `Capabilities include ${capabilities.join(', ')}. `;
  }

  // Extract key actions from system prompt
  const actionMatches = prompt.match(/(?:you (?:should|will|can|must)|your job is to) (.+?)(?:\.|$)/gi);
  if (actionMatches && actionMatches.length > 0) {
    const action = actionMatches[0].replace(/^(?:you (?:should|will|can|must)|your job is to) /i, '').trim();
    if (action.length > 15 && action.length < 200) {
      desc += action.charAt(0).toUpperCase() + action.slice(1) + '. ';
    }
  }

  desc += inputInfo;

  // Add output hint
  desc += ' Send a message to start — results stream in real-time with full tool call visibility.';

  return desc.trim();
}

export default function AgentConfigPanel({
  config,
  onChange,
  selectedNode,
  onClearSelection,
  mcpExtensions,
  mcpNodes = [],
  onConnectMcp,
  onAddMcpConnection,
  onDisconnectMcp,
}: AgentConfigPanelProps) {
  const [tab, setTab] = useState<Tab>('general');

  // Get/set tool config for selected tool node
  const selectedToolId = selectedNode?.id?.replace('tool-', '') || '';
  const selectedToolConfig: ToolConfig = config.tool_config?.[selectedToolId] || { ...DEFAULT_TOOL_CONFIG };
  const handleToolConfigChange = (tc: ToolConfig) => {
    onChange({
      tool_config: { ...(config.tool_config || {}), [selectedToolId]: tc },
    });
  };

  if (selectedNode && selectedNode.type !== 'agent') {
    return (
      <NodePropertiesPanel
        node={selectedNode}
        onBack={() => onClearSelection?.()}
        toolConfig={selectedNode.type === 'tool' ? selectedToolConfig : undefined}
        onToolConfigChange={selectedNode.type === 'tool' ? handleToolConfigChange : undefined}
      />
    );
  }

  const maxMcpServers = mcpExtensions?.max_mcp_servers || 5;

  const tabs: { key: Tab; label: string; icon?: typeof Plug }[] = [
    { key: 'general', label: 'General' },
    { key: 'model', label: 'Model' },
    { key: 'prompt', label: 'Prompt' },
    { key: 'advanced', label: 'Advanced' },
    { key: 'mcp', label: 'MCP', icon: Plug },
  ];

  const handleText = (field: keyof AgentConfig) => (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    onChange({ [field]: e.target.value });

  const tempLabels = ['Precise', 'Balanced', 'Creative'];
  const tempIdx = config.temperature <= 0.3 ? 0 : config.temperature >= 1.2 ? 2 : 1;

  return (
    <div className="w-[320px] border-l border-slate-800 bg-[#0F172A] flex flex-col shrink-0 overflow-hidden">
      <div className="flex border-b border-slate-800/50">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex-1 py-2.5 text-xs font-medium transition-colors flex items-center justify-center gap-1 ${
              tab === t.key
                ? 'text-cyan-400 border-b-2 border-cyan-400'
                : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            {t.icon && <t.icon className="w-3 h-3" />}
            {t.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {tab === 'general' && (
          <>
            {/* Completeness indicator */}
            {(() => {
              const filled = [
                config.name && config.name !== 'New Agent',
                config.description && config.description.length > 20,
                config.system_prompt && config.system_prompt.length > 20,
                config.category,
              ].filter(Boolean).length;
              return filled < 4 ? (
                <div className="bg-amber-500/5 border border-amber-500/20 rounded-lg px-3 py-2">
                  <p className="text-[10px] text-amber-400 font-medium">Complete your agent setup ({filled}/4)</p>
                  <p className="text-[9px] text-amber-400/60">Fill in Name, Description, System Prompt, and Category so users know what this agent does and how to use it.</p>
                </div>
              ) : null;
            })()}

            <div>
              <label className="block text-xs text-slate-400 mb-1.5">
                Agent Name <span className="text-red-400">*</span>
              </label>
              <input
                type="text"
                value={config.name}
                onChange={handleText('name')}
                placeholder="e.g. Financial Document Analyzer"
                className={`w-full px-3 py-2 bg-slate-800/50 border rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500 ${
                  !config.name || config.name === 'New Agent' ? 'border-amber-500/30' : 'border-slate-700'
                }`}
              />
            </div>
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-xs text-slate-400">
                  Description <span className="text-red-400">*</span>
                </label>
                <button
                  type="button"
                  onClick={() => {
                    const desc = _autoGenerateDescription(config);
                    if (desc) onChange({ description: desc });
                  }}
                  className="flex items-center gap-1 px-2 py-0.5 text-[9px] text-cyan-400 bg-cyan-500/10 rounded hover:bg-cyan-500/20 transition-colors"
                  title="Auto-generate from agent name, system prompt, and tools"
                >
                  <Sparkles className="w-3 h-3" />
                  Auto-generate
                </button>
              </div>
              <textarea
                value={config.description}
                onChange={handleText('description')}
                placeholder="Describe what this agent does, what input it expects, and what output it produces. This is shown to users on the agent card and info page."
                rows={4}
                className={`w-full px-3 py-2 bg-slate-800/50 border rounded-lg text-sm text-white placeholder-slate-500 resize-none focus:outline-none focus:border-cyan-500 ${
                  !config.description || config.description.length < 20 ? 'border-amber-500/30' : 'border-slate-700'
                }`}
              />
              <p className="text-[9px] text-slate-600 mt-1">
                {config.description.length} chars — aim for 100+ characters explaining purpose, expected input, and output format.
              </p>
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">
                Category <span className="text-red-400">*</span>
              </label>
              <select
                value={config.category}
                onChange={handleText('category')}
                className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500"
              >
                <option value="">Select category</option>
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>{c.replace('-', ' ')}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">
                Icon
              </label>
              <input
                type="text"
                value={config.icon || ''}
                onChange={handleText('icon')}
                placeholder="e.g. Bot, Headphones, ClipboardList — a lucide-react name or image URL"
                className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
              />
              <p className="text-[10px] text-slate-600 mt-1">
                Shown on the agent card. Same format YAML seeds use — a{' '}
                <a href="https://lucide.dev/icons" target="_blank" rel="noreferrer" className="text-cyan-400 hover:underline">lucide-react</a>{' '}
                name (preferred) or a full https:// image URL.
              </p>
            </div>
          </>
        )}

        {tab === 'model' && (
          <>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Model</label>
              <select
                value={config.model}
                onChange={handleText('model')}
                className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500"
              >
                {MODELS.map((m) => (
                  <option key={m.value} value={m.value}>{m.label}</option>
                ))}
              </select>
            </div>
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-xs text-slate-400">Temperature</label>
                <span className="text-xs font-mono text-cyan-400">{config.temperature.toFixed(1)}</span>
              </div>
              <input
                type="range"
                min="0"
                max="2"
                step="0.1"
                value={config.temperature}
                onChange={(e) => onChange({ temperature: parseFloat(e.target.value) })}
                className="w-full h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-cyan-500"
              />
              <div className="flex justify-between mt-1">
                {tempLabels.map((l, i) => (
                  <span key={l} className={`text-[10px] ${i === tempIdx ? 'text-cyan-400' : 'text-slate-600'}`}>
                    {l}
                  </span>
                ))}
              </div>
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Max Tokens</label>
              <input
                type="number"
                value={config.max_tokens}
                onChange={(e) => onChange({ max_tokens: parseInt(e.target.value) || 4096 })}
                min={1}
                max={32000}
                className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500"
              />
            </div>
          </>
        )}

        {tab === 'prompt' && (
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">
              System Prompt <span className="text-red-400">*</span>
            </label>
            {!config.system_prompt && (
              <div className="bg-amber-500/5 border border-amber-500/20 rounded-lg px-3 py-2 mb-2">
                <p className="text-[9px] text-amber-400">
                  The system prompt defines your agent&apos;s behavior, expertise, and response style.
                  Include: role description, capabilities, constraints, output format expectations.
                </p>
              </div>
            )}
            <textarea
              value={config.system_prompt}
              onChange={handleText('system_prompt')}
              placeholder={"You are a [role/expertise]. Your job is to [primary task].\n\nCapabilities:\n- [capability 1]\n- [capability 2]\n\nWhen given a request, you should:\n1. [step 1]\n2. [step 2]\n3. [step 3]\n\nOutput format:\n- [describe expected output]"}
              rows={20}
              className={`w-full px-3 py-2 bg-slate-950/50 border rounded-lg text-xs font-mono text-slate-200 placeholder-slate-600 resize-none focus:outline-none focus:border-cyan-500 leading-relaxed ${
                !config.system_prompt ? 'border-amber-500/30' : 'border-slate-700'
              }`}
            />
            <p className="text-[10px] text-slate-600 mt-1.5">
              {config.system_prompt.length} characters {config.system_prompt.length < 50 && config.system_prompt.length > 0 ? '— aim for 200+ characters for effective agents' : ''}
            </p>
          </div>
        )}

        {tab === 'advanced' && (
          <>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Max Iterations</label>
              <input
                type="number"
                value={config.max_iterations}
                onChange={(e) => onChange({ max_iterations: parseInt(e.target.value) || 10 })}
                min={1}
                max={50}
                className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500"
              />
              <p className="text-[10px] text-slate-600 mt-1">Max tool-use loop iterations</p>
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Timeout (seconds)</label>
              <input
                type="number"
                value={config.timeout}
                onChange={(e) => onChange({ timeout: parseInt(e.target.value) || 120 })}
                min={10}
                max={600}
                className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500"
              />
            </div>

            {/* Input Parameters — variables that users fill when executing */}
            <div className="border-t border-slate-700/50 pt-4 mt-2">
              <div className="flex items-center justify-between mb-2">
                <div>
                  <h4 className="text-xs font-semibold text-white">Input Parameters</h4>
                  <p className="text-[10px] text-slate-500">Define variables that users must provide when running this agent or pipeline</p>
                </div>
                <button
                  onClick={() => {
                    const vars = [...(config.input_variables || [])];
                    vars.push({ name: '', type: 'string', description: '', required: false });
                    onChange({ input_variables: vars });
                  }}
                  className="flex items-center gap-1 px-2 py-1 text-[10px] text-cyan-400 bg-cyan-500/10 rounded hover:bg-cyan-500/20 transition-colors"
                >
                  <Plus className="w-3 h-3" />
                  Add Parameter
                </button>
              </div>

              {(config.input_variables || []).length === 0 && (
                <p className="text-[10px] text-slate-600 italic">No input parameters defined. Users will only provide a chat message.</p>
              )}

              <div className="space-y-2">
                {(config.input_variables || []).map((v, idx) => (
                  <div key={idx} className="bg-slate-800/30 border border-slate-700/30 rounded-lg p-2.5 space-y-2">
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={v.name}
                        placeholder="Parameter name"
                        onChange={(e) => {
                          const vars = [...(config.input_variables || [])];
                          vars[idx] = { ...vars[idx], name: e.target.value.replace(/\s+/g, '_').toLowerCase() };
                          onChange({ input_variables: vars });
                        }}
                        className="flex-1 px-2 py-1 text-xs bg-slate-900/50 border border-slate-700 rounded text-white focus:outline-none focus:border-cyan-500"
                      />
                      <select
                        value={v.type}
                        onChange={(e) => {
                          const vars = [...(config.input_variables || [])];
                          vars[idx] = { ...vars[idx], type: e.target.value as InputVariable['type'] };
                          onChange({ input_variables: vars });
                        }}
                        className="w-[110px] shrink-0 px-2 py-1 text-xs bg-slate-900/50 border border-slate-700 rounded text-white focus:outline-none focus:border-cyan-500 truncate"
                      >
                        <option value="string">Text</option>
                        <option value="number">Number</option>
                        <option value="boolean">Yes/No</option>
                        <option value="url">URL</option>
                        <option value="file">File</option>
                        <option value="connection_string">DB Conn</option>
                        <option value="select">Dropdown</option>
                      </select>
                      <button
                        onClick={() => {
                          const vars = (config.input_variables || []).filter((_, i) => i !== idx);
                          onChange({ input_variables: vars });
                        }}
                        className="px-1.5 text-red-400 hover:text-red-300"
                      >
                        &times;
                      </button>
                    </div>
                    <p className="text-[9px] text-slate-600 px-1">
                      {v.type === 'string' && 'Free-form text input'}
                      {v.type === 'number' && 'Numeric value (integer or decimal)'}
                      {v.type === 'boolean' && 'Yes/No toggle switch'}
                      {v.type === 'url' && 'URL with http:// or https://'}
                      {v.type === 'file' && 'User selects a file — content read as text and passed to agent'}
                      {v.type === 'connection_string' && 'Database connection string (masked input)'}
                      {v.type === 'select' && 'Dropdown — add options in Default value (comma-separated)'}
                    </p>
                    <input
                      type="text"
                      value={v.description}
                      placeholder="Description (shown to users)"
                      onChange={(e) => {
                        const vars = [...(config.input_variables || [])];
                        vars[idx] = { ...vars[idx], description: e.target.value };
                        onChange({ input_variables: vars });
                      }}
                      className="w-full px-2 py-1 text-xs bg-slate-900/50 border border-slate-700 rounded text-slate-300 focus:outline-none focus:border-cyan-500"
                    />
                    <div className="flex items-center gap-3">
                      <label className="flex items-center gap-1 text-[10px] text-slate-400">
                        <input
                          type="checkbox"
                          checked={v.required}
                          onChange={(e) => {
                            const vars = [...(config.input_variables || [])];
                            vars[idx] = { ...vars[idx], required: e.target.checked };
                            onChange({ input_variables: vars });
                          }}
                          className="rounded border-slate-600"
                        />
                        Required
                      </label>
                      <input
                        type="text"
                        value={(v.default as string) || ''}
                        placeholder="Default value"
                        onChange={(e) => {
                          const vars = [...(config.input_variables || [])];
                          vars[idx] = { ...vars[idx], default: e.target.value };
                          onChange({ input_variables: vars });
                        }}
                        className="flex-1 px-2 py-0.5 text-[10px] bg-slate-900/50 border border-slate-700 rounded text-slate-400 focus:outline-none focus:border-cyan-500"
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Example Prompts — shown on the agent's chat page as
                starter buttons. YAML-seeded agents can declare these
                under `example_prompts`; the UI used to ignore the field
                entirely. */}
            <div className="border-t border-slate-700/50 pt-4 mt-2">
              <div className="flex items-center justify-between mb-2">
                <div>
                  <h4 className="text-xs font-semibold text-white">Example Prompts</h4>
                  <p className="text-[10px] text-slate-500">Starter prompts shown on the agent&apos;s chat page. Users click them to populate the input.</p>
                </div>
                <button
                  onClick={() => {
                    const prompts = [...(config.example_prompts || [])];
                    prompts.push('');
                    onChange({ example_prompts: prompts });
                  }}
                  className="flex items-center gap-1 px-2 py-1 text-[10px] text-cyan-400 bg-cyan-500/10 rounded hover:bg-cyan-500/20 transition-colors"
                >
                  <Plus className="w-3 h-3" />
                  Add Prompt
                </button>
              </div>
              {(config.example_prompts || []).length === 0 && (
                <p className="text-[10px] text-slate-600 italic">No example prompts. Chat page will show a plain empty input.</p>
              )}
              <div className="space-y-2">
                {(config.example_prompts || []).map((p, idx) => (
                  <div key={idx} className="flex items-start gap-2 bg-slate-800/30 border border-slate-700/30 rounded-lg p-2">
                    <input
                      type="text"
                      value={p}
                      placeholder="e.g. Summarise the attached PDF in 5 bullet points"
                      onChange={(e) => {
                        const prompts = [...(config.example_prompts || [])];
                        prompts[idx] = e.target.value;
                        onChange({ example_prompts: prompts });
                      }}
                      className="flex-1 px-2 py-1 text-xs bg-slate-900/50 border border-slate-700 rounded text-white focus:outline-none focus:border-cyan-500"
                    />
                    <button
                      onClick={() => {
                        const prompts = (config.example_prompts || []).filter((_, i) => i !== idx);
                        onChange({ example_prompts: prompts });
                      }}
                      className="px-1.5 text-red-400 hover:text-red-300"
                      title="Remove"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}

        {tab === 'mcp' && (
          <>
            {/* Header */}
            <div>
              <h3 className="text-sm font-semibold text-white">MCP Integrations</h3>
              <p className="text-[11px] text-slate-400 mt-1">
                Connect external services to extend this agent&apos;s capabilities
              </p>
            </div>

            {/* Limit indicator */}
            <div className="flex items-center justify-between px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg">
              <span className="text-[11px] text-slate-400">Servers connected</span>
              <span className="text-xs font-mono text-cyan-400">
                {mcpNodes.length} / {maxMcpServers}
              </span>
            </div>

            {/* Suggested Servers */}
            {mcpExtensions?.suggested_mcp_servers && mcpExtensions.suggested_mcp_servers.length > 0 && (
              <div>
                <label className="block text-xs text-slate-400 mb-2">Suggested Servers</label>
                <div className="space-y-2">
                  {mcpExtensions.suggested_mcp_servers.map((server) => {
                    const isConnected = mcpNodes.some(
                      (n) => n.name.toLowerCase().replace(/\s+/g, '-') === server.registry_id.replace(/-mcp$/, '').toLowerCase()
                        || n.id === `mcp-${server.registry_id}`,
                    );
                    return (
                      <div
                        key={server.registry_id}
                        className="p-3 bg-slate-800/50 border border-slate-700 rounded-lg"
                      >
                        <div className="flex items-center gap-2 mb-1">
                          <Star className="w-3 h-3 text-amber-400 fill-amber-400" />
                          <span className="text-xs font-medium text-white">
                            {formatRegistryId(server.registry_id)}
                          </span>
                        </div>
                        <p className="text-[10px] text-slate-500 mb-2">{server.reason}</p>
                        <button
                          onClick={() => onConnectMcp?.(server.registry_id)}
                          disabled={isConnected || mcpNodes.length >= maxMcpServers}
                          className={`w-full py-1.5 text-[11px] font-medium rounded-md transition-all ${
                            isConnected
                              ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
                              : mcpNodes.length >= maxMcpServers
                                ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
                                : 'bg-gradient-to-r from-cyan-500 to-blue-500 text-white hover:from-cyan-400 hover:to-blue-400'
                          }`}
                        >
                          {isConnected ? 'Connected' : 'Connect'}
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Connected Servers List */}
            {mcpNodes.length > 0 && (
              <div>
                <label className="block text-xs text-slate-400 mb-2">Connected Servers</label>
                <div className="space-y-2">
                  {mcpNodes.map((node) => (
                    <div
                      key={node.id}
                      className="flex items-center gap-2 p-3 bg-slate-800/50 border border-slate-700 rounded-lg"
                    >
                      <div className="w-7 h-7 rounded-md bg-amber-500/10 flex items-center justify-center shrink-0">
                        <Plug className="w-3.5 h-3.5 text-amber-400" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium text-white truncate">{node.name}</p>
                        {node.url && (
                          <p className="text-[10px] text-slate-500 truncate">{node.url}</p>
                        )}
                      </div>
                      <button
                        onClick={() => onDisconnectMcp?.(node.id)}
                        className="p-1 text-slate-500 hover:text-red-400 transition-colors shrink-0"
                        title="Disconnect"
                      >
                        <Unplug className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Add MCP Connection Button */}
            <button
              onClick={() => onAddMcpConnection?.()}
              disabled={mcpNodes.length >= maxMcpServers}
              className={`w-full flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-medium transition-all ${
                mcpNodes.length >= maxMcpServers
                  ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
                  : 'bg-gradient-to-r from-cyan-500 to-blue-500 text-white hover:from-cyan-400 hover:to-blue-400 shadow-lg shadow-cyan-500/20'
              }`}
            >
              <Plus className="w-4 h-4" />
              Add MCP Connection
            </button>

            {/* Info text */}
            <div className="pt-2 border-t border-slate-800">
              <p className="text-[10px] text-slate-600">
                MCP (Model Context Protocol) servers extend your agent with external
                tools and data sources. Each server can provide multiple tools.
              </p>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
