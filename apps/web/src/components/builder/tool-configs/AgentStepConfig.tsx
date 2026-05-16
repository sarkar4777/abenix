'use client';


import { useEffect, useState, useMemo } from 'react';
import { Bot, ChevronDown, Loader2, Search } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const MODELS = [
  { value: 'claude-sonnet-4-5-20250929', label: 'Claude Sonnet 4.5' },
  { value: 'claude-haiku-3-5-20241022', label: 'Claude Haiku 3.5' },
  { value: 'gpt-4o', label: 'GPT-4o' },
  { value: 'gpt-4o-mini', label: 'GPT-4o Mini' },
  { value: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash' },
];

const COMMON_TOOLS = [
  'web_search', 'calculator', 'code_executor', 'file_reader', 'http_client',
  'llm_call', 'email_sender', 'data_exporter', 'json_transformer', 'csv_analyzer',
  'database_query', 'github_tool', 'vector_search', 'text_analyzer', 'regex_extractor',
  'pii_redactor', 'structured_analyzer', 'memory_store', 'memory_recall',
];

interface AgentOption {
  id: string;
  name: string;
  description: string;
  slug: string;
}

interface AgentStepConfigProps {
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
}

export default function AgentStepConfig({ values, onChange }: AgentStepConfigProps) {
  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [agentSearch, setAgentSearch] = useState('');
  const [showToolPicker, setShowToolPicker] = useState(false);

  // Load available agents
  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (!token) { setLoading(false); return; }
    fetch(`${API_URL}/api/agents?limit=200`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.json())
      .then((body) => {
        const list = (body.data || [])
          .filter((a: Record<string, unknown>) => a.status === 'active')
          .map((a: Record<string, unknown>) => ({
            id: a.id as string,
            name: a.name as string,
            description: (a.description as string || '').slice(0, 100),
            slug: a.slug as string,
          }));
        setAgents(list);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const selectedTools = Array.isArray(values.tools) ? values.tools as string[] : [];
  const temperature = typeof values.temperature === 'number' ? values.temperature : 0.7;
  const maxIterations = typeof values.max_iterations === 'number' ? values.max_iterations : 10;
  const model = (values.model as string) || 'claude-sonnet-4-5-20250929';

  const filteredAgents = useMemo(() => {
    if (!agentSearch.trim()) return agents;
    const q = agentSearch.toLowerCase();
    return agents.filter((a) => a.name.toLowerCase().includes(q) || a.slug.toLowerCase().includes(q));
  }, [agents, agentSearch]);

  return (
    <div className="space-y-4">
      {/* Input Message (the task prompt) */}
      <div>
        <label className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1">
          <span className="font-mono text-slate-500">input_message</span>
          <span className="text-red-400 text-[8px]">required</span>
        </label>
        <textarea
          value={(values.input_message as string) || ''}
          onChange={(e) => onChange({ ...values, input_message: e.target.value })}
          placeholder="The task or prompt for the sub-agent to work on. Use {{node_id.field}} for pipeline template variables."
          rows={3}
          className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-600 resize-none focus:outline-none focus:border-cyan-500"
        />
      </div>

      {/* System Prompt */}
      <div>
        <label className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1">
          <span className="font-mono text-slate-500">system_prompt</span>
          <span className="text-red-400 text-[8px]">required</span>
        </label>
        <textarea
          value={(values.system_prompt as string) || ''}
          onChange={(e) => onChange({ ...values, system_prompt: e.target.value })}
          placeholder="Define the sub-agent's role and behavior. E.g.: You are a research assistant that finds and summarizes information."
          rows={4}
          className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-600 resize-none focus:outline-none focus:border-cyan-500"
        />
      </div>

      {/* OR pick an existing agent */}
      {agents.length > 0 && (
        <div className="bg-slate-800/30 border border-slate-700/30 rounded-lg p-3">
          <p className="text-[9px] text-slate-500 uppercase tracking-wider font-medium mb-2">
            Or copy settings from an existing agent
          </p>
          <div className="relative mb-2">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-500" />
            <input
              value={agentSearch}
              onChange={(e) => setAgentSearch(e.target.value)}
              placeholder="Search agents..."
              className="w-full pl-8 pr-3 py-1.5 bg-slate-900/50 border border-slate-700 rounded text-[10px] text-white placeholder-slate-600 focus:outline-none focus:border-cyan-500"
            />
          </div>
          <div className="max-h-32 overflow-y-auto space-y-1">
            {loading ? (
              <div className="flex items-center justify-center py-3">
                <Loader2 className="w-4 h-4 text-slate-500 animate-spin" />
              </div>
            ) : filteredAgents.length === 0 ? (
              <p className="text-[9px] text-slate-600 text-center py-2">No agents found</p>
            ) : (
              filteredAgents.slice(0, 10).map((agent) => (
                <button
                  key={agent.id}
                  onClick={() => {
                    // Copy agent info to config
                    onChange({
                      ...values,
                      system_prompt: values.system_prompt || `Act as the "${agent.name}" agent.`,
                      input_message: values.input_message || `{{context.input}}`,
                      _selected_agent_name: agent.name,
                    });
                  }}
                  className="w-full text-left px-2 py-1.5 rounded hover:bg-slate-700/50 transition-colors flex items-center gap-2"
                >
                  <Bot className="w-3 h-3 text-cyan-400 shrink-0" />
                  <div className="min-w-0">
                    <p className="text-[10px] text-slate-300 truncate">{agent.name}</p>
                    <p className="text-[8px] text-slate-600 truncate">{agent.description}</p>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      )}

      {/* Model */}
      <div>
        <label className="text-[10px] text-slate-400 mb-1 block">
          <span className="font-mono text-slate-500">model</span>
          <span className="text-slate-600 text-[8px] ml-1.5">default: claude-sonnet-4-5</span>
        </label>
        <div className="relative">
          <select
            value={model}
            onChange={(e) => onChange({ ...values, model: e.target.value })}
            className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-white focus:outline-none focus:border-cyan-500 appearance-none pr-8"
          >
            {MODELS.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
          <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
        </div>
      </div>

      {/* Tools multi-select */}
      <div>
        <label className="flex items-center justify-between text-[10px] text-slate-400 mb-1">
          <span className="font-mono text-slate-500">tools</span>
          <span className="text-slate-600">{selectedTools.length} selected</span>
        </label>
        <button
          onClick={() => setShowToolPicker(!showToolPicker)}
          className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-left text-slate-400 hover:border-slate-600 transition-colors flex items-center justify-between"
        >
          <span>{selectedTools.length > 0 ? selectedTools.join(', ') : 'Select tools for the sub-agent...'}</span>
          <ChevronDown className={`w-3.5 h-3.5 transition-transform ${showToolPicker ? 'rotate-180' : ''}`} />
        </button>
        {showToolPicker && (
          <div className="mt-1 max-h-40 overflow-y-auto bg-slate-900/50 border border-slate-700 rounded-lg p-2 space-y-0.5">
            {COMMON_TOOLS.map((tool) => (
              <label key={tool} className="flex items-center gap-2 cursor-pointer px-2 py-1 rounded hover:bg-slate-800/50 text-[10px]">
                <input
                  type="checkbox"
                  checked={selectedTools.includes(tool)}
                  onChange={(e) => {
                    const next = e.target.checked
                      ? [...selectedTools, tool]
                      : selectedTools.filter((t) => t !== tool);
                    onChange({ ...values, tools: next });
                  }}
                  className="w-3 h-3 rounded border-slate-600 bg-slate-900 text-cyan-500"
                />
                <span className="text-slate-300 font-mono">{tool}</span>
              </label>
            ))}
          </div>
        )}
      </div>

      {/* Temperature slider */}
      <div>
        <label className="flex items-center justify-between text-[10px] text-slate-400 mb-1">
          <span className="font-mono text-slate-500">temperature</span>
          <span className="text-slate-300">{temperature.toFixed(1)}</span>
        </label>
        <input
          type="range"
          min={0}
          max={2}
          step={0.1}
          value={temperature}
          onChange={(e) => onChange({ ...values, temperature: parseFloat(e.target.value) })}
          className="w-full h-1.5 bg-slate-700 rounded-full appearance-none cursor-pointer accent-cyan-500"
        />
        <div className="flex justify-between text-[8px] text-slate-600 mt-0.5">
          <span>Precise</span>
          <span>Balanced</span>
          <span>Creative</span>
        </div>
      </div>

      {/* Max iterations */}
      <div>
        <label className="flex items-center justify-between text-[10px] text-slate-400 mb-1">
          <span className="font-mono text-slate-500">max_iterations</span>
          <span className="text-slate-300">{maxIterations}</span>
        </label>
        <input
          type="range"
          min={1}
          max={25}
          step={1}
          value={maxIterations}
          onChange={(e) => onChange({ ...values, max_iterations: parseInt(e.target.value) })}
          className="w-full h-1.5 bg-slate-700 rounded-full appearance-none cursor-pointer accent-cyan-500"
        />
        <div className="flex justify-between text-[8px] text-slate-600 mt-0.5">
          <span>1 (single pass)</span>
          <span>25 (deep reasoning)</span>
        </div>
      </div>
    </div>
  );
}
