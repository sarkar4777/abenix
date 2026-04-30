'use client';

import { useState, useEffect, useMemo } from 'react';
import {
  Activity,
  ArrowRightLeft,
  BarChart3,
  Bot,
  Box,
  Brackets,
  Brain,
  Calculator,
  CalendarDays,
  ChevronDown,
  ChevronRight,
  Clock,
  Cloud,
  Code,
  Database,
  FileSearch,
  FileSpreadsheet,
  FileText,
  Flag,
  GitBranch,
  Github,
  Globe,
  Image as ImageIcon,
  Info,
  Layers,
  Mail,
  Merge,
  Newspaper,
  Package,
  Plug,
  Presentation,
  Radio,
  Regex,
  Repeat,
  Ruler,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Table,
  TrendingUp,
  Users,
  Workflow,
  X,
  Zap,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';

// Props

interface PipelineToolbarProps {
  onAddTemplate?: (templateId: string) => void;
}

// Server response shape

interface ServerTool {
  id: string;
  name: string;
  description: string;
  category: string;
}

interface PipelineToolDef {
  id: string;
  name: string;
  description: string;
  icon: LucideIcon;
  category: string;
}

interface LogicNodeDef {
  id: string;
  name: string;
  description: string;
  icon: LucideIcon;
}

// Logic nodes — these aren't tools the runtime registers. They are
// pipeline-engine primitives (switch / merge / for-each / output) so we
// keep them as a separate hardcoded list.
const LOGIC_NODES: LogicNodeDef[] = [
  { id: 'condition',  name: 'Condition', description: 'Branch based on a condition',     icon: GitBranch },
  { id: '__switch__', name: 'Switch',    description: 'Route to one of N branches',      icon: Activity },
  { id: '__merge__',  name: 'Merge',     description: 'Combine outputs from branches',   icon: Merge },
  { id: 'output',     name: 'Output',    description: 'Pipeline output endpoint',        icon: Flag },
  { id: 'for_each',   name: 'For Each',  description: 'Iterate over a list in parallel', icon: Repeat },
];

// Per-tool icon overrides — match by id so search matches user expectation.
// Falls back to category-default if no entry. Keeps the list short by
// only listing tools whose category icon would be misleading.
const TOOL_ICON_BY_ID: Record<string, LucideIcon> = {
  llm_call:              Brain,
  llm_route:             GitBranch,
  agent_step:            Bot,
  sub_pipeline:          Workflow,
  data_merger:           Merge,

  web_search:            Globe,
  tavily_search:         Globe,
  news_feed:             Newspaper,
  academic_search:       Newspaper,

  calculator:            Calculator,
  current_time:          Clock,
  date_calculator:       CalendarDays,
  unit_converter:        Ruler,

  file_reader:           FileText,
  file_system:           FileText,
  document_extractor:    FileSearch,
  document_parser:       FileSearch,
  presentation_analyzer: Presentation,
  spreadsheet_analyzer:  FileSpreadsheet,
  csv_analyzer:          Table,

  code_executor:         Code,
  code_asset:            Box,
  sandboxed_job:         Layers,
  ml_model:              Package,

  json_transformer:      Brackets,
  regex_extractor:       Regex,
  text_analyzer:         FileSearch,
  schema_validator:      ShieldCheck,
  pii_redactor:          ShieldCheck,
  structured_extractor:  Brackets,
  structured_analyzer:   Brackets,

  http_client:           ArrowRightLeft,
  api_connector:         Plug,
  github_tool:           Github,
  email_sender:          Mail,
  data_exporter:         Send,
  cloud_storage:         Cloud,
  integration_hub:       Plug,
  twilio_sms:            Send,

  database_query:        Database,
  database_writer:       Database,

  financial_calculator:  TrendingUp,
  risk_analyzer:         ShieldCheck,
  market_data:           TrendingUp,
  yahoo_finance:         TrendingUp,
  ecb_rates:             TrendingUp,
  ember_climate:         TrendingUp,
  entso_e:               TrendingUp,
  credit_risk:           ShieldCheck,

  knowledge_search:      Database,
  graph_explorer:        Database,
  graph_builder:         Database,

  image_analyzer:        ImageIcon,
  speech_to_text:        Radio,
  text_to_speech:        Radio,

  meeting_join:          Users,
  meeting_listen:        Users,
  meeting_speak:         Users,
  meeting_post_chat:     Users,
  meeting_leave:         Users,
  scope_gate:            ShieldCheck,
  defer_to_human:        Users,
  persona_rag:           Users,

  scenario_planner:      Activity,
  weather_simulator:     Activity,
  sentiment_analyzer:    Activity,
};

const CATEGORY_DEFAULT_ICON: Record<string, LucideIcon> = {
  core:        Sparkles,
  data:        FileSearch,
  integration: Plug,
  pipeline:    Workflow,
  finance:     TrendingUp,
  ml:          Package,
  code:        Code,
  meeting:     Users,
  multimodal:  ImageIcon,
  kyc:         ShieldCheck,
  enterprise:  ShieldCheck,
  ai:          Brain,
  action:      Send,
};

const CATEGORY_LABEL: Record<string, string> = {
  ai:          'AI',
  core:        'Core',
  data:        'Data',
  integration: 'Integrations',
  pipeline:    'Pipeline',
  finance:     'Finance',
  ml:          'ML',
  code:        'Code',
  meeting:     'Meetings',
  multimodal:  'Multimodal',
  kyc:         'KYC / AML',
  enterprise:  'Enterprise',
  action:      'Action',
};

const CATEGORY_ORDER: string[] = [
  'ai',          // pipeline LLM steps + agent step
  'pipeline',    // sub-pipeline, merge, route
  'core',        // calculator, time, web_search
  'data',        // csv, json, regex, etc.
  'code',        // code_asset, code_executor
  'ml',          // ml_model
  'finance',
  'integration',
  'kyc',
  'enterprise',
  'meeting',
  'multimodal',
  'action',
];

function pickIcon(id: string, category: string): LucideIcon {
  return TOOL_ICON_BY_ID[id] ?? CATEGORY_DEFAULT_ICON[category] ?? Zap;
}

// llm_call / agent_step / llm_route are technically `core` and
// `pipeline` server-side, but they read better grouped under "AI" in
// the palette. Pure presentation remap.
const PRESENTATION_CATEGORY_REMAP: Record<string, string> = {
  llm_call:    'ai',
  agent_step:  'ai',
  llm_route:   'ai',
};

// Collapsible section

function ToolbarSection({
  label,
  count,
  defaultOpen,
  children,
}: {
  label: string;
  count: number;
  defaultOpen: boolean;
  children: React.ReactNode;
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
        <span className="ml-auto text-slate-600">{count}</span>
      </button>
      {open && <div className="space-y-1 px-2 pb-2">{children}</div>}
    </div>
  );
}

// Draggable item

function DraggableToolItem({
  id,
  name,
  description,
  icon: Icon,
  isLogic,
}: {
  id: string;
  name: string;
  description: string;
  icon: LucideIcon;
  isLogic: boolean;
}) {
  const handleDragStart = (e: React.DragEvent) => {
    e.dataTransfer.setData(
      'application/abenix-pipeline-step',
      JSON.stringify({ toolId: id, name, isLogic }),
    );
    e.dataTransfer.effectAllowed = 'move';
  };

  return (
    <div
      draggable
      onDragStart={handleDragStart}
      title={`${name} (${id})`}
      className="w-full flex items-center gap-2.5 p-3 rounded-lg border bg-slate-800/50 border-slate-700/50 hover:border-emerald-500/40 transition-all text-left cursor-grab active:cursor-grabbing"
    >
      <div className="w-8 h-8 rounded-md flex items-center justify-center shrink-0 bg-slate-700/50">
        <Icon className="w-4 h-4 text-slate-400" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium text-white truncate">{name}</p>
        <p className="text-[10px] text-slate-500 truncate">{description}</p>
      </div>
    </div>
  );
}

// PipelineToolbar

const PIPELINE_TIP_KEY = 'abenix:pipeline-tip-dismissed';

export default function PipelineToolbar({ onAddTemplate }: PipelineToolbarProps) {
  const [search, setSearch] = useState('');
  const [tipDismissed, setTipDismissed] = useState(true);
  const [tools, setTools] = useState<PipelineToolDef[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setTipDismissed(localStorage.getItem(PIPELINE_TIP_KEY) === '1');
  }, []);

  // Source the palette from the live tool registry on the API. Falls back
  // to a tiny static set if the call fails so the builder is never empty.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch<ServerTool[]>('/api/tools', { silent: true });
        if (cancelled) return;
        const rows = res.data || [];
        const mapped: PipelineToolDef[] = rows.map((t) => {
          const cat = PRESENTATION_CATEGORY_REMAP[t.id] ?? t.category;
          return {
            id: t.id,
            name: t.name,
            description: t.description,
            icon: pickIcon(t.id, cat),
            category: cat,
          };
        });
        setTools(mapped);
      } catch {
        setTools([
          { id: 'llm_call',     name: 'LLM Call',     description: 'Query any language model',          icon: Brain,    category: 'ai' },
          { id: 'agent_step',   name: 'Agent Step',   description: 'Run a full AI agent as a step',     icon: Bot,      category: 'ai' },
          { id: 'code_executor',name: 'Code Executor',description: 'Run Python code',                   icon: Code,     category: 'code' },
          { id: 'web_search',   name: 'Web Search',   description: 'Search the internet',               icon: Globe,    category: 'core' },
          { id: 'http_client',  name: 'HTTP Client',  description: 'Make HTTP API requests',            icon: ArrowRightLeft, category: 'integration' },
        ]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const dismissTip = () => {
    setTipDismissed(true);
    localStorage.setItem(PIPELINE_TIP_KEY, '1');
  };

  // Filter (search matches name, id OR description so users who know the
  // runtime slug — e.g. "code_asset" — find it instantly).
  const filteredTools = useMemo(() => {
    if (!search) return tools;
    const q = search.toLowerCase();
    return tools.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        t.id.toLowerCase().includes(q) ||
        t.description.toLowerCase().includes(q),
    );
  }, [search, tools]);

  const filteredLogic = useMemo(() => {
    if (!search) return LOGIC_NODES;
    const q = search.toLowerCase();
    return LOGIC_NODES.filter(
      (n) => n.name.toLowerCase().includes(q) || n.description.toLowerCase().includes(q),
    );
  }, [search]);

  // Group by category in our preferred order; unknown categories sink to
  // the bottom alphabetically so a brand-new server category still shows.
  const groupedTools = useMemo(() => {
    const byCat = new Map<string, PipelineToolDef[]>();
    for (const t of filteredTools) {
      const arr = byCat.get(t.category) ?? [];
      arr.push(t);
      byCat.set(t.category, arr);
    }
    const knownOrder = new Set(CATEGORY_ORDER);
    const orderedKeys = [
      ...CATEGORY_ORDER.filter((k) => byCat.has(k)),
      ...[...byCat.keys()].filter((k) => !knownOrder.has(k)).sort(),
    ];
    return orderedKeys.map((category) => ({
      category,
      label: CATEGORY_LABEL[category] ?? category[0].toUpperCase() + category.slice(1),
      tools: (byCat.get(category) ?? []).sort((a, b) => a.name.localeCompare(b.name)),
    }));
  }, [filteredTools]);

  return (
    <div className="w-[280px] border-r border-slate-800 bg-[#0F172A] flex flex-col shrink-0 overflow-hidden">
      {/* Header */}
      <div className="p-3 border-b border-slate-800/50">
        <div className="flex items-center gap-2 mb-3">
          <Zap className="w-4 h-4 text-emerald-400" />
          <h3 className="text-sm font-semibold text-white">Pipeline Steps</h3>
          {!loading && (
            <span className="ml-auto text-[10px] text-slate-500">{tools.length} available</span>
          )}
        </div>
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name, id, or description…"
            className="w-full pl-8 pr-3 py-1.5 bg-slate-800/50 border border-slate-700/50 rounded-md text-xs text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500/50"
          />
        </div>
      </div>

      {/* Contextual tip */}
      {!tipDismissed && (
        <div className="mx-3 mt-2 px-3 py-2 bg-emerald-500/5 border border-emerald-500/10 rounded-lg relative">
          <button
            onClick={dismissTip}
            className="absolute top-1.5 right-1.5 text-slate-600 hover:text-slate-400 transition-colors"
          >
            <X className="w-3 h-3" />
          </button>
          <div className="flex gap-2 pr-4">
            <Info className="w-3.5 h-3.5 text-emerald-400/70 mt-0.5 shrink-0" />
            <p className="text-[10px] text-emerald-400/80 leading-relaxed">
              <strong>Pipeline mode:</strong> Drag steps onto the canvas, then
              connect them to define execution order. Steps without dependencies
              run in parallel.
            </p>
          </div>
        </div>
      )}

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <p className="text-[10px] text-slate-500 px-4 py-3">Loading tool catalog…</p>
        ) : (
          <ToolbarSection label="Pipeline Steps" count={filteredTools.length} defaultOpen>
            {groupedTools.map((group) => (
              <div key={group.category}>
                <p className="text-[10px] uppercase tracking-wider text-slate-600 px-1 pt-2 pb-1">
                  {group.label}
                </p>
                {group.tools.map((tool) => (
                  <DraggableToolItem
                    key={tool.id}
                    id={tool.id}
                    name={tool.name}
                    description={tool.description}
                    icon={tool.icon}
                    isLogic={false}
                  />
                ))}
              </div>
            ))}
            {filteredTools.length === 0 && (
              <p className="text-[10px] text-slate-600 px-3 py-2">
                No steps match your search
              </p>
            )}
          </ToolbarSection>
        )}

        {/* Logic nodes */}
        <ToolbarSection label="Logic" count={filteredLogic.length} defaultOpen>
          {filteredLogic.map((node) => (
            <DraggableToolItem
              key={node.id}
              id={node.id}
              name={node.name}
              description={node.description}
              icon={node.icon}
              isLogic
            />
          ))}
          {filteredLogic.length === 0 && (
            <p className="text-[10px] text-slate-600 px-3 py-2">
              No logic nodes match your search
            </p>
          )}
        </ToolbarSection>

        {/* Quick Templates */}
        {!search && (
          <div className="px-3 py-3">
            <p className="text-xs uppercase tracking-wider text-slate-500 mb-2">
              Quick Templates
            </p>
            <div className="space-y-2">
              <button
                onClick={() => onAddTemplate?.('parallel-compare')}
                className="w-full flex items-center gap-2.5 p-3 rounded-lg border border-slate-700/50 bg-slate-800/50 hover:border-emerald-500/40 transition-all text-left"
              >
                <div className="w-8 h-8 rounded-md flex items-center justify-center shrink-0 bg-emerald-500/10">
                  <BarChart3 className="w-4 h-4 text-emerald-400" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-medium text-white">Parallel Compare</p>
                  <p className="text-[10px] text-slate-500">Run steps in parallel and compare results</p>
                </div>
              </button>
              <button
                onClick={() => onAddTemplate?.('sequential-chain')}
                className="w-full flex items-center gap-2.5 p-3 rounded-lg border border-slate-700/50 bg-slate-800/50 hover:border-emerald-500/40 transition-all text-left"
              >
                <div className="w-8 h-8 rounded-md flex items-center justify-center shrink-0 bg-emerald-500/10">
                  <Activity className="w-4 h-4 text-emerald-400" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-medium text-white">Sequential Chain</p>
                  <p className="text-[10px] text-slate-500">Chain steps sequentially with data flow</p>
                </div>
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-3 py-2 border-t border-slate-800/50">
        <p className="text-[10px] text-slate-600 text-center">
          Drag steps onto the canvas to build your pipeline
        </p>
      </div>
    </div>
  );
}
