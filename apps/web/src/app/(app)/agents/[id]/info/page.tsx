'use client';

import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import dynamic from 'next/dynamic';
import { motion } from 'framer-motion';

const PipelineDAGPreview = dynamic(
  () => import('@/components/shared/PipelineDAGPreview'),
  { ssr: false, loading: () => <div className="h-[200px] bg-slate-900/30 rounded-xl animate-pulse" /> }
);
import {
  Bot, Code2, Copy, Check, Clock, Cpu, Database, ExternalLink,
  MessageSquare, Play, Sparkles, Terminal, Thermometer, Webhook,
  Wrench, Zap, Share2, GitBranch, Download, Upload,
} from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { usePageTitle } from '@/hooks/usePageTitle';
import ShareDialog from '@/components/agent/ShareDialog';
import VersionHistoryDialog from '@/components/agent/VersionHistoryDialog';
import ExportImportDialog from '@/components/agent/ExportImportDialog';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

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

interface AgentDetail {
  id: string;
  name: string;
  slug: string;
  description: string;
  system_prompt: string;
  agent_type: string;
  status: string;
  category?: string;
  model_config_?: {
    model?: string;
    temperature?: number;
    tools?: string[];
    mode?: string;
    input_variables?: Array<{ name: string; type: string; description: string; required: boolean }>;
  };
  model_config?: {
    model?: string;
    temperature?: number;
    tools?: string[];
    mode?: string;
    input_variables?: Array<{ name: string; type: string; description: string; required: boolean }>;
  };
}

