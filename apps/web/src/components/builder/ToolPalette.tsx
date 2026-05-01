'use client';

import { useCallback, useEffect, useState } from 'react';
import { TOOL_DOCS } from '@/lib/tool-docs';
import {
  Brain,
  Calculator,
  ChevronDown,
  ChevronRight,
  Clock,
  FileText,
  Globe,
  GraduationCap,
  Loader2,
  Mic,
  Newspaper,
  Plug,
  Search,
  Shield,
  ShieldAlert,
  TrendingUp,
  UserCheck,
  Users,
  Wrench,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface ToolItem {
  id: string;
  name: string;
  description: string;
  icon: LucideIcon;
  badge?: 'read-only' | 'destructive' | null;
  source?: 'builtin' | 'mcp';
  connectionId?: string;
}

const BUILT_IN_TOOLS: ToolItem[] = [
  // Core
  { id: 'calculator', name: 'Calculator', description: 'Evaluate math expressions', icon: Calculator, source: 'builtin' },
  { id: 'current_time', name: 'Current Time', description: 'Get time in any timezone', icon: Clock, source: 'builtin' },
  { id: 'web_search', name: 'Web Search', description: 'Search the internet', icon: Globe, source: 'builtin' },
  { id: 'file_reader', name: 'File Reader', description: 'Read PDF, DOCX, CSV files', icon: FileText, source: 'builtin' },
  // Data
  { id: 'csv_analyzer', name: 'CSV Analyzer', description: 'Analyze CSV data with statistics', icon: FileText, source: 'builtin' },
  { id: 'document_extractor', name: 'Document Extractor', description: 'Extract structured data from documents', icon: FileText, source: 'builtin' },
  { id: 'spreadsheet_analyzer', name: 'Spreadsheet Analyzer', description: 'Analyze Excel/XLSX files', icon: FileText, source: 'builtin' },
  { id: 'presentation_analyzer', name: 'Presentation Analyzer', description: 'Analyze PowerPoint/PPTX files', icon: FileText, source: 'builtin' },
  { id: 'json_transformer', name: 'JSON Transformer', description: 'Query, filter, transform JSON', icon: Wrench, source: 'builtin' },
  { id: 'text_analyzer', name: 'Text Analyzer', description: 'Keywords, readability, sentiment', icon: FileText, source: 'builtin' },
  { id: 'regex_extractor', name: 'Regex Extractor', description: 'Pattern matching and extraction', icon: Wrench, source: 'builtin' },
  { id: 'data_exporter', name: 'Data Exporter', description: 'Export as CSV, JSON, Excel, PDF', icon: FileText, source: 'builtin' },
  { id: 'data_merger', name: 'Data Merger', description: 'Merge parallel branch outputs', icon: Calculator, source: 'builtin' },
  // Search / Data — OracleNet
  { id: 'tavily_search', name: 'Tavily Search', description: 'Advanced web search with AI answers (Tavily/Brave/SerpAPI)', icon: Search, source: 'builtin' },
  { id: 'news_feed', name: 'News Feed', description: 'Search recent news articles (NewsAPI/MediaStack)', icon: Newspaper, source: 'builtin' },
  { id: 'academic_search', name: 'Academic Search', description: 'Search academic papers (Semantic Scholar/arXiv)', icon: GraduationCap, source: 'builtin' },
  { id: 'yahoo_finance', name: 'Yahoo Finance', description: 'Stock prices, company financials, economic indicators', icon: TrendingUp, source: 'builtin' },
  { id: 'entso_e', name: 'ENTSO-E Power', description: 'European electricity prices and generation data', icon: TrendingUp, source: 'builtin' },
  { id: 'ember_climate', name: 'Ember Climate', description: 'UK power prices, EU carbon prices', icon: TrendingUp, source: 'builtin' },
  { id: 'ecb_rates', name: 'ECB Rates', description: 'FX rates, inflation, interest rates', icon: TrendingUp, source: 'builtin' },
  // Search
  { id: 'contract_search', name: 'Contract Search', description: 'Search across uploaded PPA/gas contracts', icon: Search, source: 'builtin' },
  // Finance
  { id: 'financial_calculator', name: 'Financial Calculator', description: 'NPV, IRR, mortgage, amortization', icon: Calculator, source: 'builtin' },
  { id: 'risk_analyzer', name: 'Risk Analyzer', description: 'Monte Carlo, sensitivity, VaR', icon: Calculator, source: 'builtin' },
  { id: 'market_data', name: 'Market Data', description: 'Stock, forex, commodity prices', icon: Globe, source: 'builtin' },
  { id: 'ppa_calculator', name: 'PPA Calculator', description: 'LCOE, NPV, IRR, financial modeling', icon: Calculator, source: 'builtin' },
  // Utility
  { id: 'date_calculator', name: 'Date Calculator', description: 'Date math, business days, holidays', icon: Clock, source: 'builtin' },
  { id: 'unit_converter', name: 'Unit Converter', description: 'Convert length, weight, energy, etc.', icon: Calculator, source: 'builtin' },
  // Integration
  { id: 'http_client', name: 'HTTP Client', description: 'Make GET/POST/PUT/DELETE requests', icon: Globe, source: 'builtin' },
  { id: 'api_connector', name: 'API Connector', description: 'Slack, Airtable, Notion, Jira', icon: Globe, source: 'builtin' },
  { id: 'github_tool', name: 'GitHub', description: 'Repos, issues, PRs, code search', icon: Globe, source: 'builtin' },
  { id: 'email_sender', name: 'Email Sender', description: 'Send emails to recipients', icon: FileText, source: 'builtin' },
  // Pipeline
  { id: 'llm_call', name: 'LLM Call', description: 'Query an LLM as a pipeline step', icon: Wrench, source: 'builtin' },
  { id: 'code_executor', name: 'Code Executor', description: 'Run Python: pandas, matplotlib, Excel, PDF', icon: Wrench, source: 'builtin' },
  { id: 'agent_step', name: 'Agent Step', description: 'Run another agent as a sub-step', icon: Wrench, source: 'builtin' },
  { id: 'sub_pipeline', name: 'Sub-Pipeline', description: 'Execute a nested DAG pipeline', icon: Wrench, source: 'builtin' },
  // Enterprise
  { id: 'memory_store', name: 'Memory Store', description: 'Persist agent memory across sessions', icon: Wrench, source: 'builtin' },
  { id: 'memory_recall', name: 'Memory Recall', description: 'Retrieve stored agent memories', icon: Wrench, source: 'builtin' },
  { id: 'memory_forget', name: 'Memory Forget', description: 'Delete agent memories by key', icon: Wrench, source: 'builtin' },
  { id: 'human_approval', name: 'Human Approval', description: 'Pause for human approve/reject', icon: Wrench, source: 'builtin' },
  // Enterprise Data
  { id: 'database_query', name: 'Database Query', description: 'SQL queries against PostgreSQL', icon: Globe, source: 'builtin' },
  { id: 'cloud_storage', name: 'Cloud Storage', description: 'S3, GCS, Azure Blob operations', icon: Globe, source: 'builtin' },
  { id: 'image_analyzer', name: 'Image Analyzer', description: 'AI vision: OCR, charts, diagrams, objects', icon: FileText, source: 'builtin' },
  { id: 'database_writer', name: 'Database Writer', description: 'INSERT/UPSERT rows to PostgreSQL', icon: Globe, source: 'builtin' },
  { id: 'file_system', name: 'File System', description: 'Recursive directory traversal, glob', icon: FileText, source: 'builtin' },
  { id: 'schema_validator', name: 'Schema Validator', description: 'Validate JSON against schema', icon: Wrench, source: 'builtin' },
  { id: 'structured_analyzer', name: 'Structured Analyzer', description: 'LLM-powered code/doc analysis (all languages)', icon: Wrench, source: 'builtin' },
  // Multi-Modal
  { id: 'speech_to_text', name: 'Speech to Text', description: 'Transcribe audio (OpenAI Whisper)', icon: FileText, source: 'builtin' },
  { id: 'text_to_speech', name: 'Text to Speech', description: 'Generate speech audio (OpenAI TTS)', icon: FileText, source: 'builtin' },
  // Integrations
  { id: 'integration_hub', name: 'Integration Hub', description: '20+ services: Slack, Teams, Salesforce, Jira, etc.', icon: Globe, source: 'builtin' },
  // AI Pipeline Logic
  { id: 'llm_route', name: 'LLM Route', description: 'AI-powered branch routing', icon: Wrench, source: 'builtin' },
  { id: 'document_parser', name: 'Document Parser', description: 'Extract text from PDF, DOCX, TXT, CSV, HTML files', icon: FileText, source: 'builtin' },
  { id: 'structured_extractor', name: 'Structured Extractor', description: 'Extract structured JSON from text using a schema — contracts, invoices, resumes', icon: FileText, source: 'builtin' },
  { id: 'graph_builder', name: 'Graph Builder', description: 'Build dependency DAGs, provenance chains, entity maps', icon: Globe, source: 'builtin' },
  { id: 'weather_simulator', name: 'Weather Simulator', description: 'Solar, wind, temp, precipitation scenarios for any location', icon: Globe, source: 'builtin' },
  { id: 'sentiment_analyzer', name: 'Sentiment Analyzer', description: 'Market/news sentiment scoring with trend + volatility', icon: Globe, source: 'builtin' },
  { id: 'scenario_planner', name: 'Scenario Planner', description: 'Parameter sweeps, what-if analysis, sensitivity charts', icon: Calculator, source: 'builtin' },
  // Privacy & Compliance
  { id: 'pii_redactor', name: 'PII Redactor', description: 'Detect and mask personal data', icon: Wrench, source: 'builtin' },
  // Analytics
  { id: 'time_series_analyzer', name: 'Time Series Analyzer', description: 'Trends, anomalies, forecasting', icon: Calculator, source: 'builtin' },
  // ML / Models
  { id: 'ml_model', name: 'ML Model', description: 'Inference on registered sklearn/PyTorch/ONNX/XGBoost models', icon: Brain, source: 'builtin' },
  // Code Runners — run user-uploaded repos/zips as pipeline steps
  { id: 'code_asset', name: 'Code Asset', description: 'Run a registered repo/zip (Python, Node, Go, Rust, Ruby, Java) with a JSON input', icon: Wrench, source: 'builtin' },
  // Meeting primitives (build meeting agents that join calls, listen, answer)
  { id: 'meeting_join', name: 'Meeting Join', description: 'Join a LiveKit/Teams/Zoom meeting as the user\u2019s representative', icon: Users, source: 'builtin' },
  { id: 'meeting_listen', name: 'Meeting Listen', description: 'Stream STT from the meeting; VAD-chunked Whisper with early-exit', icon: Mic, source: 'builtin' },
  { id: 'meeting_speak', name: 'Meeting Speak', description: 'TTS into the meeting audio track (OpenAI or cloned voice)', icon: Mic, source: 'builtin' },
  { id: 'meeting_post_chat', name: 'Meeting Post Chat', description: 'Post a text message to the meeting chat/data channel', icon: Users, source: 'builtin' },
  { id: 'meeting_leave', name: 'Meeting Leave', description: 'Clean exit from the meeting with a decision-log summary', icon: Users, source: 'builtin' },
  { id: 'scope_gate', name: 'Scope Gate', description: 'Classify a question as answer/defer/decline against the allow-list', icon: Shield, source: 'builtin' },
  { id: 'defer_to_human', name: 'Defer to Human', description: 'Hand a question back to the user\u2019s inbox with 30s hold', icon: UserCheck, source: 'builtin' },
  { id: 'persona_rag', name: 'Persona RAG', description: 'Ring-fenced retrieval from the user\u2019s persona KB', icon: Brain, source: 'builtin' },
  // Enterprise — sandbox
  { id: 'sandboxed_job', name: 'Sandboxed Job', description: 'Run long-lived code in a sandboxed k8s Job (allow-listed images)', icon: ShieldAlert, source: 'builtin', badge: 'destructive' },
  // KYC / AML compliance tools
  { id: 'sanctions_screening', name: 'Sanctions Screening', description: 'OFAC SDN, OFAC Consolidated, EU, UN SC, UK HMT, Canada OSFI — fuzzy match w/ AKA expansion, L/M/H grade', icon: Shield, source: 'builtin', badge: 'read-only' },
  { id: 'pep_screening', name: 'PEP Screening', description: 'OpenSanctions + Wikidata + parliament rosters — classifies Domestic / Foreign / Intl-Org / Family / Close Associate / Former PEP', icon: UserCheck, source: 'builtin', badge: 'read-only' },
  { id: 'adverse_media', name: 'Adverse Media', description: 'GDELT + Google News + Tavily + Reuters — 14 FATF risk categories, 5-tier source weights, recency buckets', icon: Newspaper, source: 'builtin', badge: 'read-only' },
  { id: 'ubo_discovery', name: 'UBO Discovery', description: 'Walks corporate ownership — GLEIF + OpenCorporates + UK PSC + KRS; configurable 10/20/25% threshold', icon: Users, source: 'builtin', badge: 'read-only' },
  { id: 'country_risk_index', name: 'Country Risk Index', description: 'TI CPI rank + FATF grey/black + EU tax list + OFAC programs + WGI percentiles → MET-style Indicator I score', icon: Globe, source: 'builtin', badge: 'read-only' },
  { id: 'legal_existence_verifier', name: 'Legal Existence Verifier', description: 'Verify entity exists & is in good standing via GLEIF + OpenCorporates + UK Companies House; detects shell / dissolved / mass-address', icon: Shield, source: 'builtin', badge: 'read-only' },
  { id: 'kyc_scorer', name: 'KYC Scorer', description: 'Deterministic scoring (CPI + notional + industry + signals) → Indicator I/II/III + Aggregated Score + Simplified/Standard/Enhanced check type', icon: Calculator, source: 'builtin' },
  { id: 'regulatory_enforcement', name: 'Regulatory Enforcement', description: 'Primary-source SEC EDGAR + DOJ + FCA + CourtListener + BAILII — extracts fines, action type, source URL', icon: ShieldAlert, source: 'builtin', badge: 'read-only' },
];

interface MCPConnection {
  id: string;
  server_name: string;
  discovered_tools: {
    name: string;
    description: string;
    annotations?: Record<string, unknown>;
  }[] | null;
  health_status: string;
}

interface ToolPaletteProps {
  selectedTools: string[];
  onToggleTool: (toolId: string) => void;
}

function getBadge(annotations: Record<string, unknown> | undefined): 'read-only' | 'destructive' | null {
  if (!annotations) return null;
  if (annotations.destructiveHint) return 'destructive';
  if (annotations.readOnlyHint) return 'read-only';
  return null;
}

function BadgeTag({ badge }: { badge: 'read-only' | 'destructive' | null }) {
  if (!badge) return null;
  if (badge === 'read-only') {
    return (
      <span className="flex items-center gap-0.5 text-[9px] bg-emerald-500/10 text-emerald-400 px-1 py-0.5 rounded shrink-0">
        <Shield className="w-2.5 h-2.5" />
        safe
      </span>
    );
  }
  return (
    <span className="flex items-center gap-0.5 text-[9px] bg-red-500/10 text-red-400 px-1 py-0.5 rounded shrink-0">
      <ShieldAlert className="w-2.5 h-2.5" />
      write
    </span>
  );
}

function ToolSection({
  label,
  tools,
  selectedTools,
  onToggleTool,
  defaultOpen,
  loading,
}: {
  label: string;
  tools: ToolItem[];
  selectedTools: string[];
  onToggleTool: (id: string) => void;
  defaultOpen: boolean;
  loading?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 w-full px-3 py-2 text-xs uppercase tracking-wider text-slate-500 hover:text-slate-300 transition-colors"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        {label}
        <span className="ml-auto text-slate-600">
          {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : tools.length}
        </span>
      </button>
      {open && (
        <div className="space-y-1 px-2 pb-2">
          {loading && tools.length === 0 && (
            <p className="text-[10px] text-slate-600 px-3 py-2">Loading MCP tools...</p>
          )}
          {!loading && tools.length === 0 && (
            <p className="text-[10px] text-slate-600 px-3 py-2">No tools available</p>
          )}
          {tools.map((tool) => {
            const active = selectedTools.includes(tool.id);
            return (
              <button
                key={tool.id}
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.setData('application/abenix-tool', JSON.stringify({
                    id: tool.id,
                    name: tool.name,
                    description: tool.description,
                    source: tool.source,
                    connectionId: tool.connectionId,
                  }));
                  e.dataTransfer.effectAllowed = 'move';
                }}
                onClick={() => onToggleTool(tool.id)}
                className={`w-full flex items-center gap-2.5 p-3 rounded-lg border transition-all text-left cursor-grab active:cursor-grabbing ${
                  active
                    ? 'bg-cyan-500/10 border-cyan-500/30'
                    : 'bg-slate-800/50 border-slate-700/50 hover:border-slate-600'
                }`}
              >
                <div className={`w-8 h-8 rounded-md flex items-center justify-center shrink-0 ${
                  active ? 'bg-cyan-500/20' : 'bg-slate-700/50'
                }`}>
                  <tool.icon className={`w-4 h-4 ${active ? 'text-cyan-400' : 'text-slate-400'}`} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <p className={`text-xs font-medium truncate ${active ? 'text-cyan-400' : 'text-white'}`}>
                      {tool.name}
                    </p>
                    <BadgeTag badge={tool.badge ?? null} />
                  </div>
                  <p className="text-[10px] text-slate-500 truncate">{tool.description}</p>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function ToolPalette({ selectedTools, onToggleTool }: ToolPaletteProps) {
  const [search, setSearch] = useState('');
  const [mcpTools, setMcpTools] = useState<ToolItem[]>([]);
  const [mcpLoading, setMcpLoading] = useState(true);

  const fetchMCPTools = useCallback(async () => {
    const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
    if (!token) {
      setMcpLoading(false);
      return;
    }

    try {
      const res = await fetch(`${API_URL}/api/mcp/connections`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const json = await res.json();
      const connections: MCPConnection[] = json.data || [];

      const tools: ToolItem[] = [];
      for (const conn of connections) {
        if (conn.health_status !== 'healthy' || !conn.discovered_tools) continue;
        for (const t of conn.discovered_tools) {
          tools.push({
            id: `mcp:${conn.id}:${t.name}`,
            name: t.name,
            description: t.description,
            icon: Plug,
            badge: getBadge(t.annotations),
            source: 'mcp',
            connectionId: conn.id,
          });
        }
      }
      setMcpTools(tools);
    } catch {
      // silent
    } finally {
      setMcpLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMCPTools();
  }, [fetchMCPTools]);

  // Smart search: matches name, description, parameter names/descriptions, and category
  const filterTools = (tools: ToolItem[]) => {
    if (!search) return tools;
    const q = search.toLowerCase();
    return tools
      .map((t) => {
        let score = 0;
        if (t.id.toLowerCase().includes(q)) score += 10;
        if (t.name.toLowerCase().includes(q)) score += 8;
        const doc = TOOL_DOCS[t.id];
        if (doc) {
          if (doc.category?.toLowerCase().includes(q)) score += 6;
          if (doc.description.toLowerCase().includes(q)) score += 4;
          if (doc.parameters.some(p => p.name.toLowerCase().includes(q))) score += 2;
          if (doc.parameters.some(p => p.description.toLowerCase().includes(q))) score += 1;
        }
        return { tool: t, score };
      })
      .filter(({ score }) => score > 0)
      .sort((a, b) => b.score - a.score)
      .map(({ tool }) => tool);
  };

  // Group tools by category
  const groupToolsByCategory = (tools: ToolItem[]) => {
    const groups: Record<string, ToolItem[]> = {};
    for (const t of tools) {
      const cat = TOOL_DOCS[t.id]?.category || 'Other';
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(t);
    }
    return groups;
  };

  const filteredBuiltIn = filterTools(BUILT_IN_TOOLS);
  const builtInGroups = search ? {} : groupToolsByCategory(filteredBuiltIn);
  const showGrouped = !search && Object.keys(builtInGroups).length > 1;

  return (
    <div className="w-[280px] border-r border-slate-800 bg-[#0F172A] flex flex-col shrink-0 overflow-hidden">
      <div className="p-3 border-b border-slate-800/50">
        <div className="flex items-center gap-2 mb-3">
          <Wrench className="w-4 h-4 text-cyan-400" />
          <h3 className="text-sm font-semibold text-white">Tool Palette</h3>
          <span className="text-[10px] text-slate-500 ml-auto">{BUILT_IN_TOOLS.length} tools</span>
        </div>
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search tools, descriptions, params..."
            className="w-full pl-8 pr-3 py-1.5 bg-slate-800/50 border border-slate-700/50 rounded-md text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/50"
          />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {showGrouped ? (
          // Category-grouped view (when not searching)
          Object.entries(builtInGroups).map(([category, tools]) => (
            <ToolSection
              key={category}
              label={`${category} (${tools.length})`}
              tools={tools}
              selectedTools={selectedTools}
              onToggleTool={onToggleTool}
              defaultOpen={false}
            />
          ))
        ) : (
          // Flat view (when searching)
          <ToolSection
            label={search ? `Results (${filteredBuiltIn.length})` : "Built-in Tools"}
            tools={filteredBuiltIn}
            selectedTools={selectedTools}
            onToggleTool={onToggleTool}
            defaultOpen
          />
        )}
        <ToolSection
          label="MCP Server Tools"
          tools={filterTools(mcpTools)}
          selectedTools={selectedTools}
          onToggleTool={onToggleTool}
          defaultOpen
          loading={mcpLoading}
        />
      </div>
      <div className="px-3 py-2 border-t border-slate-800/50">
        <p className="text-[10px] text-slate-600 text-center">
          Click to toggle or drag onto canvas
        </p>
      </div>
    </div>
  );
}
