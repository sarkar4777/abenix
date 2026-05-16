'use client';

import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ArrowUp,
  Book,
  Bot,
  Brain,
  ChevronDown,
  ChevronRight,
  Cloud,
  Code,
  Copy,
  Check,
  CircleDot,
  Filter,
  Gauge,
  GitBranch,
  Globe,
  Key,
  Keyboard,
  Layers,
  List,
  Lock,
  Network,
  Play,
  Rocket,
  Search,
  Server,
  Shield,
  Sparkles,
  TrendingUp,
  Users,
  Wrench,
  Zap,
  Activity,
  AlertTriangle,
  BarChart3,
  Boxes,
  Bug,
  Workflow,
  Database,
  Terminal,
  FileText,
  Settings,
  Link,
  Eye,
  Clock,
  Cpu,
  HardDrive,
  MessageSquare,
  FolderOpen,
  Share2,
  Bell,
  Timer,
  Package,
  Plug,
  BookOpen,
  Megaphone,
  SlidersHorizontal,
  Upload,
  RefreshCw,
  ChevronsUpDown,
} from 'lucide-react';

// ─── Types ───────────────────────────────────────────────────────────────────

interface Section {
  id: string;
  title: string;
  icon: React.ElementType;
  group: string;
  content: string; // full-text searchable content
}

interface SectionGroup {
  name: string;
  icon: React.ElementType;
  color: string;
}

// ─── Section Groups ──────────────────────────────────────────────────────────

const GROUPS: SectionGroup[] = [
  { name: 'Getting Started', icon: Rocket, color: 'from-emerald-500/20 to-emerald-600/20' },
  { name: 'Core Concepts', icon: BookOpen, color: 'from-cyan-500/20 to-cyan-600/20' },
  { name: 'AI Builder Guide', icon: Sparkles, color: 'from-purple-500/20 to-purple-600/20' },
  { name: 'Built-in Tools Reference', icon: Wrench, color: 'from-amber-500/20 to-amber-600/20' },
  { name: 'Enterprise Features', icon: Shield, color: 'from-red-500/20 to-red-600/20' },
  { name: 'API Reference', icon: Globe, color: 'from-blue-500/20 to-blue-600/20' },
  { name: 'Integration', icon: Plug, color: 'from-indigo-500/20 to-indigo-600/20' },
  { name: 'Infrastructure', icon: Server, color: 'from-slate-500/20 to-slate-600/20' },
];

// ─── SECTIONS ────────────────────────────────────────────────────────────────
// The `content` field is indexed by full-text search.

const SECTIONS: Section[] = [
  // ── Getting Started ──
  {
    id: 'quick-start',
    title: 'Quick Start',
    icon: Rocket,
    group: 'Getting Started',
    content: 'clone install start.sh docker compose prerequisites node python git quick start first agent execute health check curl login credentials',
  },
  {
    id: 'architecture',
    title: 'Architecture Overview',
    icon: Layers,
    group: 'Getting Started',
    content: 'seven layer presentation api gateway auth identity agent runtime pipeline engine knowledge memory data infrastructure postgres redis neo4j service map 7-layer architecture fastapi next.js celery',
  },
  {
    id: 'environment-variables',
    title: 'Environment Variables',
    icon: Settings,
    group: 'Getting Started',
    content: 'DATABASE_URL REDIS_URL ANTHROPIC_API_KEY OPENAI_API_KEY SECRET_KEY CORS_ORIGINS NEO4J_URI PINECONE_API_KEY TAVILY_API_KEY CELERY_BROKER_URL NEXT_PUBLIC_API_URL env environment variables configuration .env ML_MODELS_DIR',
  },
  {
    id: 'default-credentials',
    title: 'Default Credentials',
    icon: Key,
    group: 'Getting Started',
    content: 'login password email admin user credentials default development seed accounts jwt token bearer access refresh registration',
  },

  // ── Core Concepts ──
  {
    id: 'agents-overview',
    title: 'Agents',
    icon: Bot,
    group: 'Core Concepts',
    content: 'agent react loop tool calling system prompt model config temperature tools slug category oob pipeline mode execute streaming SSE max_iterations agent_type mcp extensions',
  },
  {
    id: 'pipelines-overview',
    title: 'Pipelines',
    icon: Workflow,
    group: 'Core Concepts',
    content: 'pipeline DAG directed acyclic graph nodes edges depends_on parallel execution condition forEach while switch merge error branch template variables input_mappings retry backoff lifecycle pending running completed failed',
  },
  {
    id: 'knowledge-engine',
    title: 'Knowledge Engine',
    icon: Brain,
    group: 'Core Concepts',
    content: 'knowledge base cognify memify neo4j graph database pgvector vector embeddings hybrid search semantic keyword reciprocal rank fusion ingest documents entities relationships feedback loop',
  },
  {
    id: 'tools-overview',
    title: 'Tools Overview',
    icon: Wrench,
    group: 'Core Concepts',
    content: 'tools BaseTool input schema typed parameters tool registry dynamic tool MCP tool code_asset sandboxed_job built-in 50+ categories search data analysis compute io media memory AI integration pipeline security',
  },

  // ── AI Builder Guide ──
  {
    id: 'creating-agents',
    title: 'Creating Agents',
    icon: Bot,
    group: 'AI Builder Guide',
    content: 'create agent AI builder wizard name system prompt slug model config tools YAML JSON api POST /api/agents code assistant research clone duplicate',
  },
  {
    id: 'tool-configuration',
    title: 'Tool Configuration',
    icon: SlidersHorizontal,
    group: 'AI Builder Guide',
    content: 'tool config enable disable per-agent tool list model_config.tools tool library catalog add remove configure parameters',
  },
  {
    id: 'pipeline-builder',
    title: 'Pipeline Visual Builder',
    icon: Workflow,
    group: 'AI Builder Guide',
    content: 'visual builder drag drop canvas nodes edges connections pipeline config DAG parallel branches conditions loops merge error handler validate preview',
  },
  {
    id: 'input-variables',
    title: 'Input Variables',
    icon: Terminal,
    group: 'AI Builder Guide',
    content: 'input variables template double brace syntax {{variable}} __all__ source_node source_field input_mappings pipeline variables interpolation',
  },
  {
    id: 'model-configuration',
    title: 'Model Configuration',
    icon: Cpu,
    group: 'AI Builder Guide',
    content: 'model config claude sonnet haiku opus gpt openai google gemini temperature max_tokens top_p provider model selection routing llm_route',
  },
  {
    id: 'curl-import',
    title: 'cURL Import',
    icon: Terminal,
    group: 'AI Builder Guide',
    content: 'curl import paste command bearer token authorization header content-type json body query parameters POST GET flags -H -d -X supported convert agent tool http_client',
  },

  // ── Built-in Tools Reference ──
  {
    id: 'tools-search-web',
    title: 'Search & Web Tools',
    icon: Search,
    group: 'Built-in Tools Reference',
    content: 'web_search tavily_search academic_search http_client api_connector news_feed search web tavily brave serpapi serper semantic scholar arxiv HTTP REST GET POST PUT DELETE headers auth news articles',
  },
  {
    id: 'tools-data',
    title: 'Data Tools',
    icon: Database,
    group: 'Built-in Tools Reference',
    content: 'database_query database_writer csv_analyzer json_transformer data_merger data_exporter schema_validator SQL read-only write CSV JSON JMESPath merge compare export PDF Excel validate',
  },
  {
    id: 'tools-analysis',
    title: 'Analysis Tools',
    icon: BarChart3,
    group: 'Built-in Tools Reference',
    content: 'text_analyzer structured_analyzer regex_extractor risk_analyzer time_series_analyzer presentation_analyzer readability sentiment keywords extraction patterns Monte Carlo anomaly detection forecasting slides',
  },
  {
    id: 'tools-compute',
    title: 'Compute Tools',
    icon: Cpu,
    group: 'Built-in Tools Reference',
    content: 'calculator financial_calculator unit_converter date_calculator code_executor math expression NPV IRR amortization units convert timezone business days Python sandbox execute',
  },
  {
    id: 'tools-io-media',
    title: 'I/O & Media Tools',
    icon: FileText,
    group: 'Built-in Tools Reference',
    content: 'file_reader file_system document_extractor spreadsheet_analyzer cloud_storage email_sender image_analyzer speech_to_text text_to_speech PDF DOCX images OCR S3 GCS Azure Blob SMTP audio transcribe TTS vision',
  },
  {
    id: 'tools-memory-ai',
    title: 'Memory & AI Tools',
    icon: Brain,
    group: 'Built-in Tools Reference',
    content: 'memory_store memory_recall memory_forget knowledge_search vector_search llm_call llm_route agent_step key-value long-term memory semantic search dense vector pgvector LLM prompt route sub-agent invoke',
  },
  {
    id: 'tools-integration',
    title: 'Integration & Finance Tools',
    icon: Plug,
    group: 'Built-in Tools Reference',
    content: 'github_tool integration_hub event_buffer redis_stream_consumer redis_stream_publisher kafka_consumer market_data yahoo_finance pipeline_tool sub_pipeline pii_redactor human_approval current_time GitHub Slack Jira Confluence Redis Kafka stock crypto forex FRED economic PII redaction HITL',
  },
  {
    id: 'tools-specialized',
    title: 'Specialized Tools',
    icon: Sparkles,
    group: 'Built-in Tools Reference',
    content: 'moderation browser_automation translation plotly_chart mermaid_diagram semantic_diff address_normalize geocoding weather crypto_market fred_economic ecb_rates entso_e gov_data_us world_bank ember_tool patents_trademarks cloud_cost twilio_sms ml_model_tool code_asset knowledge_store graph_explorer schema_portfolio zapier_pass_through',
  },

  // ── Enterprise Features ──
  {
    id: 'moderation-gate',
    title: 'Content Moderation',
    icon: Shield,
    group: 'Enterprise Features',
    content: 'moderation gate policy vet classify block redact flag allow pre-LLM post-LLM on_tool_output custom patterns thresholds categories MODERATION_BLOCKED tenant-scoped OpenAI omni-moderation actions content policy CRUD playground preview fail_closed fail_open event history Prometheus metric',
  },
  {
    id: 'signed-webhooks',
    title: 'Signed Webhooks',
    icon: Link,
    group: 'Enterprise Features',
    content: 'webhooks signed HMAC SHA-256 secret signature header X-Abenix-Signature verify payload webhook events execution.completed execution.failed delivery retry idempotency',
  },
  {
    id: 'rbac-sharing',
    title: 'RBAC & Sharing',
    icon: Users,
    group: 'Enterprise Features',
    content: 'RBAC role-based access control admin member viewer sharing ResourceShare polymorphic tenant isolation per-user permissions sidebar groups agent sharing marketplace publish install share collaborate',
  },
  {
    id: 'cost-guardrails',
    title: 'Cost Guardrails',
    icon: BarChart3,
    group: 'Enterprise Features',
    content: 'cost guardrails budget limits monthly per-execution per-agent tenant alert threshold webhook notification automatic cancellation spending token usage USD pricing BUDGET_EXCEEDED',
  },
  {
    id: 'drift-detection',
    title: 'Drift Detection',
    icon: TrendingUp,
    group: 'Enterprise Features',
    content: 'drift detection monitor agent behavior output quality tool usage patterns cost trends response distributions statistical anomaly baseline comparison alerts',
  },
  {
    id: 'confidence-scoring',
    title: 'Confidence Scoring',
    icon: Gauge,
    group: 'Enterprise Features',
    content: 'confidence score 0-1 low-confidence HITL review fallback model quality gate threshold human approval routing',
  },
  {
    id: 'human-approval',
    title: 'Human Approval (HITL)',
    icon: Eye,
    group: 'Enterprise Features',
    content: 'human-in-the-loop HITL approval review queue pause execution critical actions database_writer email_sender cost_threshold_usd timeout_minutes approve reject pending reviews',
  },
  {
    id: 'per-tenant-slack',
    title: 'Per-Tenant Slack URL',
    icon: MessageSquare,
    group: 'Enterprise Features',
    content: 'Slack webhook URL per-tenant notifications settings tenant environment variable resolution order SLACK_WEBHOOK_URL tenant_slack_url alerts channels configure notifications',
  },
  {
    id: 'triggers-scheduling',
    title: 'Triggers & Scheduling',
    icon: Clock,
    group: 'Enterprise Features',
    content: 'triggers scheduling cron schedule recurring agent execution timed automation POST /api/triggers interval daily weekly monthly run automatically',
  },

  // ── API Reference ──
  {
    id: 'api-auth',
    title: 'Auth API',
    icon: Key,
    group: 'API Reference',
    content: 'POST /api/auth/login register refresh logout me JWT token bearer access refresh api-key authentication RS256 scopes',
  },
  {
    id: 'api-agents',
    title: 'Agents API',
    icon: Bot,
    group: 'API Reference',
    content: 'GET POST PUT DELETE /api/agents create list get update delete execute clone agent_id message stream SSE',
  },
  {
    id: 'api-executions',
    title: 'Executions API',
    icon: Play,
    group: 'API Reference',
    content: 'GET POST /api/executions list details cancel live SSE stream execution_id steps status running completed failed PENDING RUNNING COMPLETED FAILED CANCELLED',
  },
  {
    id: 'api-knowledge',
    title: 'Knowledge API',
    icon: Brain,
    group: 'API Reference',
    content: 'GET POST /api/knowledge knowledge-bases upload ingest search hybrid cognify memify documents knowledge_base_id',
  },
  {
    id: 'api-ml-models',
    title: 'ML Models API',
    icon: Cpu,
    group: 'API Reference',
    content: 'GET POST /api/ml-models deploy undeploy status upload model serving inference predict ml_model_id ML_MODELS_DIR shared storage',
  },
  {
    id: 'api-code-assets',
    title: 'Code Assets API',
    icon: Code,
    group: 'API Reference',
    content: 'GET POST /api/code-assets test run upload zip git repository Python Node Go Rust Ruby Java code_asset_id analyze sandboxed execution',
  },
  {
    id: 'api-moderation',
    title: 'Moderation API',
    icon: Shield,
    group: 'API Reference',
    content: 'POST /api/moderation/vet GET POST PATCH DELETE /api/moderation/policies GET /api/moderation/events classify content moderation policy create update delete events history',
  },
  {
    id: 'api-settings',
    title: 'Settings & Webhooks API',
    icon: Settings,
    group: 'API Reference',
    content: 'GET PUT /api/settings/tenant tenant settings notifications Slack webhook GET POST /api/webhooks deliveries webhook-config events secret signature',
  },
  {
    id: 'api-triggers',
    title: 'Triggers API',
    icon: Timer,
    group: 'API Reference',
    content: 'GET POST PUT DELETE /api/triggers schedule cron recurring agent execution automation trigger_id interval',
  },

  // ── Integration ──
  {
    id: 'sdk-python',
    title: 'Python SDK',
    icon: Code,
    group: 'Integration',
    content: 'Python SDK pip install abenix-sdk client agents list execute stream knowledge search create ingest async await',
  },
  {
    id: 'sdk-javascript',
    title: 'JavaScript / TypeScript SDK',
    icon: Code,
    group: 'Integration',
    content: 'JavaScript TypeScript SDK npm install @abenix/sdk client agents list execute stream webhooks create async iterator for await',
  },
  {
    id: 'mcp-protocol',
    title: 'MCP Protocol',
    icon: Network,
    group: 'Integration',
    content: 'MCP Model Context Protocol server connection register tools annotations allow_user_mcp max_mcp_servers suggested_mcp_servers external tools per-agent configuration',
  },
  {
    id: 'a2a-protocol',
    title: 'A2A Protocol',
    icon: Share2,
    group: 'Integration',
    content: 'A2A agent-to-agent communication protocol inter-agent messaging task delegation collaboration /api/a2a endpoint discovery capability negotiation',
  },
  {
    id: 'webhook-events',
    title: 'Webhook Events',
    icon: Bell,
    group: 'Integration',
    content: 'webhook events execution.completed execution.failed execution.started agent.created agent.updated pipeline.completed HMAC SHA-256 signature verification delivery retry payload',
  },

  // ── Infrastructure ──
  {
    id: 'kubernetes-deploy',
    title: 'Kubernetes Deploy',
    icon: Cloud,
    group: 'Infrastructure',
    content: 'deploy.sh kubernetes minikube helm chart AKS EKS GKE production local local-runtime cloud status destroy build docker images namespace abenix values rollback CI/CD',
  },
  {
    id: 'shared-storage',
    title: 'Shared Storage',
    icon: HardDrive,
    group: 'Infrastructure',
    content: 'shared storage /data knowledge bases ML models code runner hostPath PVC persistent volume claim ML_MODELS_DIR knowledge_bases code_assets layout directory structure',
  },
  {
    id: 'observability',
    title: 'Observability & Monitoring',
    icon: Activity,
    group: 'Infrastructure',
    content: 'observability Prometheus Grafana metrics /metrics health check OpenTelemetry Sentry tracing SLO alerts abenix_requests_total abenix_executions_total abenix_cost_usd_total sweeper advisory lock',
  },
  {
    id: 'prebuilt-agents',
    title: '49 Pre-Built Agents',
    icon: Boxes,
    group: 'Infrastructure',
    content: 'pre-built agents 49 42 core 7 OracleNet seeded YAML engineering finance research data compliance energy pipeline patterns code assistant deep research financial modeler data mover email composer compliance auditor fraud detector OracleNet historian current state stakeholder sim contrarian synthesizer',
  },
  {
    id: 'troubleshooting',
    title: 'Troubleshooting',
    icon: Bug,
    group: 'Infrastructure',
    content: 'troubleshooting docker compose fails database connection agent timeout JWT expired Neo4j refused Celery worker Playwright tests MCP server Helm minikube 422 validation error debugging common problems FAQ',
  },
  {
    id: 'keyboard-shortcuts',
    title: 'Keyboard Shortcuts',
    icon: Keyboard,
    group: 'Infrastructure',
    content: 'keyboard shortcuts command palette Cmd Ctrl K N E Enter Shift P T sidebar settings modal cancel escape hotkeys power user',
  },
];

// ─── Helpers ─────────────────────────────────────────────────────────────────

function cn(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(' ');
}

// ─── Code Block Component ────────────────────────────────────────────────────