export default function AgentInfoPage() {
  const params = useParams();
  const router = useRouter();
  const agentId = params.id as string;
  const [copiedField, setCopiedField] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'overview' | 'api' | 'triggers'>('overview');
  const [showShare, setShowShare] = useState(false);
  const [showVersions, setShowVersions] = useState(false);
  const [showExport, setShowExport] = useState(false);

  const { data: agent } = useApi<AgentDetail>(agentId ? `/api/agents/${agentId}` : null);
  usePageTitle(agent?.name ? `${agent.name} — Info` : 'Agent Info');

  const copy = (text: string, field: string) => {
    navigator.clipboard.writeText(text);
    setCopiedField(field);
    setTimeout(() => setCopiedField(null), 2000);
  };

  if (!agent) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-8 h-8 border-2 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin" />
      </div>
    );
  }

  const mc = agent.model_config_ || agent.model_config || {};
  const tools = mc.tools || [];
  const isPipeline = mc.mode === 'pipeline';
  const inputVars = mc.input_variables || [];

  const curlExample = `# Option 1: API key auth (for SDK / server-to-server)
curl -X POST ${API_URL}/api/agents/${agent.id}/execute \\
  -H "X-API-Key: af_your_api_key" \\
  -H "Content-Type: application/json" \\
  -d '{
    "message": "Your prompt here",
    "stream": true${inputVars.length > 0 ? `,
    "context": {
${inputVars.map(v => `      "${v.name}": "value"`).join(',\n')}
    }` : ''}
  }'

# Option 2: Bearer token auth (for browser / JWT sessions)
# curl ... -H "Authorization: Bearer <jwt_access_token>"`;


  const jsExample = `import { Abenix } from '@abenix/sdk';

const forge = new Abenix({
  apiKey: 'af_your_key',
  baseUrl: '${API_URL}'
});

// Non-streaming execution
const result = await forge.execute('${agent.slug}', 'Your prompt'${inputVars.length > 0 ? `, {
  context: { ${inputVars.map(v => `${v.name}: 'value'`).join(', ')} }
}` : ''});
console.log(result.output);
console.log('Cost:', result.cost, 'Tokens:', result.totalTokens);

// Streaming execution
for await (const event of forge.stream('${agent.slug}', 'Your prompt'${inputVars.length > 0 ? `, {
  context: { ${inputVars.map(v => `${v.name}: 'value'`).join(', ')} }
}` : ''})) {
  if (event.type === 'token') process.stdout.write(event.text);
  if (event.type === 'tool_call') console.log('Tool:', event.name);
  if (event.type === 'done') {
    console.log('Cost:', event.cost);
    console.log('Confidence:', event.confidence);
  }
}`;

  const pyExample = `from abenix_sdk import Abenix

forge = Abenix(api_key="af_your_key", base_url="${API_URL}")

# Non-streaming execution
result = await forge.execute("${agent.slug}", "Your prompt"${inputVars.length > 0 ? `,
    context={${inputVars.map(v => `"${v.name}": "value"`).join(', ')}}` : ''})
print(result.output)
print(f"Cost: \${result.cost:.4f}, Tokens: {result.total_tokens}")

# Streaming execution
async for event in forge.stream(
    "${agent.slug}",
    "Your prompt"${inputVars.length > 0 ? `,
    context={${inputVars.map(v => `"${v.name}": "value"`).join(', ')}}` : ''}
):
    if event.type == "token": print(event.text, end="")
    if event.type == "done":
        print(f"\\nCost: \${event.cost:.4f}")`;

  const webhookExample = `# 1. Create a webhook trigger
curl -X POST ${API_URL}/api/triggers \\
  -H "Authorization: Bearer YOUR_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"agent_id": "${agent.id}", "trigger_type": "webhook"}'

# Response: {"data": {"webhook_url": "/api/triggers/webhook/TOKEN_HERE"}}

# 2. Trigger execution from any external system
curl -X POST ${API_URL}/api/triggers/webhook/TOKEN_HERE \\
  -H "Content-Type: application/json" \\
  -d '{"message": "Process this data", "context": {"key": "value"}}'`;

  const scheduleExample = `# Create a cron-scheduled trigger (runs automatically)
curl -X POST ${API_URL}/api/triggers \\
  -H "Authorization: Bearer YOUR_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "agent_id": "${agent.id}",
    "trigger_type": "schedule",
    "cron_expression": "0 9 * * 1-5",
    "default_message": "Run daily analysis"
  }'
# This agent will execute every weekday at 9:00 AM UTC`;

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.3 }}>
      {/* Header */}
      <div className="flex items-start gap-4 mb-6">
        <div className="w-14 h-14 rounded-xl bg-cyan-500/10 flex items-center justify-center shrink-0">
          <Bot className="w-7 h-7 text-cyan-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-2xl font-bold text-white">{agent.name}</h1>
            {isPipeline && (
              <span className="text-xs bg-emerald-500/10 text-emerald-400 px-2 py-0.5 rounded-full font-medium">
                Pipeline
              </span>
            )}
            <span className={`text-xs px-2 py-0.5 rounded-full ${
              agent.status === 'active' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-slate-700 text-slate-400'
            }`}>
              {agent.status}
            </span>
          </div>
          <p className="text-sm text-slate-400">{agent.description}</p>
          <div className="flex items-center gap-3 mt-2">
            <code className="text-[10px] font-mono text-slate-500 bg-slate-800/50 px-2 py-0.5 rounded">{agent.slug}</code>
            {agent.category && (
              <span className="text-[10px] bg-purple-500/10 text-purple-400 px-2 py-0.5 rounded">{agent.category}</span>
            )}
          </div>
        </div>
        <div className="flex gap-2 shrink-0">
          <Link
            href={`/agents/${agent.id}/chat`}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg hover:from-cyan-400 hover:to-purple-500 shadow-lg shadow-cyan-500/25 transition-all"
          >
            <Play className="w-4 h-4" />
            Chat
          </Link>
          <Link
            href={`/triggers?agent=${agent.id}`}
            className="flex items-center gap-2 px-4 py-2 bg-slate-700/50 border border-slate-600 text-slate-200 text-sm rounded-lg hover:bg-slate-700 transition-colors"
            title="Set up webhook or scheduled triggers"
          >
            <Zap className="w-4 h-4" />
            Schedule
          </Link>
          {agent.agent_type === 'oob' ? (
            <button
              onClick={async () => {
                const token = localStorage.getItem('access_token');
                if (!token) return;
                const res = await fetch(`${API_URL}/api/agents/${agent.id}/duplicate`, {
                  method: 'POST',
                  headers: { Authorization: `Bearer ${token}` },
                });
                const json = await res.json();
                if (json.data?.id) {
                  router.push(`/builder?agent=${json.data.id}`);
                }
              }}
              className="flex items-center gap-2 px-4 py-2 bg-slate-700/50 border border-slate-600 text-slate-200 text-sm rounded-lg hover:bg-slate-700 transition-colors"
              title="Create an editable copy of this agent"
            >
              Fork & Edit
            </button>
          ) : (
            <Link
              href={`/builder?agent=${agent.id}`}
              className="flex items-center gap-2 px-4 py-2 bg-slate-700/50 border border-slate-600 text-slate-200 text-sm rounded-lg hover:bg-slate-700 transition-colors"
            >
              Edit
            </Link>
          )}
          <button onClick={() => setShowShare(true)}
            className="flex items-center gap-1.5 px-3 py-2 bg-slate-700/50 border border-slate-600 text-slate-300 text-xs rounded-lg hover:bg-slate-700 transition-colors"
            title="Share with team members">
            <Share2 className="w-3.5 h-3.5" /> Share
          </button>
          <button onClick={() => setShowVersions(true)}
            className="flex items-center gap-1.5 px-3 py-2 bg-slate-700/50 border border-slate-600 text-slate-300 text-xs rounded-lg hover:bg-slate-700 transition-colors"
            title="View version history">
            <GitBranch className="w-3.5 h-3.5" /> Versions
          </button>
          <button onClick={() => setShowExport(true)}
            className="flex items-center gap-1.5 px-3 py-2 bg-slate-700/50 border border-slate-600 text-slate-300 text-xs rounded-lg hover:bg-slate-700 transition-colors"
            title="Export as template">
            <Download className="w-3.5 h-3.5" /> Export
          </button>
          {(agent?.model_config as Record<string, unknown>)?.mode === 'pipeline' && (
            <>
              <Link
                href={`/agents/${agentId}/healing`}
                className="flex items-center gap-1.5 px-3 py-2 bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 text-xs rounded-lg hover:bg-cyan-500/20 transition-colors"
                title="Self-healing — review failure diffs and Pipeline Surgeon proposals"
              >
                <Sparkles className="w-3.5 h-3.5" /> Healing
              </Link>
              <Link
                href={`/agents/${agentId}/shell`}
                className="flex items-center gap-1.5 px-3 py-2 bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 text-xs rounded-lg hover:bg-cyan-500/20 transition-colors"
                title="Talk-to-workflow shell — drive this pipeline by typing verbs"
              >
                <Terminal className="w-3.5 h-3.5" /> Shell
              </Link>
            </>
          )}
        </div>
      </div>

      {/* Dialogs */}
      {agent && (
        <>
          <ShareDialog open={showShare} onClose={() => setShowShare(false)} agentId={agentId} agentName={agent.name} />
          <VersionHistoryDialog open={showVersions} onClose={() => setShowVersions(false)} agentId={agentId} agentName={agent.name} onReverted={() => window.location.reload()} />
          <ExportImportDialog open={showExport} onClose={() => setShowExport(false)} agentId={agentId} agentName={agent.name} mode="export" />
        </>
      )}

      {/* Tabs */}
      <div className="flex border-b border-slate-700 mb-6">
        {([
          { key: 'overview', label: 'Overview', icon: Bot },
          { key: 'api', label: 'API & SDK', icon: Code2 },
          { key: 'triggers', label: 'Triggers & Events', icon: Zap },
        ] as const).map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={`flex items-center gap-2 px-4 py-3 text-sm font-medium transition-colors border-b-2 ${
              activeTab === t.key
                ? 'text-cyan-400 border-cyan-400'
                : 'text-slate-500 border-transparent hover:text-slate-300'
            }`}
          >
            <t.icon className="w-4 h-4" />
            {t.label}
          </button>
        ))}
      </div>

      {/* Overview Tab */}
      {activeTab === 'overview' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            {/* Configuration */}
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-white mb-4">Configuration</h3>
              <div className="grid grid-cols-2 gap-4">
                <div className="flex items-center gap-3">
                  <Cpu className="w-4 h-4 text-slate-500" />
                  <div>
                    <p className="text-[10px] text-slate-500">Model</p>
                    <p className="text-sm text-white font-mono">{mc.model || 'pipeline'}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Thermometer className="w-4 h-4 text-slate-500" />
                  <div>
                    <p className="text-[10px] text-slate-500">Temperature</p>
                    <p className="text-sm text-white">{mc.temperature ?? 'N/A'}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Wrench className="w-4 h-4 text-slate-500" />
                  <div>
                    <p className="text-[10px] text-slate-500">Tools</p>
                    <p className="text-sm text-white">{tools.length} attached</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Clock className="w-4 h-4 text-slate-500" />
                  <div>
                    <p className="text-[10px] text-slate-500">Type</p>
                    <p className="text-sm text-white">{isPipeline ? 'Pipeline (DAG)' : 'Agent (iterative)'}</p>
                  </div>
                </div>
              </div>
            </div>

            {/* Input Variables */}
            {inputVars.length > 0 && (
              <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                <h3 className="text-sm font-semibold text-white mb-4">Input Parameters</h3>
                <p className="text-xs text-slate-400 mb-3">These parameters are required when executing this agent via the SDK or API.</p>
                <div className="space-y-2">
                  {inputVars.map((v) => (
                    <div key={v.name} className="flex items-start gap-3 p-3 bg-slate-900/30 border border-slate-700/20 rounded-lg">
                      <code className="text-xs font-mono text-cyan-400 shrink-0">{v.name}</code>
                      <div className="flex-1 min-w-0">
                        <span className="text-[10px] text-slate-500">{v.type}</span>
                        {v.required && <span className="text-[10px] text-red-400 ml-2">required</span>}
                        {v.description && <p className="text-xs text-slate-400 mt-0.5">{v.description}</p>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Quick Start — auto-generated SDK snippet */}
            <div className="bg-gradient-to-br from-slate-800/50 to-cyan-900/10 border border-cyan-500/20 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
                Quick Start
                <span className="text-[9px] bg-cyan-500/10 text-cyan-400 px-1.5 py-0.5 rounded-full font-normal">auto-generated</span>
              </h3>
              <pre className="text-[10px] font-mono text-slate-300 bg-slate-900/70 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap leading-relaxed">{
`curl -X POST ${API_URL}/api/agents/${agent.id}/execute \\
  -H "X-API-Key: af_YOUR_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"message": "Your prompt here"${inputVars.length > 0 ? `, "context": {${inputVars.map(v => `"${v.name}": "..."` ).join(', ')}}` : ''}, "stream": true}'`
              }</pre>
              <p className="text-[9px] text-slate-500 mt-2">
                This agent uses <strong className="text-slate-300">{tools.length} tools</strong>
                {inputVars.length > 0 && <> and requires <strong className="text-slate-300">{inputVars.length} input parameters</strong></>}.
                {' '}Results stream via SSE with token, tool_call, and done events.
              </p>
            </div>

            {/* How it works */}
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-white mb-3">How It Works</h3>
              <div className="text-xs text-slate-400 leading-relaxed space-y-2">
                {isPipeline ? (
                  <>
                    <p>This is a <strong className="text-white">pipeline agent</strong> that processes your input through a directed acyclic graph (DAG) of steps.</p>
                    <p>Each step can use different tools, and steps can run in parallel when there are no dependencies. The output of one step feeds into the next via template variables.</p>
                    <p>Pipeline execution is deterministic — the same input always follows the same path through the DAG.</p>
                    <div className="mt-4">
                      <PipelineDAGPreview agentId={String(agent?.id || '')} token={typeof window !== 'undefined' ? localStorage.getItem('access_token') || '' : ''} height={200} />
                    </div>
                  </>
                ) : (
                  <>
                    <p>This is an <strong className="text-white">iterative agent</strong> that uses an LLM in a loop with tools. The agent decides which tools to call based on your input and the results of previous tool calls.</p>
                    <p>The agent can call any of its attached tools in any order, and continues iterating until it has enough information to provide a final response.</p>
                    <p>Execution is non-deterministic — the agent may use different tools or different numbers of iterations depending on the complexity of the request.</p>
                  </>
                )}
              </div>
            </div>
          </div>

          {/* Tools sidebar */}
          <div className="space-y-4">
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-white mb-4">Tools ({tools.length})</h3>
              <div className="space-y-2">
                {tools.map((tool) => (
                  <div key={tool} className="flex items-start gap-2 p-2 bg-slate-900/30 rounded-lg">
                    <Wrench className="w-3.5 h-3.5 text-cyan-400 mt-0.5 shrink-0" />
                    <div className="min-w-0">
                      <span className="text-xs font-mono text-cyan-400">{tool}</span>
                      {TOOL_DESCRIPTIONS[tool] && (
                        <p className="text-[9px] text-slate-500 mt-0.5">{TOOL_DESCRIPTIONS[tool]}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Memory link if agent has memory tools */}
            {tools.some(t => t.startsWith('memory_')) && (
              <Link
                href={`/agents/${agent.id}/memories`}
                className="flex items-center gap-2 p-4 bg-purple-500/5 border border-purple-500/20 rounded-xl text-sm text-purple-400 hover:border-purple-500/40 transition-colors"
              >
                <Database className="w-4 h-4" />
                <div>
                  <p className="font-medium">Memory Store</p>
                  <p className="text-[10px] text-purple-400/60">Browse and manage stored memories</p>
                </div>
              </Link>
            )}

            {/* Meeting sessions link for agents that can join meetings */}
            {tools.some(t => t.startsWith('meeting_')) && (
              <Link
                href="/meetings"
                className="flex items-center gap-2 p-4 bg-cyan-500/5 border border-cyan-500/20 rounded-xl text-sm text-cyan-400 hover:border-cyan-500/40 transition-colors"
              >
                <Database className="w-4 h-4" />
                <div>
                  <p className="font-medium">Meeting sessions</p>
                  <p className="text-[10px] text-cyan-400/60">
                    Authorize + start live meetings this agent joins on your behalf
                  </p>
                </div>
              </Link>
            )}
          </div>
        </div>
      )}

      {/* API & SDK Tab */}
      {activeTab === 'api' && (
        <div className="space-y-6 max-w-4xl">
          <CodeBlock title="cURL" code={curlExample} onCopy={(c) => copy(c, 'curl')} copied={copiedField === 'curl'} />
          <CodeBlock title="JavaScript / TypeScript" code={jsExample} onCopy={(c) => copy(c, 'js')} copied={copiedField === 'js'} />
          <CodeBlock title="Python" code={pyExample} onCopy={(c) => copy(c, 'py')} copied={copiedField === 'py'} />

          {/* Response format */}
          <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
            <h3 className="text-sm font-semibold text-white mb-3">Response Format</h3>
            <div className="grid grid-cols-2 gap-4 text-xs">
              <div>
                <h4 className="font-medium text-slate-300 mb-2">Streaming (SSE Events)</h4>
                <div className="space-y-1 text-slate-400">
                  <p><code className="text-cyan-400">event: token</code> — Text token chunk</p>
                  <p><code className="text-cyan-400">event: tool_call</code> — Tool invocation with name + arguments</p>
                  <p><code className="text-cyan-400">event: tool_result</code> — Tool output/result</p>
                  <p><code className="text-cyan-400">event: done</code> — Final stats (tokens, cost, duration, confidence)</p>
                  <p><code className="text-red-400">event: error</code> — Error message</p>
                </div>
              </div>
              <div>
                <h4 className="font-medium text-slate-300 mb-2">Non-Streaming (JSON)</h4>
                <pre className="text-[10px] text-slate-400 bg-slate-900/50 p-3 rounded-lg font-mono">{`{
  "data": {
    "output": "Agent response...",
    "cost": 0.0042,
    "duration_ms": 3200,
    "total_tokens": 1500,
    "confidence_score": 0.92,
    "tool_calls": [...]
  }
}`}</pre>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Triggers Tab */}
      {activeTab === 'triggers' && (
        <div className="space-y-6 max-w-4xl">
          {/* Webhook trigger */}
          <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
            <div className="flex items-center gap-2 mb-3">
              <Webhook className="w-5 h-5 text-cyan-400" />
              <h3 className="text-sm font-semibold text-white">Webhook Trigger</h3>
            </div>
            <p className="text-xs text-slate-400 mb-4">
              Create a public URL that triggers this agent when it receives a POST request.
              Use this to integrate with Slack, GitHub, Zapier, or any external system.
            </p>
            <CodeBlock title="Create & Use Webhook" code={webhookExample} onCopy={(c) => copy(c, 'wh')} copied={copiedField === 'wh'} />
          </div>

          {/* Schedule trigger */}
          <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
            <div className="flex items-center gap-2 mb-3">
              <Clock className="w-5 h-5 text-purple-400" />
              <h3 className="text-sm font-semibold text-white">Scheduled Execution (Cron)</h3>
            </div>
            <p className="text-xs text-slate-400 mb-4">
              Run this agent automatically on a schedule using cron expressions.
              The scheduler uses APScheduler with croniter for accurate scheduling.
            </p>
            <CodeBlock title="Schedule Agent" code={scheduleExample} onCopy={(c) => copy(c, 'sched')} copied={copiedField === 'sched'} />

            <div className="mt-4 bg-slate-900/30 rounded-lg p-3">
              <h4 className="text-[10px] font-medium text-slate-400 mb-2">Common Cron Expressions</h4>
              <div className="grid grid-cols-2 gap-2 text-[10px] text-slate-500">
                <div><code className="text-cyan-400">*/5 * * * *</code> Every 5 minutes</div>
                <div><code className="text-cyan-400">0 * * * *</code> Every hour</div>
                <div><code className="text-cyan-400">0 9 * * 1-5</code> Weekdays at 9 AM</div>
                <div><code className="text-cyan-400">0 0 * * *</code> Daily at midnight</div>
                <div><code className="text-cyan-400">0 0 * * 1</code> Weekly on Monday</div>
                <div><code className="text-cyan-400">0 0 1 * *</code> Monthly on 1st</div>
              </div>
            </div>
          </div>

          {/* Event webhooks */}
          <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
            <div className="flex items-center gap-2 mb-3">
              <Zap className="w-5 h-5 text-amber-400" />
              <h3 className="text-sm font-semibold text-white">Event Notifications</h3>
            </div>
            <p className="text-xs text-slate-400 mb-3">
              Subscribe to execution events (completed, failed) via webhook endpoints.
              Your server receives a signed POST request when events occur.
            </p>
            <Link
              href="/settings/webhooks"
              className="flex items-center gap-1.5 text-xs text-cyan-400 hover:underline"
            >
              <ExternalLink className="w-3 h-3" />
              Configure Webhook Endpoints in Settings
            </Link>
          </div>

          <Link
            href="/triggers"
            className="flex items-center gap-2 px-4 py-3 bg-gradient-to-r from-cyan-500/10 to-purple-500/10 border border-cyan-500/20 rounded-xl text-sm text-cyan-400 hover:border-cyan-500/40 transition-colors"
          >
            <Zap className="w-4 h-4" />
            Manage All Triggers
            <ExternalLink className="w-3 h-3 ml-auto" />
          </Link>
        </div>
      )}
    </motion.div>
  );
}

function CodeBlock({
  title,
  code,
  onCopy,
  copied,
}: {
  title: string;
  code: string;
  onCopy: (code: string) => void;
  copied: boolean;
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-xs font-medium text-slate-400">{title}</h4>
        <button
          onClick={() => onCopy(code)}
          className="flex items-center gap-1 text-[10px] text-slate-500 hover:text-cyan-400 transition-colors"
        >
          {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="text-[10px] font-mono text-slate-300 bg-slate-900/50 border border-slate-700/30 rounded-lg p-4 overflow-x-auto whitespace-pre-wrap leading-relaxed">
        {code}
      </pre>
    </div>
  );
}
