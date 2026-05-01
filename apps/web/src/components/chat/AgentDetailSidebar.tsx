'use client';

import { useState } from 'react';
import {
  Bot,
  ChevronRight,
  ChevronLeft,
  Code2,
  Copy,
  Check,
  ExternalLink,
  MessageSquare,
  Save,
  Send,
  Settings,
  Terminal,
  Trash2,
  Webhook,
  Wrench,
  Cpu,
  Thermometer,
  X,
  Zap,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import type { AgentInfo } from '@/stores/chatStore';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// Tool descriptions for common tools
const TOOL_DESCRIPTIONS: Record<string, string> = {
  calculator: 'Evaluates mathematical expressions',
  current_time: 'Returns current time in any timezone',
  web_search: 'Searches the internet for real-time information',
  file_reader: 'Reads PDF, DOCX, CSV, and other documents',
  llm_call: 'Calls another LLM model as a sub-step',
  email_sender: 'Sends emails via SMTP',
  data_merger: 'Merges outputs from parallel steps',
  code_executor: 'Executes Python code in a sandbox',
  json_transformer: 'Reshapes and transforms JSON data',
  database_query: 'Queries PostgreSQL databases',
  database_writer: 'Writes data to PostgreSQL tables',
  http_client: 'Makes HTTP requests to external APIs',
  data_exporter: 'Exports data to S3, webhooks, or files',
  cloud_storage: 'Read/write to S3, GCS, or Azure Blob',
  memory_store: 'Stores facts in persistent agent memory',
  memory_recall: 'Recalls previously stored memories',
  memory_forget: 'Removes specific memories',
  human_approval: 'Pauses for human-in-the-loop approval',
  agent_step: 'Delegates to a sub-agent with its own prompt',
  github_tool: 'Interacts with GitHub repos, PRs, issues',
  structured_analyzer: 'LLM-powered structured data extraction',
  schema_validator: 'Validates JSON against a schema',
  image_analyzer: 'Analyzes images using vision models',
  risk_analyzer: 'Financial risk scoring and analysis',
  financial_calculator: 'LCOE, IRR, NPV, VaR calculations',
};

interface AgentDetailSidebarProps {
  agent: AgentInfo;
  onClearChat: () => void;
  onAgentUpdated?: () => void;
  isOOB?: boolean;
}

type SidebarTab = 'info' | 'integrate' | 'settings';

export default function AgentDetailSidebar({
  agent,
  onClearChat,
  onAgentUpdated,
  isOOB = false,
}: AgentDetailSidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [tab, setTab] = useState<SidebarTab>('info');
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [editModel, setEditModel] = useState(agent.model_config?.model || '');
  const [editTemp, setEditTemp] = useState(agent.model_config?.temperature ?? 0.7);
  const [copiedField, setCopiedField] = useState<string | null>(null);
  const [expandedCode, setExpandedCode] = useState<string | null>(null);

  const tools = agent.model_config?.tools ?? [];
  const isPipeline = (agent.model_config as Record<string, unknown>)?.mode === 'pipeline';

  const copy = (text: string, field: string) => {
    navigator.clipboard.writeText(text);
    setCopiedField(field);
    setTimeout(() => setCopiedField(null), 2000);
  };

  const handleSaveSettings = async () => {
    setSettingsLoading(true);
    await apiFetch(`/api/agents/${agent.id}`, {
      method: 'PATCH',
      body: JSON.stringify({
        model_config: {
          ...agent.model_config,
          model: editModel,
          temperature: editTemp,
        },
      }),
    });
    setSettingsLoading(false);
    onAgentUpdated?.();
  };

  if (collapsed) {
    return (
      <div className="w-12 border-l border-slate-800 bg-[#0F172A] flex flex-col items-center py-4 shrink-0">
        <button
          onClick={() => setCollapsed(false)}
          className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/50 transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
      </div>
    );
  }

  const jsSnippet = `import { Abenix } from '@abenix/sdk';
const forge = new Abenix({
  apiKey: 'af_...',
  baseUrl: '${API_URL}'
});

// Execute with streaming
for await (const event of forge.stream(
  '${agent.slug}',
  'Your message here'
)) {
  if (event.type === 'token') process.stdout.write(event.text);
  if (event.type === 'tool_call') console.log('Tool:', event.name);
  if (event.type === 'done') console.log('Cost:', event.cost);
}`;

  const pySnippet = `from abenix_sdk import Abenix

client = Abenix(
    api_key="af_...",
    base_url="${API_URL}"
)

# Execute with streaming
async for event in client.agents.stream(
    "${agent.slug}",
    "Your message here"
):
    if event.type == "token": print(event.text, end="")
    if event.type == "done": print(f"Cost: ${'{'}event.cost{'}'}")`;

  const curlSnippet = `curl -X POST ${API_URL}/api/agents/${agent.id}/execute \\
  -H "Authorization: Bearer YOUR_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"message": "Your prompt", "stream": true}'`;

  const webhookSnippet = `# Create a webhook trigger (auto-execute on POST)
curl -X POST ${API_URL}/api/triggers \\
  -H "Authorization: Bearer YOUR_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"agent_id": "${agent.id}", "trigger_type": "webhook"}'

# Response includes webhook_url — POST to it to trigger:
curl -X POST ${API_URL}/api/triggers/webhook/TOKEN \\
  -H "Content-Type: application/json" \\
  -d '{"message": "Data to process", "context": {}}'`;

  return (
    <div className="w-80 border-l border-slate-800 bg-[#0F172A] flex flex-col shrink-0 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-slate-800/50">
        <h3 className="text-sm font-semibold text-white">Agent Details</h3>
        <button
          onClick={() => setCollapsed(true)}
          className="w-7 h-7 flex items-center justify-center rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/50 transition-colors"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>

      {/* Tab bar */}
      <div className="flex border-b border-slate-800/50">
        {([
          { key: 'info', label: 'Info', icon: Bot },
          { key: 'integrate', label: 'Integrate', icon: Code2 },
          { key: 'settings', label: 'Settings', icon: Settings },
        ] as const).map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex-1 flex items-center justify-center gap-1.5 py-2.5 text-[10px] font-medium transition-colors ${
              tab === t.key
                ? 'text-cyan-400 border-b-2 border-cyan-400'
                : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            <t.icon className="w-3 h-3" />
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {tab === 'info' && (
          <>
            {/* Agent header */}
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-lg bg-cyan-500/10 flex items-center justify-center shrink-0">
                <Bot className="w-5 h-5 text-cyan-400" />
              </div>
              <div className="min-w-0">
                <h4 className="text-sm font-semibold text-white">{agent.name}</h4>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-[10px] text-slate-500 font-mono">{agent.slug}</span>
                  {isPipeline && (
                    <span className="text-[9px] bg-emerald-500/10 text-emerald-400 px-1.5 py-0.5 rounded-full">
                      Pipeline
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* Description */}
            <p className="text-xs text-slate-400 leading-relaxed">
              {agent.description || 'No description provided.'}
            </p>

            {/* How to Use */}
            <div className="bg-slate-800/30 border border-slate-700/30 rounded-lg p-3">
              <h5 className="text-[10px] uppercase tracking-wider text-cyan-400 mb-2 flex items-center gap-1.5">
                <MessageSquare className="w-3 h-3" />
                How to Use
              </h5>
              <p className="text-[11px] text-slate-300 leading-relaxed">
                {isPipeline ? (
                  <>Send a message to trigger the pipeline. The agent processes your input through multiple stages — each stage&apos;s output feeds into the next. You&apos;ll see tool calls and intermediate results in real-time via streaming.</>
                ) : (
                  <>Type your request in the chat. The agent will use its tools iteratively to research, compute, and compose a response. Each tool call is visible in the chat. For complex tasks, the agent may use multiple iterations.</>
                )}
              </p>
            </div>

            {/* Sample prompt */}
            <div className="bg-slate-800/30 border border-slate-700/30 rounded-lg p-3">
              <h5 className="text-[10px] uppercase tracking-wider text-slate-500 mb-2 flex items-center gap-1.5">
                <Send className="w-3 h-3" />
                Try This Prompt
              </h5>
              <p className="text-[11px] text-slate-300 italic leading-relaxed">
                &ldquo;{_getSamplePrompt(agent.slug, agent.name)}&rdquo;
              </p>
            </div>

            {/* Configuration */}
            <div className="space-y-2">
              <h5 className="text-[10px] uppercase tracking-wider text-slate-500">Configuration</h5>
              <div className="flex items-center gap-2.5 text-sm">
                <Cpu className="w-3.5 h-3.5 text-slate-500" />
                <span className="text-slate-300 font-mono text-[10px]">
                  {agent.model_config?.model || 'pipeline'}
                </span>
              </div>
              <div className="flex items-center gap-2.5 text-sm">
                <Thermometer className="w-3.5 h-3.5 text-slate-500" />
                <span className="text-slate-300 text-[10px]">
                  Temperature: {agent.model_config?.temperature ?? 'N/A'}
                </span>
              </div>
            </div>

            {/* Tools with descriptions */}
            {tools.length > 0 && (
              <div className="space-y-2">
                <h5 className="text-[10px] uppercase tracking-wider text-slate-500">
                  Tools ({tools.length})
                </h5>
                <div className="space-y-1">
                  {tools.map((tool) => (
                    <div
                      key={tool}
                      className="flex items-start gap-2 p-1.5 rounded bg-slate-800/30"
                    >
                      <Wrench className="w-3 h-3 text-cyan-400 mt-0.5 shrink-0" />
                      <div className="min-w-0">
                        <span className="text-[10px] font-mono text-cyan-400">{tool}</span>
                        {TOOL_DESCRIPTIONS[tool] && (
                          <p className="text-[9px] text-slate-500">{TOOL_DESCRIPTIONS[tool]}</p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {agent.category && (
              <span className="inline-block text-[10px] bg-purple-500/10 text-purple-400 border border-purple-500/20 px-2 py-0.5 rounded-md">
                {agent.category}
              </span>
            )}
          </>
        )}

        {tab === 'integrate' && (
          <>
            {/* Collapsible code blocks for sidebar */}
            {[
              { id: 'curl', title: 'REST API (cURL)', icon: Terminal, code: curlSnippet },
              { id: 'js', title: 'JavaScript / TypeScript', code: jsSnippet },
              { id: 'py', title: 'Python SDK', code: pySnippet },
              { id: 'webhook', title: 'Webhook Trigger', icon: Webhook, code: webhookSnippet, desc: 'Auto-execute via external POST request' },
            ].map((block) => {
              const isExpanded = expandedCode === block.id;
              const BlockIcon = block.icon;
              return (
                <div key={block.id}>
                  <button
                    onClick={() => setExpandedCode(isExpanded ? null : block.id)}
                    className="w-full flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-slate-500 hover:text-slate-300 mb-1.5 text-left"
                  >
                    {BlockIcon && <BlockIcon className="w-3 h-3" />}
                    {block.title}
                    <ChevronRight className={`w-3 h-3 ml-auto transition-transform ${isExpanded ? 'rotate-90' : ''}`} />
                  </button>
                  {block.desc && <p className="text-[9px] text-slate-600 mb-1">{block.desc}</p>}
                  <div className={`relative transition-all overflow-hidden ${isExpanded ? 'max-h-[500px]' : 'max-h-[80px]'}`}>
                    <pre className="text-[9px] font-mono text-slate-300 bg-slate-900/50 border border-slate-700/30 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap leading-relaxed">
                      {block.code}
                    </pre>
                    {!isExpanded && (
                      <div className="absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-[#0F172A] to-transparent pointer-events-none" />
                    )}
                    <button
                      onClick={(e) => { e.stopPropagation(); copy(block.code, block.id); }}
                      className="absolute top-2 right-2 p-1 text-slate-500 hover:text-cyan-400 bg-slate-800/80 rounded"
                    >
                      {copiedField === block.id ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                    </button>
                  </div>
                </div>
              );
            })}

            {/* Cron Schedule */}
            <div>
              <h5 className="text-[10px] uppercase tracking-wider text-slate-500 mb-2 flex items-center gap-1.5">
                <Zap className="w-3 h-3" />
                Scheduled Execution
              </h5>
              <p className="text-[9px] text-slate-500 mb-2">
                Run this agent on a cron schedule (e.g., every hour, daily at midnight).
              </p>
              <a
                href="/triggers"
                className="flex items-center gap-1.5 text-[10px] text-cyan-400 hover:underline"
              >
                <ExternalLink className="w-3 h-3" />
                Manage Triggers
              </a>
            </div>

            {/* Output format */}
            <div className="bg-slate-800/30 border border-slate-700/30 rounded-lg p-3">
              <h5 className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">
                Output Format
              </h5>
              <p className="text-[9px] text-slate-400 leading-relaxed">
                <strong className="text-slate-300">Streaming:</strong> SSE events with types{' '}
                <code className="bg-slate-800 px-1 rounded text-cyan-400">token</code>,{' '}
                <code className="bg-slate-800 px-1 rounded text-cyan-400">tool_call</code>,{' '}
                <code className="bg-slate-800 px-1 rounded text-cyan-400">tool_result</code>,{' '}
                <code className="bg-slate-800 px-1 rounded text-cyan-400">done</code>
              </p>
              <p className="text-[9px] text-slate-400 leading-relaxed mt-1">
                <strong className="text-slate-300">Non-streaming:</strong> JSON with{' '}
                <code className="bg-slate-800 px-1 rounded text-cyan-400">output</code>,{' '}
                <code className="bg-slate-800 px-1 rounded text-cyan-400">cost</code>,{' '}
                <code className="bg-slate-800 px-1 rounded text-cyan-400">duration_ms</code>,{' '}
                <code className="bg-slate-800 px-1 rounded text-cyan-400">confidence_score</code>
              </p>
            </div>
          </>
        )}

        {tab === 'settings' && (
          <>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Model</label>
                <select
                  value={editModel}
                  onChange={(e) => setEditModel(e.target.value)}
                  disabled={isOOB}
                  className="w-full bg-slate-800/50 border border-slate-700 text-slate-200 text-xs rounded-lg px-3 py-2 focus:border-cyan-500 focus:outline-none disabled:opacity-50"
                >
                  <option value="claude-sonnet-4-5-20250929">Claude Sonnet 4.5</option>
                  <option value="claude-haiku-3-5-20241022">Claude Haiku 3.5</option>
                  <option value="gpt-4o">GPT-4o</option>
                  <option value="gpt-4o-mini">GPT-4o Mini</option>
                  <option value="gemini-2.0-flash">Gemini 2.0 Flash</option>
                </select>
              </div>

              <div>
                <label className="text-xs text-slate-400 mb-1 block">
                  Temperature: {editTemp}
                </label>
                <input
                  type="range"
                  min="0"
                  max="2"
                  step="0.1"
                  value={editTemp}
                  onChange={(e) => setEditTemp(parseFloat(e.target.value))}
                  disabled={isOOB}
                  className="w-full accent-cyan-500 disabled:opacity-50"
                />
                <div className="flex justify-between text-[10px] text-slate-600">
                  <span>Precise</span>
                  <span>Creative</span>
                </div>
              </div>
            </div>

            {!isOOB && (
              <button
                onClick={handleSaveSettings}
                disabled={settingsLoading}
                className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg hover:from-cyan-400 hover:to-purple-500 transition-colors disabled:opacity-50"
              >
                <Save className="w-4 h-4" />
                {settingsLoading ? 'Saving...' : 'Save Settings'}
              </button>
            )}

            {isOOB && (
              <p className="text-[10px] text-slate-500 text-center italic">
                Pre-built agents cannot be modified. Fork this agent to customize.
              </p>
            )}
          </>
        )}
      </div>

      {/* Bottom actions */}
      <div className="p-4 space-y-2 border-t border-slate-800/50">
        <button
          onClick={onClearChat}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-transparent text-slate-400 text-sm rounded-lg hover:text-white hover:bg-slate-800 transition-colors"
        >
          <Trash2 className="w-4 h-4" />
          Clear Chat
        </button>
      </div>
    </div>
  );
}

function _getSamplePrompt(slug: string, name: string): string {
  const prompts: Record<string, string> = {
    'repo-analyzer': 'Analyze the repository https://github.com/anthropics/anthropic-sdk-python — map the architecture, identify security issues, and summarize the business purpose.',
    'ppa-contract-analyzer': 'Analyze this PPA contract: calculate LCOE at 5%, 8%, and 10% discount rates, assess counterparty credit risk, and model IRR scenarios over 20 years.',
    'email-triager': 'Triage this support ticket: "Our production API has been returning 500 errors for the last 30 minutes. Enterprise account. This is blocking our release." — classify, score priority, route, and draft a response.',
    'energy-market-analyst': 'Perform risk analysis on a 150MW solar portfolio: run Monte Carlo with 10,000 iterations, calculate VaR at 95% confidence, and benchmark against current wholesale prices.',
    'migration-orchestrator': 'Plan the migration of FINANCE and OPERATIONS schemas from Exasol to BigQuery. Use medallion architecture. Prioritize tables used by MicroStrategy reports.',
    'code-assistant': 'Review this Python function for security vulnerabilities, performance issues, and suggest improvements following PEP 8 best practices.',
    'research-assistant': 'Research the current state of AI agent frameworks in 2025. Compare LangGraph, CrewAI, AutoGen, and n8n — focus on enterprise readiness and marketplace features.',
    'data-analyst': 'Analyze this CSV data: identify trends, compute key statistics (mean, median, standard deviation), find outliers, and generate a summary report with recommendations.',
    'deep-research': 'Conduct a deep investigation into quantum computing applications in drug discovery. Cover current state, key players, recent breakthroughs, and 5-year outlook.',
    'compliance-auditor': 'Audit our data handling practices against GDPR requirements. Check for consent management, data retention policies, right to erasure implementation, and cross-border transfer compliance.',
    'content-writer': 'Write a comprehensive blog post about the benefits of AI-powered automation in enterprise workflows. Include statistics, use cases, and a clear call-to-action.',
    'financial-modeler': 'Build a financial model for a SaaS company: project revenue for 5 years based on current ARR of $2M, 15% monthly growth, 5% churn, and planned pricing changes.',
    'document-analyzer': 'Extract all key terms, financial figures, obligations, and deadlines from this legal document. Flag any unusual clauses or potential risks.',
    'competitive-analyst': 'Analyze the competitive landscape for AI agent builder platforms. Compare pricing, features, market positioning, and identify gaps we can exploit.',
    'cloud-cost-optimizer': 'Analyze our AWS bill: identify unused resources, recommend right-sizing for EC2 instances, suggest Reserved Instance purchases, and estimate potential monthly savings.',
  };
  return prompts[slug] || `Help me with a task that leverages ${name}'s capabilities. Provide detailed analysis and actionable recommendations.`;
}