function CodeBlock({ code, language = 'bash' }: { code: string; language?: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [code]);
  return (
    <div className="relative group rounded-lg overflow-hidden border border-slate-700/50 bg-[#0d1117] my-3">
      <div className="flex items-center justify-between px-4 py-2 bg-slate-800/60 border-b border-slate-700/50">
        <span className="text-xs text-slate-500 font-mono">{language}</span>
        <button
          onClick={handleCopy}
          className="text-slate-500 hover:text-slate-300 transition-colors"
          aria-label="Copy code"
        >
          {copied ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
        </button>
      </div>
      <pre className="p-4 overflow-x-auto text-sm leading-relaxed">
        <code className="text-slate-300 font-mono whitespace-pre">{code}</code>
      </pre>
    </div>
  );
}

// ─── Collapsible Section ─────────────────────────────────────────────────────

function DocSection({
  id,
  icon: Icon,
  title,
  children,
  isOpen,
  onToggle,
}: {
  id: string;
  icon: React.ElementType;
  title: string;
  children: React.ReactNode;
  isOpen: boolean;
  onToggle: () => void;
}) {
  return (
    <motion.div
      id={id}
      initial={{ opacity: 0, y: 12 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-50px' }}
      transition={{ duration: 0.4 }}
      className="bg-slate-800/30 backdrop-blur-xl border border-slate-700/50 rounded-xl overflow-hidden scroll-mt-24"
    >
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-6 py-5 hover:bg-slate-700/20 transition-colors"
      >
        <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-cyan-500/20 to-purple-600/20 border border-cyan-500/20 flex items-center justify-center shrink-0">
          <Icon className="w-5 h-5 text-cyan-400" />
        </div>
        <span className="font-semibold text-lg text-slate-100 flex-1 text-left">{title}</span>
        {isOpen ? (
          <ChevronDown className="w-5 h-5 text-slate-500" />
        ) : (
          <ChevronRight className="w-5 h-5 text-slate-500" />
        )}
      </button>
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3 }}
            className="overflow-hidden"
          >
            <div className="px-6 pb-6 border-t border-slate-700/50 pt-4">
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// ─── Small heading helpers ──────────────────────────────────────────────────

function H3({ children }: { children: React.ReactNode }) {
  return <h3 className="text-base font-semibold text-white mt-6 mb-2">{children}</h3>;
}

function H4({ children }: { children: React.ReactNode }) {
  return <h4 className="text-sm font-semibold text-slate-200 mt-4 mb-1.5">{children}</h4>;
}

function P({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-slate-400 leading-relaxed mb-3">{children}</p>;
}

function Badge({ children, color = 'cyan' }: { children: React.ReactNode; color?: string }) {
  const colors: Record<string, string> = {
    cyan: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20',
    purple: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
    emerald: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
    amber: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
    red: 'bg-red-500/10 text-red-400 border-red-500/20',
    slate: 'bg-slate-700/50 text-slate-300 border-slate-600/50',
    blue: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  };
  return (
    <span className={cn('inline-flex px-2 py-0.5 rounded text-xs font-medium border', colors[color])}>
      {children}
    </span>
  );
}

function EndpointRow({ method, path, desc }: { method: string; path: string; desc: string }) {
  const methodColors: Record<string, string> = {
    GET: 'bg-emerald-500/10 text-emerald-400',
    POST: 'bg-cyan-500/10 text-cyan-400',
    PUT: 'bg-amber-500/10 text-amber-400',
    PATCH: 'bg-amber-500/10 text-amber-400',
    DELETE: 'bg-red-500/10 text-red-400',
  };
  return (
    <div className="flex items-start gap-3 py-2 border-b border-slate-700/30 last:border-0">
      <span className={cn('px-2 py-0.5 rounded text-xs font-mono font-bold shrink-0 w-16 text-center', methodColors[method])}>
        {method}
      </span>
      <code className="text-sm text-cyan-300 font-mono shrink-0">{path}</code>
      <span className="text-xs text-slate-500 ml-auto">{desc}</span>
    </div>
  );
}

function ToolRow({ name, category, description }: { name: string; category: string; description: string }) {
  const catColors: Record<string, string> = {
    'Data': 'purple',
    'Search': 'cyan',
    'Analysis': 'emerald',
    'I/O': 'amber',
    'AI': 'cyan',
    'Memory': 'purple',
    'Integration': 'amber',
    'Compute': 'red',
    'Pipeline': 'slate',
    'Finance': 'emerald',
    'Media': 'amber',
    'Security': 'red',
    'Visualization': 'blue',
    'Utility': 'slate',
    'Moderation': 'red',
    'Communication': 'cyan',
    'Geo': 'emerald',
    'Government': 'blue',
    'Energy': 'amber',
    'ML': 'purple',
  };
  return (
    <div className="flex items-center gap-3 py-2 border-b border-slate-700/30 last:border-0">
      <code className="text-sm text-cyan-300 font-mono w-52 shrink-0">{name}</code>
      <Badge color={catColors[category] || 'slate'}>{category}</Badge>
      <span className="text-xs text-slate-400 ml-2">{description}</span>
    </div>
  );
}

function InfoBox({ children, variant = 'info' }: { children: React.ReactNode; variant?: 'info' | 'warning' | 'tip' }) {
  const styles = {
    info: 'bg-cyan-500/5 border-cyan-500/20 text-cyan-200',
    warning: 'bg-amber-500/5 border-amber-500/20 text-amber-200',
    tip: 'bg-emerald-500/5 border-emerald-500/20 text-emerald-200',
  };
  return (
    <div className={cn('rounded-lg border p-4 my-3 text-sm', styles[variant])}>
      {children}
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function DocsPage() {
  const [searchQuery, setSearchQuery] = useState('');
  const [openSections, setOpenSections] = useState<Set<string>>(new Set(['quick-start']));
  const [activeSection, setActiveSection] = useState('quick-start');
  const [showBackToTop, setShowBackToTop] = useState(false);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const mainRef = useRef<HTMLDivElement>(null);

  // Track scroll for back-to-top and active section
  useEffect(() => {
    const handleScroll = () => {
      setShowBackToTop(window.scrollY > 400);
      const sectionEls = SECTIONS.map((s) => document.getElementById(s.id));
      for (let i = sectionEls.length - 1; i >= 0; i--) {
        const el = sectionEls[i];
        if (el && el.getBoundingClientRect().top <= 120) {
          setActiveSection(SECTIONS[i].id);
          break;
        }
      }
    };
    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  const toggleSection = useCallback((id: string) => {
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const scrollToSection = useCallback((id: string) => {
    // Open the section first, then scroll after DOM updates
    setOpenSections((prev) => new Set(prev).add(id));
    setTimeout(() => {
      const el = document.getElementById(id);
      if (el) {
        const top = el.getBoundingClientRect().top + window.scrollY - 100;
        window.scrollTo({ top, behavior: 'smooth' });
      }
    }, 50);
  }, []);

  const toggleGroup = useCallback((groupName: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(groupName)) next.delete(groupName);
      else next.add(groupName);
      return next;
    });
  }, []);

  const expandAllInGroup = useCallback((groupName: string) => {
    const ids = SECTIONS.filter((s) => s.group === groupName).map((s) => s.id);
    setOpenSections((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => next.add(id));
      return next;
    });
  }, []);

  const collapseAllInGroup = useCallback((groupName: string) => {
    const ids = SECTIONS.filter((s) => s.group === groupName).map((s) => s.id);
    setOpenSections((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => next.delete(id));
      return next;
    });
  }, []);

  // Full-text search: title + content + id
  const filteredSections = useMemo(() => {
    if (!searchQuery.trim()) return SECTIONS;
    const q = searchQuery.toLowerCase();
    return SECTIONS.filter(
      (s) =>
        s.title.toLowerCase().includes(q) ||
        s.id.toLowerCase().includes(q) ||
        s.content.toLowerCase().includes(q),
    );
  }, [searchQuery]);

  const filteredGroups = useMemo(() => {
    return GROUPS.filter((g) => filteredSections.some((s) => s.group === g.name));
  }, [filteredSections]);

  const sectionVisible = useCallback(
    (id: string) => filteredSections.some((s) => s.id === id),
    [filteredSections],
  );

  return (
    <div className="min-h-screen bg-[#0B0F19] text-white">
      {/* ── Navbar ── */}
      <motion.nav
        initial={{ y: -20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.5 }}
        className="fixed top-0 left-0 right-0 z-50 bg-[#0B0F19]/80 backdrop-blur-xl border-b border-slate-800/50"
      >
        <div className="mx-auto px-6 xl:px-10 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <a href="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
              <img src="/logo.svg" alt="Abenix" className="w-8 h-8" />
              <span className="text-lg font-bold text-white">Abenix</span>
            </a>
            <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-gradient-to-r from-cyan-500 to-purple-600 text-white">
              DOCS
            </span>
          </div>
          <div className="hidden md:flex items-center gap-1">
            <a href="/" className="flex items-center gap-1.5 px-3 py-2 text-sm text-slate-400 hover:text-white rounded-lg hover:bg-slate-800/50 transition-colors">
              <Sparkles className="w-4 h-4" />
              Home
            </a>
            <a href="/demo" className="flex items-center gap-1.5 px-3 py-2 text-sm text-slate-400 hover:text-white rounded-lg hover:bg-slate-800/50 transition-colors">
              <Play className="w-4 h-4" />
              Demo
            </a>
            <a href="/docs" className="flex items-center gap-1.5 px-3 py-2 text-sm text-cyan-400 rounded-lg bg-slate-800/50 transition-colors">
              <Book className="w-4 h-4" />
              Docs
            </a>
          </div>
          <div />
        </div>
      </motion.nav>

      {/* ── Hero ── */}
      <div className="pt-24 pb-12 px-6 xl:px-10">
        <div className="mx-auto">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
            className="text-center mb-10"
          >
            <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-slate-800/60 border border-slate-700/50 mb-6">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-xs text-slate-400">50+ Tools &middot; 49 Agents &middot; Full API Reference</span>
            </div>
            <h1 className="text-4xl md:text-5xl font-bold mb-4">
              <span className="bg-gradient-to-r from-cyan-400 via-purple-400 to-cyan-400 bg-clip-text text-transparent">
                Developer Documentation
              </span>
            </h1>
            <p className="text-slate-400 text-lg max-w-2xl mx-auto">
              Everything you need to build, deploy, and operate AI agents on Abenix.
              Enterprise-grade infrastructure with DAG pipelines, content moderation, RBAC, and full observability.
            </p>
          </motion.div>

          {/* ── Search bar ── */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
            className="max-w-xl mx-auto mb-10"
          >
            <div className="relative">
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-500" />
              <input
                type="text"
                placeholder="Search documentation (titles, content, keywords)..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-12 pr-4 py-3.5 bg-slate-800/50 border border-slate-700/50 rounded-xl text-sm text-white placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/40 focus:border-cyan-500/40 transition-all"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="absolute right-4 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 text-xs"
                >
                  Clear
                </button>
              )}
            </div>
            {searchQuery && (
              <p className="text-xs text-slate-500 mt-2 text-center">
                {filteredSections.length} section{filteredSections.length !== 1 ? 's' : ''} match{filteredSections.length === 1 ? 'es' : ''}
              </p>
            )}
          </motion.div>
        </div>
      </div>

      {/* ── Main content with sidebar ── */}
      <div className="mx-auto px-6 xl:px-10 pb-20 flex gap-6">
        {/* ── Sidebar ── */}
        <aside className="hidden lg:block w-60 shrink-0">
          <div className="sticky top-24 max-h-[calc(100vh-7rem)] overflow-y-auto pb-8 pr-2 scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent">
            <nav className="space-y-3">
              {filteredGroups.map((group) => {
                const groupSections = filteredSections.filter((s) => s.group === group.name);
                const isGroupCollapsed = collapsedGroups.has(group.name);
                if (groupSections.length === 0) return null;
                return (
                  <div key={group.name}>
                    <button
                      onClick={() => toggleGroup(group.name)}
                      className="w-full flex items-center gap-2 px-2 py-1.5 text-xs font-semibold text-slate-500 uppercase tracking-wider hover:text-slate-300 transition-colors"
                    >
                      {isGroupCollapsed ? (
                        <ChevronRight className="w-3 h-3" />
                      ) : (
                        <ChevronDown className="w-3 h-3" />
                      )}
                      <group.icon className="w-3.5 h-3.5" />
                      <span className="flex-1 text-left">{group.name}</span>
                      <span className="text-[10px] text-slate-600">{groupSections.length}</span>
                    </button>
                    {!isGroupCollapsed && (
                      <div className="ml-2 mt-0.5 space-y-0.5 border-l border-slate-800/60 pl-2">
                        {groupSections.map((section) => {
                          const isActive = activeSection === section.id;
                          return (
                            <button
                              key={section.id}
                              onClick={() => scrollToSection(section.id)}
                              className={cn(
                                'w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-xs transition-all text-left',
                                isActive
                                  ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20'
                                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50',
                              )}
                            >
                              <section.icon className="w-3.5 h-3.5 shrink-0" />
                              <span className="truncate">{section.title}</span>
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </nav>
          </div>
        </aside>

        {/* ── Content ── */}
        <main ref={mainRef} className="flex-1 min-w-0 space-y-4">

          {/* ================================================================ */}
          {/* GROUP: GETTING STARTED                                           */}
          {/* ================================================================ */}

          {filteredGroups.some((g) => g.name === 'Getting Started') && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white flex items-center gap-2">
                  <Rocket className="w-5 h-5 text-emerald-400" />
                  Getting Started
                </h2>
                <div className="flex gap-2">
                  <button onClick={() => expandAllInGroup('Getting Started')} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">Expand All</button>
                  <span className="text-slate-700">|</span>
                  <button onClick={() => collapseAllInGroup('Getting Started')} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">Collapse All</button>
                </div>
              </div>

              {/* ── Quick Start ── */}
              {sectionVisible('quick-start') && (
                <DocSection id="quick-start" icon={Rocket} title="Quick Start" isOpen={openSections.has('quick-start')} onToggle={() => toggleSection('quick-start')}>
                  <H3>Prerequisites</H3>
                  <P>Docker Desktop (or Podman), Node.js 18+, Python 3.11+, and Git.</P>

                  <H3>1. Clone and start</H3>
                  <CodeBlock language="bash" code={`git clone https://github.com/sarkar4777/abenix.git
cd abenix
chmod +x start.sh
./start.sh            # spins up all services via Docker Compose`} />
                  <P>The <code className="text-cyan-300">start.sh</code> script runs <code className="text-cyan-300">docker compose up -d</code> and waits for all health checks to pass. First run pulls images and takes ~3 minutes. Subsequent starts are under 15 seconds.</P>

                  <H3>2. Default credentials</H3>
                  <div className="bg-slate-900/60 border border-slate-700/50 rounded-lg p-4 my-3 space-y-2">
                    <div className="flex items-center gap-3">
                      <Badge color="cyan">Admin</Badge>
                      <span className="text-sm text-slate-300">admin@abenix.dev / admin123</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <Badge color="emerald">Member</Badge>
                      <span className="text-sm text-slate-300">user@abenix.dev / user123</span>
                    </div>
                  </div>
                  <InfoBox variant="warning">Change these credentials immediately in production. They are seeded by the initial migration and intended for local development only.</InfoBox>

                  <H3>3. Verify services</H3>
                  <CodeBlock language="bash" code={`# API health check
curl http://localhost:8000/health
# {"status":"healthy","version":"1.0.0","services":{"postgres":"connected","redis":"connected","neo4j":"connected"}}

# Web UI
open http://localhost:3000

# Agent Runtime health
curl http://localhost:8001/health

# Interactive API docs (Swagger UI)
open http://localhost:8000/docs`} />

                  <H3>4. Create your first agent</H3>
                  <CodeBlock language="bash" code={`# Login and get a JWT token
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \\
  -H "Content-Type: application/json" \\
  -d '{"email":"admin@abenix.dev","password":"admin123"}' \\
  | jq -r '.data.access_token')

# Create an agent
curl -X POST http://localhost:8000/api/agents \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "My First Agent",
    "system_prompt": "You are a helpful assistant that can search the web and do math.",
    "model_config": {
      "model": "claude-sonnet-4-5-20250929",
      "temperature": 0.3,
      "tools": ["web_search", "calculator"]
    }
  }'`} />

                  <H3>5. Execute the agent</H3>
                  <CodeBlock language="bash" code={`# Replace {agent_id} with the id from the creation response
curl -X POST http://localhost:8000/api/agents/{agent_id}/execute \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"message": "What is the current price of Bitcoin and what would $10k invested at the start of 2024 be worth now?"}'

# Stream results with SSE
curl -N -X POST http://localhost:8000/api/agents/{agent_id}/execute \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"message": "Write a market analysis of AI chips", "stream": true}'`} />
                </DocSection>
              )}

              {/* ── Architecture ── */}
              {sectionVisible('architecture') && (
                <DocSection id="architecture" icon={Layers} title="Architecture Overview" isOpen={openSections.has('architecture')} onToggle={() => toggleSection('architecture')}>
                  <P>Abenix is a 7-layer platform built for enterprise AI agent deployment. Each layer is independently scalable and communicates through well-defined interfaces.</P>

                  <H3>7-Layer Architecture</H3>
                  <div className="space-y-3 my-4">
                    {[
                      { layer: '7', name: 'Presentation', desc: 'Next.js 14 App Router, React 18, Tailwind CSS, Framer Motion', color: 'from-cyan-500/20 to-cyan-600/20' },
                      { layer: '6', name: 'API Gateway', desc: 'FastAPI with 42 routers, OpenAPI docs, rate limiting, CORS', color: 'from-blue-500/20 to-blue-600/20' },
                      { layer: '5', name: 'Auth & Identity', desc: 'RS256 JWT (15-min access, 7-day refresh), API keys (af_ prefix, SHA-256), RBAC', color: 'from-indigo-500/20 to-indigo-600/20' },
                      { layer: '4', name: 'Agent Runtime', desc: 'ReAct loop, tool orchestration, streaming SSE, 50+ built-in tools, moderation gate', color: 'from-purple-500/20 to-purple-600/20' },
                      { layer: '3', name: 'Pipeline Engine', desc: 'DAG executor, conditions, forEach, while, switch, retry, error branches, merge', color: 'from-violet-500/20 to-violet-600/20' },
                      { layer: '2', name: 'Knowledge & Memory', desc: 'Neo4j 5 graph DB, Cognify (build), Memify (evolve), hybrid vector+graph search, MemPalace', color: 'from-fuchsia-500/20 to-fuchsia-600/20' },
                      { layer: '1', name: 'Data & Infrastructure', desc: 'PostgreSQL 16 + pgvector, Redis (Celery, cache, state), 35+ SQLAlchemy models, Alembic', color: 'from-pink-500/20 to-pink-600/20' },
                    ].map((l) => (
                      <div key={l.layer} className={cn('flex items-start gap-4 p-4 rounded-lg border border-slate-700/40 bg-gradient-to-r', l.color)}>
                        <span className="text-2xl font-bold text-slate-500 w-8 text-center shrink-0">{l.layer}</span>
                        <div>
                          <div className="font-semibold text-white text-sm">{l.name}</div>
                          <div className="text-xs text-slate-400 mt-1">{l.desc}</div>
                        </div>
                      </div>
                    ))}
                  </div>

                  <H3>Service Map</H3>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 my-3">
                    {[
                      { name: 'web', port: '3000', desc: 'Next.js 14 frontend' },
                      { name: 'api', port: '8000', desc: 'FastAPI backend (42 routers)' },
                      { name: 'agent-runtime', port: '8001', desc: 'Agent execution engine' },
                      { name: 'worker', port: '--', desc: 'Celery async task runner' },
                      { name: 'postgres', port: '5432', desc: 'PostgreSQL 16 + pgvector' },
                      { name: 'redis', port: '6379', desc: 'Cache, broker, live state' },
                      { name: 'neo4j', port: '7687', desc: 'Knowledge graph (Neo4j 5)' },
                    ].map((s) => (
                      <div key={s.name} className="flex items-center gap-3 p-3 bg-slate-900/40 border border-slate-700/40 rounded-lg">
                        <Server className="w-4 h-4 text-cyan-400 shrink-0" />
                        <div>
                          <code className="text-sm text-cyan-300">{s.name}</code>
                          <span className="text-xs text-slate-500 ml-2">:{s.port}</span>
                          <div className="text-xs text-slate-400">{s.desc}</div>
                        </div>
                      </div>
                    ))}
                  </div>

                  <H3>Request Flow</H3>
                  <CodeBlock language="text" code={`Browser (Next.js) ─── NEXT_PUBLIC_API_URL ───> FastAPI (Layer 6)
                                                    │
                  ┌─────────────────────────────────┤
                  │                                 │
           Auth Middleware               Router Dispatch
           (JWT / API Key)               (42 routers)
                  │                                 │
                  ▼                                 ▼
           PostgreSQL (L1)              Agent Runtime (L4)
           Redis (L1)                   ├── ReAct Loop
           Neo4j (L2)                   ├── Tool Executor
                                        ├── Moderation Gate
                                        └── Pipeline Engine (L3)`} />
                </DocSection>
              )}

              {/* ── Environment Variables ── */}
              {sectionVisible('environment-variables') && (
                <DocSection id="environment-variables" icon={Settings} title="Environment Variables" isOpen={openSections.has('environment-variables')} onToggle={() => toggleSection('environment-variables')}>
                  <P>Copy from <code className="text-cyan-300">.env.example</code> and fill in your values. Never commit secrets to version control.</P>

                  <div className="space-y-3 my-3">
                    {[
                      {
                        group: 'Database',
                        vars: [
                          { name: 'DATABASE_URL', desc: 'PostgreSQL connection string (asyncpg for API, psycopg2 for Alembic)' },
                          { name: 'POSTGRES_USER', desc: 'PostgreSQL username (default: abenix)' },
                          { name: 'POSTGRES_PASSWORD', desc: 'PostgreSQL password' },
                          { name: 'POSTGRES_DB', desc: 'Database name (default: abenix)' },
                        ],
                      },
                      {
                        group: 'Redis & Celery',
                        vars: [
                          { name: 'REDIS_URL', desc: 'Redis connection URL for cache and live state' },
                          { name: 'CELERY_BROKER_URL', desc: 'Redis URL for Celery task broker' },
                          { name: 'CELERY_RESULT_BACKEND', desc: 'Redis URL for Celery result storage' },
                        ],
                      },
                      {
                        group: 'API & Web',
                        vars: [
                          { name: 'API_HOST', desc: 'API bind address (default: 0.0.0.0)' },
                          { name: 'API_PORT', desc: 'API port (default: 8000)' },
                          { name: 'SECRET_KEY', desc: 'JWT signing secret -- change in production!' },
                          { name: 'CORS_ORIGINS', desc: 'Allowed CORS origins (JSON array)' },
                          { name: 'NEXT_PUBLIC_API_URL', desc: 'API URL for the Next.js frontend' },
                        ],
                      },
                      {
                        group: 'LLM Providers',
                        vars: [
                          { name: 'ANTHROPIC_API_KEY', desc: 'Anthropic API key for Claude models (primary)' },
                          { name: 'OPENAI_API_KEY', desc: 'OpenAI API key (optional, for GPT and moderation)' },
                          { name: 'GOOGLE_API_KEY', desc: 'Google AI API key for Gemini (optional)' },
                        ],
                      },
                      {
                        group: 'Search Providers',
                        vars: [
                          { name: 'SEARCH_PROVIDER', desc: 'Default search: tavily, brave, serpapi, serper' },
                          { name: 'TAVILY_API_KEY', desc: 'Tavily search API key (recommended)' },
                          { name: 'BRAVE_SEARCH_API_KEY', desc: 'Brave search API key' },
                          { name: 'SERPAPI_API_KEY', desc: 'SerpAPI key' },
                          { name: 'SERPER_API_KEY', desc: 'Serper API key' },
                          { name: 'NEWS_API_KEY', desc: 'NewsAPI key for news_feed tool' },
                          { name: 'MEDIASTACK_API_KEY', desc: 'MediaStack key for news_feed tool' },
                          { name: 'FRED_API_KEY', desc: 'FRED economic data API key' },
                        ],
                      },
                      {
                        group: 'Knowledge Engine',
                        vars: [
                          { name: 'NEO4J_URI', desc: 'Neo4j Bolt connection URI (bolt://localhost:7687)' },
                          { name: 'NEO4J_USER', desc: 'Neo4j username' },
                          { name: 'NEO4J_PASSWORD', desc: 'Neo4j password' },
                          { name: 'PINECONE_API_KEY', desc: 'Pinecone vector store API key' },
                          { name: 'PINECONE_INDEX_NAME', desc: 'Pinecone index name' },
                        ],
                      },
                      {
                        group: 'Shared Storage',
                        vars: [
                          { name: 'ML_MODELS_DIR', desc: 'Path to ML model files (default: /data/ml-models)' },
                          { name: 'STORAGE_BACKEND', desc: 'File storage: local, s3, or azure' },
                          { name: 'STORAGE_S3_BUCKET', desc: 'S3 bucket name' },
                          { name: 'STORAGE_S3_ENDPOINT', desc: 'S3 endpoint URL (for MinIO/R2)' },
                        ],
                      },
                      {
                        group: 'Runtime & Observability',
                        vars: [
                          { name: 'RUNTIME_MODE', desc: 'Agent runtime: embedded (local) or remote (K8s)' },
                          { name: 'RUNTIME_URL', desc: 'URL of remote agent runtime service' },
                          { name: 'SENTRY_DSN', desc: 'Sentry DSN for error tracking (optional)' },
                          { name: 'PROMETHEUS_MULTIPROC_DIR', desc: 'Directory for Prometheus multiprocess mode' },
                          { name: 'SLACK_WEBHOOK_URL', desc: 'Global Slack webhook for alerts (tenant can override)' },
                        ],
                      },
                    ].map((section) => (
                      <div key={section.group} className="bg-slate-900/40 border border-slate-700/40 rounded-lg p-3">
                        <div className="text-sm font-semibold text-white mb-2">{section.group}</div>
                        <div className="space-y-1">
                          {section.vars.map((v) => (
                            <div key={v.name} className="flex items-start gap-2 text-xs">
                              <code className="text-cyan-300 font-mono shrink-0 w-60">{v.name}</code>
                              <span className="text-slate-400">{v.desc}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>

                  <InfoBox variant="tip">
                    In Kubernetes, these are set via the Helm values file (<code className="text-emerald-300">values-minikube.yaml</code> or <code className="text-emerald-300">values-production.yaml</code>) and injected as container environment variables from a Secret.
                  </InfoBox>
                </DocSection>
              )}

              {/* ── Default Credentials ── */}
              {sectionVisible('default-credentials') && (
                <DocSection id="default-credentials" icon={Key} title="Default Credentials" isOpen={openSections.has('default-credentials')} onToggle={() => toggleSection('default-credentials')}>
                  <P>The seed migration creates two accounts and their associated tenant. These are for local development only.</P>

                  <H3>Development Accounts</H3>
                  <div className="space-y-2 my-3">
                    <div className="bg-slate-900/60 border border-slate-700/50 rounded-lg p-4 space-y-3">
                      <div className="flex items-center gap-3">
                        <Badge color="red">Admin</Badge>
                        <code className="text-sm text-slate-300">admin@abenix.dev</code>
                        <code className="text-sm text-slate-500">/ admin123</code>
                      </div>
                      <P>Full access: create agents, manage team members, configure tenant settings, manage API keys, access all routers.</P>
                      <div className="flex items-center gap-3">
                        <Badge color="emerald">Member</Badge>
                        <code className="text-sm text-slate-300">user@abenix.dev</code>
                        <code className="text-sm text-slate-500">/ user123</code>
                      </div>
                      <P>Standard access: create and execute agents, view executions, search knowledge. Cannot manage team or settings.</P>
                    </div>
                  </div>

                  <H3>Service Credentials</H3>
                  <div className="space-y-1 my-3">
                    {[
                      { service: 'PostgreSQL', user: 'abenix', pass: 'abenix', port: '5432' },
                      { service: 'Redis', user: '(no auth)', pass: '--', port: '6379' },
                      { service: 'Neo4j', user: 'neo4j', pass: 'abenix', port: '7687' },
                    ].map((s) => (
                      <div key={s.service} className="flex items-center gap-3 text-sm text-slate-300 py-1 border-b border-slate-700/30 last:border-0">
                        <span className="w-24 text-slate-400">{s.service}</span>
                        <code className="text-cyan-300">{s.user}</code>
                        <span className="text-slate-600">/</span>
                        <code className="text-slate-500">{s.pass}</code>
                        <span className="text-xs text-slate-600 ml-auto">:{s.port}</span>
                      </div>
                    ))}
                  </div>

                  <H3>API Key Management</H3>
                  <P>Create scoped API keys for server-to-server integrations. All keys are prefixed with <code className="text-cyan-300">af_</code> and stored as SHA-256 hashes.</P>
                  <CodeBlock language="bash" code={`# Create an API key
curl -X POST http://localhost:8000/api/api-keys \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"name": "CI Pipeline", "scopes": ["agents:read", "agents:execute"]}'

# Response includes the key ONCE -- store it securely:
# { "data": { "key": "af_live_a1b2c3d4e5...", "id": "...", "name": "CI Pipeline" } }

# Use the API key in subsequent requests
curl http://localhost:8000/api/agents \\
  -H "X-API-Key: af_live_a1b2c3d4e5..."`} />

                  <H3>Available Scopes</H3>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 my-3">
                    {[
                      'agents:read', 'agents:write', 'agents:execute', 'agents:delete',
                      'executions:read', 'executions:cancel',
                      'knowledge:read', 'knowledge:write',
                      'pipelines:read', 'pipelines:write', 'pipelines:execute',
                      'settings:read', 'settings:write',
                      'team:read', 'team:write',
                      'api-keys:manage',
                    ].map((scope) => (
                      <code key={scope} className="text-xs bg-slate-800/60 border border-slate-700/40 rounded px-2 py-1 text-cyan-300">{scope}</code>
                    ))}
                  </div>
                </DocSection>
              )}
            </div>
          )}

          {/* ================================================================ */}
          {/* GROUP: CORE CONCEPTS                                             */}
          {/* ================================================================ */}

          {filteredGroups.some((g) => g.name === 'Core Concepts') && (
            <div className="space-y-4 mt-8">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white flex items-center gap-2">
                  <BookOpen className="w-5 h-5 text-cyan-400" />
                  Core Concepts
                </h2>
                <div className="flex gap-2">
                  <button onClick={() => expandAllInGroup('Core Concepts')} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">Expand All</button>
                  <span className="text-slate-700">|</span>
                  <button onClick={() => collapseAllInGroup('Core Concepts')} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">Collapse All</button>
                </div>
              </div>

              {/* ── Agents ── */}
              {sectionVisible('agents-overview') && (
                <DocSection id="agents-overview" icon={Bot} title="Agents" isOpen={openSections.has('agents-overview')} onToggle={() => toggleSection('agents-overview')}>
                  <P>Agents are the core execution units in Abenix. Each agent has a system prompt, model configuration, and a set of tools. Agents operate in two modes:</P>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 my-3">
                    <div className="p-4 bg-slate-900/40 border border-slate-700/40 rounded-lg">
                      <div className="flex items-center gap-2 mb-2">
                        <Bot className="w-5 h-5 text-cyan-400" />
                        <span className="font-semibold text-white text-sm">Agent Mode (ReAct)</span>
                      </div>
                      <p className="text-xs text-slate-400">The agent receives a message, reasons about which tools to call, executes them, observes results, and iterates until the task is complete or max_iterations is reached. Best for open-ended tasks.</p>
                    </div>
                    <div className="p-4 bg-slate-900/40 border border-slate-700/40 rounded-lg">
                      <div className="flex items-center gap-2 mb-2">
                        <Workflow className="w-5 h-5 text-purple-400" />
                        <span className="font-semibold text-white text-sm">Pipeline Mode (DAG)</span>
                      </div>
                      <p className="text-xs text-slate-400">A deterministic directed acyclic graph of tool executions with explicit dependencies, input mappings, and template variable interpolation. Best for repeatable workflows.</p>
                    </div>
                  </div>

                  <H3>Agent YAML Configuration</H3>
                  <CodeBlock language="yaml" code={`name: Code Assistant
slug: code-assistant
agent_type: oob          # out-of-the-box, seeded at startup
category: engineering
system_prompt: |
  You are a senior software engineer. Help users write,
  review, debug, and understand code across all languages.

model_config:
  model: claude-sonnet-4-5-20250929
  temperature: 0.2
  max_tokens: 4096
  tools:
    - file_reader
    - web_search
    - calculator
    - code_executor
    - json_transformer
    - regex_extractor
    - text_analyzer
    - http_client

mcp_extensions:
  allow_user_mcp: true    # users can attach their own MCP servers
  max_mcp_servers: 5
  suggested_mcp_servers:
    - name: GitHub
      url: https://github.com/modelcontextprotocol/server-github`} />

                  <H3>Execution Flow</H3>
                  <CodeBlock language="text" code={`User Message
     │
     ▼
┌─ Moderation Gate (pre-LLM) ─┐
│  Check user input against    │
│  tenant's active policy      │
└──────────────────────────────┘
     │ ALLOW
     ▼
┌─ LLM Call ──────────────────┐
│  System Prompt + User Msg   │
│  → Model decides action     │
└─────────────────────────────┘
     │
     ├── tool_call: web_search("AI chips market")
     │       │
     │       ▼
     │   Tool Executor → Result
     │       │
     │       ▼
     │   Observe result, iterate
     │
     ├── tool_call: calculator("...")
     │       ...
     │
     ▼
┌─ Moderation Gate (post-LLM) ┐
│  Check model output against  │
│  tenant's active policy      │
└──────────────────────────────┘
     │ ALLOW
     ▼
  Final Response → SSE Stream → Client`} />

                  <H3>Key Configuration Fields</H3>
                  <div className="space-y-1 my-3">
                    {[
                      { field: 'model', desc: 'LLM model identifier (e.g., claude-sonnet-4-5-20250929, gpt-4o)' },
                      { field: 'temperature', desc: 'Creativity vs determinism (0.0 - 1.0, default 0.3)' },
                      { field: 'max_tokens', desc: 'Maximum response tokens (default: 4096)' },
                      { field: 'tools', desc: 'Array of tool names the agent can invoke' },
                      { field: 'max_iterations', desc: 'Maximum ReAct loop iterations (default: 25)' },
                      { field: 'timeout_seconds', desc: 'Per-execution timeout (default: 120)' },
                    ].map((f) => (
                      <div key={f.field} className="flex items-start gap-3 text-sm py-1">
                        <code className="text-cyan-300 font-mono w-36 shrink-0">{f.field}</code>
                        <span className="text-slate-400 text-xs">{f.desc}</span>
                      </div>
                    ))}
                  </div>
                </DocSection>
              )}

              {/* ── Pipelines ── */}
              {sectionVisible('pipelines-overview') && (
                <DocSection id="pipelines-overview" icon={Workflow} title="Pipelines" isOpen={openSections.has('pipelines-overview')} onToggle={() => toggleSection('pipelines-overview')}>
                  <P>The pipeline engine executes directed acyclic graphs (DAGs) of tool invocations. Nodes run in parallel when their dependencies are satisfied.</P>

                  <H3>Node Types</H3>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 my-3">
                    {[
                      { name: 'Tool Node', desc: 'Executes a built-in tool with arguments', icon: Wrench },
                      { name: 'LLM Call', desc: 'Invokes an LLM with a prompt template', icon: Brain },
                      { name: 'Condition', desc: 'Branching based on expression evaluation', icon: GitBranch },
                      { name: 'forEach', desc: 'Iterates over a collection from upstream', icon: List },
                      { name: 'While', desc: 'Loop until a condition is false', icon: CircleDot },
                      { name: 'Switch', desc: 'Multi-way branching on a value', icon: Filter },
                      { name: 'Merge', desc: 'Combines outputs from parallel branches', icon: Network },
                      { name: 'Error Branch', desc: 'Handles failures from upstream nodes', icon: AlertTriangle },
                    ].map((n) => (
                      <div key={n.name} className="flex items-start gap-3 p-3 bg-slate-900/40 border border-slate-700/40 rounded-lg">
                        <n.icon className="w-4 h-4 text-purple-400 shrink-0 mt-0.5" />
                        <div>
                          <div className="text-sm font-medium text-white">{n.name}</div>
                          <div className="text-xs text-slate-400">{n.desc}</div>
                        </div>
                      </div>
                    ))}
                  </div>

                  <H3>Pipeline Example</H3>
                  <CodeBlock language="yaml" code={`name: Deep Research Agent
model_config:
  mode: pipeline
  tools: [web_search, data_merger, llm_call, text_analyzer]
  pipeline_config:
    nodes:
      - id: search_primary
        tool_name: web_search
        arguments: { query: "{{input.topic}}", num_results: 10 }
      - id: search_academic
        tool_name: web_search
        arguments: { query: "{{input.topic}} research papers", num_results: 10 }
      - id: merge_sources
        tool_name: data_merger
        arguments: { merge_strategy: comparison }
        depends_on: [search_primary, search_academic]
      - id: synthesize
        tool_name: llm_call
        arguments:
          prompt: "Synthesize these sources into a report: {{merge_sources.__all__}}"
        depends_on: [merge_sources]
    edges:
      - { source: search_primary, target: merge_sources }
      - { source: search_academic, target: merge_sources }
      - { source: merge_sources, target: synthesize }`} />

                  <H3>Template Variables</H3>
                  <P>Reference upstream node outputs in arguments using double-brace syntax:</P>
                  <CodeBlock language="yaml" code={`# Reference all output from a node
prompt: "Summarize: {{merge_sources.__all__}}"

# Reference a specific field
text: "{{synthesize.response}}"

# Reference the input to the pipeline
query: "{{input.topic}}"

# Alternative: input_mappings
input_mappings:
  prompt:
    source_node: merge_sources
    source_field: __all__`} />

                  <H3>Control Flow</H3>
                  <CodeBlock language="yaml" code={`# Retry with exponential backoff
- id: fetch_data
  tool: http_client
  max_retries: 3
  retry_delay: 2  # seconds, doubles each attempt

# Conditional execution
- id: check_quality
  tool: code_executor
  condition: "{{extract_data.row_count}} > 100"

# Error branch with fallback
- id: handle_error
  tool: llm_call
  error_handler_for: fetch_data
  arguments:
    prompt: "Fetch failed: {{fetch_data.__error__}}. Suggest alternatives."`} />

                  <H3>Execution Lifecycle</H3>
                  <div className="flex flex-wrap gap-2 my-3">
                    {['PENDING', 'RUNNING', 'WAITING_APPROVAL', 'COMPLETED', 'FAILED', 'CANCELLED'].map((s) => (
                      <Badge key={s} color={s === 'COMPLETED' ? 'emerald' : s === 'FAILED' ? 'red' : s === 'CANCELLED' ? 'amber' : 'slate'}>{s}</Badge>
                    ))}
                  </div>
                </DocSection>
              )}

              {/* ── Knowledge Engine ── */}
              {sectionVisible('knowledge-engine') && (
                <DocSection id="knowledge-engine" icon={Brain} title="Knowledge Engine" isOpen={openSections.has('knowledge-engine')} onToggle={() => toggleSection('knowledge-engine')}>
                  <P>The knowledge engine uses Neo4j 5 as a graph database for semantic knowledge storage, combined with pgvector for dense vector embeddings. It provides two core operations and hybrid search.</P>

                  <H3>Cognify -- Build Knowledge</H3>
                  <P>Extracts entities, relationships, and concepts from documents and builds a structured knowledge graph. Identifies people, organizations, topics, and their interconnections.</P>
                  <CodeBlock language="bash" code={`curl -X POST http://localhost:8000/api/knowledge-engine/cognify \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "knowledge_base_id": "kb_123",
    "documents": ["doc_456", "doc_789"],
    "extraction_mode": "deep"
  }'`} />

                  <H3>Memify -- Evolve Memory</H3>
                  <P>Takes agent execution traces and conversation history, extracts learnings, and integrates them into the knowledge graph. Over time, agents develop persistent memory.</P>
                  <CodeBlock language="bash" code={`curl -X POST http://localhost:8000/api/knowledge-engine/memify \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "agent_id": "agent_123",
    "execution_ids": ["exec_456"],
    "feedback": { "quality": 0.9, "relevance": 0.85 }
  }'`} />

                  <H3>Hybrid Search</H3>
                  <P>Queries combine vector similarity (pgvector), graph traversal (Neo4j), and keyword matching for comprehensive retrieval. Results are re-ranked using reciprocal rank fusion.</P>
                  <CodeBlock language="bash" code={`curl -X POST http://localhost:8000/api/knowledge/kb_123/search \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "query": "What are the key risk factors?",
    "search_type": "hybrid",
    "top_k": 10,
    "filters": { "document_type": "10-Q" }
  }'`} />

                  <H3>Feedback Loop</H3>
                  <div className="bg-slate-900/60 border border-slate-700/50 rounded-lg p-4 my-3 space-y-2 text-sm text-slate-300">
                    {['Agent executes a task using knowledge search', 'User provides feedback (thumbs up/down, corrections)', 'Memify processes execution trace + feedback', 'Knowledge graph edges are strengthened or weakened', 'Next search returns improved results'].map((step, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <span className="text-cyan-400 font-bold">{i + 1}.</span>
                        {step}
                      </div>
                    ))}
                  </div>
                </DocSection>
              )}

              {/* ── Tools Overview ── */}
              {sectionVisible('tools-overview') && (
                <DocSection id="tools-overview" icon={Wrench} title="Tools Overview" isOpen={openSections.has('tools-overview')} onToggle={() => toggleSection('tools-overview')}>
                  <P>Abenix ships with 90+ built-in tools organized by category. Each tool extends <code className="text-cyan-300">BaseTool</code> and exposes a typed input schema that the LLM uses for function calling.</P>

                  <H3>Tool Categories</H3>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 my-3">
                    {[
                      { cat: 'Search', count: 6, icon: Search },
                      { cat: 'Data', count: 7, icon: Database },
                      { cat: 'Analysis', count: 6, icon: BarChart3 },
                      { cat: 'Compute', count: 5, icon: Cpu },
                      { cat: 'I/O & Media', count: 9, icon: FileText },
                      { cat: 'Memory & AI', count: 7, icon: Brain },
                      { cat: 'Integration', count: 10, icon: Plug },
                      { cat: 'Finance', count: 4, icon: TrendingUp },
                      { cat: 'Specialized', count: 25, icon: Sparkles },
                    ].map((c) => (
                      <div key={c.cat} className="flex items-center gap-2 p-2 bg-slate-900/40 border border-slate-700/40 rounded-lg">
                        <c.icon className="w-4 h-4 text-cyan-400 shrink-0" />
                        <span className="text-sm text-white">{c.cat}</span>
                        <span className="text-xs text-slate-500 ml-auto">{String(c.count)}</span>
                      </div>
                    ))}
                  </div>

                  <H3>How Tools Work</H3>
                  <P>When the LLM decides to use a tool, it emits a structured function call with the tool name and arguments. The runtime resolves the tool from the registry, validates the input schema, executes the tool, and returns the result to the LLM for the next reasoning step.</P>
                  <CodeBlock language="python" code={`# Every tool follows this pattern:
class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web using multiple engines"

    class InputSchema(BaseModel):
        query: str
        num_results: int = 10
        search_type: str = "general"  # general, news, academic

    async def execute(self, input: InputSchema) -> ToolResult:
        results = await self._search(input.query, input.num_results)
        return ToolResult(output=results)`} />

                  <H3>Dynamic Tools</H3>
                  <P>Beyond built-in tools, agents can use <strong className="text-white">MCP tools</strong> (from external MCP servers), <strong className="text-white">code_asset tools</strong> (from uploaded code repositories), and <strong className="text-white">ml_model_tool</strong> (from deployed ML models). These are resolved dynamically at execution time.</P>
                </DocSection>
              )}
            </div>
          )}

          {/* ================================================================ */}
          {/* GROUP: AI BUILDER GUIDE                                          */}
          {/* ================================================================ */}

          {filteredGroups.some((g) => g.name === 'AI Builder Guide') && (
            <div className="space-y-4 mt-8">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white flex items-center gap-2">
                  <Sparkles className="w-5 h-5 text-purple-400" />
                  AI Builder Guide
                </h2>
                <div className="flex gap-2">
                  <button onClick={() => expandAllInGroup('AI Builder Guide')} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">Expand All</button>
                  <span className="text-slate-700">|</span>
                  <button onClick={() => collapseAllInGroup('AI Builder Guide')} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">Collapse All</button>
                </div>
              </div>

              {/* ── Creating Agents ── */}
              {sectionVisible('creating-agents') && (
                <DocSection id="creating-agents" icon={Bot} title="Creating Agents" isOpen={openSections.has('creating-agents')} onToggle={() => toggleSection('creating-agents')}>
                  <P>There are three ways to create agents: the AI Builder wizard in the UI, the REST API, or YAML seed files.</P>

                  <H3>Using the AI Builder (UI)</H3>
                  <div className="bg-slate-900/60 border border-slate-700/50 rounded-lg p-4 my-3 space-y-2 text-sm text-slate-300">
                    {['Navigate to /agents and click "Create Agent"', 'Choose a name and category (engineering, research, finance, etc.)', 'Write a system prompt describing the agent\'s role and behavior', 'Select a model (Claude Sonnet 4.5, GPT-4o, Gemini, etc.)', 'Choose tools from the catalog (50+ available)', 'Optionally configure MCP server connections', 'Click "Create" -- the agent is ready to execute immediately'].map((step, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <span className="text-cyan-400 font-bold w-4">{i + 1}.</span>
                        {step}
                      </div>
                    ))}
                  </div>

                  <H3>Using the API</H3>
                  <CodeBlock language="bash" code={`curl -X POST http://localhost:8000/api/agents \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "Contract Analyzer",
    "slug": "contract-analyzer",
    "category": "finance",
    "system_prompt": "You are an expert contract analyst. Extract key terms, risks, and financial obligations from legal documents.",
    "model_config": {
      "model": "claude-sonnet-4-5-20250929",
      "temperature": 0.1,
      "max_tokens": 8192,
      "tools": [
        "document_extractor",
        "text_analyzer",
        "regex_extractor",
        "risk_analyzer",
        "financial_calculator",
        "data_exporter"
      ]
    }
  }'`} />

                  <H3>Cloning Agents</H3>
                  <P>Clone any agent (including pre-built ones) to create a customized copy:</P>
                  <CodeBlock language="bash" code={`curl -X POST http://localhost:8000/api/agents/{agent_id}/clone \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"name": "My Custom Research Agent"}'`} />

                  <InfoBox variant="tip">
                    Start with a pre-built agent that is close to what you need, clone it, and customize the system prompt and tools. This is faster than building from scratch.
                  </InfoBox>
                </DocSection>
              )}

              {/* ── Tool Configuration ── */}
              {sectionVisible('tool-configuration') && (
                <DocSection id="tool-configuration" icon={SlidersHorizontal} title="Tool Configuration" isOpen={openSections.has('tool-configuration')} onToggle={() => toggleSection('tool-configuration')}>
                  <P>Tools are configured per-agent in the <code className="text-cyan-300">model_config.tools</code> array. The agent can only call tools that are explicitly listed.</P>

                  <H3>Enabling Tools</H3>
                  <CodeBlock language="json" code={`{
  "model_config": {
    "model": "claude-sonnet-4-5-20250929",
    "tools": [
      "web_search",           // Search the web
      "calculator",           // Math calculations
      "code_executor",        // Run Python code
      "file_reader",          // Read uploaded files
      "knowledge_search",     // Search knowledge bases
      "human_approval"        // Pause for HITL review
    ]
  }
}`} />

                  <H3>Tool Library</H3>
                  <P>Browse all available tools in the UI at <code className="text-cyan-300">/tools</code> or via the API:</P>
                  <CodeBlock language="bash" code={`# List all available tools
curl http://localhost:8000/api/tool-library \\
  -H "Authorization: Bearer $TOKEN"

# Get tool details (schema, parameters, examples)
curl http://localhost:8000/api/tool-library/web_search \\
  -H "Authorization: Bearer $TOKEN"`} />

                  <H3>Gotchas</H3>
                  <InfoBox variant="warning">
                    Do not restrict tools too aggressively. An agent with only <code className="text-amber-300">web_search</code> cannot process the results without <code className="text-amber-300">text_analyzer</code> or <code className="text-amber-300">json_transformer</code>. Give agents the budget to do real work -- quality over artificial speed limits.
                  </InfoBox>
                </DocSection>
              )}

              {/* ── Pipeline Visual Builder ── */}
              {sectionVisible('pipeline-builder') && (
                <DocSection id="pipeline-builder" icon={Workflow} title="Pipeline Visual Builder" isOpen={openSections.has('pipeline-builder')} onToggle={() => toggleSection('pipeline-builder')}>
                  <P>The pipeline visual builder at <code className="text-cyan-300">/pipelines/new</code> provides a drag-and-drop canvas for designing DAG workflows.</P>

                  <H3>Building a Pipeline</H3>
                  <div className="bg-slate-900/60 border border-slate-700/50 rounded-lg p-4 my-3 space-y-2 text-sm text-slate-300">
                    {['Drag tool nodes from the left panel onto the canvas', 'Connect nodes by dragging from an output port to an input port', 'Configure each node\'s arguments in the right panel', 'Use template variables ({{node_id.field}}) to pass data between nodes', 'Add condition nodes for branching and merge nodes to combine', 'Click "Validate" to check the DAG for cycles and missing dependencies', 'Save and execute from the pipeline detail page'].map((step, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <span className="text-purple-400 font-bold w-4">{i + 1}.</span>
                        {step}
                      </div>
                    ))}
                  </div>

                  <H3>Validate Before Execution</H3>
                  <CodeBlock language="bash" code={`# Validate a pipeline config (catches cycles, missing tools, type errors)
curl -X POST http://localhost:8000/api/pipelines/validate \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{ "pipeline_config": { "nodes": [...], "edges": [...] } }'`} />
                </DocSection>
              )}

              {/* ── Input Variables ── */}
              {sectionVisible('input-variables') && (
                <DocSection id="input-variables" icon={Terminal} title="Input Variables" isOpen={openSections.has('input-variables')} onToggle={() => toggleSection('input-variables')}>
                  <P>Input variables let you pass data between pipeline nodes and from the execution request into the pipeline.</P>

                  <H3>Variable Syntax</H3>
                  <div className="space-y-2 my-3">
                    {[
                      { syntax: '{{input.field}}', desc: 'Reference a field from the execution request body' },
                      { syntax: '{{node_id.__all__}}', desc: 'Reference the complete output of a node' },
                      { syntax: '{{node_id.field}}', desc: 'Reference a specific field from a node\'s output' },
                      { syntax: '{{node_id.__error__}}', desc: 'Reference the error message from a failed node' },
                    ].map((v) => (
                      <div key={v.syntax} className="flex items-start gap-3 text-sm">
                        <code className="text-cyan-300 font-mono w-48 shrink-0">{v.syntax}</code>
                        <span className="text-slate-400 text-xs">{v.desc}</span>
                      </div>
                    ))}
                  </div>

                  <CodeBlock language="json" code={`// Execution request with input variables
{
  "message": "Analyze the market",
  "variables": {
    "topic": "AI semiconductor market",
    "depth": "comprehensive",
    "format": "executive_summary"
  }
}

// Then in the pipeline node:
{
  "id": "search",
  "tool_name": "web_search",
  "arguments": {
    "query": "{{input.topic}} market analysis {{input.depth}}"
  }
}`} />
                </DocSection>
              )}

              {/* ── Model Configuration ── */}
              {sectionVisible('model-configuration') && (
                <DocSection id="model-configuration" icon={Cpu} title="Model Configuration" isOpen={openSections.has('model-configuration')} onToggle={() => toggleSection('model-configuration')}>
                  <P>Abenix supports multiple LLM providers. Configure the model per-agent, or use <code className="text-cyan-300">llm_route</code> to dynamically route based on task complexity.</P>

                  <H3>Supported Models</H3>
                  <div className="space-y-1 my-3">
                    {[
                      { provider: 'Anthropic', models: 'claude-sonnet-4-5-20250929, claude-haiku-3-5, claude-opus-4' },
                      { provider: 'OpenAI', models: 'gpt-4o, gpt-4o-mini, gpt-4-turbo, o1, o1-mini' },
                      { provider: 'Google', models: 'gemini-2.0-flash, gemini-1.5-pro, gemini-1.5-flash' },
                    ].map((p) => (
                      <div key={p.provider} className="flex items-start gap-3 text-sm py-2 border-b border-slate-700/30 last:border-0">
                        <span className="text-white font-medium w-20 shrink-0">{p.provider}</span>
                        <code className="text-xs text-cyan-300">{p.models}</code>
                      </div>
                    ))}
                  </div>

                  <H3>Configuration Options</H3>
                  <CodeBlock language="json" code={`{
  "model_config": {
    "model": "claude-sonnet-4-5-20250929",
    "temperature": 0.3,       // 0.0 = deterministic, 1.0 = creative
    "max_tokens": 4096,       // max response length
    "top_p": 0.95,            // nucleus sampling
    "tools": ["web_search", "calculator"],
    "max_iterations": 25,     // ReAct loop limit
    "timeout_seconds": 120    // per-execution timeout
  }
}`} />

                  <H3>LLM Routing</H3>
                  <P>The <code className="text-cyan-300">llm_route</code> tool automatically selects the best model based on task complexity -- simpler tasks use Haiku for cost efficiency, complex tasks use Sonnet or Opus.</P>
                </DocSection>
              )}

              {/* ── cURL Import ── */}
              {sectionVisible('curl-import') && (
                <DocSection id="curl-import" icon={Terminal} title="cURL Import" isOpen={openSections.has('curl-import')} onToggle={() => toggleSection('curl-import')}>
                  <P>The AI Builder supports importing cURL commands to pre-configure <code className="text-cyan-300">http_client</code> tool calls. Paste a cURL command and the builder extracts the method, URL, headers, body, and query parameters.</P>

                  <H3>How to Use</H3>
                  <div className="bg-slate-900/60 border border-slate-700/50 rounded-lg p-4 my-3 space-y-2 text-sm text-slate-300">
                    {['Open the AI Builder and select "cURL Import" from the toolbar', 'Paste your cURL command into the input field', 'The builder parses: method (-X), URL, headers (-H), body (-d/--data), and query params', 'Review the extracted configuration and adjust as needed', 'The extracted config is applied to an http_client tool node'].map((step, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <span className="text-cyan-400 font-bold w-4">{i + 1}.</span>
                        {step}
                      </div>
                    ))}
                  </div>

                  <H3>Supported Flags</H3>
                  <div className="space-y-1 my-3">
                    {[
                      { flag: '-X, --request', desc: 'HTTP method (GET, POST, PUT, DELETE, PATCH)' },
                      { flag: '-H, --header', desc: 'Request headers (e.g., "Content-Type: application/json")' },
                      { flag: '-d, --data', desc: 'Request body (JSON or form data)' },
                      { flag: '--data-raw', desc: 'Raw request body (no processing)' },
                      { flag: '-u, --user', desc: 'Basic auth credentials (user:password)' },
                      { flag: '-k, --insecure', desc: 'Skip TLS verification' },
                    ].map((f) => (
                      <div key={f.flag} className="flex items-start gap-3 text-sm py-1">
                        <code className="text-cyan-300 font-mono w-32 shrink-0">{f.flag}</code>
                        <span className="text-slate-400 text-xs">{f.desc}</span>
                      </div>
                    ))}
                  </div>

                  <H3>Special Handling</H3>
                  <P><strong className="text-white">Bearer tokens:</strong> <code className="text-cyan-300">-H &quot;Authorization: Bearer xxx&quot;</code> is extracted into a separate auth configuration field so it can be rotated without editing the tool node.</P>
                  <P><strong className="text-white">JSON bodies:</strong> <code className="text-cyan-300">-d &apos;{`{"key":"val"}`}&apos;</code> with <code className="text-cyan-300">Content-Type: application/json</code> is parsed into structured fields rather than a raw string.</P>
                  <P><strong className="text-white">Query parameters:</strong> URL query strings like <code className="text-cyan-300">?page=1&amp;limit=50</code> are extracted into the params configuration.</P>

                  <H3>Example</H3>
                  <CodeBlock language="bash" code={`# Paste this into the cURL Import dialog:
curl -X POST https://api.example.com/v1/analyze \\
  -H "Authorization: Bearer sk-abc123" \\
  -H "Content-Type: application/json" \\
  -d '{"text": "Analyze this contract", "options": {"detailed": true}}'

# The builder extracts:
#   Method:  POST
#   URL:     https://api.example.com/v1/analyze
#   Auth:    Bearer sk-abc123 (stored separately)
#   Headers: Content-Type: application/json
#   Body:    {"text": "...", "options": {"detailed": true}}`} />
                </DocSection>
              )}
            </div>
          )}

          {/* ================================================================ */}
          {/* GROUP: BUILT-IN TOOLS REFERENCE                                  */}
          {/* ================================================================ */}

          {filteredGroups.some((g) => g.name === 'Built-in Tools Reference') && (
            <div className="space-y-4 mt-8">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white flex items-center gap-2">
                  <Wrench className="w-5 h-5 text-amber-400" />
                  Built-in Tools Reference
                </h2>
                <div className="flex gap-2">
                  <button onClick={() => expandAllInGroup('Built-in Tools Reference')} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">Expand All</button>
                  <span className="text-slate-700">|</span>
                  <button onClick={() => collapseAllInGroup('Built-in Tools Reference')} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">Collapse All</button>
                </div>
              </div>

              {/* ── Search & Web ── */}
              {sectionVisible('tools-search-web') && (
                <DocSection id="tools-search-web" icon={Search} title="Search & Web Tools" isOpen={openSections.has('tools-search-web')} onToggle={() => toggleSection('tools-search-web')}>
                  <div className="overflow-x-auto my-4">
                    <div className="space-y-0.5 min-w-[600px]">
                      <div className="flex items-center gap-3 py-2 border-b border-slate-600/50 text-xs font-semibold text-slate-400 uppercase tracking-wide">
                        <span className="w-52 shrink-0">Tool Name</span>
                        <span className="w-24">Category</span>
                        <span className="ml-2">Description</span>
                      </div>
                      <ToolRow name="web_search" category="Search" description="Search the web using multiple engines, returns structured results with titles, URLs, and snippets" />
                      <ToolRow name="tavily_search" category="Search" description="Multi-provider web search (Tavily, Brave, SerpAPI, Serper) with automatic fallback between providers" />
                      <ToolRow name="academic_search" category="Search" description="Search academic papers via Semantic Scholar and arXiv. Returns abstracts, citations, and DOI links" />
                      <ToolRow name="http_client" category="Search" description="Make HTTP requests (GET/POST/PUT/DELETE) with custom headers, auth, query params, and body" />
                      <ToolRow name="api_connector" category="Integration" description="Connect to external REST APIs with configurable base URLs, auth, and response mapping" />
                      <ToolRow name="news_feed" category="Search" description="Search recent news from NewsAPI and MediaStack. Filter by topic, source, language, and date range" />
                    </div>
                  </div>

                  <H3>web_search Parameters</H3>
                  <CodeBlock language="json" code={`{
  "query": "AI semiconductor market 2025",
  "num_results": 10,
  "search_type": "general"  // general | news | academic
}`} />

                  <H3>http_client Example</H3>
                  <CodeBlock language="json" code={`{
  "url": "https://api.example.com/data",
  "method": "POST",
  "headers": { "Authorization": "Bearer sk-xxx" },
  "body": { "query": "analyze this" },
  "timeout": 30
}`} />
                </DocSection>
              )}

              {/* ── Data Tools ── */}
              {sectionVisible('tools-data') && (
                <DocSection id="tools-data" icon={Database} title="Data Tools" isOpen={openSections.has('tools-data')} onToggle={() => toggleSection('tools-data')}>
                  <div className="overflow-x-auto my-4">
                    <div className="space-y-0.5 min-w-[600px]">
                      <div className="flex items-center gap-3 py-2 border-b border-slate-600/50 text-xs font-semibold text-slate-400 uppercase tracking-wide">
                        <span className="w-52 shrink-0">Tool Name</span>
                        <span className="w-24">Category</span>
                        <span className="ml-2">Description</span>
                      </div>
                      <ToolRow name="database_query" category="Data" description="Execute read-only SQL queries against connected PostgreSQL databases" />
                      <ToolRow name="database_writer" category="Data" description="Execute write SQL operations (INSERT/UPDATE/DELETE). Often gated by HITL" />
                      <ToolRow name="csv_analyzer" category="Data" description="Parse, filter, aggregate, and analyze CSV data with column stats and pivots" />
                      <ToolRow name="json_transformer" category="Data" description="Transform, filter, and restructure JSON data using JMESPath expressions" />
                      <ToolRow name="data_merger" category="Data" description="Merge and compare datasets from multiple sources with union, intersection, and diff" />
                      <ToolRow name="data_exporter" category="Data" description="Export data to CSV, JSON, Excel, or PDF format with configurable formatting" />
                      <ToolRow name="schema_validator" category="Data" description="Validate data against JSON Schema definitions and report violations" />
                    </div>
                  </div>

                  <H3>database_query Parameters</H3>
                  <CodeBlock language="json" code={`{
  "query": "SELECT name, revenue FROM companies WHERE sector = $1 ORDER BY revenue DESC LIMIT 10",
  "params": ["technology"],
  "database": "default",
  "timeout_seconds": 30
}`} />
                  <InfoBox variant="warning">
                    <code className="text-amber-300">database_query</code> enforces read-only mode: INSERT, UPDATE, DELETE, DROP, and TRUNCATE statements are rejected before execution. Use <code className="text-amber-300">database_writer</code> for write operations, and pair it with <code className="text-amber-300">human_approval</code> for production safety.
                  </InfoBox>

                  <H3>json_transformer Example</H3>
                  <CodeBlock language="json" code={`{
  "data": {"users": [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]},
  "expression": "users[?age > \`28\`].name",
  "output_format": "array"
}
// Result: ["Alice"]`} />

                  <H3>csv_analyzer Example</H3>
                  <CodeBlock language="json" code={`{
  "csv_content": "name,revenue,quarter\\nAcme,1200000,Q1\\nAcme,1350000,Q2",
  "operations": [
    { "type": "describe" },
    { "type": "filter", "column": "revenue", "operator": ">", "value": 1300000 },
    { "type": "aggregate", "column": "revenue", "function": "mean" }
  ]
}`} />
                </DocSection>
              )}

              {/* ── Analysis Tools ── */}
              {sectionVisible('tools-analysis') && (
                <DocSection id="tools-analysis" icon={BarChart3} title="Analysis Tools" isOpen={openSections.has('tools-analysis')} onToggle={() => toggleSection('tools-analysis')}>
                  <div className="overflow-x-auto my-4">
                    <div className="space-y-0.5 min-w-[600px]">
                      <div className="flex items-center gap-3 py-2 border-b border-slate-600/50 text-xs font-semibold text-slate-400 uppercase tracking-wide">
                        <span className="w-52 shrink-0">Tool Name</span>
                        <span className="w-24">Category</span>
                        <span className="ml-2">Description</span>
                      </div>
                      <ToolRow name="text_analyzer" category="Analysis" description="Readability scores (Flesch, Gunning-Fog), sentiment analysis, keyword and entity extraction" />
                      <ToolRow name="structured_analyzer" category="Analysis" description="Analyze documents with custom extraction prompts and structured output schemas" />
                      <ToolRow name="regex_extractor" category="Analysis" description="Extract patterns from text using regular expressions with named groups" />
                      <ToolRow name="risk_analyzer" category="Finance" description="Scenario analysis, Monte Carlo simulations, risk scoring matrices, and VaR calculations" />
                      <ToolRow name="time_series_analyzer" category="Analysis" description="Decomposition (trend, seasonal, residual), forecasting (ARIMA), and anomaly detection (z-score)" />
                      <ToolRow name="presentation_analyzer" category="Analysis" description="Analyze slide decks (PPTX) for content structure, key messages, and visual quality" />
                    </div>
                  </div>

                  <H3>text_analyzer Parameters</H3>
                  <CodeBlock language="json" code={`{
  "text": "The quarterly earnings exceeded analyst expectations...",
  "analyses": ["readability", "sentiment", "keywords", "entities", "summary"],
  "language": "en"
}
// Result includes:
// readability: { flesch_reading_ease: 45.2, gunning_fog: 14.1, grade_level: "college" }
// sentiment: { score: 0.72, label: "positive", confidence: 0.89 }
// keywords: ["quarterly earnings", "analyst expectations", ...]
// entities: [{ text: "Q4", type: "DATE" }, ...]`} />

                  <H3>risk_analyzer Parameters</H3>
                  <CodeBlock language="json" code={`{
  "scenario": "Market downturn impact on portfolio",
  "variables": [
    { "name": "revenue_decline", "distribution": "normal", "mean": -0.15, "std": 0.05 },
    { "name": "cost_increase", "distribution": "uniform", "min": 0.02, "max": 0.08 }
  ],
  "simulations": 10000,
  "confidence_levels": [0.95, 0.99],
  "output": ["var", "cvar", "histogram", "sensitivity"]
}`} />

                  <H3>time_series_analyzer Example</H3>
                  <CodeBlock language="json" code={`{
  "data": [100, 105, 98, 110, 115, 108, 120, 125, 118, 130],
  "frequency": "monthly",
  "operations": ["decompose", "forecast", "anomaly_detect"],
  "forecast_periods": 6,
  "anomaly_method": "zscore",
  "anomaly_threshold": 2.0
}`} />
                </DocSection>
              )}

              {/* ── Compute Tools ── */}
              {sectionVisible('tools-compute') && (
                <DocSection id="tools-compute" icon={Cpu} title="Compute Tools" isOpen={openSections.has('tools-compute')} onToggle={() => toggleSection('tools-compute')}>
                  <div className="overflow-x-auto my-4">
                    <div className="space-y-0.5 min-w-[600px]">
                      <div className="flex items-center gap-3 py-2 border-b border-slate-600/50 text-xs font-semibold text-slate-400 uppercase tracking-wide">
                        <span className="w-52 shrink-0">Tool Name</span>
                        <span className="w-24">Category</span>
                        <span className="ml-2">Description</span>
                      </div>
                      <ToolRow name="calculator" category="Compute" description="Mathematical calculations and safe expression evaluation (no eval())" />
                      <ToolRow name="financial_calculator" category="Finance" description="NPV, IRR, amortization schedules, compound interest, LCOE calculations" />
                      <ToolRow name="unit_converter" category="Compute" description="Convert between units (length, weight, temperature, pressure, energy, etc.)" />
                      <ToolRow name="date_calculator" category="Compute" description="Date arithmetic, business day calculations, timezone conversion, duration parsing" />
                      <ToolRow name="code_executor" category="Compute" description="Execute Python code in a sandboxed environment with numpy, pandas, and matplotlib" />
                      <ToolRow name="current_time" category="Compute" description="Get current date/time in any timezone with formatting options" />
                    </div>
                  </div>

                  <H3>code_executor Sandbox</H3>
                  <P>The code_executor runs Python in an isolated sandbox. Available packages: numpy, pandas, matplotlib, scipy, scikit-learn, requests, json, csv, re, math. Network access is disabled. Execution timeout: 30 seconds. Memory limit: 256MB.</P>

                  <H4>Example Usage</H4>
                  <CodeBlock language="json" code={`{
  "code": "import pandas as pd\\nimport json\\n\\ndata = json.loads(input_data)\\ndf = pd.DataFrame(data['records'])\\nresult = df.groupby('category')['amount'].agg(['sum', 'mean', 'count'])\\nprint(result.to_json())",
  "input_data": "{\\"records\\": [{\\"category\\": \\"A\\", \\"amount\\": 100}, {\\"category\\": \\"B\\", \\"amount\\": 200}]}",
  "timeout_seconds": 30
}`} />
                  <InfoBox variant="info">
                    The sandbox captures stdout as the tool result. Write your output with <code className="text-cyan-300">print()</code>. The <code className="text-cyan-300">input_data</code> variable is available as a string in the sandbox scope. Matplotlib figures are captured as base64-encoded PNG and returned as part of the result.
                  </InfoBox>

                  <H3>calculator Parameters</H3>
                  <CodeBlock language="json" code={`{
  "expression": "(1500 * 12 * 0.08) / (1 - (1 + 0.08)^(-30))",
  "precision": 2
}
// Result: 1337.16 (monthly payment for a $1500/mo loan at 8% over 30 years)`} />

                  <H3>financial_calculator Modes</H3>
                  <div className="space-y-1 my-3">
                    {[
                      { mode: 'npv', desc: 'Net Present Value given cash flows and discount rate' },
                      { mode: 'irr', desc: 'Internal Rate of Return from cash flow series' },
                      { mode: 'amortization', desc: 'Full amortization schedule with principal/interest breakdown' },
                      { mode: 'compound_interest', desc: 'Future value with compounding frequency options' },
                      { mode: 'lcoe', desc: 'Levelized Cost of Energy for renewable projects' },
                      { mode: 'dcf', desc: 'Discounted Cash Flow with terminal value' },
                    ].map((m) => (
                      <div key={m.mode} className="flex items-start gap-3 text-sm py-1 border-b border-slate-700/30 last:border-0">
                        <code className="text-cyan-300 font-mono w-36 shrink-0">{m.mode}</code>
                        <span className="text-slate-400 text-xs">{m.desc}</span>
                      </div>
                    ))}
                  </div>
                </DocSection>
              )}

              {/* ── I/O & Media ── */}
              {sectionVisible('tools-io-media') && (
                <DocSection id="tools-io-media" icon={FileText} title="I/O & Media Tools" isOpen={openSections.has('tools-io-media')} onToggle={() => toggleSection('tools-io-media')}>
                  <div className="overflow-x-auto my-4">
                    <div className="space-y-0.5 min-w-[600px]">
                      <div className="flex items-center gap-3 py-2 border-b border-slate-600/50 text-xs font-semibold text-slate-400 uppercase tracking-wide">
                        <span className="w-52 shrink-0">Tool Name</span>
                        <span className="w-24">Category</span>
                        <span className="ml-2">Description</span>
                      </div>
                      <ToolRow name="file_reader" category="I/O" description="Read text, PDF, DOCX, XLSX, PPTX, CSV, and image files. Auto-detects format" />
                      <ToolRow name="file_system" category="I/O" description="File system operations: list, create, move, delete, stat, and tree view" />
                      <ToolRow name="document_extractor" category="I/O" description="AI-powered structured data extraction from documents using vision and NLP" />
                      <ToolRow name="spreadsheet_analyzer" category="I/O" description="Analyze Excel/Google Sheets with formula evaluation, pivots, and charts" />
                      <ToolRow name="cloud_storage" category="I/O" description="Upload/download from S3, GCS, and Azure Blob with presigned URL generation" />
                      <ToolRow name="email_sender" category="Communication" description="Send emails via configured SMTP or provider with HTML templates" />
                      <ToolRow name="image_analyzer" category="Media" description="Analyze images using vision models, OCR, object detection, and classification" />
                      <ToolRow name="speech_to_text" category="Media" description="Transcribe audio files (WAV, MP3, M4A) to text using Whisper" />
                      <ToolRow name="text_to_speech" category="Media" description="Convert text to audio using TTS models with voice selection" />
                    </div>
                  </div>

                  <H3>file_reader Supported Formats</H3>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 my-3">
                    {['PDF', 'DOCX', 'XLSX', 'PPTX', 'CSV', 'TXT', 'JSON', 'XML', 'HTML', 'MD', 'PNG', 'JPG', 'WEBP', 'GIF'].map((fmt) => (
                      <div key={fmt} className="text-center py-1.5 bg-slate-900/40 border border-slate-700/40 rounded text-xs text-cyan-300 font-mono">{fmt}</div>
                    ))}
                  </div>

                  <H3>document_extractor Example</H3>
                  <CodeBlock language="json" code={`{
  "file_path": "/uploads/contract.pdf",
  "extraction_prompt": "Extract: parties, effective date, term, total value, payment schedule, termination clauses",
  "output_schema": {
    "parties": ["string"],
    "effective_date": "date",
    "term_months": "integer",
    "total_value_usd": "number",
    "payment_schedule": "string",
    "termination_clauses": ["string"]
  }
}`} />

                  <H3>cloud_storage Operations</H3>
                  <CodeBlock language="json" code={`// Upload to S3
{
  "operation": "upload",
  "provider": "s3",
  "bucket": "my-bucket",
  "key": "reports/2026/q1.pdf",
  "file_path": "/data/exports/q1-report.pdf"
}

// Generate presigned URL
{
  "operation": "presign",
  "provider": "s3",
  "bucket": "my-bucket",
  "key": "reports/2026/q1.pdf",
  "expires_in": 3600
}`} />
                </DocSection>
              )}

              {/* ── Memory & AI ── */}
              {sectionVisible('tools-memory-ai') && (
                <DocSection id="tools-memory-ai" icon={Brain} title="Memory & AI Tools" isOpen={openSections.has('tools-memory-ai')} onToggle={() => toggleSection('tools-memory-ai')}>
                  <div className="overflow-x-auto my-4">
                    <div className="space-y-0.5 min-w-[600px]">
                      <div className="flex items-center gap-3 py-2 border-b border-slate-600/50 text-xs font-semibold text-slate-400 uppercase tracking-wide">
                        <span className="w-52 shrink-0">Tool Name</span>
                        <span className="w-24">Category</span>
                        <span className="ml-2">Description</span>
                      </div>
                      <ToolRow name="memory_store" category="Memory" description="Store key-value pairs with optional MemPalace hierarchy (wing/hall/room)" />
                      <ToolRow name="memory_recall" category="Memory" description="Retrieve memories by key, keyword search, or semantic similarity" />
                      <ToolRow name="memory_forget" category="Memory" description="Delete memories with cascading scope (room, hall, or wing)" />
                      <ToolRow name="knowledge_search" category="Memory" description="Search knowledge graphs and vector stores with hybrid ranking" />
                      <ToolRow name="knowledge_store" category="Memory" description="Store facts and relationships into the knowledge graph" />
                      <ToolRow name="vector_search" category="Memory" description="Dense vector similarity search using pgvector" />
                      <ToolRow name="llm_call" category="AI" description="Direct LLM call with custom prompt, temperature, and model override" />
                      <ToolRow name="llm_route" category="AI" description="Route to optimal LLM based on task complexity (Haiku/Sonnet/Opus)" />
                      <ToolRow name="agent_step" category="AI" description="Invoke another agent as a sub-step within a pipeline" />
                    </div>
                  </div>

                  <H3>memory_store Parameters</H3>
                  <CodeBlock language="json" code={`{
  "key": "client_preferences",
  "value": "Prefers executive summaries, conservative risk tolerance, quarterly cadence",
  "wing": "acme-corp",         // MemPalace: top-level grouping
  "hall_type": "factual",      // factual | procedural | episodic | emotional | decision
  "importance": 8,             // 1-10, affects L1 context inclusion
  "ttl_days": null             // null = permanent, or number of days
}`} />

                  <H3>memory_recall Parameters</H3>
                  <CodeBlock language="json" code={`{
  "query": "client preferences for reports",
  "mode": "semantic",          // exact | search | semantic
  "wing": "acme-corp",        // optional: scope to a wing
  "top_k": 5,
  "include_context": true      // prepend L0 + L1 context
}`} />

                  <H3>llm_call Parameters</H3>
                  <CodeBlock language="json" code={`{
  "prompt": "Summarize the following text in 3 bullet points:\\n{{upstream_node.__all__}}",
  "model": "claude-haiku-3-5",    // override the agent's default model
  "temperature": 0.1,
  "max_tokens": 500,
  "system_prompt": "You are a concise summarizer."
}`} />
                  <P>The <code className="text-cyan-300">llm_call</code> tool is essential for pipeline nodes that need LLM processing. It supports all the same model configuration options as the top-level agent config.</P>
                </DocSection>
              )}

              {/* ── Integration & Finance ── */}
              {sectionVisible('tools-integration') && (
                <DocSection id="tools-integration" icon={Plug} title="Integration & Finance Tools" isOpen={openSections.has('tools-integration')} onToggle={() => toggleSection('tools-integration')}>
                  <div className="overflow-x-auto my-4">
                    <div className="space-y-0.5 min-w-[600px]">
                      <div className="flex items-center gap-3 py-2 border-b border-slate-600/50 text-xs font-semibold text-slate-400 uppercase tracking-wide">
                        <span className="w-52 shrink-0">Tool Name</span>
                        <span className="w-24">Category</span>
                        <span className="ml-2">Description</span>
                      </div>
                      <ToolRow name="github_tool" category="Integration" description="GitHub API: repos, issues, PRs, commits, code search, and release management" />
                      <ToolRow name="integration_hub" category="Integration" description="Connect to Slack, Jira, Confluence, Linear, Notion, and more" />
                      <ToolRow name="event_buffer" category="Integration" description="Read buffered platform events with filtering by type and time window" />
                      <ToolRow name="redis_stream_consumer" category="Integration" description="Consume from Redis Streams with consumer groups and acknowledgment" />
                      <ToolRow name="redis_stream_publisher" category="Integration" description="Publish messages to Redis Streams for inter-service communication" />
                      <ToolRow name="kafka_consumer" category="Integration" description="Consume from Kafka topics with offset management and deserialization" />
                      <ToolRow name="market_data" category="Finance" description="Real-time and historical market data (stocks, crypto, forex)" />
                      <ToolRow name="yahoo_finance" category="Finance" description="Stock prices, financials, earnings, dividends, and FRED economic indicators" />
                      <ToolRow name="pipeline_tool" category="Pipeline" description="Execute a sub-pipeline as a tool within an agent" />
                      <ToolRow name="sub_pipeline" category="Pipeline" description="Invoke a named pipeline with parameter passing" />
                      <ToolRow name="pii_redactor" category="Security" description="Detect and redact PII (names, SSNs, emails, phones, custom patterns)" />
                      <ToolRow name="human_approval" category="Security" description="Pause execution and wait for human approval via the review queue" />
                    </div>
                  </div>
                </DocSection>
              )}

              {/* ── Specialized Tools ── */}
              {sectionVisible('tools-specialized') && (
                <DocSection id="tools-specialized" icon={Sparkles} title="Specialized Tools" isOpen={openSections.has('tools-specialized')} onToggle={() => toggleSection('tools-specialized')}>
                  <P>Additional tools covering visualization, geolocation, government data, energy markets, ML serving, browser automation, and more.</P>
                  <div className="overflow-x-auto my-4">
                    <div className="space-y-0.5 min-w-[600px]">
                      <div className="flex items-center gap-3 py-2 border-b border-slate-600/50 text-xs font-semibold text-slate-400 uppercase tracking-wide">
                        <span className="w-52 shrink-0">Tool Name</span>
                        <span className="w-24">Category</span>
                        <span className="ml-2">Description</span>
                      </div>
                      <ToolRow name="moderation" category="Moderation" description="Agent-callable content moderation (same engine as the gate)" />
                      <ToolRow name="browser_automation" category="Integration" description="Headless browser automation for scraping, form filling, screenshots" />
                      <ToolRow name="translation" category="AI" description="Translate text between 100+ languages with auto-detection" />
                      <ToolRow name="plotly_chart" category="Visualization" description="Generate interactive Plotly charts (bar, line, scatter, heatmap)" />
                      <ToolRow name="mermaid_diagram" category="Visualization" description="Generate Mermaid diagrams (flowcharts, sequence, entity-relationship)" />
                      <ToolRow name="semantic_diff" category="Analysis" description="Compare two texts semantically, highlighting meaning changes" />
                      <ToolRow name="address_normalize" category="Utility" description="Normalize and validate postal addresses across formats" />
                      <ToolRow name="geocoding" category="Geo" description="Forward and reverse geocoding (address to lat/lng and back)" />
                      <ToolRow name="weather" category="Geo" description="Current weather and forecasts by location" />
                      <ToolRow name="crypto_market" category="Finance" description="Real-time cryptocurrency prices, market caps, and volume" />
                      <ToolRow name="fred_economic" category="Finance" description="Federal Reserve Economic Data (GDP, CPI, unemployment, rates)" />
                      <ToolRow name="ecb_rates" category="Energy" description="European Central Bank exchange rates" />
                      <ToolRow name="entso_e" category="Energy" description="European electricity market data (ENTSO-E transparency)" />
                      <ToolRow name="gov_data_us" category="Government" description="US government open data (data.gov)" />
                      <ToolRow name="world_bank" category="Government" description="World Bank economic indicators and development data" />
                      <ToolRow name="ember_tool" category="Energy" description="Global electricity generation and emissions data (Ember)" />
                      <ToolRow name="patents_trademarks" category="Government" description="Patent and trademark search (USPTO/EPO)" />
                      <ToolRow name="cloud_cost" category="Integration" description="Cloud cost analysis across AWS, GCP, Azure" />
                      <ToolRow name="twilio_sms" category="Communication" description="Send SMS messages via Twilio" />
                      <ToolRow name="ml_model_tool" category="ML" description="Invoke deployed ML models for inference" />
                      <ToolRow name="code_asset" category="Compute" description="Execute uploaded code repositories (Python/Node/Go/Rust/Ruby/Java)" />
                      <ToolRow name="sandboxed_job" category="Compute" description="Run arbitrary container images in a sandboxed K8s Job" />
                      <ToolRow name="graph_explorer" category="Data" description="Explore and query the Neo4j knowledge graph directly" />
                      <ToolRow name="schema_portfolio" category="Data" description="Manage database schema portfolios and mappings" />
                      <ToolRow name="zapier_pass_through" category="Integration" description="Trigger Zapier webhooks for 5000+ app integrations" />
                    </div>
                  </div>
                </DocSection>
              )}
            </div>
          )}

          {/* ================================================================ */}
          {/* GROUP: ENTERPRISE FEATURES                                       */}
          {/* ================================================================ */}

          {filteredGroups.some((g) => g.name === 'Enterprise Features') && (
            <div className="space-y-4 mt-8">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white flex items-center gap-2">
                  <Shield className="w-5 h-5 text-red-400" />
                  Enterprise Features
                </h2>
                <div className="flex gap-2">
                  <button onClick={() => expandAllInGroup('Enterprise Features')} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">Expand All</button>
                  <span className="text-slate-700">|</span>
                  <button onClick={() => collapseAllInGroup('Enterprise Features')} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">Collapse All</button>
                </div>
              </div>

              {/* ── Content Moderation ── */}
              {sectionVisible('moderation-gate') && (
                <DocSection id="moderation-gate" icon={Shield} title="Content Moderation" isOpen={openSections.has('moderation-gate')} onToggle={() => toggleSection('moderation-gate')}>
                  <P>The moderation system provides non-bypassable content filtering for agent inputs and outputs. It consists of two layers: the <strong className="text-white">Moderation Gate</strong> (automatic, wired into the executor) and the <strong className="text-white">moderation_vet tool</strong> (opt-in, agent-callable).</P>

                  <H3>Architecture</H3>
                  <CodeBlock language="text" code={`User Input ─── pre-LLM gate ──> LLM ─── post-LLM gate ──> Response
                  │                          │
                  ▼                          ▼
          ModerationPolicy           ModerationPolicy
          (tenant-scoped)            (tenant-scoped)
                  │                          │
                  ├── ALLOW → continue       ├── ALLOW → return
                  ├── BLOCK → abort exec     ├── BLOCK → abort exec
                  ├── REDACT → mask content  ├── REDACT → mask output
                  └── FLAG → log + continue  └── FLAG → log + return`} />

                  <H3>Policy Configuration</H3>
                  <P>Policies are per-tenant. Only tenant admins can create or modify them. When multiple active policies exist, the most recently updated one is used.</P>
                  <CodeBlock language="bash" code={`# Create a moderation policy
curl -X POST http://localhost:8000/api/moderation/policies \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "Production Policy",
    "description": "Block harmful content, redact PII",
    "is_active": true,
    "pre_llm": true,
    "post_llm": true,
    "on_tool_output": false,
    "provider": "openai",
    "provider_model": "omni-moderation-latest",
    "default_threshold": 0.5,
    "thresholds": {
      "harassment": 0.3,
      "self-harm": 0.1,
      "violence": 0.4,
      "sexual": 0.3
    },
    "default_action": "block",
    "category_actions": {
      "harassment": "block",
      "self-harm": "block",
      "violence": "flag",
      "sexual": "redact"
    },
    "custom_patterns": [
      { "pattern": "\\\\b(SSN|social security)\\\\b", "action": "redact", "label": "PII-SSN" },
      { "pattern": "\\\\b\\\\d{3}-\\\\d{2}-\\\\d{4}\\\\b", "action": "redact", "label": "SSN-Pattern" }
    ],
    "redaction_mask": "█████",
    "fail_closed": false
  }'`} />

                  <H3>Actions</H3>
                  <div className="grid grid-cols-2 gap-3 my-3">
                    {[
                      { action: 'ALLOW', desc: 'Content passes. No modification.', color: 'emerald' },
                      { action: 'BLOCK', desc: 'Execution is aborted. Failure code: MODERATION_BLOCKED.', color: 'red' },
                      { action: 'REDACT', desc: 'Flagged spans are replaced with the redaction mask. Execution continues.', color: 'amber' },
                      { action: 'FLAG', desc: 'Content passes but a ModerationEvent is logged for review.', color: 'purple' },
                    ].map((a) => (
                      <div key={a.action} className="p-3 bg-slate-900/40 border border-slate-700/40 rounded-lg">
                        <Badge color={a.color}>{a.action}</Badge>
                        <p className="text-xs text-slate-400 mt-1">{a.desc}</p>
                      </div>
                    ))}
                  </div>

                  <H3>Vet Playground</H3>
                  <P>The <code className="text-cyan-300">/api/moderation/vet</code> endpoint lets you preview what the moderation gate would do without running an agent. Use it from the UI moderation playground or via API.</P>
                  <CodeBlock language="bash" code={`# Preview moderation for a piece of content
curl -X POST http://localhost:8000/api/moderation/vet \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"content": "This is the text to analyze for policy violations."}'

# Response:
# {
#   "data": {
#     "decision": "allow",
#     "categories": {"harassment": 0.01, "violence": 0.02, ...},
#     "custom_matches": [],
#     "applied_action": "allow"
#   }
# }`} />

                  <H3>Event History</H3>
                  <CodeBlock language="bash" code={`# List moderation events (filter by outcome, date, source)
curl "http://localhost:8000/api/moderation/events?outcome=blocked&since=2026-04-01" \\
  -H "Authorization: Bearer $TOKEN"`} />

                  <H3>Failure Code Integration</H3>
                  <P>When moderation blocks an execution, the execution record gets <code className="text-cyan-300">failure_code: &quot;MODERATION_BLOCKED&quot;</code>. This appears in the <code className="text-cyan-300">/alerts</code> page and Grafana failure breakdown panel.</P>

                  <H3>Prometheus Metric</H3>
                  <P>Moderation events are tracked in Prometheus: <code className="text-cyan-300">abenix_moderation_events_total</code> with labels for <code className="text-cyan-300">outcome</code> (allow, block, redact, flag) and <code className="text-cyan-300">source</code> (pre_llm, post_llm, vet).</P>

                  <H3>Fail-Open vs Fail-Closed</H3>
                  <InfoBox variant="warning">
                    By default, the gate <strong>fails open</strong>: if the moderation provider returns an error, content is allowed through (and an error event is logged). For strict compliance, set <code className="text-amber-300">fail_closed: true</code> on the policy -- then provider errors result in BLOCK.
                  </InfoBox>

                  <H3>Custom Pattern Examples</H3>
                  <P>Custom patterns use regex and are evaluated before the LLM-based classifier. They are fast (sub-millisecond) and do not require API calls.</P>
                  <CodeBlock language="json" code={`{
  "custom_patterns": [
    { "pattern": "\\\\b\\\\d{3}-\\\\d{2}-\\\\d{4}\\\\b", "action": "redact", "label": "SSN" },
    { "pattern": "\\\\b[A-Z]{2}\\\\d{6,8}\\\\b", "action": "redact", "label": "passport-number" },
    { "pattern": "\\\\b4[0-9]{12}(?:[0-9]{3})?\\\\b", "action": "redact", "label": "visa-card" },
    { "pattern": "(?i)\\\\b(confidential|internal only|do not distribute)\\\\b", "action": "flag", "label": "classification-marker" },
    { "pattern": "(?i)\\\\b(ignore previous instructions|system prompt)\\\\b", "action": "block", "label": "prompt-injection" }
  ]
}`} />

                  <H3>Policy CRUD Example</H3>
                  <CodeBlock language="bash" code={`# List policies
curl http://localhost:8000/api/moderation/policies \\
  -H "Authorization: Bearer $TOKEN"

# Update a policy (PATCH -- partial update)
curl -X PATCH http://localhost:8000/api/moderation/policies/{policy_id} \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"default_threshold": 0.4, "post_llm": false}'

# Delete a policy
curl -X DELETE http://localhost:8000/api/moderation/policies/{policy_id} \\
  -H "Authorization: Bearer $TOKEN"`} />

                  <H3>Moderation Categories (OpenAI)</H3>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 my-3">
                    {['harassment', 'harassment/threatening', 'hate', 'hate/threatening', 'illicit', 'illicit/violent', 'self-harm', 'self-harm/intent', 'self-harm/instructions', 'sexual', 'sexual/minors', 'violence', 'violence/graphic'].map((cat) => (
                      <code key={cat} className="text-xs bg-slate-800/60 border border-slate-700/40 rounded px-2 py-1 text-slate-300">{cat}</code>
                    ))}
                  </div>
                  <P>Each category returns a score from 0.0 to 1.0. When a score exceeds the configured threshold for that category, the corresponding action (block, redact, flag) is applied.</P>
                </DocSection>
              )}

              {/* ── Signed Webhooks ── */}
              {sectionVisible('signed-webhooks') && (
                <DocSection id="signed-webhooks" icon={Link} title="Signed Webhooks" isOpen={openSections.has('signed-webhooks')} onToggle={() => toggleSection('signed-webhooks')}>
                  <P>Webhooks deliver real-time notifications to your endpoints. Each delivery is signed with HMAC-SHA256 so you can verify authenticity.</P>

                  <H3>Creating a Webhook</H3>
                  <CodeBlock language="bash" code={`curl -X POST http://localhost:8000/api/webhooks \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "url": "https://your-app.com/webhook",
    "events": ["execution.completed", "execution.failed", "agent.created"],
    "secret": "whsec_your_secret_key_here"
  }'`} />

                  <H3>Verifying Signatures</H3>
                  <P>Each webhook delivery includes a <code className="text-cyan-300">X-Abenix-Signature</code> header containing the HMAC-SHA256 signature of the payload body.</P>
                  <CodeBlock language="python" code={`import hmac, hashlib

def verify_webhook(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)`} />

                  <H3>Delivery & Retry</H3>
                  <P>Failed deliveries (non-2xx status or timeout) are retried with exponential backoff: 1 min, 5 min, 30 min, 2 hours. After 4 failed attempts, the delivery is marked as permanently failed.</P>
                  <CodeBlock language="bash" code={`# View delivery history for a webhook
curl http://localhost:8000/api/webhooks/{webhook_id}/deliveries \\
  -H "Authorization: Bearer $TOKEN"`} />
                </DocSection>
              )}

              {/* ── RBAC & Sharing ── */}
              {sectionVisible('rbac-sharing') && (
                <DocSection id="rbac-sharing" icon={Users} title="RBAC & Sharing" isOpen={openSections.has('rbac-sharing')} onToggle={() => toggleSection('rbac-sharing')}>
                  <P>Role-based access control with tenant isolation. Every resource (agent, pipeline, knowledge base, etc.) belongs to a tenant. Sharing is handled through a polymorphic <code className="text-cyan-300">ResourceShare</code> model.</P>

                  <H3>Roles</H3>
                  <div className="space-y-2 my-3">
                    {[
                      { role: 'Admin', desc: 'Full access: manage team, settings, API keys, billing, moderation policies. Can CRUD all resources.', color: 'red' },
                      { role: 'Member', desc: 'Create and execute agents, pipelines, knowledge bases. View own executions. Cannot manage team or tenant settings.', color: 'cyan' },
                      { role: 'Viewer', desc: 'Read-only access to shared resources. Can view agents, executions, and knowledge bases shared with them.', color: 'slate' },
                    ].map((r) => (
                      <div key={r.role} className="flex items-start gap-3 p-3 bg-slate-900/40 border border-slate-700/40 rounded-lg">
                        <Badge color={r.color}>{r.role}</Badge>
                        <span className="text-xs text-slate-400">{r.desc}</span>
                      </div>
                    ))}
                  </div>

                  <H3>Resource Sharing</H3>
                  <CodeBlock language="bash" code={`# Share an agent with another user
curl -X POST http://localhost:8000/api/agent-sharing \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "agent_id": "agent_123",
    "user_id": "user_456",
    "permission": "execute"
  }'

# Publish to marketplace
curl -X POST http://localhost:8000/api/agent-sharing \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "agent_id": "agent_123",
    "share_type": "marketplace",
    "visibility": "public"
  }'`} />

                  <H3>Sidebar Permission Groups</H3>
                  <P>The UI sidebar shows 6 navigation groups, each gated by the user&apos;s permissions from <code className="text-cyan-300">/api/me/permissions</code>. Admins see all groups, members see a subset, viewers see only shared resources.</P>
                </DocSection>
              )}

              {/* ── Cost Guardrails ── */}
              {sectionVisible('cost-guardrails') && (
                <DocSection id="cost-guardrails" icon={BarChart3} title="Cost Guardrails" isOpen={openSections.has('cost-guardrails')} onToggle={() => toggleSection('cost-guardrails')}>
                  <P>Set spending limits at the tenant, agent, or execution level. When a limit is reached, the execution is automatically cancelled and a notification is sent.</P>

                  <H3>Configuration</H3>
                  <CodeBlock language="bash" code={`# Set tenant-level cost limits
curl -X PUT http://localhost:8000/api/settings/tenant \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "cost_limits": {
      "monthly_budget_usd": 500.00,
      "per_execution_max_usd": 5.00,
      "per_agent_monthly_max_usd": 100.00,
      "alert_threshold_percent": 80,
      "webhook_url": "https://your-app.com/budget-alert"
    }
  }'`} />

                  <H3>How It Works</H3>
                  <P>The agent runtime tracks token usage and applies model-specific pricing (with a fallback for unknown models). When cumulative cost exceeds the configured limit, the execution is cancelled with failure code <code className="text-cyan-300">BUDGET_EXCEEDED</code>. If alert_threshold_percent is set, a webhook fires when spending reaches that percentage of the budget.</P>

                  <H3>Pricing Model</H3>
                  <div className="space-y-1 my-3 text-xs">
                    {[
                      { model: 'claude-sonnet-4-5-20250929', input: '$3.00', output: '$15.00' },
                      { model: 'claude-haiku-3-5', input: '$0.25', output: '$1.25' },
                      { model: 'gpt-4o', input: '$2.50', output: '$10.00' },
                      { model: 'gpt-4o-mini', input: '$0.15', output: '$0.60' },
                    ].map((m) => (
                      <div key={m.model} className="flex items-center gap-3 text-sm py-1 border-b border-slate-700/30 last:border-0">
                        <code className="text-cyan-300 font-mono w-60 shrink-0">{m.model}</code>
                        <span className="text-slate-400">Input: {m.input}/1M</span>
                        <span className="text-slate-400">Output: {m.output}/1M</span>
                      </div>
                    ))}
                  </div>
                </DocSection>
              )}

              {/* ── Drift Detection ── */}
              {sectionVisible('drift-detection') && (
                <DocSection id="drift-detection" icon={TrendingUp} title="Drift Detection" isOpen={openSections.has('drift-detection')} onToggle={() => toggleSection('drift-detection')}>
                  <P>Monitor agent behavior over time to detect changes in output quality, tool usage patterns, cost trends, and response distributions.</P>

                  <H3>What Is Tracked</H3>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 my-3">
                    {[
                      { name: 'Response Quality', desc: 'Track confidence scores and user feedback over time to detect degradation' },
                      { name: 'Tool Usage Patterns', desc: 'Monitor which tools agents call and how frequently -- detect unexpected changes' },
                      { name: 'Cost Trends', desc: 'Per-agent cost moving averages with anomaly detection for spending spikes' },
                      { name: 'Error Rate', desc: 'Track failure rates by failure_code to detect emerging issues' },
                    ].map((d) => (
                      <div key={d.name} className="p-3 bg-slate-900/40 border border-slate-700/40 rounded-lg">
                        <span className="text-sm font-medium text-white">{d.name}</span>
                        <p className="text-xs text-slate-400 mt-1">{d.desc}</p>
                      </div>
                    ))}
                  </div>

                  <H3>Viewing Drift Data</H3>
                  <P>Drift data is visible in the Grafana dashboards and the <code className="text-cyan-300">/analytics</code> API endpoints. The <code className="text-cyan-300">/alerts</code> page groups failures by <code className="text-cyan-300">failure_code</code> to show trending issues.</P>
                </DocSection>
              )}

              {/* ── Confidence Scoring ── */}
              {sectionVisible('confidence-scoring') && (
                <DocSection id="confidence-scoring" icon={Gauge} title="Confidence Scoring" isOpen={openSections.has('confidence-scoring')} onToggle={() => toggleSection('confidence-scoring')}>
                  <P>Each agent response includes a confidence score (0.0 to 1.0) computed from the model&apos;s token probabilities and the number of tool iterations taken.</P>

                  <H3>How Confidence Is Computed</H3>
                  <div className="bg-slate-900/60 border border-slate-700/50 rounded-lg p-4 my-3 space-y-2 text-sm text-slate-300">
                    <div className="flex items-center gap-2"><span className="text-cyan-400 font-bold">1.</span>Base score from model log-probabilities</div>
                    <div className="flex items-center gap-2"><span className="text-cyan-400 font-bold">2.</span>Penalty for high iteration count (many retries = lower confidence)</div>
                    <div className="flex items-center gap-2"><span className="text-cyan-400 font-bold">3.</span>Boost for tool verification (multiple sources = higher confidence)</div>
                    <div className="flex items-center gap-2"><span className="text-cyan-400 font-bold">4.</span>Final score clamped to [0.0, 1.0]</div>
                  </div>

                  <H3>Low-Confidence Routing</H3>
                  <P>Configure agents to automatically route low-confidence outputs to HITL review or escalate to a more capable model:</P>
                  <CodeBlock language="json" code={`{
  "confidence_config": {
    "threshold": 0.6,
    "low_action": "hitl_review",   // hitl_review | escalate_model | flag
    "escalate_model": "claude-opus-4"
  }
}`} />
                </DocSection>
              )}

              {/* ── Human Approval (HITL) ── */}
              {sectionVisible('human-approval') && (
                <DocSection id="human-approval" icon={Eye} title="Human Approval (HITL)" isOpen={openSections.has('human-approval')} onToggle={() => toggleSection('human-approval')}>
                  <P>Pause agent executions for human review before critical actions. Configurable per-agent, per-tool, or by cost threshold.</P>

                  <H3>Configuration</H3>
                  <CodeBlock language="bash" code={`# Enable HITL for specific tools
curl -X PUT http://localhost:8000/api/agents/{agent_id} \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "hitl_config": {
      "enabled": true,
      "require_approval_for": ["database_writer", "email_sender", "cloud_storage"],
      "cost_threshold_usd": 1.00,
      "timeout_minutes": 60
    }
  }'`} />

                  <H3>Review Workflow</H3>
                  <CodeBlock language="bash" code={`# List pending approvals
curl http://localhost:8000/api/reviews?status=pending \\
  -H "Authorization: Bearer $TOKEN"

# Approve a pending action
curl -X POST http://localhost:8000/api/reviews/{review_id}/approve \\
  -H "Authorization: Bearer $TOKEN"

# Reject with a reason
curl -X POST http://localhost:8000/api/reviews/{review_id}/reject \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"reason": "Query would delete production data"}'`} />

                  <P>When approval times out (default: 60 minutes), the execution transitions to <Badge color="amber">CANCELLED</Badge> status.</P>
                </DocSection>
              )}

              {/* ── Per-Tenant Slack URL ── */}
              {sectionVisible('per-tenant-slack') && (
                <DocSection id="per-tenant-slack" icon={MessageSquare} title="Per-Tenant Slack URL" isOpen={openSections.has('per-tenant-slack')} onToggle={() => toggleSection('per-tenant-slack')}>
                  <P>Each tenant can configure their own Slack webhook URL for alerts and notifications. This overrides the platform-level <code className="text-cyan-300">SLACK_WEBHOOK_URL</code> environment variable.</P>

                  <H3>Resolution Order</H3>
                  <div className="bg-slate-900/60 border border-slate-700/50 rounded-lg p-4 my-3 space-y-2 text-sm text-slate-300">
                    <div className="flex items-center gap-2"><span className="text-cyan-400 font-bold">1.</span>Tenant-specific Slack URL (from <code className="text-cyan-300">/api/settings/tenant</code>)</div>
                    <div className="flex items-center gap-2"><span className="text-cyan-400 font-bold">2.</span>Platform-level <code className="text-cyan-300">SLACK_WEBHOOK_URL</code> environment variable</div>
                    <div className="flex items-center gap-2"><span className="text-cyan-400 font-bold">3.</span>No notification (logged but not sent)</div>
                  </div>

                  <H3>Configuration</H3>
                  <CodeBlock language="bash" code={`# Set tenant Slack webhook
curl -X PUT http://localhost:8000/api/settings/tenant \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "tenant_slack_url": "https://hooks.slack.com/services/T00/B00/xxxx",
    "notification_channels": {
      "execution_failed": true,
      "budget_alert": true,
      "moderation_blocked": true,
      "drift_detected": true
    }
  }'`} />

                  <H3>Validation</H3>
                  <P>The URL is validated on save: it must start with <code className="text-cyan-300">https://hooks.slack.com/</code> and a test message is sent to verify connectivity. Invalid URLs are rejected with a descriptive error.</P>
                </DocSection>
              )}

              {/* ── Triggers & Scheduling ── */}
              {sectionVisible('triggers-scheduling') && (
                <DocSection id="triggers-scheduling" icon={Clock} title="Triggers & Scheduling" isOpen={openSections.has('triggers-scheduling')} onToggle={() => toggleSection('triggers-scheduling')}>
                  <P>Schedule agent executions to run on a recurring cron schedule. Triggers are managed via the API and executed by the Celery worker.</P>

                  <H3>Creating a Trigger</H3>
                  <CodeBlock language="bash" code={`# Run a market analysis agent every morning at 8 AM UTC
curl -X POST http://localhost:8000/api/triggers \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "agent_id": "agent_123",
    "name": "Daily Market Analysis",
    "cron_expression": "0 8 * * *",
    "input": {
      "message": "Generate today\\'s market analysis for the AI semiconductor sector"
    },
    "enabled": true
  }'`} />

                  <H3>Managing Triggers</H3>
                  <CodeBlock language="bash" code={`# List all triggers
curl http://localhost:8000/api/triggers \\
  -H "Authorization: Bearer $TOKEN"

# Disable a trigger
curl -X PUT http://localhost:8000/api/triggers/{trigger_id} \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"enabled": false}'

# Delete a trigger
curl -X DELETE http://localhost:8000/api/triggers/{trigger_id} \\
  -H "Authorization: Bearer $TOKEN"`} />

                  <H3>Cron Syntax</H3>
                  <div className="space-y-1 my-3">
                    {[
                      { expr: '0 8 * * *', desc: 'Every day at 8:00 AM UTC' },
                      { expr: '0 */6 * * *', desc: 'Every 6 hours' },
                      { expr: '0 9 * * 1-5', desc: 'Weekdays at 9:00 AM' },
                      { expr: '0 0 1 * *', desc: 'First day of each month at midnight' },
                      { expr: '*/15 * * * *', desc: 'Every 15 minutes' },
                    ].map((c) => (
                      <div key={c.expr} className="flex items-center gap-3 text-sm py-1 border-b border-slate-700/30 last:border-0">
                        <code className="text-cyan-300 font-mono w-32 shrink-0">{c.expr}</code>
                        <span className="text-slate-400 text-xs">{c.desc}</span>
                      </div>
                    ))}
                  </div>
                </DocSection>
              )}
            </div>
          )}

          {/* ================================================================ */}
          {/* GROUP: API REFERENCE                                             */}
          {/* ================================================================ */}

          {filteredGroups.some((g) => g.name === 'API Reference') && (
            <div className="space-y-4 mt-8">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white flex items-center gap-2">
                  <Globe className="w-5 h-5 text-blue-400" />
                  API Reference
                </h2>
                <div className="flex gap-2">
                  <button onClick={() => expandAllInGroup('API Reference')} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">Expand All</button>
                  <span className="text-slate-700">|</span>
                  <button onClick={() => collapseAllInGroup('API Reference')} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">Collapse All</button>
                </div>
              </div>

              <P>All endpoints return a standard JSON envelope. Interactive docs at <code className="text-cyan-300">http://localhost:8000/docs</code> (Swagger) and <code className="text-cyan-300">/redoc</code>.</P>
              <CodeBlock language="json" code={`// Success envelope
{ "data": { ... }, "error": null, "meta": { "total": 42, "limit": 20, "offset": 0 } }

// Error envelope
{ "data": null, "error": { "message": "Not found", "code": 404 }, "meta": null }`} />

              {/* ── Auth API ── */}
              {sectionVisible('api-auth') && (
                <DocSection id="api-auth" icon={Key} title="Auth API" isOpen={openSections.has('api-auth')} onToggle={() => toggleSection('api-auth')}>
                  <P>RS256 JWT tokens with asymmetric key signing. Access tokens expire in 15 minutes, refresh tokens last 7 days.</P>
                  <div className="space-y-0.5">
                    <EndpointRow method="POST" path="/api/auth/register" desc="Register new user + tenant" />
                    <EndpointRow method="POST" path="/api/auth/login" desc="Login, returns JWT pair (access + refresh)" />
                    <EndpointRow method="POST" path="/api/auth/refresh" desc="Rotate access token using refresh token" />
                    <EndpointRow method="POST" path="/api/auth/logout" desc="Invalidate refresh token" />
                    <EndpointRow method="GET" path="/api/auth/me" desc="Current user profile + role + tenant" />
                  </div>

                  <H3>Login Example</H3>
                  <CodeBlock language="bash" code={`curl -X POST http://localhost:8000/api/auth/login \\
  -H "Content-Type: application/json" \\
  -d '{"email":"admin@abenix.dev","password":"admin123"}'

# Response:
# { "data": {
#     "access_token": "eyJhbGciOiJSUzI1NiIs...",
#     "refresh_token": "eyJhbGciOiJSUzI1NiIs...",
#     "token_type": "bearer",
#     "expires_in": 900
#   }
# }`} />

                  <H3>API Key Alternative</H3>
                  <P>For server-to-server, use <code className="text-cyan-300">X-API-Key: af_live_xxx</code> header instead of Bearer tokens.</P>
                </DocSection>
              )}

              {/* ── Agents API ── */}
              {sectionVisible('api-agents') && (
                <DocSection id="api-agents" icon={Bot} title="Agents API" isOpen={openSections.has('api-agents')} onToggle={() => toggleSection('api-agents')}>
                  <div className="space-y-0.5">
                    <EndpointRow method="GET" path="/api/agents" desc="List agents (paginated, filterable by category, search)" />
                    <EndpointRow method="POST" path="/api/agents" desc="Create a new agent" />
                    <EndpointRow method="GET" path="/api/agents/:id" desc="Get agent details including model_config and tools" />
                    <EndpointRow method="PUT" path="/api/agents/:id" desc="Update agent (system_prompt, tools, model_config)" />
                    <EndpointRow method="DELETE" path="/api/agents/:id" desc="Delete agent and associated executions" />
                    <EndpointRow method="POST" path="/api/agents/:id/execute" desc="Execute agent (sync or stream via SSE)" />
                    <EndpointRow method="POST" path="/api/agents/:id/clone" desc="Clone an agent with optional name override" />
                  </div>

                  <H3>Execution with Input Variables</H3>
                  <CodeBlock language="bash" code={`curl -X POST http://localhost:8000/api/agents/{id}/execute \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "message": "Analyze the competitive landscape",
    "stream": true,
    "variables": {
      "industry": "AI semiconductors",
      "competitors": ["NVIDIA", "AMD", "Intel"]
    }
  }'`} />

                  <H3>Create Agent Request Body</H3>
                  <CodeBlock language="json" code={`{
  "name": "My Agent",
  "slug": "my-agent",                      // optional, auto-generated from name
  "category": "research",                   // engineering, research, finance, data, communication, operations, industry
  "system_prompt": "You are a helpful...",
  "model_config": {
    "model": "claude-sonnet-4-5-20250929",  // required
    "temperature": 0.3,                     // 0.0 - 1.0
    "max_tokens": 4096,
    "tools": ["web_search", "calculator"],  // array of tool names
    "max_iterations": 25                    // ReAct loop limit
  },
  "hitl_config": {                          // optional
    "enabled": false,
    "require_approval_for": [],
    "cost_threshold_usd": null,
    "timeout_minutes": 60
  },
  "mcp_extensions": {                       // optional
    "allow_user_mcp": true,
    "max_mcp_servers": 5
  }
}`} />

                  <H3>Execution Response</H3>
                  <CodeBlock language="json" code={`{
  "data": {
    "execution_id": "exec_abc123",
    "agent_id": "agent_def456",
    "status": "completed",
    "response": "Based on my analysis of the AI semiconductor market...",
    "steps": [
      { "tool": "web_search", "input": {"query": "AI chip market 2025"}, "duration_ms": 1200 },
      { "tool": "calculator", "input": {"expression": "87.2 * 1.23"}, "duration_ms": 15 }
    ],
    "tokens_used": { "input": 2450, "output": 1870, "total": 4320 },
    "cost_usd": 0.0234,
    "duration_seconds": 8.7,
    "confidence_score": 0.84
  }
}`} />
                </DocSection>
              )}

              {/* ── Executions API ── */}
              {sectionVisible('api-executions') && (
                <DocSection id="api-executions" icon={Play} title="Executions API" isOpen={openSections.has('api-executions')} onToggle={() => toggleSection('api-executions')}>
                  <div className="space-y-0.5">
                    <EndpointRow method="GET" path="/api/executions" desc="List executions (paginated, filterable by status, agent, date)" />
                    <EndpointRow method="GET" path="/api/executions/:id" desc="Execution details with tool steps, token usage, cost" />
                    <EndpointRow method="POST" path="/api/executions/:id/cancel" desc="Cancel a running execution" />
                    <EndpointRow method="GET" path="/api/executions/live" desc="Live execution stream (SSE) for real-time dashboard" />
                  </div>

                  <H3>Execution Status Flow</H3>
                  <CodeBlock language="text" code={`PENDING ──> RUNNING ──> COMPLETED
                    │            │
                    │            ├──> FAILED (with failure_code)
                    │            │
                    │            └──> WAITING_APPROVAL ──> COMPLETED
                    │                                  └──> CANCELLED
                    │
                    └──> CANCELLED`} />

                  <H3>Failure Codes</H3>
                  <div className="space-y-1 my-3">
                    {[
                      { code: 'LLM_RATE_LIMIT', desc: 'LLM provider rate limit exceeded (429)' },
                      { code: 'LLM_PROVIDER_ERROR', desc: 'LLM provider returned an error' },
                      { code: 'SANDBOX_TIMEOUT', desc: 'Code execution exceeded time limit' },
                      { code: 'SANDBOX_OOM', desc: 'Code execution exceeded memory limit' },
                      { code: 'TOOL_NOT_FOUND', desc: 'Referenced tool does not exist in registry' },
                      { code: 'TOOL_ERROR', desc: 'Tool execution failed' },
                      { code: 'BUDGET_EXCEEDED', desc: 'Cost guardrail triggered' },
                      { code: 'MODERATION_BLOCKED', desc: 'Content moderation policy triggered' },
                      { code: 'STALE_SWEEP', desc: 'Execution stuck and cleaned up by sweeper' },
                      { code: 'INFRA_CRASH', desc: 'Infrastructure error (connection refused, etc.)' },
                    ].map((f) => (
                      <div key={f.code} className="flex items-start gap-3 text-sm py-1 border-b border-slate-700/30 last:border-0">
                        <code className="text-red-400 font-mono w-44 shrink-0">{f.code}</code>
                        <span className="text-slate-400 text-xs">{f.desc}</span>
                      </div>
                    ))}
                  </div>

                  <H3>Listing Executions with Filters</H3>
                  <CodeBlock language="bash" code={`# Filter by status and agent
curl "http://localhost:8000/api/executions?status=failed&agent_id=agent_123&limit=20&offset=0" \\
  -H "Authorization: Bearer $TOKEN"

# Filter by date range
curl "http://localhost:8000/api/executions?since=2026-04-01&until=2026-04-15" \\
  -H "Authorization: Bearer $TOKEN"

# Get execution details with all steps and tool calls
curl http://localhost:8000/api/executions/exec_abc123 \\
  -H "Authorization: Bearer $TOKEN"`} />

                  <H3>Live Execution Stream (SSE)</H3>
                  <CodeBlock language="bash" code={`# Stream all live executions as Server-Sent Events
curl -N http://localhost:8000/api/executions/live \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Accept: text/event-stream"

# Events:
# data: {"event": "execution.started", "execution_id": "exec_123", "agent_name": "Deep Research"}
# data: {"event": "tool.called", "tool": "web_search", "execution_id": "exec_123"}
# data: {"event": "execution.completed", "execution_id": "exec_123", "duration_seconds": 12.5}`} />
                </DocSection>
              )}

              {/* ── Knowledge API ── */}
              {sectionVisible('api-knowledge') && (
                <DocSection id="api-knowledge" icon={Brain} title="Knowledge API" isOpen={openSections.has('api-knowledge')} onToggle={() => toggleSection('api-knowledge')}>
                  <div className="space-y-0.5">
                    <EndpointRow method="GET" path="/api/knowledge" desc="List knowledge bases" />
                    <EndpointRow method="POST" path="/api/knowledge" desc="Create knowledge base" />
                    <EndpointRow method="GET" path="/api/knowledge/:id" desc="Knowledge base details" />
                    <EndpointRow method="POST" path="/api/knowledge/:id/ingest" desc="Ingest documents (PDF, DOCX, TXT, CSV)" />
                    <EndpointRow method="POST" path="/api/knowledge/:id/search" desc="Hybrid search (vector + graph + keyword)" />
                    <EndpointRow method="DELETE" path="/api/knowledge/:id" desc="Delete knowledge base and documents" />
                    <EndpointRow method="POST" path="/api/knowledge-engine/cognify" desc="Build knowledge graph from documents" />
                    <EndpointRow method="POST" path="/api/knowledge-engine/memify" desc="Evolve memory graph from executions" />
                  </div>

                  <H3>Document Upload</H3>
                  <CodeBlock language="bash" code={`# Create a knowledge base
KB_ID=$(curl -s -X POST http://localhost:8000/api/knowledge \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"name": "Q4 Financial Reports"}' | jq -r '.data.id')

# Upload documents
curl -X POST http://localhost:8000/api/knowledge/$KB_ID/ingest \\
  -H "Authorization: Bearer $TOKEN" \\
  -F "files=@report-q4.pdf" \\
  -F "files=@earnings-call.docx"`} />
                </DocSection>
              )}

              {/* ── ML Models API ── */}
              {sectionVisible('api-ml-models') && (
                <DocSection id="api-ml-models" icon={Cpu} title="ML Models API" isOpen={openSections.has('api-ml-models')} onToggle={() => toggleSection('api-ml-models')}>
                  <div className="space-y-0.5">
                    <EndpointRow method="GET" path="/api/ml-models" desc="List uploaded ML models" />
                    <EndpointRow method="POST" path="/api/ml-models" desc="Upload a new ML model" />
                    <EndpointRow method="GET" path="/api/ml-models/:id" desc="Model details (status, metrics, version)" />
                    <EndpointRow method="POST" path="/api/ml-models/:id/deploy" desc="Deploy model for inference serving" />
                    <EndpointRow method="POST" path="/api/ml-models/:id/undeploy" desc="Stop serving the model" />
                    <EndpointRow method="POST" path="/api/ml-models/:id/predict" desc="Run inference on deployed model" />
                    <EndpointRow method="DELETE" path="/api/ml-models/:id" desc="Delete model and files" />
                  </div>

                  <H3>Deploy Flow</H3>
                  <P>Models are stored in <code className="text-cyan-300">ML_MODELS_DIR</code> (default: <code className="text-cyan-300">/data/ml-models</code>). On deploy, the model file is loaded and a serving endpoint is created. The <code className="text-cyan-300">ml_model_tool</code> can then invoke it from any agent.</P>
                </DocSection>
              )}

              {/* ── Code Assets API ── */}
              {sectionVisible('api-code-assets') && (
                <DocSection id="api-code-assets" icon={Code} title="Code Assets API" isOpen={openSections.has('api-code-assets')} onToggle={() => toggleSection('api-code-assets')}>
                  <div className="space-y-0.5">
                    <EndpointRow method="GET" path="/api/code-assets" desc="List code assets (uploaded repos)" />
                    <EndpointRow method="POST" path="/api/code-assets" desc="Upload code asset (zip or git URL)" />
                    <EndpointRow method="GET" path="/api/code-assets/:id" desc="Code asset details (language, entrypoint, status)" />
                    <EndpointRow method="POST" path="/api/code-assets/:id/test" desc="Test-run the code asset in sandbox" />
                    <EndpointRow method="DELETE" path="/api/code-assets/:id" desc="Delete code asset and files" />
                  </div>

                  <H3>Supported Languages</H3>
                  <div className="flex flex-wrap gap-2 my-3">
                    {['Python', 'Node.js', 'Go', 'Rust', 'Ruby', 'Java'].map((lang) => (
                      <Badge key={lang} color="cyan">{lang}</Badge>
                    ))}
                  </div>

                  <H3>Upload & Test</H3>
                  <CodeBlock language="bash" code={`# Upload a Python project as a zip
curl -X POST http://localhost:8000/api/code-assets \\
  -H "Authorization: Bearer $TOKEN" \\
  -F "file=@my-project.zip" \\
  -F "language=python" \\
  -F "entrypoint=main.py"

# Test-run it
curl -X POST http://localhost:8000/api/code-assets/{id}/test \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"input": "Hello from the test harness"}'`} />
                </DocSection>
              )}

              {/* ── Moderation API ── */}
              {sectionVisible('api-moderation') && (
                <DocSection id="api-moderation" icon={Shield} title="Moderation API" isOpen={openSections.has('api-moderation')} onToggle={() => toggleSection('api-moderation')}>
                  <div className="space-y-0.5">
                    <EndpointRow method="POST" path="/api/moderation/vet" desc="One-shot classify content against tenant policy" />
                    <EndpointRow method="GET" path="/api/moderation/policies" desc="List tenant moderation policies" />
                    <EndpointRow method="POST" path="/api/moderation/policies" desc="Create or replace active policy (admin only)" />
                    <EndpointRow method="GET" path="/api/moderation/policies/:id" desc="Get policy details" />
                    <EndpointRow method="PATCH" path="/api/moderation/policies/:id" desc="Update policy fields" />
                    <EndpointRow method="DELETE" path="/api/moderation/policies/:id" desc="Delete policy (admin only)" />
                    <EndpointRow method="GET" path="/api/moderation/events" desc="Moderation event history (filterable)" />
                  </div>

                  <H3>Vet Endpoint</H3>
                  <P>The <code className="text-cyan-300">/vet</code> endpoint runs the same <code className="text-cyan-300">evaluate()</code> function the agent gate uses, so the UI playground shows exactly what an agent run would see.</P>
                  <CodeBlock language="bash" code={`curl -X POST http://localhost:8000/api/moderation/vet \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "content": "Analyze quarterly earnings for $TSLA",
    "policy_override": {
      "thresholds": { "harassment": 0.2 }
    }
  }'`} />
                </DocSection>
              )}

              {/* ── Settings & Webhooks API ── */}
              {sectionVisible('api-settings') && (
                <DocSection id="api-settings" icon={Settings} title="Settings & Webhooks API" isOpen={openSections.has('api-settings')} onToggle={() => toggleSection('api-settings')}>
                  <H3>Tenant Settings</H3>
                  <div className="space-y-0.5">
                    <EndpointRow method="GET" path="/api/settings/tenant" desc="Get tenant configuration" />
                    <EndpointRow method="PUT" path="/api/settings/tenant" desc="Update tenant settings (admin only)" />
                  </div>

                  <H3>Webhooks</H3>
                  <div className="space-y-0.5 mt-3">
                    <EndpointRow method="GET" path="/api/webhooks" desc="List configured webhooks" />
                    <EndpointRow method="POST" path="/api/webhooks" desc="Create webhook subscription" />
                    <EndpointRow method="GET" path="/api/webhooks/:id" desc="Webhook details" />
                    <EndpointRow method="PUT" path="/api/webhooks/:id" desc="Update webhook (URL, events, secret)" />
                    <EndpointRow method="DELETE" path="/api/webhooks/:id" desc="Delete webhook" />
                    <EndpointRow method="GET" path="/api/webhooks/:id/deliveries" desc="Delivery history with status codes" />
                  </div>

                  <H3>Account & API Keys</H3>
                  <div className="space-y-0.5 mt-3">
                    <EndpointRow method="GET" path="/api/account" desc="Account details" />
                    <EndpointRow method="PUT" path="/api/account" desc="Update account (name, email, password)" />
                    <EndpointRow method="GET" path="/api/api-keys" desc="List API keys (hashes, not values)" />
                    <EndpointRow method="POST" path="/api/api-keys" desc="Create API key (returns key once)" />
                    <EndpointRow method="DELETE" path="/api/api-keys/:id" desc="Revoke API key" />
                  </div>
                </DocSection>
              )}

              {/* ── Triggers API ── */}
              {sectionVisible('api-triggers') && (
                <DocSection id="api-triggers" icon={Timer} title="Triggers API" isOpen={openSections.has('api-triggers')} onToggle={() => toggleSection('api-triggers')}>
                  <div className="space-y-0.5">
                    <EndpointRow method="GET" path="/api/triggers" desc="List scheduled triggers" />
                    <EndpointRow method="POST" path="/api/triggers" desc="Create a cron trigger for an agent" />
                    <EndpointRow method="GET" path="/api/triggers/:id" desc="Trigger details (next_run, last_run, status)" />
                    <EndpointRow method="PUT" path="/api/triggers/:id" desc="Update trigger (cron, input, enabled)" />
                    <EndpointRow method="DELETE" path="/api/triggers/:id" desc="Delete trigger" />
                  </div>
                </DocSection>
              )}
            </div>
          )}

          {/* ================================================================ */}
          {/* GROUP: INTEGRATION                                               */}
          {/* ================================================================ */}

          {filteredGroups.some((g) => g.name === 'Integration') && (
            <div className="space-y-4 mt-8">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white flex items-center gap-2">
                  <Plug className="w-5 h-5 text-indigo-400" />
                  Integration
                </h2>
                <div className="flex gap-2">
                  <button onClick={() => expandAllInGroup('Integration')} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">Expand All</button>
                  <span className="text-slate-700">|</span>
                  <button onClick={() => collapseAllInGroup('Integration')} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">Collapse All</button>
                </div>
              </div>

              {/* ── Python SDK ── */}
              {sectionVisible('sdk-python') && (
                <DocSection id="sdk-python" icon={Code} title="Python SDK" isOpen={openSections.has('sdk-python')} onToggle={() => toggleSection('sdk-python')}>
                  <H3>Installation</H3>
                  <CodeBlock language="bash" code={`pip install abenix-sdk`} />

                  <H3>Quick Start</H3>
                  <CodeBlock language="python" code={`from abenix_sdk import Abenix

# Initialize client
client = Abenix(
    base_url="http://localhost:8000",
    api_key="af_live_your_key_here"
)

# List agents
agents = client.agents.list()
for agent in agents:
    print(f"{agent.name} ({agent.slug})")

# Execute an agent (synchronous)
result = client.agents.execute(
    agent_id="agent_123",
    message="What are the key trends in AI?",
    stream=False
)
print(result.response)
print("Cost:", result.cost_usd)
print("Tokens:", result.tokens_used)

# Execute with streaming
for chunk in client.agents.execute(
    agent_id="agent_123",
    message="Write a market analysis",
    stream=True
):
    print(chunk.text, end="", flush=True)

# Knowledge base operations
kb = client.knowledge.create(name="Q4 Reports")
client.knowledge.ingest(kb.id, files=["report.pdf", "earnings.docx"])
results = client.knowledge.search(kb.id, query="revenue growth")
for r in results:
    print(r.score, r.text[:100])

# Pipeline execution
result = client.pipelines.execute(
    pipeline_id="pipeline_456",
    variables={"topic": "AI semiconductors", "depth": "comprehensive"}
)`} />

                  <H3>Async Usage</H3>
                  <CodeBlock language="python" code={`import asyncio
from abenix_sdk import AsyncAbenix

async def main():
    client = AsyncAbenix(api_key="af_live_xxx")
    result = await client.agents.execute(
        agent_id="agent_123",
        message="Summarize this quarter's results"
    )
    print(result.response)

asyncio.run(main())`} />

                  <H3>Error Handling</H3>
                  <CodeBlock language="python" code={`from abenix_sdk import Abenix, AbenixError, RateLimitError

client = Abenix(api_key="af_live_xxx")

try:
    result = client.agents.execute(agent_id="agent_123", message="Analyze this")
except RateLimitError as e:
    print(f"Rate limited. Retry after {e.retry_after}s")
except AbenixError as e:
    print(f"Error {e.status_code}: {e.message}")`} />

                  <H3>Webhook Listener</H3>
                  <CodeBlock language="python" code={`from abenix_sdk.webhooks import verify_signature
from flask import Flask, request

app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def handle_webhook():
    payload = request.get_data()
    signature = request.headers.get("X-Abenix-Signature")

    if not verify_signature(payload, signature, secret="whsec_xxx"):
        return "Invalid signature", 401

    event = request.json
    if event["event"] == "execution.completed":
        print(f"Execution {event['data']['execution_id']} completed!")
    return "OK", 200`} />

                  <H3>Batch Execution</H3>
                  <CodeBlock language="python" code={`# Execute multiple agents in parallel
import asyncio
from abenix_sdk import AsyncAbenix

async def batch_analyze(topics: list[str]):
    client = AsyncAbenix(api_key="af_live_xxx")
    tasks = [
        client.agents.execute(
            agent_id="deep-research",
            message=f"Research: {topic}"
        )
        for topic in topics
    ]
    results = await asyncio.gather(*tasks)
    return results

results = asyncio.run(batch_analyze(["AI chips", "Quantum computing", "Robotics"]))`} />
                </DocSection>
              )}

              {/* ── JavaScript SDK ── */}
              {sectionVisible('sdk-javascript') && (
                <DocSection id="sdk-javascript" icon={Code} title="JavaScript / TypeScript SDK" isOpen={openSections.has('sdk-javascript')} onToggle={() => toggleSection('sdk-javascript')}>
                  <H3>Installation</H3>
                  <CodeBlock language="bash" code={`npm install @abenix/sdk`} />

                  <H3>Quick Start</H3>
                  <CodeBlock language="typescript" code={`import { Abenix } from '@abenix/sdk';

const client = new Abenix({
  baseUrl: 'http://localhost:8000',
  apiKey: 'af_live_your_key_here',
});

// List agents
const agents = await client.agents.list();
console.log(agents.map(a => a.name));

// Execute with streaming
const stream = await client.agents.execute({
  agentId: 'agent_123',
  message: 'Summarize this document',
  stream: true,
});

for await (const chunk of stream) {
  process.stdout.write(chunk.text);
}

// Create webhook
await client.webhooks.create({
  url: 'https://your-app.com/webhook',
  events: ['execution.completed', 'execution.failed'],
  secret: 'whsec_your_secret',
});

// Knowledge search
const results = await client.knowledge.search({
  knowledgeBaseId: 'kb_123',
  query: 'revenue drivers',
  topK: 5,
});`} />

                  <H3>React Integration</H3>
                  <CodeBlock language="typescript" code={`'use client';
import { useState } from 'react';
import { Abenix } from '@abenix/sdk';

const client = new Abenix({ baseUrl: '/api', apiKey: 'af_live_xxx' });

export function AgentChat({ agentId }: { agentId: string }) {
  const [response, setResponse] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit(message: string) {
    setLoading(true);
    setResponse('');

    const stream = await client.agents.execute({
      agentId,
      message,
      stream: true,
    });

    for await (const chunk of stream) {
      setResponse(prev => prev + chunk.text);
    }
    setLoading(false);
  }

  return (
    <div>
      <textarea onKeyDown={(e) => {
        if (e.key === 'Enter' && !e.shiftKey) handleSubmit(e.currentTarget.value);
      }} />
      {loading && <span>Thinking...</span>}
      <div>{response}</div>
    </div>
  );
}`} />

                  <H3>Node.js Server Integration</H3>
                  <CodeBlock language="typescript" code={`import express from 'express';
import { Abenix } from '@abenix/sdk';

const app = express();
const forge = new Abenix({ apiKey: process.env.ABENIX_API_KEY! });

app.post('/analyze', async (req, res) => {
  try {
    const result = await forge.agents.execute({
      agentId: 'deep-research',
      message: req.body.query,
    });
    res.json({ analysis: result.response, cost: result.costUsd });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});`} />
                </DocSection>
              )}

              {/* ── MCP Protocol ── */}
              {sectionVisible('mcp-protocol') && (
                <DocSection id="mcp-protocol" icon={Network} title="MCP Protocol" isOpen={openSections.has('mcp-protocol')} onToggle={() => toggleSection('mcp-protocol')}>
                  <P>Agents can connect to external MCP (Model Context Protocol) servers to access additional tools beyond the 90+ built-in ones.</P>

                  <H3>Managing MCP Servers</H3>
                  <div className="space-y-0.5 my-3">
                    <EndpointRow method="GET" path="/api/mcp/servers" desc="List registered MCP servers" />
                    <EndpointRow method="POST" path="/api/mcp/servers" desc="Register a new MCP server" />
                    <EndpointRow method="GET" path="/api/mcp/servers/:id/tools" desc="List tools exposed by MCP server" />
                    <EndpointRow method="DELETE" path="/api/mcp/servers/:id" desc="Remove MCP server" />
                  </div>

                  <H3>Registering a Server</H3>
                  <CodeBlock language="bash" code={`# Register a GitHub MCP server
curl -X POST http://localhost:8000/api/mcp/servers \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "GitHub",
    "url": "https://github.com/modelcontextprotocol/server-github",
    "transport": "stdio",
    "env": { "GITHUB_TOKEN": "ghp_xxx" }
  }'`} />

                  <H3>Per-Agent MCP Configuration</H3>
                  <CodeBlock language="json" code={`{
  "mcp_extensions": {
    "allow_user_mcp": true,
    "max_mcp_servers": 5,
    "suggested_mcp_servers": [
      { "name": "GitHub", "url": "..." },
      { "name": "Filesystem", "url": "..." }
    ]
  }
}`} />

                  <InfoBox variant="info">
                    MCP servers must implement the Model Context Protocol specification. The agent runtime connects to them at execution time and discovers available tools dynamically. Each tool appears in the LLM&apos;s function-calling schema alongside built-in tools.
                  </InfoBox>

                  <H3>Popular MCP Servers</H3>
                  <div className="space-y-1 my-3">
                    {[
                      { name: 'GitHub', desc: 'Repository management, issues, PRs, code search', url: 'modelcontextprotocol/server-github' },
                      { name: 'Filesystem', desc: 'Local file read/write/search operations', url: 'modelcontextprotocol/server-filesystem' },
                      { name: 'PostgreSQL', desc: 'Direct database queries and schema inspection', url: 'modelcontextprotocol/server-postgres' },
                      { name: 'Slack', desc: 'Send messages, read channels, manage workspace', url: 'modelcontextprotocol/server-slack' },
                      { name: 'Google Drive', desc: 'Search, read, and create documents', url: 'modelcontextprotocol/server-gdrive' },
                      { name: 'Brave Search', desc: 'Web search with Brave API', url: 'modelcontextprotocol/server-brave-search' },
                    ].map((s) => (
                      <div key={s.name} className="flex items-start gap-3 text-sm py-2 border-b border-slate-700/30 last:border-0">
                        <span className="text-white font-medium w-28 shrink-0">{s.name}</span>
                        <span className="text-slate-400 text-xs flex-1">{s.desc}</span>
                        <code className="text-xs text-slate-600">{s.url}</code>
                      </div>
                    ))}
                  </div>

                  <H3>MCP Security Considerations</H3>
                  <P>MCP servers run with the permissions of the runtime container. In Kubernetes, use network policies to restrict which external endpoints the runtime pod can reach. The <code className="text-cyan-300">max_mcp_servers</code> limit prevents resource exhaustion from too many concurrent connections.</P>
                </DocSection>
              )}

              {/* ── A2A Protocol ── */}
              {sectionVisible('a2a-protocol') && (
                <DocSection id="a2a-protocol" icon={Share2} title="A2A Protocol" isOpen={openSections.has('a2a-protocol')} onToggle={() => toggleSection('a2a-protocol')}>
                  <P>Agent-to-Agent (A2A) communication allows agents to discover each other&apos;s capabilities and delegate tasks.</P>

                  <H3>Endpoints</H3>
                  <div className="space-y-0.5">
                    <EndpointRow method="POST" path="/api/a2a/discover" desc="Discover agents matching a capability query" />
                    <EndpointRow method="POST" path="/api/a2a/delegate" desc="Delegate a task to another agent" />
                    <EndpointRow method="GET" path="/api/a2a/capabilities" desc="List this agent's advertised capabilities" />
                  </div>

                  <H3>How It Works</H3>
                  <P>When an agent determines it needs a capability it does not have, it can use the <code className="text-cyan-300">agent_step</code> tool to invoke another agent. The A2A protocol provides discovery (finding agents by capability), delegation (passing tasks with context), and result aggregation.</P>
                  <CodeBlock language="python" code={`# In a pipeline, chain agents via agent_step:
{
  "id": "research",
  "tool_name": "agent_step",
  "arguments": {
    "agent_slug": "deep-research",
    "message": "Research {{input.topic}} across 10 sources"
  }
}`} />

                  <H3>Discovery Example</H3>
                  <CodeBlock language="bash" code={`# Find agents that can analyze financial documents
curl -X POST http://localhost:8000/api/a2a/discover \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "capability": "financial document analysis",
    "required_tools": ["document_extractor", "financial_calculator"],
    "max_results": 5
  }'

# Response includes matching agents ranked by capability fit:
# { "data": [
#   { "agent_id": "...", "name": "Financial Modeler", "match_score": 0.92 },
#   { "agent_id": "...", "name": "Contract Risk Assessor", "match_score": 0.87 }
# ] }`} />

                  <H3>Delegation with Context</H3>
                  <CodeBlock language="bash" code={`# Delegate a task to a discovered agent
curl -X POST http://localhost:8000/api/a2a/delegate \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "target_agent_id": "agent_123",
    "task": "Analyze the attached PPA contract for risk factors",
    "context": {
      "document_id": "doc_456",
      "priority": "high",
      "callback_url": "https://your-app.com/results"
    }
  }'`} />
                </DocSection>
              )}

              {/* ── Webhook Events ── */}
              {sectionVisible('webhook-events') && (
                <DocSection id="webhook-events" icon={Bell} title="Webhook Events" isOpen={openSections.has('webhook-events')} onToggle={() => toggleSection('webhook-events')}>
                  <P>Subscribe to webhook events to receive real-time notifications when things happen in Abenix.</P>

                  <H3>Available Events</H3>
                  <div className="space-y-1 my-3">
                    {[
                      { event: 'execution.started', desc: 'Agent execution has started' },
                      { event: 'execution.completed', desc: 'Agent execution completed successfully' },
                      { event: 'execution.failed', desc: 'Agent execution failed (includes failure_code)' },
                      { event: 'execution.cancelled', desc: 'Execution was manually cancelled' },
                      { event: 'agent.created', desc: 'New agent was created' },
                      { event: 'agent.updated', desc: 'Agent configuration was modified' },
                      { event: 'agent.deleted', desc: 'Agent was deleted' },
                      { event: 'pipeline.completed', desc: 'Pipeline execution completed' },
                      { event: 'knowledge.ingested', desc: 'Documents ingested into knowledge base' },
                      { event: 'moderation.blocked', desc: 'Content was blocked by moderation' },
                      { event: 'budget.alert', desc: 'Spending threshold reached' },
                    ].map((e) => (
                      <div key={e.event} className="flex items-start gap-3 text-sm py-1 border-b border-slate-700/30 last:border-0">
                        <code className="text-cyan-300 font-mono w-44 shrink-0">{e.event}</code>
                        <span className="text-slate-400 text-xs">{e.desc}</span>
                      </div>
                    ))}
                  </div>

                  <H3>Payload Format</H3>
                  <CodeBlock language="json" code={`{
  "event": "execution.completed",
  "timestamp": "2026-04-15T14:30:00Z",
  "data": {
    "execution_id": "exec_789",
    "agent_id": "agent_123",
    "status": "completed",
    "duration_seconds": 12.5,
    "tokens_used": 3420,
    "cost_usd": 0.0185
  }
}`} />

                  <H3>Webhook Verification in Multiple Languages</H3>
                  <CodeBlock language="typescript" code={`// Node.js verification
import crypto from 'crypto';

function verifyWebhook(payload: string, signature: string, secret: string): boolean {
  const expected = crypto
    .createHmac('sha256', secret)
    .update(payload)
    .digest('hex');
  return crypto.timingSafeEqual(
    Buffer.from(\`sha256=\${expected}\`),
    Buffer.from(signature)
  );
}`} />
                  <CodeBlock language="python" code={`# Python verification
import hmac, hashlib

def verify_webhook(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)`} />

                  <H3>Retry Policy</H3>
                  <P>Failed deliveries are retried with exponential backoff:</P>
                  <div className="space-y-1 my-3">
                    {[
                      { attempt: '1st retry', delay: '1 minute', total: '~1 min after failure' },
                      { attempt: '2nd retry', delay: '5 minutes', total: '~6 min after failure' },
                      { attempt: '3rd retry', delay: '30 minutes', total: '~36 min after failure' },
                      { attempt: '4th retry', delay: '2 hours', total: '~2.5 hours after failure' },
                      { attempt: 'Give up', delay: '--', total: 'Marked as permanently failed' },
                    ].map((r) => (
                      <div key={r.attempt} className="flex items-center gap-3 text-sm py-1 border-b border-slate-700/30 last:border-0">
                        <span className="text-slate-300 w-24 shrink-0">{r.attempt}</span>
                        <span className="text-cyan-300 w-24 shrink-0">{r.delay}</span>
                        <span className="text-slate-500 text-xs">{r.total}</span>
                      </div>
                    ))}
                  </div>
                </DocSection>
              )}
            </div>
          )}

          {/* ================================================================ */}
          {/* GROUP: INFRASTRUCTURE                                            */}
          {/* ================================================================ */}

          {filteredGroups.some((g) => g.name === 'Infrastructure') && (
            <div className="space-y-4 mt-8">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white flex items-center gap-2">
                  <Server className="w-5 h-5 text-slate-400" />
                  Infrastructure
                </h2>
                <div className="flex gap-2">
                  <button onClick={() => expandAllInGroup('Infrastructure')} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">Expand All</button>
                  <span className="text-slate-700">|</span>
                  <button onClick={() => collapseAllInGroup('Infrastructure')} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">Collapse All</button>
                </div>
              </div>

              {/* ── Kubernetes Deploy ── */}
              {sectionVisible('kubernetes-deploy') && (
                <DocSection id="kubernetes-deploy" icon={Cloud} title="Kubernetes Deploy" isOpen={openSections.has('kubernetes-deploy')} onToggle={() => toggleSection('kubernetes-deploy')}>
                  <P>The <code className="text-cyan-300">scripts/deploy.sh</code> script handles everything from building Docker images to deploying Helm charts.</P>

                  <H3>deploy.sh Commands</H3>
                  <div className="space-y-2 my-3">
                    {[
                      { cmd: './scripts/deploy.sh local', desc: 'Deploy to minikube with embedded runtime (no separate runtime pod). Builds images using minikube\'s Docker daemon.' },
                      { cmd: './scripts/deploy.sh local-runtime', desc: 'Deploy to minikube with a separate agent-runtime pod. Better mirrors production topology.' },
                      { cmd: './scripts/deploy.sh cloud', desc: 'Deploy to current kubectl context (production). Uses your configured container registry.' },
                      { cmd: './scripts/deploy.sh status', desc: 'Check deployment health: pod status, service endpoints, health checks.' },
                      { cmd: './scripts/deploy.sh destroy', desc: 'Tear down everything: helm uninstall, delete namespace, clean up volumes.' },
                      { cmd: './scripts/deploy.sh build', desc: 'Build Docker images only, without deploying.' },
                    ].map((c) => (
                      <div key={c.cmd} className="p-3 bg-slate-900/40 border border-slate-700/40 rounded-lg">
                        <code className="text-sm text-cyan-300 font-mono">{c.cmd}</code>
                        <p className="text-xs text-slate-400 mt-1">{c.desc}</p>
                      </div>
                    ))}
                  </div>

                  <H3>Environment Overrides</H3>
                  <CodeBlock language="bash" code={`# Deploy with custom settings
NAMESPACE=my-ns RELEASE_NAME=my-forge IMAGE_TAG=v2.1.0 ./scripts/deploy.sh cloud

# Force a clean start
FRESH=true ./scripts/deploy.sh local`} />

                  <H3>start.sh (Development)</H3>
                  <P>For local development without Kubernetes, use <code className="text-cyan-300">start.sh</code> which runs Docker Compose:</P>
                  <CodeBlock language="bash" code={`chmod +x start.sh
./start.sh
# Starts: web (3000), api (8000), runtime (8001), worker, postgres, redis, neo4j
# Waits for all health checks to pass before returning`} />

                  <H3>Minikube Setup</H3>
                  <CodeBlock language="bash" code={`# Start minikube with sufficient resources
minikube start --memory=8192 --cpus=4

# Deploy
./scripts/deploy.sh local

# Access via tunnel (run in a separate terminal)
minikube tunnel

# Then open http://localhost:3000`} />

                  <H3>Cloud (AKS / EKS / GKE)</H3>
                  <CodeBlock language="bash" code={`# Azure AKS
az aks get-credentials --name abenix-prod --resource-group abenix-rg
./scripts/deploy.sh cloud

# AWS EKS
aws eks update-kubeconfig --name abenix-prod
./scripts/deploy.sh cloud

# GCP GKE
gcloud container clusters get-credentials abenix-prod
./scripts/deploy.sh cloud`} />

                  <H3>Rollback</H3>
                  <CodeBlock language="bash" code={`# List release history
helm history abenix -n abenix

# Rollback to revision 3
helm rollback abenix 3 -n abenix

# Verify
kubectl get pods -n abenix`} />

                  <H3>CI/CD Pipeline</H3>
                  <P>The repository includes GitHub Actions workflows. The pipeline runs tests (Playwright E2E + unit), builds Docker images, pushes to a container registry, and deploys.</P>
                  <CodeBlock language="yaml" code={`# .github/workflows/deploy.yml (simplified)
name: Deploy
on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm ci && npx playwright install
      - run: docker compose up -d
      - run: npx playwright test

  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: ./scripts/deploy.sh cloud
        env:
          IMAGE_TAG: \${{ github.sha }}
          REGISTRY: ghcr.io/sarkar4777`} />

                  <H3>Health Check Probes (Kubernetes)</H3>
                  <P>All pods expose health endpoints for Kubernetes probes:</P>
                  <CodeBlock language="yaml" code={`# In the Helm chart values:
api:
  livenessProbe:
    httpGet:
      path: /health
      port: 8000
    initialDelaySeconds: 15
    periodSeconds: 10
  readinessProbe:
    httpGet:
      path: /health
      port: 8000
    initialDelaySeconds: 5
    periodSeconds: 5`} />
                  <InfoBox variant="tip">
                    Set <code className="text-emerald-300">initialDelaySeconds</code> high enough for Neo4j (30-60s) and PostgreSQL (10-20s). The API&apos;s health check verifies all downstream dependencies, so if Neo4j is still starting, the API probe will fail -- which is the correct behavior (it prevents traffic before the system is ready).
                  </InfoBox>
                </DocSection>
              )}

              {/* ── Shared Storage ── */}
              {sectionVisible('shared-storage') && (
                <DocSection id="shared-storage" icon={HardDrive} title="Shared Storage" isOpen={openSections.has('shared-storage')} onToggle={() => toggleSection('shared-storage')}>
                  <P>Knowledge bases, ML models, and Code Runner assets all share a <code className="text-cyan-300">/data</code> directory. In Docker Compose this is a bind mount, in Kubernetes it is a PersistentVolumeClaim (or hostPath for minikube).</P>

                  <H3>/data Directory Layout</H3>
                  <CodeBlock language="text" code={`/data/
├── knowledge_bases/       # Uploaded documents for KB ingestion
│   ├── kb_abc123/
│   │   ├── report.pdf
│   │   └── earnings.docx
│   └── kb_def456/
│       └── contracts.pdf
├── ml-models/             # ML model files (ML_MODELS_DIR)
│   ├── model_001/
│   │   ├── model.pkl
│   │   └── metadata.json
│   └── model_002/
│       └── model.onnx
├── code_assets/           # Uploaded code repositories
│   ├── asset_aaa/
│   │   ├── main.py
│   │   └── requirements.txt
│   └── asset_bbb/
│       ├── main.go
│       └── go.mod
└── uploads/               # Temporary file uploads
    └── tmp_xxx.pdf`} />

                  <H3>Kubernetes Storage</H3>
                  <CodeBlock language="yaml" code={`# values-minikube.yaml (hostPath for development)
persistence:
  enabled: true
  storageClass: standard
  size: 10Gi
  hostPath: /mnt/data/abenix

# values-production.yaml (PVC with cloud storage class)
persistence:
  enabled: true
  storageClass: managed-premium  # AKS example
  size: 100Gi`} />

                  <H3>ML_MODELS_DIR</H3>
                  <P>The <code className="text-cyan-300">ML_MODELS_DIR</code> environment variable controls where ML model files are stored. Default: <code className="text-cyan-300">/data/ml-models</code>. Both the API and the agent-runtime need access to this path. In Kubernetes, they share the same PVC.</P>

                  <InfoBox variant="warning">
                    In minikube, the hostPath is mounted from the minikube VM, not your host machine. Use <code className="text-amber-300">minikube mount</code> if you need to access files from the host. In production, always use a PVC with a proper storage class.
                  </InfoBox>
                </DocSection>
              )}

              {/* ── Observability ── */}
              {sectionVisible('observability') && (
                <DocSection id="observability" icon={Activity} title="Observability & Monitoring" isOpen={openSections.has('observability')} onToggle={() => toggleSection('observability')}>
                  <P>Full observability stack: Prometheus metrics, Grafana dashboards, health checks, stale execution sweeper, and failure code grouping.</P>

                  <H3>Health Checks</H3>
                  <CodeBlock language="bash" code={`# API health (includes DB, Redis, Neo4j status)
curl http://localhost:8000/health
# {"status":"healthy","version":"1.0.0","services":{"postgres":"connected","redis":"connected","neo4j":"connected"}}

# Agent runtime health
curl http://localhost:8001/health`} />

                  <H3>Prometheus Metrics</H3>
                  <P>Every pod exposes <code className="text-cyan-300">/metrics</code> in Prometheus format.</P>
                  <div className="space-y-1 my-3">
                    {[
                      { metric: 'abenix_requests_total', desc: 'Total API requests by endpoint, method, status' },
                      { metric: 'abenix_request_duration_seconds', desc: 'Request latency histogram' },
                      { metric: 'abenix_executions_total', desc: 'Agent executions by status (completed, failed, cancelled)' },
                      { metric: 'abenix_execution_duration_seconds', desc: 'Execution time histogram' },
                      { metric: 'abenix_tool_calls_total', desc: 'Tool invocations by tool name' },
                      { metric: 'abenix_tokens_used_total', desc: 'LLM tokens consumed (input + output)' },
                      { metric: 'abenix_cost_usd_total', desc: 'Cumulative cost in USD' },
                      { metric: 'abenix_active_executions', desc: 'Currently running executions gauge' },
                      { metric: 'abenix_moderation_events_total', desc: 'Moderation events by outcome and source' },
                    ].map((m) => (
                      <div key={m.metric} className="flex items-start gap-3 text-sm">
                        <code className="text-cyan-300 font-mono text-xs shrink-0 w-72">{m.metric}</code>
                        <span className="text-slate-400 text-xs">{m.desc}</span>
                      </div>
                    ))}
                  </div>

                  <H3>Grafana Dashboards</H3>
                  <P>The <code className="text-cyan-300">deploy.sh</code> script deploys Prometheus and Grafana alongside the application. Access Grafana at the NodePort or via port-forward. Pre-built dashboards include:</P>
                  <div className="space-y-1 my-3">
                    {[
                      'Overview: execution count, success rate, active executions, cost',
                      'Failure Breakdown: grouped by failure_code (LLM_RATE_LIMIT, MODERATION_BLOCKED, etc.)',
                      'Token Usage: by model, agent, and time period',
                      'Tool Performance: call count and latency per tool',
                      'Cost Tracking: daily/weekly/monthly spend with budget overlay',
                    ].map((d) => (
                      <div key={d} className="flex items-center gap-2 text-sm text-slate-300">
                        <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 shrink-0" />
                        {d}
                      </div>
                    ))}
                  </div>

                  <H3>Prometheus Multiprocess Mode</H3>
                  <P>When running with multiple workers (Gunicorn or Uvicorn), set <code className="text-cyan-300">PROMETHEUS_MULTIPROC_DIR</code> to a writable directory. The deploy.sh script configures this automatically.</P>

                  <H3>Stale Execution Sweeper</H3>
                  <P>A background task runs every 2 minutes to find executions stuck in RUNNING state for more than 10 minutes. These are marked as FAILED with <code className="text-cyan-300">failure_code: STALE_SWEEP</code>. Uses a PostgreSQL advisory lock to prevent duplicate sweeps across worker replicas.</P>

                  <H3>Alerts Page</H3>
                  <P>The <code className="text-cyan-300">/alerts</code> page in the web UI shows failed executions grouped by <code className="text-cyan-300">failure_code</code>. This makes it easy to identify systemic issues (e.g., all failures are LLM_RATE_LIMIT = you need a higher API tier).</P>

                  <H3>Alert Channels</H3>
                  <P>Configure where alerts are sent. Two channels are supported out of the box:</P>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 my-3">
                    <div className="p-3 bg-slate-900/40 border border-slate-700/40 rounded-lg">
                      <span className="text-sm font-medium text-white">Slack</span>
                      <p className="text-xs text-slate-400 mt-1">Webhook-based. Set per-tenant via <code className="text-cyan-300">/api/settings/tenant</code> or globally via <code className="text-cyan-300">SLACK_WEBHOOK_URL</code> env var. Messages include execution ID, agent name, failure code, and a direct link.</p>
                    </div>
                    <div className="p-3 bg-slate-900/40 border border-slate-700/40 rounded-lg">
                      <span className="text-sm font-medium text-white">Email</span>
                      <p className="text-xs text-slate-400 mt-1">SMTP-based. Configure via <code className="text-cyan-300">SMTP_HOST</code>, <code className="text-cyan-300">SMTP_PORT</code>, <code className="text-cyan-300">SMTP_USER</code> environment variables. Sends to the tenant admin email address.</p>
                    </div>
                  </div>

                  <H3>OpenTelemetry Tracing</H3>
                  <P>Distributed tracing spans from the API gateway through tool execution and external calls. Export to Jaeger, Zipkin, or any OTLP-compatible backend via the <code className="text-cyan-300">OTEL_EXPORTER_OTLP_ENDPOINT</code> environment variable.</P>

                  <H3>Sentry Integration</H3>
                  <P>Set <code className="text-cyan-300">SENTRY_DSN</code> to enable error tracking and performance monitoring. Captures unhandled exceptions, slow transactions (&gt;2s), and breadcrumbs from agent executions.</P>

                  <H3>SLOs</H3>
                  <div className="bg-slate-900/60 border border-slate-700/50 rounded-lg p-4 my-3 space-y-2 text-sm">
                    {[
                      { name: 'API Availability', target: '99.9%' },
                      { name: 'API Latency (p95)', target: '< 500ms' },
                      { name: 'Execution Success Rate', target: '> 95%' },
                      { name: 'Knowledge Search Latency (p95)', target: '< 2s' },
                    ].map((s) => (
                      <div key={s.name} className="flex items-center justify-between">
                        <span className="text-slate-300">{s.name}</span>
                        <Badge color="emerald">{s.target}</Badge>
                      </div>
                    ))}
                  </div>
                </DocSection>
              )}

              {/* ── Pre-Built Agents ── */}
              {sectionVisible('prebuilt-agents') && (
                <DocSection id="prebuilt-agents" icon={Boxes} title="49 Pre-Built Agents" isOpen={openSections.has('prebuilt-agents')} onToggle={() => toggleSection('prebuilt-agents')}>
                  <P>Abenix ships with 49 out-of-the-box agents (42 core + 7 OracleNet) seeded from YAML configurations. These cover engineering, finance, research, data, compliance, energy, and pipeline patterns.</P>

                  {[
                    {
                      category: 'Engineering',
                      color: 'cyan',
                      agents: [
                        { name: 'Code Assistant', slug: 'code-assistant', desc: 'Reviews code, explains algorithms, debugs errors across all major languages', tools: 'file_reader, web_search, calculator, code_executor, json_transformer, regex_extractor, text_analyzer, http_client' },
                        { name: 'Repo Analyzer', slug: 'repo-analyzer', desc: 'Deep-dive analysis of GitHub repositories: code structure, quality, dependencies', tools: 'github_tool, file_reader, code_executor, web_search, text_analyzer' },
                        { name: 'Pipeline Builder', slug: 'pipeline-builder', desc: 'Natural language pipeline builder: describe what you want, get a DAG config', tools: 'llm_call, json_transformer, schema_validator, code_executor' },
                        { name: 'Schema Architect', slug: 'schema-architect', desc: 'Designs optimal BigQuery schemas with medallion layers and Data Vault 2.0', tools: 'database_query, llm_call, code_executor, json_transformer' },
                        { name: 'Validation Agent', slug: 'validation-agent', desc: 'Data integrity: row counts, checksums, null distribution, schema conformance', tools: 'database_query, calculator, code_executor, data_exporter' },
                      ],
                    },
                    {
                      category: 'Research & Analysis',
                      color: 'purple',
                      agents: [
                        { name: 'Deep Research Agent', slug: 'deep-research', desc: 'Multi-source research with cross-referencing, consensus detection, citations', tools: 'web_search, llm_call, text_analyzer, json_transformer, http_client, data_merger, code_executor, calculator' },
                        { name: 'Research Assistant', slug: 'research-assistant', desc: 'Synthesizes findings from multiple sources with structured summaries', tools: 'web_search, llm_call, text_analyzer, calculator' },
                        { name: 'Competitive Analyst', slug: 'competitive-analyst', desc: 'Parallel competitive landscape analysis with comparative reports', tools: 'web_search, data_merger, llm_call, text_analyzer, json_transformer' },
                        { name: 'Document Analyzer', slug: 'document-analyzer', desc: 'Multi-format document analysis with cross-document comparison', tools: 'document_extractor, file_reader, text_analyzer, regex_extractor, web_search, calculator, data_exporter' },
                        { name: 'Data Analyst', slug: 'data-analyst', desc: 'Statistics, trends, outlier detection, correlation analysis, data quality', tools: 'file_reader, csv_analyzer, spreadsheet_analyzer, calculator, financial_calculator, web_search, json_transformer, code_executor' },
                      ],
                    },
                    {
                      category: 'Finance',
                      color: 'emerald',
                      agents: [
                        { name: 'Financial Modeler', slug: 'financial-modeler', desc: 'DCF valuations, LBO models, LCOE calculations, sensitivity analysis', tools: 'financial_calculator, calculator, csv_analyzer, risk_analyzer, market_data, code_executor' },
                        { name: 'Financial Analysis Pipeline', slug: 'financial-analysis-pipeline', desc: 'Multi-pass financial document analysis with cross-validation', tools: 'document_extractor, text_analyzer, calculator, risk_analyzer, llm_call, data_exporter' },
                        { name: 'Contract Risk Assessor', slug: 'contract-risk-assessor', desc: 'Risk assessment across contract types with financial exposure analysis', tools: 'document_extractor, text_analyzer, regex_extractor, risk_analyzer, calculator, web_search, data_exporter' },
                        { name: 'Fraud Detector', slug: 'fraud-detector', desc: 'Streaming fraud detection with rule-based checks and HITL approval gates', tools: 'redis_stream_consumer, time_series_analyzer, risk_analyzer, code_executor, human_approval' },
                        { name: 'Dynamic Pricing Engine', slug: 'dynamic-pricing-engine', desc: 'Real-time pricing with demand signals and Monte Carlo optimization', tools: 'redis_stream_consumer, time_series_analyzer, risk_analyzer, code_executor, market_data' },
                      ],
                    },
                    {
                      category: 'Data & Migration',
                      color: 'amber',
                      agents: [
                        { name: 'Data Mover', slug: 'data-mover', desc: 'Exasol to BigQuery via GCS with extraction, staging, loading, validation', tools: 'database_query, cloud_storage, code_executor, calculator, data_exporter' },
                        { name: 'Data Pipeline Engineer', slug: 'data-pipeline-engineer', desc: 'End-to-end data pipelines with profiling, cleansing, joining, enrichment', tools: 'csv_analyzer, json_transformer, database_query, database_writer, code_executor, schema_validator' },
                        { name: 'SQL Transformer', slug: 'sql-transformer', desc: 'SQL dialect transformation (Exasol to BigQuery Standard SQL)', tools: 'code_executor, llm_call, database_query' },
                        { name: 'Migration Orchestrator', slug: 'migration-orchestrator', desc: 'Enterprise migration: wave planning, scheduling, validation, rollbacks', tools: 'database_query, database_writer, code_executor, llm_call, calculator, integration_hub' },
                        { name: 'Migration Pipeline', slug: 'migration-pipeline', desc: '7-stage Exasol-to-BigQuery pipeline with validation gates', tools: 'llm_call, database_query, code_executor, calculator, data_exporter' },
                      ],
                    },
                    {
                      category: 'Communication',
                      color: 'cyan',
                      agents: [
                        { name: 'Email Composer', slug: 'email-composer', desc: 'Drafts professional emails for cold outreach, follow-ups, support', tools: 'text_analyzer, web_search, email_sender' },
                        { name: 'Email Triager', slug: 'email-triager', desc: 'Triages incoming emails by urgency and category with routing', tools: 'text_analyzer, regex_extractor, llm_call, integration_hub' },
                        { name: 'Content Writer', slug: 'content-writer', desc: 'Blog posts, marketing copy, social media with SEO optimization', tools: 'web_search, text_analyzer, llm_call, code_executor' },
                        { name: 'Meeting Scheduler', slug: 'meeting-scheduler', desc: 'Plans meetings across time zones with agendas and pre-briefs', tools: 'date_calculator, email_sender, web_search, calculator' },
                      ],
                    },
                    {
                      category: 'Operations & Compliance',
                      color: 'red',
                      agents: [
                        { name: 'Compliance Auditor', slug: 'compliance-auditor', desc: 'Regulatory compliance auditing with gap identification', tools: 'document_extractor, text_analyzer, regex_extractor, web_search, risk_analyzer' },
                        { name: 'HIPAA Processor', slug: 'hipaa-document-processor', desc: 'HIPAA-compliant clinical data extraction with PHI/PII redaction', tools: 'document_extractor, pii_redactor, text_analyzer, schema_validator' },
                        { name: 'Task Manager', slug: 'task-manager', desc: 'Task breakdown, progress tracking, blocker identification, reminders', tools: 'date_calculator, calculator, integration_hub, email_sender, memory_store' },
                        { name: 'Cloud Cost Optimizer', slug: 'cloud-cost-optimizer', desc: 'Cloud cost analysis with savings opportunities and right-sizing', tools: 'web_search, calculator, code_executor, data_exporter, market_data' },
                        { name: 'Supply Chain Monitor', slug: 'supply-chain-risk-monitor', desc: 'Continuous supply chain risk monitoring with Monte Carlo scoring', tools: 'redis_stream_consumer, web_search, risk_analyzer, time_series_analyzer, memory_store' },
                      ],
                    },
                    {
                      category: 'Industry',
                      color: 'purple',
                      agents: [
                        { name: 'Energy Market Analyst', slug: 'energy-market-analyst', desc: 'Wholesale electricity, renewables, capacity markets, price forecasting', tools: 'web_search, market_data, financial_calculator, time_series_analyzer' },
                        { name: 'IoT Sensor Monitor', slug: 'iot-sensor-monitor', desc: 'Real-time IoT monitoring with z-score anomaly detection and alerts', tools: 'redis_stream_consumer, time_series_analyzer, memory_store, integration_hub' },
                        { name: 'Predictive Maintenance', slug: 'predictive-maintenance', desc: 'Equipment degradation profiling, failure forecasting, work orders', tools: 'redis_stream_consumer, time_series_analyzer, memory_store, code_executor' },
                      ],
                    },
                    {
                      category: 'Pipeline Patterns',
                      color: 'slate',
                      agents: [
                        { name: 'Smart Routing', slug: 'smart-routing-pipeline', desc: 'AI-powered ticket routing with LLM classification into tracks', tools: 'llm_call, text_analyzer, json_transformer' },
                        { name: 'Quality Gate', slug: 'quality-gate-pipeline', desc: 'Confidence-gated analysis: auto-process or route to human review', tools: 'llm_call, text_analyzer, human_approval' },
                        { name: 'Error Resilient', slug: 'error-resilient-pipeline', desc: 'Fault-tolerant pipeline with error branches and continue-on-fail', tools: 'http_client, llm_call, code_executor' },
                        { name: 'Customer Support', slug: 'customer-support-pipeline', desc: 'Classification, priority scoring, sentiment, team routing, draft responses', tools: 'llm_call, text_analyzer, calculator, integration_hub' },
                      ],
                    },
                    {
                      category: 'OracleNet Decision Engine',
                      color: 'cyan',
                      agents: [
                        { name: 'OracleNet Pipeline', slug: 'oraclenet-pipeline', desc: 'Master pipeline orchestrating 6 agents for strategic decision analysis', tools: 'llm_call, web_search, data_merger' },
                        { name: 'Historian', slug: 'oraclenet-historian', desc: 'Finds 3-5 historical analogies with outcomes', tools: 'web_search, llm_call, text_analyzer' },
                        { name: 'Current State', slug: 'oraclenet-current-state', desc: 'Real-time market, competitive, regulatory intelligence', tools: 'web_search, llm_call, tavily_search' },
                        { name: 'Stakeholder Sim', slug: 'oraclenet-stakeholder-sim', desc: 'Predicts stakeholder group reactions', tools: 'llm_call, web_search' },
                        { name: 'Second-Order', slug: 'oraclenet-second-order', desc: 'Cascading effects 2-3 levels deep', tools: 'llm_call, web_search' },
                        { name: 'Contrarian', slug: 'oraclenet-contrarian', desc: "Devil's advocate: finds every failure mode", tools: 'llm_call, web_search' },
                        { name: 'Synthesizer', slug: 'oraclenet-synthesizer', desc: 'Final Decision Brief with probability-weighted scenarios', tools: 'llm_call, data_merger' },
                      ],
                    },
                  ].map((group) => (
                    <div key={group.category} className="my-4">
                      <H4>{group.category}</H4>
                      <div className="space-y-1 mt-2">
                        {group.agents.map((a) => (
                          <div key={a.slug} className="p-3 bg-slate-900/40 border border-slate-700/40 rounded-lg">
                            <div className="flex items-center gap-2 mb-1">
                              <Bot className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                              <span className="text-sm font-medium text-slate-200">{a.name}</span>
                              <code className="text-[10px] text-slate-600 ml-auto">{a.slug}</code>
                            </div>
                            <p className="text-xs text-slate-400 ml-5.5 mb-1">{a.desc}</p>
                            <div className="ml-5.5 flex flex-wrap gap-1">
                              {a.tools.split(', ').slice(0, 6).map((t) => (
                                <code key={t} className="text-[10px] bg-slate-800/60 border border-slate-700/40 rounded px-1.5 py-0.5 text-cyan-400">{t}</code>
                              ))}
                              {a.tools.split(', ').length > 6 && (
                                <span className="text-[10px] text-slate-500">+{a.tools.split(', ').length - 6} more</span>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </DocSection>
              )}

              {/* ── Security & Compliance ── */}
              {sectionVisible('prebuilt-agents') && (
                <div className="mt-6 bg-slate-800/30 backdrop-blur-xl border border-slate-700/50 rounded-xl p-6">
                  <div className="flex items-center gap-3 mb-4">
                    <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-red-500/20 to-red-600/20 border border-red-500/20 flex items-center justify-center">
                      <Lock className="w-5 h-5 text-red-400" />
                    </div>
                    <h3 className="font-semibold text-lg text-slate-100">Security & Compliance</h3>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-4">
                    {[
                      'RS256 asymmetric JWT signing',
                      'API key SHA-256 hashing at rest',
                      'RBAC with tenant isolation',
                      'Rate limiting per endpoint',
                      'CORS whitelist configuration',
                      'Sandboxed code execution',
                      'Input sanitization on all endpoints',
                      'Encrypted secrets in K8s',
                      'Content moderation gate (pre/post LLM)',
                      'PII detection and redaction',
                      'GDPR data export and deletion',
                      'Configurable data retention policies',
                    ].map((m) => (
                      <div key={m} className="flex items-center gap-2 text-sm text-slate-300">
                        <Check className="w-4 h-4 text-emerald-400 shrink-0" />
                        {m}
                      </div>
                    ))}
                  </div>

                  <H4>GDPR Endpoints</H4>
                  <div className="space-y-0.5 my-3">
                    <EndpointRow method="GET" path="/api/account/data-export" desc="Export all user data (GDPR Art. 20)" />
                    <EndpointRow method="DELETE" path="/api/account/data-delete" desc="Delete all user data (GDPR Art. 17)" />
                    <EndpointRow method="GET" path="/api/settings/privacy" desc="View data processing settings" />
                    <EndpointRow method="PUT" path="/api/settings/privacy" desc="Update consent and retention policies" />
                  </div>

                  <H4>Data Retention</H4>
                  <P>Configurable per-tenant. Execution logs, conversation history, and agent memory can auto-expire after 30, 60, 90, 180 days, or indefinite. Audit logs are immutable and queryable via the analytics API.</P>
                </div>
              )}

              {/* ── Troubleshooting ── */}
              {sectionVisible('troubleshooting') && (
                <DocSection id="troubleshooting" icon={Bug} title="Troubleshooting" isOpen={openSections.has('troubleshooting')} onToggle={() => toggleSection('troubleshooting')}>
                  {[
                    { q: 'Docker Compose fails to start', a: 'Ensure Docker Desktop is running and ports 3000, 8000, 5432, 6379, 7687 are free. Run `docker compose down -v` to clean up stale volumes, then `./start.sh` again.' },
                    { q: 'Cannot connect to database', a: 'Check that PostgreSQL is running: `docker compose ps postgres`. Verify DATABASE_URL in .env. Note: the API uses asyncpg while Alembic uses psycopg2 -- two different connection strings are needed.' },
                    { q: 'Agent execution times out', a: 'Default timeout is 120 seconds. Increase via AGENT_EXECUTION_TIMEOUT_SECONDS. Also check max_iterations -- agents hitting the iteration limit will be slower. Give agents enough tools to avoid excessive retries.' },
                    { q: 'JWT token expired errors', a: 'Access tokens expire after 15 minutes. Use /api/auth/refresh with your refresh token. Refresh tokens last 7 days.' },
                    { q: 'Neo4j connection refused', a: 'Neo4j takes 30-60 seconds to start. Check `docker compose logs neo4j`. Verify NEO4J_URI is bolt://localhost:7687.' },
                    { q: 'Celery worker not processing tasks', a: 'Ensure Redis is running and CELERY_BROKER_URL points to it. In Kubernetes, verify the worker pod can reach the Redis service. Check: `kubectl logs deployment/abenix-worker -n abenix`.' },
                    { q: 'Executions stuck in RUNNING', a: 'The stale execution sweeper runs every 2 minutes. If executions are stuck longer, check worker health and Redis connectivity. Stuck executions are swept with failure_code=STALE_SWEEP.' },
                    { q: 'Prometheus metrics empty in Grafana', a: 'For multi-worker deployments, set PROMETHEUS_MULTIPROC_DIR to a writable directory. Without it, each worker has its own metric registry and Grafana only sees one.' },
                    { q: 'Helm deployment fails on minikube', a: 'Ensure minikube has 8GB RAM and 4 CPUs: `minikube start --memory=8192 --cpus=4`. Use FRESH=true to do a clean deploy if prior state is corrupt.' },
                    { q: 'API returns 422 Validation Error', a: 'Check the request body against the OpenAPI schema at /docs. Common issues: missing required fields, wrong types, invalid enum values. The error includes field-level details.' },
                    { q: 'Moderation gate blocking everything', a: 'Check your policy thresholds -- default_threshold of 0.1 is too aggressive for most use cases. Start with 0.5 and tune down. Use /api/moderation/vet to test content before enabling.' },
                    { q: 'MCP server connection fails', a: 'Verify the MCP server URL is reachable from the agent runtime container. In Kubernetes, use service DNS names. Check that the MCP server implements the protocol spec correctly.' },
                  ].map((item) => (
                    <div key={item.q} className="py-3 border-b border-slate-700/30 last:border-0">
                      <div className="flex items-start gap-2">
                        <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                        <div>
                          <div className="text-sm font-medium text-white">{item.q}</div>
                          <div className="text-xs text-slate-400 mt-1 leading-relaxed">{item.a}</div>
                        </div>
                      </div>
                    </div>
                  ))}
                </DocSection>
              )}

              {/* ── Keyboard Shortcuts ── */}
              {sectionVisible('keyboard-shortcuts') && (
                <DocSection id="keyboard-shortcuts" icon={Keyboard} title="Keyboard Shortcuts" isOpen={openSections.has('keyboard-shortcuts')} onToggle={() => toggleSection('keyboard-shortcuts')}>
                  <P>Abenix includes a command palette and keyboard shortcuts for power users.</P>
                  <div className="space-y-0.5 my-3">
                    {[
                      { keys: 'Cmd/Ctrl + K', action: 'Open command palette' },
                      { keys: 'Cmd/Ctrl + /', action: 'Toggle sidebar' },
                      { keys: 'Cmd/Ctrl + N', action: 'Create new agent' },
                      { keys: 'Cmd/Ctrl + E', action: 'Open executions' },
                      { keys: 'Cmd/Ctrl + Enter', action: 'Send message / Execute agent' },
                      { keys: 'Cmd/Ctrl + Shift + P', action: 'Open pipeline builder' },
                      { keys: 'Cmd/Ctrl + Shift + K', action: 'Open knowledge manager' },
                      { keys: 'Cmd/Ctrl + Shift + T', action: 'Open tool library' },
                      { keys: 'Cmd/Ctrl + ,', action: 'Open settings' },
                      { keys: 'Esc', action: 'Close modal / Cancel operation' },
                    ].map((s) => (
                      <div key={s.keys} className="flex items-center gap-4 py-2 border-b border-slate-700/30 last:border-0">
                        <div className="flex gap-1 shrink-0">
                          {s.keys.split(' + ').map((k, i) => (
                            <span key={i}>
                              {i > 0 && <span className="text-slate-600 mx-0.5">+</span>}
                              <kbd className="px-2 py-1 bg-slate-800/80 border border-slate-600/50 rounded text-xs font-mono text-slate-300">{k.trim()}</kbd>
                            </span>
                          ))}
                        </div>
                        <span className="text-sm text-slate-400">{s.action}</span>
                      </div>
                    ))}
                  </div>
                </DocSection>
              )}
            </div>
          )}

          {/* ── No results ── */}
          {filteredSections.length === 0 && (
            <div className="text-center py-20">
              <Search className="w-12 h-12 text-slate-600 mx-auto mb-4" />
              <p className="text-slate-400 text-lg">No sections match &quot;{searchQuery}&quot;</p>
              <button onClick={() => setSearchQuery('')} className="mt-3 text-cyan-400 hover:text-cyan-300 text-sm">Clear search</button>
            </div>
          )}
        </main>
      </div>

      {/* ── Footer ── */}
      <footer className="border-t border-slate-800/50 py-8 px-6">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <img src="/logo.svg" alt="Abenix" className="w-6 h-6" />
            <span className="text-sm text-slate-500">Abenix Developer Documentation</span>
          </div>
          <div className="flex items-center gap-4 text-sm text-slate-500">
            <a href="/" className="hover:text-slate-300 transition-colors">Home</a>
            <a href="/demo" className="hover:text-slate-300 transition-colors">Demo</a>
            <span>90+ Tools</span>
            <span>49 Agents</span>
            <span>42 API Routers</span>
          </div>
        </div>
      </footer>

      {/* ── Back to top ── */}
      <AnimatePresence>
        {showBackToTop && (
          <motion.button
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.8 }}
            onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
            className="fixed bottom-8 right-8 z-50 w-12 h-12 rounded-full bg-gradient-to-r from-cyan-500 to-purple-600 text-white flex items-center justify-center shadow-lg shadow-cyan-500/20 hover:shadow-cyan-500/40 transition-shadow"
            aria-label="Back to top"
          >
            <ArrowUp className="w-5 h-5" />
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  );
}
