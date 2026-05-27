'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ChevronDown, Upload, Brain, Shield, Activity, MessageSquare,
  Database, Layers, Zap, GitBranch, Cpu, BarChart3, Scale,
  Search, FileText, TrendingUp, Globe, Calculator, AlertTriangle,
  Sparkles, Sunrise, Handshake, AlertOctagon, Receipt, Telescope,
  GitCompareArrows, ShieldCheck, BookOpen, Network, Lock,
  CheckCircle2, Flame, Gauge, Target, DollarSign, ArrowRight,
  Clock, Lightbulb, Play, FileCode2, Key, LineChart,
  Compass, Users, Sigma, Binary,
} from 'lucide-react';

function Section({ title, icon: Icon, children, defaultOpen = false }: { title: string; icon: any; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-slate-800/50 transition-colors">
        <div className="flex items-center gap-3">
          <Icon className="w-5 h-5 text-emerald-400" />
          <span className="text-sm font-semibold text-white">{title}</span>
        </div>
        <ChevronDown className={`w-4 h-4 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.2 }}>
            <div className="px-5 pb-5 text-sm text-slate-300 leading-relaxed space-y-4">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Badge({ children, color = 'emerald' }: { children: React.ReactNode; color?: string }) {
  const colors: Record<string, string> = {
    emerald: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
    cyan:    'bg-cyan-500/10 text-cyan-300 border-cyan-500/30',
    amber:   'bg-amber-500/10 text-amber-300 border-amber-500/30',
    purple:  'bg-purple-500/10 text-purple-300 border-purple-500/30',
    red:     'bg-red-500/10 text-red-300 border-red-500/30',
    pink:    'bg-pink-500/10 text-pink-300 border-pink-500/30',
    teal:    'bg-teal-500/10 text-teal-300 border-teal-500/30',
    indigo:  'bg-indigo-500/10 text-indigo-300 border-indigo-500/30',
    violet:  'bg-violet-500/10 text-violet-300 border-violet-500/30',
    slate:   'bg-slate-700/30 text-slate-300 border-slate-600/30',
  };
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono border ${colors[color]}`}>
      {children}
    </span>
  );
}

function Code({ children }: { children: React.ReactNode }) {
  return <code className="px-1.5 py-0.5 rounded bg-slate-900/80 border border-slate-700/50 text-emerald-300 text-[11px] font-mono">{children}</code>;
}

type AgentSpec = {
  slug: string;
  title: string;
  icon: any;
  accent: string;          // e.g. 'emerald'
  model: 'gemini-2.5-pro' | 'gemini-2.0-flash';
  surface: string;          // where output shows up
  oneLiner: string;
  tools: string[];
  workflow: string[];       // numbered steps
  output: string[];         // key JSON keys / metrics
  whyItWorks?: string;      // optional explanation of the "magic"
};

function AgentCard({ a }: { a: AgentSpec }) {
  const Icon = a.icon;
  const badgeColors: Record<string, string> = {
    emerald: 'border-emerald-500/30 bg-emerald-500/5',
    amber:   'border-amber-500/30 bg-amber-500/5',
    cyan:    'border-cyan-500/30 bg-cyan-500/5',
    purple:  'border-purple-500/30 bg-purple-500/5',
    red:     'border-red-500/30 bg-red-500/5',
    pink:    'border-pink-500/30 bg-pink-500/5',
    teal:    'border-teal-500/30 bg-teal-500/5',
    indigo:  'border-indigo-500/30 bg-indigo-500/5',
    violet:  'border-violet-500/30 bg-violet-500/5',
    slate:   'border-slate-500/30 bg-slate-500/5',
    orange:  'border-orange-500/30 bg-orange-500/5',
  };
  const iconColors: Record<string, string> = {
    emerald: 'text-emerald-400',
    amber: 'text-amber-400',
    cyan: 'text-cyan-400',
    purple: 'text-purple-400',
    red: 'text-red-400',
    pink: 'text-pink-400',
    teal: 'text-teal-400',
    indigo: 'text-indigo-400',
    violet: 'text-violet-400',
    slate: 'text-slate-400',
    orange: 'text-orange-400',
  };
  return (
    <div className={`rounded-xl border ${badgeColors[a.accent]} p-4 space-y-3`}>
      <div className="flex items-start gap-3">
        <div className={`w-10 h-10 rounded-lg border ${badgeColors[a.accent]} flex items-center justify-center flex-shrink-0`}>
          <Icon className={`w-5 h-5 ${iconColors[a.accent]}`} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h4 className="text-sm font-semibold text-white">{a.title}</h4>
            <Badge color={a.model === 'gemini-2.5-pro' ? 'violet' : 'cyan'}>{a.model}</Badge>
          </div>
          <div className="flex items-center gap-2 mt-1">
            <Code>{a.slug}</Code>
          </div>
          <p className="text-xs text-slate-300 mt-2 leading-relaxed">{a.oneLiner}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">Workflow</p>
          <ol className="list-decimal list-inside text-[11px] text-slate-400 leading-relaxed space-y-1">
            {a.workflow.map((step, i) => <li key={i}>{step}</li>)}
          </ol>
        </div>
        <div className="space-y-3">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">Tools</p>
            <div className="flex flex-wrap gap-1">
              {a.tools.map(t => <Badge key={t} color="slate">{t}</Badge>)}
            </div>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">Output</p>
            <div className="flex flex-wrap gap-1">
              {a.output.map(o => <Badge key={o} color={a.accent}>{o}</Badge>)}
            </div>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between text-[10px] text-slate-500 pt-2 border-t border-slate-700/40">
        <span>→ Surfaces in <span className="text-slate-300">{a.surface}</span></span>
        {a.whyItWorks && (
          <span className="italic text-slate-400">{a.whyItWorks}</span>
        )}
      </div>
    </div>
  );
}

// ─── Data ──────────────────────────────────────────────────────────────

const EXTRACTION_AGENTS: AgentSpec[] = [
  {
    slug: 'contractiq-extractor',
    title: 'Contract Extractor (multi-pass, self-discovering)',
    icon: FileText,
    accent: 'emerald',
    model: 'gemini-2.5-pro',
    surface: 'Contract detail · Deal Clusters · all downstream workflows',
    oneLiner: 'The foundational agent. Reads the full contract text and produces the complete structured data model: parties, clauses, assets, events, risk categories, deal clusters and deal legs.',
    tools: ['(prompt-only, no tools)'],
    workflow: [
      'Receives contract text + a taxonomy hint with the top-N cluster/leg/field keys this user has already used across the portfolio.',
      'Runs ONE long-form call on Gemini 2.5 Pro with 65k output tokens so nothing is truncated.',
      'Self-discovers cluster types (power_physical, power_swap, gas_physical, certificate_physical, fee_cash, …) and deal-leg names inside each cluster.',
      'Reuses stable key names across contracts instead of inventing new ones — the taxonomy hint pins vocabulary.',
      'Emits a strict JSON with every section populated; API parses + commits + updates the self-learning taxonomy in the same transaction.',
    ],
    output: ['parties', 'clauses[]', 'assets[]', 'events[]', 'risk_assessment[]', 'deal_clusters{}', 'commercial/technical/legal/financial_terms[]'],
    whyItWorks: 'Taxonomy grows with every contract → cluster names stay stable portfolio-wide.',
  },
  {
    slug: 'contractiq-deep-extractor',
    title: 'Deep Extractor (long-tail field rescue)',
    icon: Telescope,
    accent: 'cyan',
    model: 'gemini-2.0-flash',
    surface: 'Contract detail · Extracted Data tab',
    oneLiner: 'Second pass focused on sections the primary extractor flagged as thin. Optional; triggered on demand when completeness_score is low.',
    tools: ['portfolio_energy_contracts', 'database_query', 'financial_calculator', 'text_analyzer'],
    workflow: [
      'Takes the primary extraction + the list of missing_fields.',
      'Pulls the raw_text snippet per missing section and re-analyses it with a targeted prompt.',
      'Appends any newly found fields to the contract detail without overwriting the primary extraction.',
    ],
    output: ['recovered_fields[]', 'completeness_delta'],
  },
  {
    slug: 'contractiq-functional-analysis',
    title: 'Functional Analysis (SEE-BV taxonomy)',
    icon: Network,
    accent: 'purple',
    model: 'gemini-2.0-flash',
    surface: 'Contract detail · Functional Analysis tab',
    oneLiner: 'Maps every clause into the SEE-BV functional taxonomy: 11 functional categories (Electricity Delivery, Gas Delivery, Payment, Volumetric, Price, Imbalance, Termination, Credit & Collateral, Force Majeure, Constraint, Events) with a cross-clause DAG.',
    tools: ['graph_builder'],
    workflow: [
      'Walks the persisted clauses for the contract.',
      'Classifies each into one of the 11 categories with a prefix code (ED, GD, PM, VT, PR, …) and sub-attributes.',
      'Builds a DAG of cross-references ("termination depends on credit event") and per-clause event chains.',
      'Returns the graph JSON which the Contract Detail page renders as clickable nodes.',
    ],
    output: ['categories{}', 'clause_nodes[]', 'dag_edges[]', 'events[]'],
    whyItWorks: 'Mirrors how big energy desks actually file contracts — same taxonomy their lawyers use.',
  },
];

const INSIGHTS_AGENTS: AgentSpec[] = [
  {
    slug: 'contractiq-executive-briefing',
    title: 'Daily Executive Briefing',
    icon: Sunrise,
    accent: 'amber',
    model: 'gemini-2.0-flash',
    surface: 'Insights Hub → Briefing',
    oneLiner: 'Writes the morning CFO briefing: overnight MtM move, alerts crossed, top 3-5 prioritised actions.',
    tools: ['portfolio_energy_contracts', 'database_query', 'entso_e', 'ember_climate', 'ecb_rates', 'financial_calculator', 'current_time'],
    workflow: [
      'Anchors "today" via current_time.',
      'Pulls portfolio summary + last 24h of contractiq_market_alerts + upcoming events (next 30 days).',
      'Pulls a current power price + FX rate for context.',
      'Synthesises a mobile-readable markdown body with metrics + top_actions.',
    ],
    output: ['headline', 'metrics{}', 'body_markdown', 'top_actions[]'],
  },
  {
    slug: 'contractiq-renewal-copilot',
    title: 'Renewal Negotiation Copilot',
    icon: Handshake,
    accent: 'emerald',
    model: 'gemini-2.0-flash',
    surface: 'Insights Hub → Renewals',
    oneLiner: 'For upcoming renewals: market context + historical pricing + counterparty intel + a 3-position term sheet (aggressive / middle / fallback) with NPV uplift vs status quo.',
    tools: ['portfolio_energy_contracts', 'database_query', 'entso_e', 'ember_climate', 'ecb_rates', 'tavily_search', 'financial_calculator'],
    workflow: [
      'Loads the contract + days_to_expiry.',
      'Queries market tools for current forwards vs contract strike.',
      'Runs 1–2 Tavily searches on the counterparty for recent news / earnings.',
      'Produces a term_sheet with three positions, each with cost + NPV_uplift, and a full negotiation packet in markdown.',
    ],
    output: ['market_context{}', 'historical_pricing{}', 'counterparty_intel{}', 'term_sheet{aggressive,middle,fallback}', 'npv_uplift', 'full_packet_markdown'],
  },
  {
    slug: 'contractiq-force-majeure-monitor',
    title: 'Force Majeure Monitor',
    icon: AlertOctagon,
    accent: 'red',
    model: 'gemini-2.0-flash',
    surface: 'Insights Hub → Force Majeure',
    oneLiner: 'Scans for FM-triggering events — curtailment, pipeline outage, FX shock, regulation — and auto-drafts notices that cite the exact clause numbers.',
    tools: ['database_query', 'entso_e', 'ember_climate', 'ecb_rates', 'tavily_search', 'financial_calculator', 'current_time'],
    workflow: [
      'Checks market tools for unusual movement (curtailment flags, pipeline outage news).',
      'Cross-references the contract\'s force_majeure clause text for coverage.',
      'If applicable, drafts a formal FM notice referencing the clause number + deadline_to_notify.',
      'Row is created with status="awaiting_review" for HITL sign-off.',
    ],
    output: ['trigger_type', 'applicable_clauses[]', 'financial_impact_usd', 'draft_notice', 'deadline_to_notify'],
  },
  {
    slug: 'contractiq-settlement-reconciler',
    title: 'Settlement Reconciliation',
    icon: Receipt,
    accent: 'cyan',
    model: 'gemini-2.0-flash',
    surface: 'Insights Hub → Reconciliation',
    oneLiner: 'Recomputes an invoice against the contract\'s pricing, escalation, indexation and FX terms. Flags line-item variances and drafts a dispute letter when the variance > 1%.',
    tools: ['portfolio_energy_contracts', 'database_query', 'financial_calculator', 'entso_e', 'ember_climate', 'ecb_rates'],
    workflow: [
      'Reads the invoice + contract.',
      'Recomputes expected amount line-by-line (price × volume, escalation, FX).',
      'Flags discrepancies with variance_pct; auto-drafts a dispute letter if variance > 1%.',
    ],
    output: ['invoice_amount', 'expected_amount', 'variance_amount', 'line_items[]', 'discrepancies[]', 'dispute_letter'],
  },
  {
    slug: 'contractiq-clause-anomaly',
    title: 'Clause Anomaly Detector',
    icon: Telescope,
    accent: 'purple',
    model: 'gemini-2.0-flash',
    surface: 'Insights Hub → Anomalies',
    oneLiner: 'Statistical outlier detection across your portfolio. Flags clauses that deviate materially from your baseline (e.g. 7-day termination when portfolio avg is 90 days).',
    tools: ['database_query', 'knowledge_search', 'portfolio_energy_contracts'],
    workflow: [
      'Enumerates clauses in the user\'s portfolio bucketed by type.',
      'Computes baseline values (notice periods, cure windows, liability caps).',
      'For each clause, scores anomaly_score ∈ [0,1] relative to the baseline.',
      'Persists only anomalies with verified FKs (hallucinated IDs are filtered).',
    ],
    output: ['scanned_clauses', 'anomalies_found', 'anomalies[]{severity, anomaly_score, explanation, benchmark}'],
  },
  {
    slug: 'contractiq-clause-benchmarker',
    title: 'Clause Benchmarker',
    icon: Scale,
    accent: 'indigo',
    model: 'gemini-2.5-pro',
    surface: 'Insights Hub → Benchmarking',
    oneLiner: 'Benchmarks a specific clause against (a) market standard (EFET / AIPN / ISDA model forms + published commentary via Tavily) and (b) peer clauses in your own portfolio. Returns a stance rating, deviation score, peer comparison, recommendations, and concrete suggested replacement language.',
    tools: ['tavily_search', 'web_search', 'database_query', 'portfolio_energy_contracts', 'current_time'],
    workflow: [
      'Receives clause text + type + contract type + jurisdiction, plus up to 10 peer clauses from your portfolio appended by the API.',
      'Runs 1–2 Tavily queries to establish market standard for that clause type in that contract class.',
      'Compares target clause against market standard and each peer; assigns stance (favourable / standard / adverse / aggressive / lenient) and deviation_score ∈ [-1, +1].',
      'Produces recommendations with priority (critical / high / medium / low) and concrete redline-ready suggested_language.',
    ],
    output: ['stance', 'deviation_score', 'market_standard_summary', 'peer_comparisons[]', 'recommendations[]', 'suggested_language', 'sources[]', 'narrative'],
    whyItWorks: 'Uses your own portfolio as the peer set — benchmarks are tailored, not generic.',
  },
  {
    slug: 'contractiq-version-diff',
    title: 'Semantic Version Diff',
    icon: GitCompareArrows,
    accent: 'pink',
    model: 'gemini-2.0-flash',
    surface: 'Insights Hub → Version Diff',
    oneLiner: 'Compares two contract versions clause-by-clause semantically — not just textually. Classifies each change as tightened / loosened / added / removed with an impact rating.',
    tools: ['portfolio_energy_contracts', 'database_query'],
    workflow: [
      'Loads both contracts\' clause sets grouped by clause_type.',
      'Pairs semantically-matching clauses across versions.',
      'For each pair emits { change_kind, before, after, impact, rationale }.',
      'Aggregates to an overall_impact: favourable / neutral / adverse / mixed.',
    ],
    output: ['summary', 'changes[]', 'overall_impact'],
  },
  {
    slug: 'contractiq-stress-test',
    title: 'Stress Test Simulator',
    icon: Activity,
    accent: 'orange',
    model: 'gemini-2.0-flash',
    surface: 'Insights Hub → Stress Test',
    oneLiner: 'Full Monte Carlo simulation (1k–10k iterations) with power / FX / credit shocks. Returns P5/P50/P95 NPV, VaR(95%), expected shortfall, and the worst 10 scenarios with driver attribution.',
    tools: ['portfolio_energy_contracts', 'database_query', 'entso_e', 'ember_climate', 'ecb_rates', 'financial_calculator', 'code_executor'],
    workflow: [
      'Loads the target contract / portfolio + historical volatilities.',
      'Computes the base NPV with financial_calculator.',
      'Hands the distribution parameters to code_executor (real Python with numpy/scipy) to run N iterations.',
      'Computes p5/p50/p95 + VaR + expected_shortfall + histogram bins.',
      'Identifies the worst 10 iterations and attributes them to input drivers.',
    ],
    output: ['base_npv', 'p5/p50/p95_npv', 'var_95', 'expected_shortfall', 'distribution[]', 'worst_scenarios[]'],
    whyItWorks: 'The Monte Carlo runs in real Python, not LLM tokens — fast, precise, auditable.',
  },
  {
    slug: 'contractiq-hedge-advisor',
    title: 'Hedge Advisor',
    icon: ShieldCheck,
    accent: 'teal',
    model: 'gemini-2.0-flash',
    surface: 'Insights Hub → Hedge',
    oneLiner: 'For each floating exposure, designs swap / collar / zero-cost-collar / option structures. Prices each via financial_calculator (Black-Scholes) and recommends the best fit for the stated risk tolerance.',
    tools: ['portfolio_energy_contracts', 'database_query', 'entso_e', 'ember_climate', 'ecb_rates', 'financial_calculator'],
    workflow: [
      'Identifies the exposure: power_price / fx / interest_rate / carbon.',
      'Builds 3–5 candidate structures parameterised by tenor, strike, and premium.',
      'Prices each with financial_calculator; fills in residual_risk.',
      'Ranks against risk_tolerance (low / medium / high) and recommends one.',
    ],
    output: ['exposure_type', 'structures[]', 'recommended_structure', 'rationale'],
  },
];

const VALUATION_AGENTS: AgentSpec[] = [
  {
    slug: 'contractiq-price-forecaster',
    title: 'Price Forecaster (forward curves)',
    icon: LineChart,
    accent: 'indigo',
    model: 'gemini-2.5-pro',
    surface: 'Valuation page → Forward Curves panel',
    oneLiner: 'Produces a monthly forward price curve (1–60 months) for any energy or FX market blending live market data, sentiment from news, and explicit fundamental drivers.',
    tools: ['current_time', 'entso_e', 'ember_climate', 'ecb_rates', 'yahoo_finance', 'tavily_search', 'web_search', 'financial_calculator', 'database_query'],
    workflow: [
      'Picks spot + observable forwards from entso_e / ember_climate / yahoo_finance / ecb_rates.',
      'If methodology includes sentiment: runs 1–2 Tavily queries over the last 60 days → sentiment_score ∈ [-1, +1] → small mid-tenor adjustment (typically |x|<5%).',
      'If methodology includes fundamentals: enumerates 3–5 drivers (storage, wind utilisation, LNG send-out, CBAM, rates) with curve-shape effect.',
      'Adds confidence bands of ±8–20% depending on tenor.',
      'Any tenor without an observed price is tagged data_quality="estimated" — never fabricated.',
    ],
    output: ['curve[]', 'fundamental_drivers[]', 'sentiment_score', 'sentiment_adjustment_pct', 'narrative', 'data_sources[]'],
  },
  {
    slug: 'contractiq-portfolio-valuator',
    title: 'Portfolio Valuator (Mark-to-Market)',
    icon: TrendingUp,
    accent: 'emerald',
    model: 'gemini-2.5-pro',
    surface: 'Valuation page → Portfolio MtM panel',
    oneLiner: 'Marks the whole portfolio to market. Walks every deal_cluster in every contract, prices each leg against the latest forward curve, rolls up to per-contract, per-cluster-type, and portfolio MtM + Greeks.',
    tools: ['database_query', 'financial_calculator', 'current_time'],
    workflow: [
      'Receives portfolio context + the latest forward curves compressed into the prompt (first 12 points per market).',
      'Walks each deal_cluster → each deal_leg → values it against the right curve.',
      'Converts to USD using the FX curve.',
      'Computes 3 portfolio-level Greeks: delta_power, delta_gas, delta_eurusd.',
      'Identifies top_risks — the 3–5 most unhedged / OOTM positions.',
    ],
    output: ['portfolio_mtm', 'per_contract[]', 'cluster_type_totals{}', 'greeks{}', 'top_risks[]'],
  },
  {
    slug: 'contractiq-top-monitor',
    title: 'Take-or-Pay Monitor',
    icon: Gauge,
    accent: 'amber',
    model: 'gemini-2.5-pro',
    surface: 'Valuation page → T-o-P Monitor panel',
    oneLiner: 'Projects year-end lifted volume and flags T-o-P / ACQ / UIOSI shortfalls before they become $-million problems. Recommends lift vs pay-and-make-up.',
    tools: ['database_query', 'financial_calculator', 'current_time'],
    workflow: [
      'Anchors today + year-end.',
      'For each gas / capacity / physical-power contract extracts ACQ, T-o-P %, unit price, make-up right tenor.',
      'Projects year-end lifted volume = YTD × 365/days_elapsed.',
      'shortfall_units = max(0, threshold - projected). shortfall_usd = shortfall_units × price.',
      'Classifies severity (critical/high/medium) and recommends lift-more vs accept-T-o-P-with-make-up.',
    ],
    output: ['alerts[]', 'portfolio_shortfall_usd', 'narrative'],
  },
];

const ORCHESTRATION_AGENTS: AgentSpec[] = [
  {
    slug: 'contractiq-pipeline',
    title: 'Master Extraction Pipeline',
    icon: GitBranch,
    accent: 'cyan',
    model: 'gemini-2.0-flash',
    surface: 'Internal — runs on upload',
    oneLiner: 'The orchestrator. Chains the extractor + functional analysis + market context + knowledge-graph indexing in a single upload workflow.',
    tools: ['llm_call', 'agent_step', 'document_extractor', 'file_reader', 'text_analyzer', 'code_executor', 'entso_e', 'ember_climate', 'ecb_rates', 'tavily_search', 'financial_calculator', 'database_query'],
    workflow: [
      'Runs document_extractor to turn PDF → structured text.',
      'Hands off to contractiq-extractor via agent_step.',
      'Kicks off knowledge_graph indexing (Cognify) as a non-blocking background task.',
      'Emits SSE status events for every sub-agent so the UI can render a live progress strip.',
    ],
    output: ['(chains of agent outputs)'],
  },
  {
    slug: 'contractiq-market-monitor',
    title: 'Market Monitor',
    icon: Activity,
    accent: 'cyan',
    model: 'gemini-2.0-flash',
    surface: 'Market & Risk page → Alerts',
    oneLiner: 'Periodic (or on-demand) sweep. Pulls live power + carbon + FX, computes portfolio PnL vs strike, and writes price-breach / FX-risk / market-favorable alerts back to the DB.',
    tools: ['llm_call', 'agent_step', 'entso_e', 'ember_climate', 'ecb_rates', 'financial_calculator', 'database_query', 'database_writer', 'current_time'],
    workflow: [
      'Loads contracts + current live market data.',
      'For each contract: computes PnL per MWh vs current spot, flags breaches of tolerance.',
      'Writes ContractIQMarketAlert rows via database_writer so the Market & Risk page surfaces them instantly.',
    ],
    output: ['alerts_created', 'snapshots{}'],
  },
  {
    slug: 'contractiq-market-simulator',
    title: 'Market Simulator',
    icon: Sigma,
    accent: 'violet',
    model: 'gemini-2.0-flash',
    surface: 'Simulations page',
    oneLiner: 'Scenario engine. Combines weather_simulator + scenario_planner + sentiment_analyzer to project portfolio impact under narrative shocks ("cold winter + 30% gas spike + regulator U-turn on CBAM").',
    tools: ['portfolio_energy_contracts', 'weather_simulator', 'sentiment_analyzer', 'scenario_planner', 'financial_calculator', 'risk_analyzer', 'entso_e', 'ember_climate', 'ecb_rates', 'graph_builder'],
    workflow: [
      'Builds the scenario DAG from the user\'s free-text prompt.',
      'Draws samples from the weather/price/sentiment engines.',
      'Feeds into risk_analyzer + financial_calculator for P&L impact.',
      'Renders a scenario tree the UI displays.',
    ],
    output: ['scenario_tree{}', 'pnl_impact', 'narrative'],
  },
  {
    slug: 'contractiq-chat',
    title: 'Cross-Contract Chat',
    icon: MessageSquare,
    accent: 'emerald',
    model: 'gemini-2.0-flash',
    surface: 'Chat page',
    oneLiner: 'Your conversational interface to the whole portfolio. Cross-references structured data + semantic search + the contract graph for questions like "which PPA has the weakest curtailment protection?".',
    tools: ['portfolio_energy_contracts', 'graph_explorer', 'knowledge_search', 'financial_calculator', 'entso_e', 'ember_climate', 'ecb_rates'],
    workflow: [
      'Decomposes the user\'s question into sub-queries.',
      'Fires portfolio_energy_contracts for structured, knowledge_search for semantic, graph_explorer for relationship questions.',
      'Cross-references results and always cites specific contracts by title in the answer.',
    ],
    output: ['natural-language answer with contract citations'],
  },
];

export default function ContractIQHelpPage() {
  return (
    <div className="p-6">
      <div className="max-w-6xl mx-auto space-y-6">
        {/* Hero header */}
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center">
              <BookOpen className="w-5 h-5 text-emerald-400" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white">E&C-Copilot — The Agent Atlas</h1>
              <p className="text-sm text-slate-400">Every agent in the platform — what it does, what tools it uses, and how it thinks.</p>
            </div>
          </div>
        </motion.div>

        {/* Stats strip */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {[
            { label: 'AI Agents',          value: '19',  icon: Cpu,       color: 'text-violet-400' },
            { label: 'on Gemini 2.5 Pro',   value: '5',   icon: Sparkles,  color: 'text-indigo-400' },
            { label: 'Insights Workflows',  value: '11',  icon: Lightbulb, color: 'text-emerald-400' },
            { label: 'Generic Tools',       value: '13',  icon: Database,  color: 'text-cyan-400' },
            { label: 'Typical cost/run',    value: '~$0.05', icon: DollarSign, color: 'text-amber-400' },
          ].map(s => (
            <div key={s.label} className="rounded-xl border border-slate-800/50 bg-slate-900/30 p-4">
              <div className="flex items-center gap-2 mb-2">
                <s.icon className={`w-4 h-4 ${s.color}`} />
                <span className="text-[10px] text-slate-500 uppercase tracking-wider">{s.label}</span>
              </div>
              <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
            </div>
          ))}
        </div>

        {/* ── Zero-to-Expert primer — read this first if you've never traded a commodity in your life ── */}
        <Section title="Commodities 101 — from zero to expert in 10 minutes" icon={Lightbulb} defaultOpen={true}>
          <p className="text-slate-300">
            New to this world? Start here. By the end of this section you&apos;ll understand <em>what</em> the app does,
            <em> why</em> it exists, <em>who</em> uses it, and <em>every term</em> you&apos;ll see in the rest of the
            documentation. We&apos;ll start with a fruit-basket analogy and end with you reading a real forward curve.
          </p>

          {/* The 60-second mental model */}
          <h4 className="text-white font-semibold pt-3">The 60-second mental model</h4>
          <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4 my-2">
            <p className="text-sm text-slate-200 leading-relaxed">
              Imagine you run a chain of bakeries. You need flour every week — and flour prices move. You can
              <strong className="text-white"> buy now</strong> at today&apos;s price (and store it), <strong className="text-white">lock in a future price</strong> with a paper contract, or <strong className="text-white">pay whatever the market is</strong> next week. The cheaper choice depends on the weather (will the harvest be good?), demand (will pasta-makers buy lots of flour?), and your storage capacity.
            </p>
            <p className="text-sm text-slate-200 leading-relaxed mt-2">
              Energy companies face the same problem, but with <strong className="text-white">gas, electricity, LNG, and
              carbon credits</strong>. They have customers who will draw demand later (homes, factories, retail
              accounts), they own storage and power plants, and they trade contracts to lock in margins. The price
              swings can be 10× bigger than flour, and the decisions are sometimes hourly.
            </p>
            <p className="text-sm text-slate-300 leading-relaxed mt-2">
              <strong className="text-emerald-300">E&amp;C-Copilot tells you what to expect</strong> (demand forecasts), <strong className="text-emerald-300">what it&apos;s worth</strong> (price curves with confidence intervals), <strong className="text-emerald-300">where things look mispriced</strong> (anomaly flags), and <strong className="text-emerald-300">what to do about it</strong> (recommendations that wait for human sign-off). It&apos;s a copilot for the team that has to decide whether to buy 1 GWh of gas at 9am or wait.
            </p>
          </div>

          {/* What is a commodity */}
          <h4 className="text-white font-semibold pt-3">What is a &quot;commodity&quot;?</h4>
          <p>
            A commodity is something <em>standardised</em> enough that anyone&apos;s tonne of wheat is interchangeable
            with anyone else&apos;s. Oil, natural gas, coal, electricity, copper, gold — all commodities. Energy companies
            care about four of them, which become the four hubs in the sidebar:
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 my-2">
            {[
              { name: 'Natural Gas', icon: Flame, color: 'orange', what: 'Methane piped across Europe. Heats homes, runs power plants. Priced in €/MWh.', who: 'Households, factories, power-plant operators, traders.' },
              { name: 'Power (Electricity)', icon: Zap, color: 'amber', what: 'Electricity. Can\'t store it (much), so price moves hour-by-hour with weather and demand. Priced in €/MWh.', who: 'Every business and every home, plus heavy industry.' },
              { name: 'LNG', icon: Globe, color: 'cyan', what: 'Liquefied natural gas — gas cooled to -162°C so it fits in a ship. Lets gas trade between continents.', who: 'Exporters (US, Qatar), importers (Europe, Japan), shipping companies.' },
              { name: 'Environmental certificates', icon: Sparkles, color: 'emerald', what: 'Paper rights: EUAs (EU carbon allowances), GoOs (proves 1 MWh was renewable), biomethane certs. They make pollution costly and green energy valuable.', who: 'Every polluter (must surrender EUAs), every renewable generator (sells GoOs).' },
            ].map(c => (
              <div key={c.name} className={`rounded-xl border border-${c.color}-500/30 bg-${c.color}-500/5 p-4`}>
                <div className="flex items-center gap-2 mb-2">
                  <c.icon className={`w-4 h-4 text-${c.color}-400`} />
                  <p className="text-sm font-semibold text-white">{c.name}</p>
                </div>
                <p className="text-xs text-slate-300 mb-1.5"><strong className="text-slate-200">What:</strong> {c.what}</p>
                <p className="text-xs text-slate-400"><strong className="text-slate-300">Who cares:</strong> {c.who}</p>
              </div>
            ))}
          </div>

          {/* How trading actually works */}
          <h4 className="text-white font-semibold pt-3">How energy trading actually works (with a real example)</h4>
          <p>
            Let&apos;s walk through one trade. It&apos;s September. A retail energy supplier signs up a million households
            in Belgium, promising them gas heating all winter at <strong>€42/MWh fixed</strong>. They have to deliver
            gas in January, February, March. Where do they get it?
          </p>
          <ol className="list-decimal pl-5 space-y-1.5 text-sm text-slate-300">
            <li><strong className="text-white">Forecast demand.</strong> How many MWh will those households actually use? Depends on the winter. The forecaster gives a P50 (most likely) of 320 GWh/day, P10 296, P90 341.</li>
            <li><strong className="text-white">Look at the forward curve.</strong> The price for &quot;gas delivered in January&quot; today is €34.82/MWh. That&apos;s the J+1 forward. February is €35.10. They can lock these prices in <em>today</em> for delivery later.</li>
            <li><strong className="text-white">Compare to their selling price.</strong> Households pay €42/MWh, gas costs €35. That&apos;s a €7/MWh margin — but only if demand lands on P50. If everyone has a cold winter (P90 = 341 GWh/day), they need more gas than they bought, and the &quot;balancing&quot; price could spike to €80/MWh. Suddenly they lose €38/MWh on the extra volume.</li>
            <li><strong className="text-white">Hedge.</strong> They buy a bit more than P50 to cover that risk. They might also buy a swap (a paper contract that pays them the difference if January spot goes above €50). Costs €0.50/MWh in premium, saves a fortune in the bad scenario.</li>
            <li><strong className="text-white">Cover unexpected.</strong> A cold snap hits in November. The forecaster updates: P90 now 370 GWh/day. Buy more on the spot market. Slightly worse price, but the size is small because earlier hedges did most of the work.</li>
          </ol>
          <p className="text-xs text-slate-400 italic">
            That&apos;s it. The whole job — forecast, mark, hedge, watch — happens for every commodity, every desk,
            every day. E&amp;C-Copilot wires the four steps into one workflow so the team isn&apos;t copy-pasting
            between Excel, Bloomberg, and three internal tools.
          </p>

          {/* Where things trade */}
          <h4 className="text-white font-semibold pt-3">Where things trade — &quot;hubs&quot; and &quot;exchanges&quot;</h4>
          <p>
            You can&apos;t literally meet a gas trader in Amsterdam. Trading happens at <em>hubs</em> — virtual
            marketplaces. The most important European ones:
          </p>
          <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 overflow-x-auto my-2">
            <table className="w-full text-xs">
              <thead className="bg-slate-900/60 text-slate-400">
                <tr>
                  <th className="text-left px-3 py-2 font-medium">Hub</th>
                  <th className="text-left px-3 py-2 font-medium">What</th>
                  <th className="text-left px-3 py-2 font-medium">Why it matters</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ['TTF (Netherlands)',  'Gas',   'The reference price for European gas. When you read &quot;TTF €34&quot; in the news, that\'s the front-month here.'],
                  ['THE (Germany)',      'Gas',   'Germany\'s merged hub. Trades close to TTF; the difference is &quot;basis&quot;.'],
                  ['CEGH (Austria)',     'Gas',   'Central European gas. Storage-heavy, feeds Hungary, Slovakia.'],
                  ['PSV (Italy)',        'Gas',   'Italian gas. Influenced by African pipelines + LNG terminals.'],
                  ['EEX (Germany)',      'Power', 'Power + carbon exchange. Day-ahead auction sets tomorrow\'s 24 hourly prices.'],
                  ['Nord Pool (Nordics)','Power', 'Hydro-heavy Nordic power. Pioneer of the day-ahead auction model.'],
                  ['EPEX SPOT',          'Power', 'Central Western Europe power (DE, FR, NL, BE).'],
                  ['EU ETS',             'Carbon','Where EUAs (carbon allowances) are auctioned and traded.'],
                  ['JKM (Asia)',         'LNG',   'The Asian LNG benchmark. Tells you if cargoes go to Japan or Europe.'],
                ].map(r => (
                  <tr key={r[0]} className="border-t border-slate-800/60">
                    <td className="px-3 py-2 text-white font-medium">{r[0]}</td>
                    <td className="px-3 py-2 text-cyan-300">{r[1]}</td>
                    <td className="px-3 py-2 text-slate-300">{r[2]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-slate-400">
            A <strong>TSO</strong> (transmission system operator) is the company that physically moves the gas or power
            — they publish flow data the platform reads.
          </p>

          {/* The "forward curve" concept */}
          <h4 className="text-white font-semibold pt-3">Reading a forward curve (the most important picture in this job)</h4>
          <p>
            A <strong>forward curve</strong> is the line that says &quot;today, the market thinks gas delivered in
            January costs X, in February Y, in March Z, ...&quot;. It bends with seasonality (winter is more
            expensive), with supply news, with weather forecasts.
          </p>
          <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-4 my-2">
            <svg viewBox="0 0 600 200" className="w-full h-auto max-w-[600px]">
              <defs>
                <marker id="hp101-arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" />
                </marker>
              </defs>
              <line x1="40" y1="170" x2="570" y2="170" stroke="#475569" />
              <line x1="40" y1="170" x2="40" y2="30" stroke="#475569" />
              <text x="305" y="195" textAnchor="middle" fill="#94a3b8" fontSize="11">time (next 6 months)</text>
              <text x="22" y="100" textAnchor="middle" fill="#94a3b8" fontSize="11" transform="rotate(-90 22 100)">price (€/MWh)</text>

              {[ ['M+1', 80, 32], ['M+2', 160, 35], ['Q+1', 240, 39], ['Q+2', 320, 34], ['Cal+1', 400, 33], ['Cal+2', 480, 31] ].map((p, i, arr) => {
                const x = 40 + (p[1] as number);
                const y = 170 - ((p[2] as number) - 28) * 9;
                const next = arr[i + 1];
                const nx = next ? 40 + (next[1] as number) : null;
                const ny = next ? 170 - ((next[2] as number) - 28) * 9 : null;
                return (
                  <g key={p[0] as string}>
                    {nx !== null && ny !== null && <line x1={x} y1={y} x2={nx} y2={ny} stroke="#10b981" strokeWidth="2.5" />}
                    <circle cx={x} cy={y} r="5" fill="#0B0F19" stroke="#10b981" strokeWidth="2.5" />
                    <text x={x} y={185} textAnchor="middle" fill="#94a3b8" fontSize="10">{p[0]}</text>
                    <text x={x} y={y - 10} textAnchor="middle" fill="#a7f3d0" fontSize="10">€{p[2]}</text>
                  </g>
                );
              })}

              <text x="135" y="60" fill="#fbbf24" fontSize="10">winter premium →</text>
              <path d="M 135 65 L 200 105" stroke="#fbbf24" strokeWidth="1" markerEnd="url(#hp101-arr)" />
              <text x="380" y="60" fill="#22d3ee" fontSize="10">contango: future cheaper than near</text>
              <path d="M 380 70 L 420 95" stroke="#22d3ee" strokeWidth="1" markerEnd="url(#hp101-arr)" />
            </svg>
          </div>
          <ul className="list-disc pl-5 space-y-1 text-sm text-slate-300">
            <li><strong className="text-white">M+1</strong> means &quot;delivery 1 month from today&quot;. <strong>Q+1</strong> = next quarter. <strong>Cal+1</strong> = next calendar year (12 months).</li>
            <li><strong className="text-white">Winter premium:</strong> Q+1 (Jan-Mar) is higher than M+2 — that&apos;s the seasonal pattern. People burn more gas when it&apos;s cold.</li>
            <li><strong className="text-white">Contango / backwardation:</strong> if the curve slopes up (further = pricier), it&apos;s in contango — usually means oversupply now. If it slopes down (further = cheaper), it&apos;s in backwardation — usually means shortage now.</li>
            <li><strong className="text-white">Storage trade:</strong> buy gas in summer at €31, sell winter at €39. The €8 spread is what storage owners earn.</li>
          </ul>

          {/* The fan chart */}
          <h4 className="text-white font-semibold pt-3">The fan chart — uncertainty visualised</h4>
          <p>
            A single forecast number is a lie. The world is uncertain. The Forecaster page draws a <strong>fan chart</strong>:
            a middle line (the best guess) sandwiched between a top edge (90th-percentile — &quot;could be this high&quot;)
            and a bottom edge (10th-percentile — &quot;could be this low&quot;).
          </p>
          <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-4 my-2">
            <svg viewBox="0 0 600 200" className="w-full h-auto max-w-[600px]">
              <defs>
                <linearGradient id="hp101-fan" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#10b981" stopOpacity="0.30" />
                  <stop offset="100%" stopColor="#10b981" stopOpacity="0.05" />
                </linearGradient>
              </defs>
              <line x1="40" y1="170" x2="570" y2="170" stroke="#475569" />
              <line x1="40" y1="170" x2="40" y2="30" stroke="#475569" />

              {(() => {
                const pts = [40, 110, 180, 250, 320, 390, 460, 530].map((x, i) => {
                  const p50 = 100 - i * 4 + Math.sin(i) * 5;
                  return { x, p10: p50 + 35, p50: p50, p90: p50 - 35 };
                });
                const top = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.p90}`).join(' ');
                const bot = pts.slice().reverse().map(p => `L ${p.x} ${p.p10}`).join(' ');
                return (
                  <>
                    <path d={`${top} ${bot} Z`} fill="url(#hp101-fan)" />
                    <path d={pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.p50}`).join(' ')} stroke="#10b981" strokeWidth="2.5" fill="none" />
                    {pts.map(p => <circle key={p.x} cx={p.x} cy={p.p50} r="3" fill="#0B0F19" stroke="#10b981" strokeWidth="2" />)}
                  </>
                );
              })()}
              <text x="80" y="50" fill="#22c55e" fontSize="10">P90 — worst-case high</text>
              <text x="80" y="130" fill="#22c55e" fontSize="10">P50 — best guess (median)</text>
              <text x="80" y="180" fill="#22c55e" fontSize="10">P10 — worst-case low</text>
              <text x="305" y="195" textAnchor="middle" fill="#94a3b8" fontSize="11">days ahead</text>
            </svg>
          </div>
          <p>
            <strong className="text-white">Why P10 / P90 not min/max?</strong> Because the absolute extremes are too
            paranoid (you&apos;d hedge against an asteroid strike). P10 / P90 covers the 80% middle of likely
            outcomes — what you actually plan around.
          </p>

          {/* SHAP drivers */}
          <h4 className="text-white font-semibold pt-3">SHAP drivers — why did the model say that?</h4>
          <p>
            A black-box AI saying &quot;buy&quot; is useless if the trader can&apos;t check the reasoning. <strong>SHAP</strong>
            (SHapley Additive exPlanations) decomposes a prediction into per-feature contributions: <em>&quot;the
            forecast says 318 GWh/day; of that, HDD added +12, weekday added +9, churn took 3 off, customer-mix added 5...&quot;</em>
            The bars line up to the final number, like a financial-statement walk.
          </p>
          <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-4 my-2">
            <svg viewBox="0 0 600 200" className="w-full h-auto max-w-[600px]">
              <line x1="300" y1="20" x2="300" y2="180" stroke="#475569" strokeDasharray="2 3" />
              <text x="300" y="14" textAnchor="middle" fill="#94a3b8" fontSize="10">baseline</text>
              {[
                { label: 'HDD next 7 days', value:  12, y: 40, color: '#22c55e' },
                { label: 'Weekday indicator', value:  9, y: 65, color: '#22c55e' },
                { label: 'Customer mix shift', value:  5, y: 90, color: '#22c55e' },
                { label: 'Price elasticity', value: -3, y: 115, color: '#ef4444' },
                { label: 'Retention churn drag', value: -3, y: 140, color: '#ef4444' },
              ].map(d => {
                const w = d.value * 10;
                return (
                  <g key={d.label}>
                    <text x="290" y={d.y + 4} textAnchor="end" fill="#cbd5e1" fontSize="10">{d.label}</text>
                    <rect x={d.value > 0 ? 300 : 300 + w} y={d.y - 4} width={Math.abs(w)} height="10" fill={d.color} opacity="0.7" />
                    <text x={d.value > 0 ? 305 + w : 295 + w} y={d.y + 4} fill={d.color} fontSize="10">{d.value > 0 ? '+' : ''}{d.value}</text>
                  </g>
                );
              })}
              <text x="300" y="175" textAnchor="middle" fill="#22c55e" fontSize="11" fontWeight="bold">Final: 318 GWh/day</text>
            </svg>
          </div>

          {/* Anomaly + IsolationForest */}
          <h4 className="text-white font-semibold pt-3">Anomalies — &quot;when one signal disagrees with the others&quot;</h4>
          <p>
            If the fundamental balance says €33/MWh, the econometric model says €34, but the ML model says €37 — one
            of them is seeing something the others missed. That gap is the <strong>residual</strong>. When the
            residual is more than 2 standard deviations from zero (statistically rare), it&apos;s an <strong>anomaly</strong>
            — a possible mispricing. <strong>IsolationForest</strong> is the algorithm that scores how unusual the
            current point is vs history. Big score = real flag. The flag routes to the Approvals queue for a human
            to decide if it&apos;s a trade or a glitch.
          </p>

          {/* Drift + PSI */}
          <h4 className="text-white font-semibold pt-3">Drift — &quot;the model is going stale&quot;</h4>
          <p>
            The world isn&apos;t stationary. A model trained on 2022 data may not work in 2026 because the customer
            mix changed, the geopolitics changed, the gas-vs-power substitution changed. <strong>Drift</strong>
            measures how different the inputs the model sees today are from what it was trained on. <strong>PSI</strong>
            (population stability index) is the standard metric: below 0.10 = stable, 0.10-0.25 = watch, above 0.25
            for 7 days = automatic retraining proposal.
          </p>

          {/* Approvals + HITL */}
          <h4 className="text-white font-semibold pt-3">Why &quot;a human approves it&quot; matters</h4>
          <p>
            Forecasts and recommendations are advisory. A model saying &quot;sell 50 GWh of Q1&quot; doesn&apos;t
            execute the trade. Every actionable recommendation goes into an <strong>Approvals queue</strong> where
            the head of the relevant desk signs off (or overrides) before anything hits the broker. This is
            <strong> HITL</strong> — Human In The Loop. It catches the rare cases where the model is wrong, and it
            also gives a clean paper trail for the regulator.
          </p>

          {/* The 5 modules — beginner pass */}
          <h4 className="text-white font-semibold pt-3">The 5 modules — in plain English</h4>
          <p className="text-sm">
            With those concepts under your belt, here&apos;s what each module of the platform actually does, in the
            simplest words possible. The technical deep-dive comes in the next section.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 my-2">
            {[
              { mod: 'M1', name: 'Data Fabric', accent: 'cyan',  plain: 'The plumbing. Every price tick, weather forecast, sensor reading, news headline flows through here, gets cleaned, and lands in one place. Without this, the rest of the app is guessing.' },
              { mod: 'M2', name: 'Forecaster', accent: 'emerald', plain: 'Predicts how much gas / power your customers will actually use, days to a year ahead. Gives you a best guess and an uncertainty band, plus explains which factors moved the prediction.' },
              { mod: 'M3', name: 'Price Engine', accent: 'violet', plain: 'Asks &quot;what should gas in January cost?&quot; three different ways (supply-demand balance, statistical model, machine-learning model) and blends them. When the three disagree, that&apos;s a tradeable signal.' },
              { mod: 'M4', name: 'Performance & Backtest', accent: 'cyan', plain: 'Watches every model in production. Tracks accuracy. Flags when a model is going stale. Re-runs models on history to check &quot;if I had used this strategy last year, would it have made money?&quot;' },
              { mod: 'M5', name: 'Workbench & Recommendations', accent: 'amber', plain: 'Where the analyst lives. SHAP explanations, what-if sliders, annotations, overrides. The recommendation engine turns the outputs of M2 + M3 + M4 into clear &quot;buy / sell / hedge / hold&quot; cards that wait for the desk head to approve.' },
            ].map(m => (
              <div key={m.mod} className={`rounded-xl border border-${m.accent}-500/30 bg-${m.accent}-500/5 p-4`}>
                <div className="flex items-baseline gap-2 mb-2">
                  <Badge color={m.accent as any}>{m.mod}</Badge>
                  <h4 className="text-sm font-semibold text-white">{m.name}</h4>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed">{m.plain}</p>
              </div>
            ))}
          </div>

          {/* The personas */}
          <h4 className="text-white font-semibold pt-3">Who actually uses this — the four personas</h4>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 my-2">
            {[
              { who: 'Short-term trader',       sees: 'Forecaster (1-7 day horizon) + Price Engine (front-month) + live mispricing flags. Acts in seconds to minutes.', accent: 'cyan' },
              { who: 'Analyst / quant',         sees: 'Workbench (SHAP, sensitivity), Performance tab (model accuracy, drift). Improves the models, signs off on overrides.', accent: 'amber' },
              { who: 'Portfolio / risk manager',sees: 'Price Engine (forward curves across all hubs), Recommendations, contract panel. Tracks book P&L. Owns hedging strategy.', accent: 'violet' },
              { who: 'Originator / structurer', sees: 'Forecaster (annual offtake by customer segment), Contracts (Take-or-Pay, indexation), Commodity hubs. Prices new long-term deals.', accent: 'emerald' },
            ].map(p => (
              <div key={p.who} className={`rounded-xl border border-${p.accent}-500/30 bg-${p.accent}-500/5 p-4`}>
                <p className="text-sm font-semibold text-white mb-1.5">{p.who}</p>
                <p className="text-xs text-slate-400 leading-relaxed">{p.sees}</p>
              </div>
            ))}
          </div>

          {/* Quick glossary */}
          <h4 className="text-white font-semibold pt-3">Pocket glossary — every term you&apos;ll meet</h4>
          <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-slate-900/60 text-slate-400">
                <tr>
                  <th className="text-left px-3 py-2 font-medium">Term</th>
                  <th className="text-left px-3 py-2 font-medium">Plain English</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ['Spot price',         'The price for delivery right now / very soon (today, this hour).'],
                  ['Forward price',      'The price agreed today for delivery in the future (next month, next year).'],
                  ['Forward curve',      'The whole line of forward prices across delivery dates.'],
                  ['Hub',                'A virtual marketplace where a commodity trades. TTF for gas in Netherlands, EEX for German power, etc.'],
                  ['Basis',              'The price difference between two hubs (e.g. THE minus TTF). Tells you where the cheap gas is.'],
                  ['Spread',             'A price difference. Front-month minus back-month spread is the storage P&L.'],
                  ['Offtake',            'How much gas / power a customer actually takes off the grid. Demand, measured.'],
                  ['Load profile',       'The hourly shape of a customer\'s demand (households peak at 7pm; factories run flat 24/7).'],
                  ['HDD / CDD',          'Heating-Degree-Day / Cooling-Degree-Day. How many degrees below 18°C (HDD) or above (CDD). Drives gas + power demand.'],
                  ['Day-ahead market',   'Tomorrow\'s 24 hourly power prices auctioned at noon today. Sets the reference for everything.'],
                  ['Intraday market',    'Continuous power trading from day-ahead close until 1 hour before delivery. Where weather surprises get hedged.'],
                  ['Balancing market',   'The TSO\'s last-resort market to keep supply = demand in real time. Highest price; you don\'t want to end up here unhedged.'],
                  ['Take-or-Pay',        'Contract clause: you commit to buy a minimum volume; if you don\'t lift it, you still pay. Common in long-term gas/LNG deals.'],
                  ['LNG send-out',       'The rate at which an LNG terminal turns liquid back into gas and pushes it into the pipeline.'],
                  ['EUA',                'EU Allowance — the right to emit 1 tonne of CO₂. Polluters must surrender one per tonne emitted. Trades on EEX.'],
                  ['GoO',                'Guarantee of Origin — proves 1 MWh of electricity was made from a specific renewable. Sold separately from the electricity.'],
                  ['Clean-spark spread', 'Profit margin of a gas-fired power plant: power price − (gas × heat rate) − (EUA × emission rate). Positive = plant runs profitably.'],
                  ['BESS',               'Battery Energy Storage System. Charges when power is cheap, discharges when expensive. Also earns balancing-reserve income.'],
                  ['CCGT',               'Combined-Cycle Gas Turbine — efficient gas-fired power plant. Most common gas-to-power technology in Europe.'],
                  ['Storage cycling',    'Buy gas in summer (cheap), inject into storage, withdraw + sell in winter (expensive). The seasonal spread is the P&L.'],
                  ['Linepack',           'Gas pressurised inside the pipeline network — short-term storage built into the grid.'],
                  ['TSO',                'Transmission System Operator. The neutral party that physically operates the gas pipes or the power grid.'],
                  ['Hedge',              'A trade you do to reduce risk on another position. Buy a swap to lock in a price; sell a forward to offset stored inventory.'],
                  ['VaR / CVaR',         'Value-at-Risk / Conditional VaR. Statistical loss estimates for your portfolio: VaR = &quot;95% chance you lose ≤ X tomorrow&quot;, CVaR = &quot;if you do hit the bad 5%, average loss is Y&quot;.'],
                  ['MAE / RMSE / MAPE',  'Forecast accuracy metrics. MAE = average error in units. RMSE = error penalised more heavily for big mistakes. MAPE = average error as a % of actual.'],
                  ['P10 / P50 / P90',    '10th, 50th, 90th percentile of a probabilistic forecast. P50 = best guess, P10/P90 = uncertainty band.'],
                  ['SHAP',               'A way to explain why a model made a prediction — attributes the prediction to each input feature with a + or − number.'],
                  ['IsolationForest',    'A ML algorithm that finds anomalies. Trains on what\'s normal; flags points that don\'t fit.'],
                  ['BayesianRidge',      'A regression model that gives you a point prediction and an uncertainty around it. Common for forward-curve fair-value.'],
                  ['XGBoost',            'A widely-used machine-learning algorithm. Strong on tabular data; good for offtake forecasting.'],
                  ['LSTM',               'A neural network family good at time-series. Used here for industrial baseload sequence modelling.'],
                  ['Prophet',            'A simple, robust forecaster from Meta. Good for series with strong seasonality and holidays (like residential demand).'],
                  ['PSI',                'Population Stability Index. Measures distribution shift between training data and live data. Trigger for retraining.'],
                  ['HITL',               'Human In The Loop. An approval step where a person reviews a model output before it triggers a real action.'],
                  ['Approval',           'A workflow step where a designated human (head of desk, head of risk) signs off on a model-generated recommendation.'],
                  ['Backtest',           'Running a model on historical data to estimate how well it would have performed.'],
                  ['Point-in-time join', 'Joining data so each row only sees what was knowable at that historical moment. Prevents lookahead bias in backtests.'],
                ].map(r => (
                  <tr key={r[0]} className="border-t border-slate-800/60 hover:bg-slate-800/30">
                    <td className="px-3 py-2 text-white font-medium whitespace-nowrap">{r[0]}</td>
                    <td className="px-3 py-2 text-slate-300">{r[1]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Try-it-yourself path */}
          <h4 className="text-white font-semibold pt-3">Become an expert in 10 clicks</h4>
          <ol className="list-decimal pl-5 space-y-1.5 text-sm text-slate-300">
            <li>Open <Code>/data-fabric</Code>. Look at the connector table — that&apos;s every source the system pulls from. Note the lag and quality columns; that&apos;s your data trust dashboard.</li>
            <li>Click <Code>/forecaster</Code>. Drag the &quot;Temperature shift&quot; slider to −4°C. Watch the fan chart lift. Read the SHAP drivers on the right — the HDD bar grew. That&apos;s the model telling you why.</li>
            <li>Switch to <Code>/price-engine</Code>. Pick TTF. Drag the &quot;Fundamental&quot; weight to 100%. The curve shifts. Drag back. Switch hub to DE-Power. Note that for power the three layers disagree more than for gas — power is harder.</li>
            <li>Click on the <Code>/commodities/gas</Code> hub. Same curve, but only for gas hubs, with contracts + signals filtered. This is the trader&apos;s home page.</li>
            <li>Open <Code>/workbench</Code>. Pick a forecast. Read the SHAP waterfall. Note one driver you don&apos;t agree with. Type a value in &quot;Override&quot; with your rationale. That overrides creates an Approval — go check <Code>/approvals</Code>.</li>
            <li>Open <Code>/model-performance</Code>. Pick &quot;offtake_residential&quot;. Note the PSI is 0.31 (drifting). Read the MAPE timeline — see the upward slope. That&apos;s a model getting stale.</li>
            <li>Open <Code>/recommendations</Code>. Read one. Note the thesis, the drivers, the PV, the confidence. Click &quot;Open workbench&quot; to see the SHAP that produced the rec.</li>
            <li>Open <Code>/contracts</Code>. Pick any long-term gas contract. Read the Take-or-Pay clause. Note how the platform extracted the volume + price + indexation.</li>
            <li>Open <Code>/risk</Code>. Read the VaR / CVaR — that&apos;s the portfolio loss estimate for tomorrow. If you hedged properly, VaR is small.</li>
            <li>Come back to this help page. Read the technical section below — it&apos;ll all make sense now.</li>
          </ol>
        </Section>

        {/* ── Forecasting & Trading platform — 5 modules ── */}
        <Section title="Forecasting & Trading platform — the 5-module suite" icon={TrendingUp} defaultOpen={true}>
          <p className="text-slate-300">
            On top of the contract intelligence layer, E&amp;C-Copilot bundles five modules that handle the full
            short-term-to-strategic trading workflow: ingesting market &amp; operational data, predicting offtake,
            marking forward curves, validating with analysts, and watching every model&apos;s accuracy in production.
          </p>

          <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-4 my-2 overflow-x-auto">
            <svg viewBox="0 0 1100 360" className="w-full h-auto min-w-[900px]">
              <defs>
                <marker id="hp5-arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="#475569" />
                </marker>
                <linearGradient id="hp5-grad" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor="#10b981" />
                  <stop offset="100%" stopColor="#06b6d4" />
                </linearGradient>
              </defs>
              <text x="550" y="22" textAnchor="middle" fill="#94a3b8" fontSize="11" fontWeight="bold">THE 5-MODULE ARCHITECTURE</text>

              <rect x="20" y="50" width="170" height="270" rx="12" fill="#0f172a" stroke="#f97316" />
              <text x="105" y="74" textAnchor="middle" fill="#fed7aa" fontSize="13" fontWeight="bold">EXTERNAL SOURCES</text>
              {['Exchanges', 'TSOs / ISOs', 'Weather', 'SCADA / Telemetry', 'Geopolitical news', 'Macro indicators', 'Asset bookings', 'Client offtake'].map((s, i) => (
                <text key={s} x={105} y={106 + i * 26} textAnchor="middle" fill="#fdba74" fontSize="11">{s}</text>
              ))}

              <rect x="220" y="50" width="180" height="270" rx="12" fill="#0f172a" stroke="url(#hp5-grad)" strokeWidth="2" />
              <text x="310" y="74" textAnchor="middle" fill="#a7f3d0" fontSize="13" fontWeight="bold">M1 · Data Fabric</text>
              <text x="310" y="100" textAnchor="middle" fill="#94a3b8" fontSize="10">22 connectors</text>
              <text x="310" y="120" textAnchor="middle" fill="#94a3b8" fontSize="10">Adapter registry</text>
              <text x="310" y="140" textAnchor="middle" fill="#94a3b8" fontSize="10">Anomaly imputer</text>
              <text x="310" y="160" textAnchor="middle" fill="#94a3b8" fontSize="10">TimescaleDB lakehouse</text>
              <text x="310" y="180" textAnchor="middle" fill="#94a3b8" fontSize="10">Point-in-time feature</text>
              <text x="310" y="200" textAnchor="middle" fill="#94a3b8" fontSize="10">store</text>
              <text x="310" y="285" textAnchor="middle" fill="#cbd5e1" fontSize="11" fontWeight="bold">→ /data-fabric</text>

              <rect x="430" y="50" width="180" height="130" rx="12" fill="#0f172a" stroke="#10b981" />
              <text x="520" y="74" textAnchor="middle" fill="#a7f3d0" fontSize="13" fontWeight="bold">M2 · Forecaster</text>
              <text x="520" y="100" textAnchor="middle" fill="#94a3b8" fontSize="10">Residential · Industrial</text>
              <text x="520" y="116" textAnchor="middle" fill="#94a3b8" fontSize="10">Storage cycling</text>
              <text x="520" y="132" textAnchor="middle" fill="#94a3b8" fontSize="10">XGB · Prophet · LSTM</text>
              <text x="520" y="148" textAnchor="middle" fill="#94a3b8" fontSize="10">Fan chart · SHAP drivers</text>
              <text x="520" y="171" textAnchor="middle" fill="#cbd5e1" fontSize="11" fontWeight="bold">→ /forecaster</text>

              <rect x="430" y="190" width="180" height="130" rx="12" fill="#0f172a" stroke="#a78bfa" />
              <text x="520" y="214" textAnchor="middle" fill="#ddd6fe" fontSize="13" fontWeight="bold">M3 · Price Engine</text>
              <text x="520" y="240" textAnchor="middle" fill="#94a3b8" fontSize="10">Fundamental + Econometric</text>
              <text x="520" y="256" textAnchor="middle" fill="#94a3b8" fontSize="10">+ ML hybrid blend</text>
              <text x="520" y="272" textAnchor="middle" fill="#94a3b8" fontSize="10">Cold winter · Pipe outage</text>
              <text x="520" y="288" textAnchor="middle" fill="#94a3b8" fontSize="10">Mispricing flags (z &gt; 2σ)</text>
              <text x="520" y="311" textAnchor="middle" fill="#cbd5e1" fontSize="11" fontWeight="bold">→ /price-engine</text>

              <rect x="640" y="50" width="180" height="130" rx="12" fill="#0f172a" stroke="#06b6d4" />
              <text x="730" y="74" textAnchor="middle" fill="#a5f3fc" fontSize="13" fontWeight="bold">M4 · Performance</text>
              <text x="730" y="100" textAnchor="middle" fill="#94a3b8" fontSize="10">MAE · RMSE · MAPE</text>
              <text x="730" y="116" textAnchor="middle" fill="#94a3b8" fontSize="10">PSI drift detector</text>
              <text x="730" y="132" textAnchor="middle" fill="#94a3b8" fontSize="10">365-day backtest harness</text>
              <text x="730" y="148" textAnchor="middle" fill="#94a3b8" fontSize="10">Auto-retrain triggers</text>
              <text x="730" y="171" textAnchor="middle" fill="#cbd5e1" fontSize="11" fontWeight="bold">→ /model-performance</text>

              <rect x="640" y="190" width="180" height="130" rx="12" fill="#0f172a" stroke="#f59e0b" />
              <text x="730" y="214" textAnchor="middle" fill="#fde68a" fontSize="13" fontWeight="bold">M5 · Workbench</text>
              <text x="730" y="240" textAnchor="middle" fill="#94a3b8" fontSize="10">SHAP / LIME explainability</text>
              <text x="730" y="256" textAnchor="middle" fill="#94a3b8" fontSize="10">Sensitivity sliders</text>
              <text x="730" y="272" textAnchor="middle" fill="#94a3b8" fontSize="10">Annotations · Overrides</text>
              <text x="730" y="288" textAnchor="middle" fill="#94a3b8" fontSize="10">Recommendation thesis</text>
              <text x="730" y="311" textAnchor="middle" fill="#cbd5e1" fontSize="11" fontWeight="bold">→ /workbench</text>

              <rect x="850" y="50" width="220" height="270" rx="12" fill="#0f172a" stroke="#34d399" strokeWidth="2" />
              <text x="960" y="74" textAnchor="middle" fill="#a7f3d0" fontSize="13" fontWeight="bold">TRADERS · ANALYSTS · PMs</text>
              <text x="960" y="100" textAnchor="middle" fill="#94a3b8" fontSize="10">Per-commodity hubs</text>
              <text x="960" y="116" textAnchor="middle" fill="#94a3b8" fontSize="10">filter the same engines</text>
              <text x="960" y="142" textAnchor="middle" fill="#cbd5e1" fontSize="11">/commodities/gas</text>
              <text x="960" y="160" textAnchor="middle" fill="#cbd5e1" fontSize="11">/commodities/power</text>
              <text x="960" y="178" textAnchor="middle" fill="#cbd5e1" fontSize="11">/commodities/lng</text>
              <text x="960" y="196" textAnchor="middle" fill="#cbd5e1" fontSize="11">/commodities/environmental</text>
              <text x="960" y="226" textAnchor="middle" fill="#94a3b8" fontSize="10">Recommendations route</text>
              <text x="960" y="242" textAnchor="middle" fill="#94a3b8" fontSize="10">through Approvals HITL</text>
              <text x="960" y="270" textAnchor="middle" fill="#fbbf24" fontSize="11" fontWeight="bold">→ /recommendations</text>

              <line x1="190" y1="185" x2="220" y2="185" stroke="#475569" strokeWidth="1.5" markerEnd="url(#hp5-arr)" />
              <line x1="400" y1="115" x2="430" y2="115" stroke="#475569" strokeWidth="1.5" markerEnd="url(#hp5-arr)" />
              <line x1="400" y1="255" x2="430" y2="255" stroke="#475569" strokeWidth="1.5" markerEnd="url(#hp5-arr)" />
              <line x1="610" y1="115" x2="640" y2="115" stroke="#475569" strokeWidth="1.5" markerEnd="url(#hp5-arr)" />
              <line x1="610" y1="255" x2="640" y2="255" stroke="#475569" strokeWidth="1.5" markerEnd="url(#hp5-arr)" />
              <line x1="820" y1="115" x2="850" y2="115" stroke="#475569" strokeWidth="1.5" markerEnd="url(#hp5-arr)" />
              <line x1="820" y1="255" x2="850" y2="255" stroke="#475569" strokeWidth="1.5" markerEnd="url(#hp5-arr)" />
              <path d="M 960 320 C 960 340, 310 340, 310 320" fill="none" stroke="#10b981" strokeWidth="1" strokeDasharray="3 3" />
              <text x="635" y="354" textAnchor="middle" fill="#10b981" fontSize="10" fontStyle="italic">feedback · annotations · retraining triggers</text>
            </svg>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {[
              { mod: 'M1', name: 'Data Fabric & Harmonization', href: '/data-fabric', accent: 'cyan',
                what: '22 connectors (EEX · ICE Endex · Nord Pool · EPEX · PEGAS · ENTSOG · ENTSO-E · ECMWF · SCADA streams · retail smart-meter + B2B baseload) into one canonical lakehouse. Anomaly detection and KNN-spline imputation run before any downstream engine sees a byte. Every join is point-in-time — no leakage into backtests.',
                why: 'You can\'t forecast on a curve you don\'t trust. The fabric is the trust layer.' },
              { mod: 'M2', name: 'Predictive Offtake Forecaster', href: '/forecaster', accent: 'emerald',
                what: 'Three demand surfaces, three model families. Residential + SME via Prophet + XGBoost (HDD / CDD / calendar / customer mix). Industrial baseload via LSTM (PMI / utilisation / cluster profiles). Storage cycling via XGBoost + LP (front-winter spread + days-to-withdrawal + injection capacity). Outputs P10 / P50 / P90 fan chart with cited SHAP drivers.',
                why: 'Demand is the swing factor. Marking your book without an offtake view is guessing.' },
              { mod: 'M3', name: 'Dynamic Forward Price Engine', href: '/price-engine', accent: 'violet',
                what: 'Three-layer hybrid per hub. Fundamental balance (supply-demand from connectors). Econometric (cointegration + GARCH on existing forward_curve / iv_surface). ML (BayesianRidge fair-value + IsolationForest anomaly). Blend with tunable weights. Residual z-score > 2 triggers a mispricing flag that routes to /approvals.',
                why: 'No single layer is right alone — they tell you when they disagree, and that\'s the trade.' },
              { mod: 'M4', name: 'Performance & Backtest', href: '/model-performance', accent: 'cyan',
                what: 'MAE / RMSE / MAPE per model, 30-day timeline view. PSI drift detector flips Stable → Watch → Drifting at 0.10 / 0.25 thresholds. 7-day drift triggers an auto-retraining proposal. One-click 365-day historical-replay backtest with strict point-in-time joins.',
                why: 'Production ML rots silently. The performance tab is the smoke alarm.' },
              { mod: 'M5', name: 'Analyst Workbench & Recommendations', href: '/workbench', accent: 'amber',
                what: 'SHAP waterfall per forecast — top drivers with absolute impact, sign, and a plain-English explanation. Live sensitivity sliders. Pinned annotations from the desk. Analyst overrides route through the Approvals HITL gate (head of desk reviews). The recommendation agent (Haiku 4.5) synthesises forecast + drivers + anomaly into a buy / sell / hedge / hold thesis with confidence.',
                why: 'Analysts trust the model when they can override it cleanly. Overrides feed retraining.' },
            ].map(m => (
              <a key={m.mod} href={m.href} className={`group block rounded-xl border border-${m.accent}-500/30 bg-${m.accent}-500/5 hover:bg-${m.accent}-500/10 p-4 transition-colors`}>
                <div className="flex items-baseline gap-2 mb-2">
                  <Badge color={m.accent as any}>{m.mod}</Badge>
                  <h4 className="text-sm font-semibold text-white">{m.name}</h4>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed">{m.what}</p>
                <p className="text-[11px] text-slate-500 italic mt-2">Why it matters: {m.why}</p>
                <p className="text-[11px] text-cyan-400 mt-2 group-hover:text-cyan-300">Open {m.href} →</p>
              </a>
            ))}
          </div>

          <h4 className="text-white font-semibold pt-3">Per-commodity hubs — same engines, sliced</h4>
          <p>The four commodity hubs (Gas · Power · LNG · Environmental) aren&apos;t separate apps — each is a
            filtered view into the five modules above. The numbers on /commodities/gas live in the same Data Fabric
            and Price Engine that /commodities/power reads from; you never get inconsistent prices between desks.</p>

          <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-4 my-2 overflow-x-auto">
            <svg viewBox="0 0 1100 260" className="w-full h-auto min-w-[900px]">
              <defs>
                <marker id="hp5b-arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="#475569" />
                </marker>
              </defs>
              <text x="550" y="22" textAnchor="middle" fill="#94a3b8" fontSize="11" fontWeight="bold">BIFURCATION — COMMODITY VIEWS OVER SHARED ENGINES</text>

              <rect x="20" y="50" width="240" height="170" rx="12" fill="#0f172a" stroke="#7c3aed" strokeWidth="2" />
              <text x="140" y="74" textAnchor="middle" fill="#ddd6fe" fontSize="12" fontWeight="bold">SHARED ENGINES</text>
              <text x="140" y="100" textAnchor="middle" fill="#cbd5e1" fontSize="11">Data Fabric · Forecaster</text>
              <text x="140" y="116" textAnchor="middle" fill="#cbd5e1" fontSize="11">Price Engine · Workbench</text>
              <text x="140" y="132" textAnchor="middle" fill="#cbd5e1" fontSize="11">Performance · Recs</text>
              <text x="140" y="160" textAnchor="middle" fill="#94a3b8" fontSize="10">22 connectors · 10 models</text>
              <text x="140" y="178" textAnchor="middle" fill="#94a3b8" fontSize="10">One forecast, one curve</text>
              <text x="140" y="196" textAnchor="middle" fill="#94a3b8" fontSize="10">No desk-by-desk drift</text>

              {[
                { x: 320, y: 50, color: '#f97316', name: 'Gas', sub: 'TTF · THE · CEGH · PSV' },
                { x: 320, y: 140, color: '#fbbf24', name: 'Power', sub: 'DE · HU · PL · IT · NORDIC' },
                { x: 600, y: 50, color: '#0ea5e9', name: 'LNG', sub: 'JKM · Krk · Brunsbüttel' },
                { x: 600, y: 140, color: '#22c55e', name: 'Environmental', sub: 'EUA · GoO · biomethane' },
              ].map((c) => (
                <g key={c.name}>
                  <rect x={c.x} y={c.y} width="220" height="80" rx="10" fill="#0f172a" stroke={c.color} />
                  <text x={c.x + 110} y={c.y + 30} textAnchor="middle" fill="#e2e8f0" fontSize="13" fontWeight="bold">{c.name}</text>
                  <text x={c.x + 110} y={c.y + 50} textAnchor="middle" fill="#94a3b8" fontSize="11">{c.sub}</text>
                  <text x={c.x + 110} y={c.y + 68} textAnchor="middle" fill="#94a3b8" fontSize="9">/commodities/{c.name.toLowerCase()}</text>
                  <line x1={260} y1={135} x2={c.x} y2={c.y + 40} stroke="#475569" strokeWidth="1" strokeDasharray="3 3" markerEnd="url(#hp5b-arr)" />
                </g>
              ))}

              <rect x="860" y="80" width="220" height="120" rx="10" fill="#0f172a" stroke="#34d399" strokeWidth="2" />
              <text x="970" y="106" textAnchor="middle" fill="#a7f3d0" fontSize="12" fontWeight="bold">DESK USER</text>
              <text x="970" y="128" textAnchor="middle" fill="#94a3b8" fontSize="10">Lands on commodity hub</text>
              <text x="970" y="144" textAnchor="middle" fill="#94a3b8" fontSize="10">Sees curve · signals · contracts</text>
              <text x="970" y="160" textAnchor="middle" fill="#94a3b8" fontSize="10">Clicks → Forecaster / Engine /</text>
              <text x="970" y="176" textAnchor="middle" fill="#94a3b8" fontSize="10">Workbench in filtered context</text>

              <line x1={540} y1={90}  x2={860} y2={130} stroke="#475569" strokeWidth="1" markerEnd="url(#hp5b-arr)" />
              <line x1={540} y1={180} x2={860} y2={150} stroke="#475569" strokeWidth="1" markerEnd="url(#hp5b-arr)" />
              <line x1={820} y1={90}  x2={860} y2={130} stroke="#475569" strokeWidth="1" markerEnd="url(#hp5b-arr)" />
              <line x1={820} y1={180} x2={860} y2={150} stroke="#475569" strokeWidth="1" markerEnd="url(#hp5b-arr)" />
            </svg>
          </div>

          <h4 className="text-white font-semibold pt-3">The 10 ML models</h4>
          <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-slate-900/60 text-slate-400">
                <tr>
                  <th className="text-left px-3 py-2 font-medium">Model</th>
                  <th className="text-left px-3 py-2 font-medium">Family</th>
                  <th className="text-left px-3 py-2 font-medium">Used by</th>
                  <th className="text-left px-3 py-2 font-medium">Trained on</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ['offtake_residential',      'Prophet + XGBoost',   'M2 Forecaster',     'ENTSO-E load + HDD/CDD'],
                  ['offtake_industrial',       'LSTM',                'M2 Forecaster',     'Baseload + sector PMI'],
                  ['offtake_storage_cycling',  'XGBoost + LP solve',  'M2 Forecaster',     'Storage inj/wd + spread'],
                  ['price_fairvalue_gas_hubs', 'BayesianRidge',       'M3 Price Engine',   'TTF/THE/CEGH day-ahead'],
                  ['price_fairvalue_power_hubs','BayesianRidge',      'M3 Price Engine',   'DE/HU/PL/CZ/IT day-ahead'],
                  ['price_anomaly',            'IsolationForest',     'M3 Price Engine',   'Blended-curve residuals'],
                  ['scenario_prior_gas',       'GaussianNB',          'M2 + M3 priors',    'Historical regime tags'],
                  ['scenario_prior_power',     'GaussianNB',          'M2 + M3 priors',    'Historical regime tags'],
                  ['lng_send_out_optimiser',   'LP solver',           'LNG hub',           'Slot calendar + curves'],
                  ['recommendation_thesis',    'Haiku 4.5 LLM',       'M5 Workbench',      'Forecast + driver + anomaly synthesis'],
                ].map(row => (
                  <tr key={row[0]} className="border-t border-slate-800/60 hover:bg-slate-800/30">
                    <td className="px-3 py-2 text-white font-mono text-[11px]">{row[0]}</td>
                    <td className="px-3 py-2 text-cyan-300 text-[11px]">{row[1]}</td>
                    <td className="px-3 py-2 text-slate-300">{row[2]}</td>
                    <td className="px-3 py-2 text-slate-400">{row[3]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h4 className="text-white font-semibold pt-3">From a model output to a sign-off</h4>
          <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-4 my-2 overflow-x-auto">
            <svg viewBox="0 0 1100 130" className="w-full h-auto min-w-[800px]">
              <defs>
                <marker id="hp5c-arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="#475569" />
                </marker>
              </defs>
              {[
                { x: 20,  label: 'Connector ingest', sub: 'EEX, ENTSO-E, SCADA', color: '#f97316' },
                { x: 200, label: 'Anomaly imputer', sub: 'KNN spline', color: '#06b6d4' },
                { x: 380, label: 'Forecast model', sub: 'P10 P50 P90 + SHAP', color: '#10b981' },
                { x: 560, label: 'Price engine', sub: '3-layer blend', color: '#a78bfa' },
                { x: 740, label: 'Recommendation', sub: 'Haiku thesis', color: '#f59e0b' },
                { x: 920, label: 'Approvals HITL', sub: 'head of desk', color: '#34d399' },
              ].map((s, i, arr) => (
                <g key={s.label}>
                  <rect x={s.x} y={30} width={160} height={60} rx={10} fill="#0f172a" stroke={s.color} />
                  <text x={s.x + 80} y={56} textAnchor="middle" fill="#e2e8f0" fontSize="12" fontWeight="bold">{s.label}</text>
                  <text x={s.x + 80} y={75} textAnchor="middle" fill="#94a3b8" fontSize="10">{s.sub}</text>
                  {i < arr.length - 1 && <line x1={s.x + 160} y1={60} x2={arr[i + 1].x} y2={60} stroke="#475569" strokeWidth="1.5" markerEnd="url(#hp5c-arr)" />}
                </g>
              ))}
              <text x="550" y="120" textAnchor="middle" fill="#64748b" fontSize="10" fontStyle="italic">end-to-end provenance — every recommendation cites the exact connector reads + model versions that produced it</text>
            </svg>
          </div>
        </Section>

        {/* Feature catalogue — every spec item end-to-end */}
        <Section title="Feature catalogue (every page, every grid)" icon={BookOpen} defaultOpen={true}>
          <p className="text-slate-300 mb-3">
            Thirteen platform features cover the full PPA contract lifecycle. Each row below maps a
            user-visible feature to the page that owns it and the API endpoint that powers it.
          </p>
          <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 overflow-x-auto" data-testid="feature-catalogue">
            <table className="w-full text-xs">
              <thead className="bg-slate-900/60 text-slate-400">
                <tr>
                  <th className="text-left px-3 py-2 font-medium">#</th>
                  <th className="text-left px-3 py-2 font-medium">Feature</th>
                  <th className="text-left px-3 py-2 font-medium">Page</th>
                  <th className="text-left px-3 py-2 font-medium">Endpoint</th>
                  <th className="text-left px-3 py-2 font-medium">What it does</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ['1','PPA Document Upload','/upload','POST /api/contractiq/contracts/upload','Drop PDF/TXT contracts; the master extraction pipeline auto-runs.'],
                  ['2','Automated Contract Analysis','/contracts/{id}','POST /api/contractiq/contracts/{id}/analyze','Reads the contract end-to-end, extracts clauses, parties, dates.'],
                  ['3','Key Information Extraction','/contracts/{id}','POST /api/contractiq/contracts/{id}/extract','Structured pull of terms, clauses, events with full provenance.'],
                  ['4','Clause Library / Taxonomy','/deal-clusters','GET /api/contractiq/taxonomy','Self-learning catalog of clause + leg types grown from every contract analysed.'],
                  ['5','Clause Dependency Graph','/contracts/{id}','served from /contracts/{id}','Per-clause dependency DAG; clause type drives node colour.'],
                  ['6','Contract events per clause','/contracts/{id} (Events tab)','served from /contracts/{id}','Each clause emits typed events that inherit the parent\'s attrs.'],
                  ['7','Event Dependency Graph','/contracts/{id} (combined DAG)','served from /contracts/{id}','Events form their own DAG, anchored to the parent clause.'],
                  ['8','Update Event → Cascade','/contracts/{id}','PATCH event field on detail page','Editing an event (e.g. price on a Price node) propagates downstream cashflows.'],
                  ['9','Cluster Clauses by Rule','/deal-clusters','GET /api/contractiq/deal-clusters','Commodity × delivery × cashflow grouping; the 12-row matrix below is the rule.'],
                  ['10','Interactive Event Timeline','/timeline','GET /api/contractiq/timeline','Single chronological feed of every event in the portfolio with overdue / upcoming KPIs.'],
                  ['11','Contract Q&A','/chat','POST /api/contractiq/chat','Ask anything in natural language; answers cite the clause + page.'],
                  ['12','Comprehensive Event Details List','/contracts/{id} (Events tab) + /timeline','served from /contracts/{id}','Every event with date, type, status, recurrence, notice window.'],
                  ['13','Proactive Notifications','/market (Alerts panel)','GET /api/contractiq/alerts + POST /alerts/{id}/acknowledge','Deadline + market-trigger alerts; ack queues consumed by Slack/email.'],
                ].map(row => (
                  <tr key={row[0]} className="border-t border-slate-800/60 hover:bg-slate-800/30">
                    <td className="px-3 py-2 text-slate-500">{row[0]}</td>
                    <td className="px-3 py-2 text-white">{row[1]}</td>
                    <td className="px-3 py-2 text-cyan-400 font-mono text-[11px]">{row[2]}</td>
                    <td className="px-3 py-2 text-slate-400 font-mono text-[11px]">{row[3]}</td>
                    <td className="px-3 py-2 text-slate-300">{row[4]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>

        {/* ETRM Deal-Type Matrix (Sheet 2 of the spec) */}
        <Section title="ETRM Deal-Type Matrix" icon={Database} defaultOpen={true}>
          <p className="text-slate-300 mb-3">
            Every clause cluster maps to exactly one ETRM deal type via the table below
            (commodity × delivery × optionality × cashflow). This is the rule the
            extraction pipeline uses to slice a PPA into Endur / Allegro / Openlink-ready legs.
          </p>
          <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 overflow-x-auto" data-testid="help-etrm-matrix">
            <table className="w-full text-xs">
              <thead className="bg-slate-900/60 text-slate-400">
                <tr>
                  <th className="text-left px-3 py-2 font-medium">#</th>
                  <th className="text-left px-3 py-2 font-medium">Commodity</th>
                  <th className="text-left px-3 py-2 font-medium">Delivery</th>
                  <th className="text-left px-3 py-2 font-medium">Optionality</th>
                  <th className="text-left px-3 py-2 font-medium">Type</th>
                  <th className="text-left px-3 py-2 font-medium">Cashflow</th>
                  <th className="text-left px-3 py-2 font-medium">ETRM Deal Type</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ['1','Power','Physical','No','—','Commodity payment','Power Physical'],
                  ['2','Power','Physical','No','—','Volume-dep payment','Power Physical · Deal Fee'],
                  ['3','Power','Physical','Yes','European','Premium','Power European Option · Phys'],
                  ['4','Power','Physical','Yes','European','Option pay-off','Power European Option · Phys'],
                  ['5','Power','Financial','No','—','Pay fix / receive float','Power Financial Swap'],
                  ['6','Power','Financial','Yes','Asian','Premium','Power Asian Option · Financial'],
                  ['7','Power','Financial','Yes','Asian','Option pay-off','Power Asian Option · Financial'],
                  ['8','Power','Financial','Yes','Strategy (Straddle/Floor/Collar/…)','Premium','Split into multiple deals'],
                  ['9','Power','Financial','Yes','Strategy (Straddle/Floor/Collar/…)','Option pay-off','Split into multiple deals'],
                  ['10','Natural Gas','Physical','No','—','Commodity payment','Commodity Physical (Gas)'],
                  ['11','Natural Gas','Physical','No','—','Volume-dep payment','Commodity Fees'],
                  ['12','GoO Certificate','Physical','No','—','Certificate payment','Commodity Physical (Certificate)'],
                ].map(r => (
                  <tr key={r[0]} className="border-t border-slate-800/60">
                    <td className="px-3 py-2 text-slate-500">{r[0]}</td>
                    <td className="px-3 py-2 text-slate-200 whitespace-nowrap">{r[1]}</td>
                    <td className="px-3 py-2 text-slate-300 whitespace-nowrap">{r[2]}</td>
                    <td className="px-3 py-2 text-slate-300 whitespace-nowrap">{r[3]}</td>
                    <td className="px-3 py-2 text-slate-400">{r[4]}</td>
                    <td className="px-3 py-2 text-slate-300">{r[5]}</td>
                    <td className="px-3 py-2 font-medium text-emerald-300 whitespace-nowrap">{r[6]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-slate-500 mt-2">
            Live, interactive copy of this matrix sits at the top of <Code>/deal-clusters</Code> next to
            real cluster rows from your portfolio.
          </p>
        </Section>

        {/* Endur JSON Templates feature */}
        <Section title="Endur JSON Templates — LLM-populated deal payloads" icon={Database} defaultOpen={true}>
          <p className="text-slate-300 mb-3">
            On <Code>/deal-clusters</Code> we ship a per-tenant template registry. Operators upload a JSON
            skeleton for any of the 12 ETRM deal types; the LLM fills the <code className="text-emerald-300">{`\${placeholder}`}</code> tokens
            using a deal cluster&apos;s clauses + legs and returns a populated payload an Endur engineer
            can paste straight in.
          </p>
          <ol className="list-decimal list-inside space-y-1 text-sm text-slate-300">
            <li>Open <strong className="text-white">/deal-clusters</strong>. The <em>Endur JSON Templates</em> panel sits between the matrix and the cluster grid.</li>
            <li>Click <strong className="text-emerald-300">Upload template</strong> — pick a category, paste/upload a JSON skeleton with <code>{`\${placeholders}`}</code>, save. The 12 starter templates ship pre-seeded for every demo account.</li>
            <li>Pick any cluster from the &ldquo;Generate Endur JSON for a cluster&rdquo; row. The modal lets you choose the template, then runs the LLM with the cluster + clause context.</li>
            <li>The populated JSON renders syntax-highlighted in the right pane. <strong>Copy</strong> sends it to the clipboard, <strong>Download</strong> writes a <Code>endur_*.json</Code> file. The left pane shows the source clauses for audit.</li>
          </ol>
          <p className="text-[11px] text-slate-500 mt-3">
            Endpoints: <Code>GET /api/contractiq/templates</Code>, <Code>POST /api/contractiq/templates</Code>,
            <Code>DELETE /api/contractiq/templates/{`{id}`}</Code>, <Code>POST /api/contractiq/generate-endur-json</Code>.
            12 supported categories: power_physical, power_physical_deal_fee, power_european_option_phys,
            power_financial_swap, power_asian_option_financial, power_option_strategy,
            commodity_physical_gas, commodity_fees, commodity_physical_certificate,
            power_swap, lng_tolling, interconnector_capacity.
          </p>
        </Section>

        {/* Quick start */}
        <Section title="5-Minute Quick Start" icon={Zap} defaultOpen={true}>
          <div className="bg-slate-900/50 rounded-lg p-4 space-y-2">
            <ol className="list-decimal list-inside space-y-1 text-xs text-slate-300">
              <li>Sign in with the demo user <Code>test@contractiq.com</Code> / <Code>TestPass123!</Code>.</li>
              <li>Upload a contract (PDF or TXT) from <strong className="text-white">/upload</strong>. The Master Pipeline runs all extraction agents.</li>
              <li>Open <strong className="text-white">/deal-clusters</strong> to see the 4-stage pipeline view: <em>Contract → Cluster → Deal Legs → Endur Template</em>.</li>
              <li>Open <strong className="text-white">/valuation</strong> and click <em>Refresh Valuation</em> — runs 3 agents (forecaster → valuator → T-o-P) end to end.</li>
              <li>Open <strong className="text-white">/insights</strong> for the 11 agentic workflows. Try <em>Benchmarking</em> against any clause on one of your contracts.</li>
              <li>Use <strong className="text-white">/chat</strong> for natural-language questions across the portfolio.</li>
            </ol>
          </div>
        </Section>

        {/* ═══════════════ Architecture in one picture ═══════════════ */}
        <Section title="How E&C-Copilot Uses Abenix — One Page" icon={Cpu}>
          <p className="text-slate-300">
            E&C-Copilot is a <strong className="text-white">fully standalone</strong> Next.js + FastAPI app. It does NOT
            run any LLM code itself. Every AI action is a call into Abenix via the SDK with <Code>actAs</Code>
            delegation. The agent YAMLs live in <Code>packages/db/seeds/agents/contractiq_*.yaml</Code> and are
            registered in Abenix's <Code>agents</Code> table.
          </p>
          <div className="rounded-xl border border-slate-700/50 bg-slate-900/50 p-5 space-y-3">
            {[
              ['E&C-Copilot user clicks "Run ..."', 'JWT issued by E&C-Copilot\'s own auth service.'],
              ['API calls Abenix SDK', 'One platform API key, X-Abenix-Subject: contractiq:{user_id} on every call.'],
              ['Abenix runs the agent YAML', 'Executes tools in sandbox. Logs cost, latency, tokens, tool calls.'],
              ['Tools enforce row-level RBAC', 'portfolio_energy_contracts + knowledge_search + graph_explorer all scoped to this user_id.'],
              ['Agent returns strict JSON', 'API parses, persists to the E&C-Copilot DB, returns to the UI.'],
            ].map(([step, detail], i) => (
              <div key={i} className="flex items-start gap-3">
                <Badge color="emerald">{String(i + 1)}</Badge>
                <div className="flex-1">
                  <p className="text-xs font-semibold text-white">{step}</p>
                  <p className="text-[11px] text-slate-400">{detail}</p>
                </div>
              </div>
            ))}
          </div>
        </Section>

        {/* ═══════════════ Extraction ═══════════════ */}
        <Section title="Extraction Agents — The Foundation" icon={FileText} defaultOpen={true}>
          <p className="text-slate-300">
            These agents turn a raw contract into structured data. Everything downstream depends on their output.
            The <strong className="text-white">self-learning taxonomy</strong> means the vocabulary these agents
            use stays stable across your portfolio — cluster key <Code>power_physical</Code> means the same thing
            on contract #1 and contract #50.
          </p>
          <div className="space-y-3">
            {EXTRACTION_AGENTS.map(a => <AgentCard key={a.slug} a={a} />)}
          </div>
        </Section>

        {/* ═══════════════ Valuation (Wave 1) ═══════════════ */}
        <Section title="Valuation Agents — Forward Curves, MtM, Take-or-Pay" icon={LineChart} defaultOpen={true}>
          <p className="text-slate-300">
            The <strong className="text-white">Wave 1 valuation stack</strong> — all on Gemini 2.5 Pro for depth.
            The forecaster feeds the valuator; the valuator and T-o-P monitor run independently against the portfolio.
            The whole stack is deterministic enough to rebuild daily; Gemini's reasoning handles the fuzzy edges
            (estimated tenors, sentiment adjustments, recommendation wording).
          </p>
          <div className="space-y-3">
            {VALUATION_AGENTS.map(a => <AgentCard key={a.slug} a={a} />)}
          </div>
          <div className="rounded-xl border border-indigo-500/30 bg-indigo-500/5 p-4 text-xs text-slate-300 leading-relaxed">
            <div className="flex items-center gap-2 mb-2 text-indigo-300">
              <Compass className="w-4 h-4" /> <span className="font-semibold">How forecasting actually works</span>
            </div>
            When you click <em>Run Forecaster</em>, the API inspects your cluster mix and picks only the markets you
            actually need (e.g. N2EX UK Power if you have <Code>power_physical</Code>, TTF if <Code>gas_physical</Code>).
            Each market gets one <Code>contractiq_forecast_curves</Code> row with <Code>status='running'</Code>; the
            forecaster agent is fired via the SDK. Inside Gemini, it orchestrates tool calls: spot + observable forwards
            from the market tools, 1-2 Tavily news queries for sentiment, an explicit fundamental-driver pass. Points
            without a real observation are tagged <Code>data_quality='estimated'</Code> — never fabricated. Total cost
            on the reference portfolio: ~$0.05 per curve, ~45-90s per market.
          </div>
        </Section>

        {/* ═══════════════ Insights Hub (11 cards) ═══════════════ */}
        <Section title="Insights Hub Agents — The 11 Workflows" icon={Sparkles}>
          <p className="text-slate-300">
            Each card in the Insights Hub is backed by one agent. They share the same generic platform tools; the
            <strong className="text-white"> domain knowledge is in the prompts, not the tools</strong>. This is why
            the same platform can drive E&C-Copilot (energy contracts), Mideast Tourism (travel forecasting), OracleNet
            (intelligence analysis), and others with no platform-level changes.
          </p>
          <div className="space-y-3">
            {INSIGHTS_AGENTS.map(a => <AgentCard key={a.slug} a={a} />)}
          </div>
        </Section>

        {/* ═══════════════ Orchestration ═══════════════ */}
        <Section title="Orchestration & Chat — The Long-Running Workflows" icon={GitBranch}>
          <p className="text-slate-300">
            These agents chain other agents or run long-running scans. They are the "runtime" of E&C-Copilot — what
            hums in the background so every page loads with fresh data.
          </p>
          <div className="space-y-3">
            {ORCHESTRATION_AGENTS.map(a => <AgentCard key={a.slug} a={a} />)}
          </div>
        </Section>

        {/* ═══════════════ Tools ═══════════════ */}
        <Section title="The 13 Generic Platform Tools" icon={Database}>
          <p className="text-slate-300">
            Agents don't hardcode business logic — they call generic tools. The tool registry lives in Abenix,
            not E&C-Copilot. Same tools power all vertical apps.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {[
              ['portfolio_energy_contracts', 'Schema-driven portfolio tool. Loads schema from portfolio_schemas at runtime.'],
              ['database_query',             'Generic read-only SQL. RBAC enforced inside the tool, not just at the API.'],
              ['database_writer',            'Generic writes (insert/update/upsert/delete).'],
              ['entso_e',                    'EU electricity: day-ahead prices, generation, forecasts.'],
              ['ember_climate',              'UK power + EU ETS carbon prices.'],
              ['ecb_rates',                  'FX, inflation, rates — from the European Central Bank.'],
              ['yahoo_finance',              'Brent, JKM, TTF, EUA, other financial futures.'],
              ['tavily_search',              'Real-time web search. Used for sentiment + counterparty news + market commentary.'],
              ['web_search',                 'Fallback when Tavily rate-limits.'],
              ['financial_calculator',       'NPV, IRR, LCOE, Black-Scholes, amortisation, WACC.'],
              ['knowledge_search',           'Hybrid vector + graph search via Cognify.'],
              ['graph_explorer',             'Direct Neo4j traversal: entities, relationships, shortest paths.'],
              ['code_executor',              'Sandboxed Python — used by stress_test for Monte Carlo.'],
            ].map(([name, desc]) => (
              <div key={name} className="bg-slate-800/20 border border-slate-700/30 rounded-lg p-3">
                <div className="flex items-center gap-2 mb-1">
                  <Database className="w-3.5 h-3.5 text-emerald-400" />
                  <span className="text-xs font-mono text-white">{name}</span>
                </div>
                <p className="text-[11px] text-slate-400">{desc}</p>
              </div>
            ))}
          </div>
        </Section>

        {/* ═══════════════ Model choice ═══════════════ */}
        <Section title="Why Gemini 2.5 Pro for some agents but 2.0 Flash for most" icon={Brain}>
          <p>
            Models are chosen per-agent based on <strong className="text-white">input size × reasoning depth × cost</strong>:
          </p>
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-violet-500/30 bg-violet-500/5 p-4 space-y-2">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-violet-300" />
                <p className="text-sm font-semibold text-white">Gemini 2.5 Pro (5 agents)</p>
              </div>
              <p className="text-[11px] text-slate-400">
                Extractor, functional analysis, price forecaster, portfolio valuator, top monitor, clause benchmarker.
                These need deep reasoning, long input, and strict JSON discipline. The extractor needs 65k output tokens.
                Forecaster + valuator need to reason numerically about curves.
              </p>
            </div>
            <div className="rounded-lg border border-cyan-500/30 bg-cyan-500/5 p-4 space-y-2">
              <div className="flex items-center gap-2">
                <Zap className="w-4 h-4 text-cyan-300" />
                <p className="text-sm font-semibold text-white">Gemini 2.0 Flash (13 agents)</p>
              </div>
              <p className="text-[11px] text-slate-400">
                Everything else. Flash is 5-10× cheaper and fast enough for short-context workflows like daily
                briefings, anomaly scans, and chat. Quality is indistinguishable for these use cases.
              </p>
            </div>
          </div>
        </Section>

        {/* ═══════════════ NEW · One platform, three asset families ═══════════════ */}
        <Section title="One platform · PPA · Gas · Metals" icon={Compass} defaultOpen>
          <div className="space-y-3">
            <p>
              E&C-Copilot now runs as a polymorphic contract platform. The same UI, same calculation engine, same audit ledger — three commodity families with their own specialised data sources, agents, and what-if scenarios.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="p-3 rounded-lg bg-cyan-500/5 border border-cyan-500/20">
                <div className="text-cyan-300 font-semibold mb-1">Power (PPA / VPPA / Tolling)</div>
                <div className="text-[11px] text-slate-300 space-y-1">
                  <div>Drivers: power price, capacity factor, curtailment, EUA carbon, FX.</div>
                  <div>Feeds: ENTSO-E, Ember, ECB.</div>
                  <div>Units: MW · MWh · EUR/MWh.</div>
                </div>
              </div>
              <div className="p-3 rounded-lg bg-orange-500/5 border border-orange-500/20">
                <div className="text-orange-300 font-semibold mb-1">Natural Gas / LNG</div>
                <div className="text-[11px] text-slate-300 space-y-1">
                  <div>Drivers: HH, TTF, JKM, demand, take-or-pay, pipeline outage.</div>
                  <div>Feeds: EIA, TTF settlement, JKM, Baltic LNG freight.</div>
                  <div>Units: MMBtu · therm · USD/MMBtu.</div>
                </div>
              </div>
              <div className="p-3 rounded-lg bg-amber-500/5 border border-amber-500/20">
                <div className="text-amber-300 font-semibold mb-1">Precious Metals</div>
                <div className="text-[11px] text-slate-300 space-y-1">
                  <div>Drivers: spot, lease rate, USDCHF, assay variance, refiner status, sanctions.</div>
                  <div>Feeds: LBMA gold/silver, LPPM Pt/Pd, COMEX, SGE, ETF flows.</div>
                  <div>Units: troy oz · USD/oz · fineness (decimal).</div>
                </div>
              </div>
            </div>
          </div>
        </Section>

        {/* ═══════════════ NEW · What-if ═══════════════ */}
        <Section title="What-If Analysis (every contract type)" icon={Gauge} defaultOpen>
          <p>
            Every analyzed contract gets a <strong className="text-white">What-If</strong> button on its detail page. The page loads the right scenario library for the contract's type, lets you fire a pre-built scenario or compose a custom perturbation, and stores every run with a calculation signature so the result is reproducible.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-[12px]">
            <div className="p-3 rounded-md bg-slate-800/40 border border-slate-800">
              <div className="text-cyan-300 font-semibold mb-1.5">PPA scenarios</div>
              <ul className="space-y-0.5 list-disc list-inside text-slate-300">
                <li>Power -20% / +15%</li>
                <li>Capacity factor -10pp</li>
                <li>EUR -5%</li>
                <li>10-day curtailment</li>
                <li>EUA +30%</li>
              </ul>
            </div>
            <div className="p-3 rounded-md bg-slate-800/40 border border-slate-800">
              <div className="text-orange-300 font-semibold mb-1.5">Gas scenarios</div>
              <ul className="space-y-0.5 list-disc list-inside text-slate-300">
                <li>HH -30%</li>
                <li>TTF +50% (cold snap)</li>
                <li>Demand -20% (warm winter)</li>
                <li>30-day transport outage</li>
                <li>Take-or-pay miss this quarter</li>
                <li>JKM-TTF arb opens $4/MMBtu</li>
              </ul>
            </div>
            <div className="p-3 rounded-md bg-slate-800/40 border border-slate-800">
              <div className="text-amber-300 font-semibold mb-1.5">Metals scenarios</div>
              <ul className="space-y-0.5 list-disc list-inside text-slate-300">
                <li>Gold -10% / +20%</li>
                <li>Silver -15%</li>
                <li>Platinum -25%</li>
                <li>Lease rate +3pp</li>
                <li>USDCHF +5%</li>
                <li>Assay variance breach</li>
                <li>Counterparty refiner delisted</li>
                <li>Russia sanctions tighten</li>
              </ul>
            </div>
          </div>
          <p className="text-[12px] text-slate-400">
            Each run returns a per-driver decomposition ("HH -30% → -$200k, TTF +50% → +$50k, net -$150k") so credit committees see exactly which assumption drove the result.
          </p>
        </Section>

        {/* ═══════════════ NEW · Market Risk ═══════════════ */}
        <Section title="Market Risk (VaR · CVaR · correlations · forward curves)" icon={Activity} defaultOpen>
          <p>
            <strong className="text-white">/risk</strong> is the new single-page market-risk dashboard. Pick a preset (Gold 1d 95% on $10M, Platinum 1d 99% on $5M, etc.) and the engine runs VaR + CVaR with one of three methods and saves the run with a cryptographic signature.
          </p>
          <ul className="space-y-1 list-disc list-inside text-[12px]">
            <li><strong className="text-white">Parametric</strong> — Normal-distribution VaR with mean and stdev. Fast. Underestimates tail.</li>
            <li><strong className="text-white">Historical</strong> — empirical percentile from the actual history. No distribution assumption.</li>
            <li><strong className="text-white">Filtered Historical (FHS)</strong> — historical-sim rescaled to today's vol regime via EWMA(λ=0.94). The default — does not let a low-vol decade make today's tail look small.</li>
          </ul>
          <p className="text-[12px] text-slate-400">
            CVaR (Expected Shortfall) is computed alongside every VaR — the average loss past the VaR threshold. Use it for credit-committee tail conversations where the question is "if it does break, how bad does it get?".
          </p>
          <p className="text-[12px]">
            <strong className="text-white">Correlations:</strong> the page shows an EWMA-weighted correlation matrix across the four PGMs by default. Configurable up to 365 days of history. Override the lambda from the URL.
          </p>
        </Section>

        {/* ═══════════════ NEW · Market Data Sources ═══════════════ */}
        <Section title="Market Data — one tool, many presets" icon={Database}>
          <p>
            Market-data feeds are <strong>not</strong> hand-written adapters in E&C-Copilot. They are <strong>presets</strong> in Abenix — labelled, per-tenant bundles of <code className="bg-slate-800 px-1 rounded">(tool_slug, default_args)</code> over a single generic <code className="bg-slate-800 px-1 rounded">yahoo_finance</code> tool. One engine, many configured shortcuts. Add or edit any preset from <code className="bg-slate-800 px-1 rounded">/admin/tool-presets</code> in Abenix; E&C-Copilot reads them via the SDK.
          </p>
          <p className="text-[12px] text-slate-400">
            Shipped presets (each is one row in <code className="bg-slate-800 px-1 rounded">tool_presets</code>; <code>tool_slug</code> is always <code>yahoo_finance</code>):
          </p>
          <table className="w-full text-[11px]">
            <thead className="text-slate-500 uppercase">
              <tr>
                <th className="text-left py-1">Preset slug</th>
                <th className="text-left py-1">Label</th>
                <th className="text-left py-1">default_args</th>
              </tr>
            </thead>
            <tbody className="text-slate-300">
              {[
                ["lbma_gold_fix", "LBMA Gold AM/PM Fix", "{action: commodity_future, symbol: gold}"],
                ["lbma_silver_price", "LBMA Silver Price", "{action: commodity_future, symbol: silver}"],
                ["lppm_platinum_fix", "LPPM Platinum Fix", "{action: commodity_future, symbol: platinum}"],
                ["lppm_palladium_fix", "LPPM Palladium Fix", "{action: commodity_future, symbol: palladium}"],
                ["comex_copper", "COMEX copper settlement", "{action: commodity_future, symbol: copper}"],
                ["metals_etf_gld", "GLD NAV (flow proxy)", "{action: commodity_future, symbol: etf_gld}"],
                ["shanghai_gold_usdcny", "USD/CNY for SGE derive", "{action: fx_rate, symbol: usdcny}"],
                ["ttf_settlement", "TTF settlement", "{action: commodity_future, symbol: natgas_ttf}"],
                ["henry_hub_natgas", "Henry Hub natgas", "{action: commodity_future, symbol: natgas_henry_hub}"],
                ["wti_crude", "WTI crude", "{action: commodity_future, symbol: wti}"],
                ["brent_crude", "Brent crude", "{action: commodity_future, symbol: brent}"],
              ].map((row, i) => (
                <tr key={i} className="border-t border-slate-800/40">
                  <td className="py-1 font-mono text-cyan-300">{row[0]}</td>
                  <td className="py-1">{row[1]}</td>
                  <td className="py-1 font-mono text-[10px] text-slate-400">{row[2]}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-[12px] text-slate-400">
            <strong>Aspirational vs real today:</strong> the marketing names (LBMA, LPPM, COMEX) are aspirational — every preset currently resolves to a Yahoo Finance futures symbol via the friendly-alias map in the abenix tool. No API keys today. Promoting any preset to a paid feed (LBMA, ICE, Refinitiv) means editing the <code className="bg-slate-800 px-1 rounded">tool_slug</code> field to the new paid-feed tool (or editing the preset's <code className="bg-slate-800 px-1 rounded">config</code> to carry the API key) — <em>zero E&C-Copilot deploy</em>. The schema is built for it.
          </p>
          <p className="text-[12px] text-slate-400">
            <strong>Why this architecture:</strong> the platform supports 60+ universal tools. Wrapping every instrument in its own tool class would mean dozens of one-line subclasses and a brittle catalog. With one generic tool + presets, every other app (Wingman, Industrial IoT, Mideast Tourism) gets the same metals feeds for free by importing the preset slugs.
          </p>
        </Section>

        {/* ═══════════════ NEW · ML Models as tools ═══════════════ */}
        <Section title="ML Models — first-class tools, deployable from UI" icon={Cpu}>
          <p>
            Every ML model registered in Abenix is callable through the same tool surface as Yahoo, KYC screening, or the calculator. The <code className="bg-slate-800 px-1 rounded">ml_model</code> tool routes to a registered model by name. sklearn, PyTorch, ONNX, XGBoost are first-class.
          </p>
          <ul className="space-y-1 list-disc list-inside text-[12px]">
            <li><strong>Register</strong> at <code className="bg-slate-800 px-1 rounded">/ml-models</code> in Abenix. Upload a pickle / ONNX / SavedModel and capture input/output schemas plus a sample payload.</li>
            <li><strong>Deploy</strong> via the same admin page. The platform spins up a per-model k8s deployment (<code className="bg-slate-800 px-1 rounded">ml-model-&lt;id&gt;</code>) and the registry knows where to route inference.</li>
            <li><strong>Use as a tool</strong> from any agent: <code className="bg-slate-800 px-1 rounded">ml_model.predict(model_name, input_data)</code>.</li>
            <li><strong>Use directly</strong> via SDK: <code className="bg-slate-800 px-1 rounded">forge.tools.execute("ml_model", arguments=&#123;operation:"predict", model_name, input_data&#125;)</code>. No LLM round-trip.</li>
          </ul>

          <h4 className="text-white font-semibold pt-4 pb-1">Four E&C-Copilot-shipped models</h4>
          <p className="text-[12px] text-slate-400">
            All four ship out-of-the-box. Synthetic-but-realistic training corpora. Re-train on customer-labelled data after deployment. Calc-signature for every prediction lands in the <code className="bg-slate-800 px-1 rounded">tool_invocations</code> table via the gate.
          </p>

          <div className="space-y-3 text-[12px]">
            <div className="rounded-md border border-violet-700/40 bg-violet-900/15 p-3">
              <div className="flex items-baseline gap-2 mb-1.5">
                <code className="font-mono text-violet-300">contractiq-clause-classifier</code>
                <span className="text-[10px] text-slate-500">TF-IDF (1-2 grams) + Multinomial Logistic Regression · 401 KB</span>
              </div>
              <p className="text-slate-300 mb-1.5">
                Classifies a clause's raw text into one of ~30 ETRM clause types (<code>term_and_termination</code>, <code>delivery_point</code>, <code>pricing_formula</code>, <code>indexation</code>, <code>tolerance_band</code>, <code>minimum_quantity</code>, <code>take_or_pay</code>, <code>force_majeure</code>, <code>credit_support</code>, <code>change_of_law</code>, <code>regulatory_compliance</code>, <code>warranties</code>, <code>liability_cap</code>, <code>indemnity</code>, <code>confidentiality</code>, <code>assignment</code>, <code>governing_law</code>, <code>dispute_resolution</code>, <code>notices</code>, <code>entire_agreement</code>, <code>tax</code>, <code>settlement</code>, <code>delivery_obligations</code>, <code>metering</code>, <code>insurance</code>, <code>environmental</code>, <code>ip_rights</code>, <code>audit_rights</code>, <code>step_in_rights</code>, <code>decommissioning</code>).
              </p>
              <p className="text-slate-400 text-[11px] mb-1">
                <strong>Used by:</strong> the master extraction pipeline as an OPTIONAL pre-filter before PASS 3. Threshold 0.70. Above &rarr; type is taken as a hint and the clause's <code>evidence</code> block carries the predicted_class + confidence. Below &rarr; the LLM-extracted type wins.
              </p>
              <p className="text-slate-400 text-[11px]">
                <strong>Input:</strong> <code>&#123;text: "&lt;clause text&gt;"&#125;</code> &nbsp; <strong>Output:</strong> top class + per-class probabilities.
                Hold-out accuracy on the synthetic corpus: <strong>100%</strong> (the corpus is class-separable by design).
              </p>
            </div>

            <div className="rounded-md border border-cyan-700/40 bg-cyan-900/15 p-3">
              <div className="flex items-baseline gap-2 mb-1.5">
                <code className="font-mono text-cyan-300">contractiq-risk-tier-predictor</code>
                <span className="text-[10px] text-slate-500">StandardScaler &rarr; CalibratedClassifierCV(GradientBoostingClassifier) · 2.9 MB</span>
              </div>
              <p className="text-slate-300 mb-1.5">
                Maps a contract's 10 structural features to a four-level deal risk tier: <code>low</code>, <code>medium</code>, <code>high</code>, <code>critical</code>. Calibrated probabilities so the trader can see how confident the model is.
              </p>
              <p className="text-slate-400 text-[11px] mb-1">
                <strong>Used by:</strong> the hedge_advisor agent and the market-risk dashboard. The agent calls this FIRST. If the prior says <code>low</code> and the agent confirms, it can skip the deep VaR sweep and recommend a thinner hedge. Quoted in the rationale section of the final answer next to the analytical VaR number.
              </p>
              <div className="text-slate-400 text-[11px] space-y-0.5">
                <div><strong>Features (10, ordered):</strong> <code>notional_usd</code>, <code>tenor_years</code>, <code>tolerance_pct</code>, <code>indexation_strength</code> (0-1), <code>counterparty_rating_num</code> (1=AAA &hellip; 10=NR), <code>credit_support_ratio</code> (LC / 90d MTM), <code>force_majeure_clarity</code> (0-1), <code>governing_law_friction</code> (0-1), <code>has_take_or_pay</code> (0/1), <code>market_volatility_z</code>.</div>
                <div><strong>Output:</strong> tier label + calibrated probabilities. <strong>Hold-out accuracy:</strong> 92.83% on 1,500 synthetic deals.</div>
              </div>
            </div>

            <div className="rounded-md border border-emerald-700/40 bg-emerald-900/15 p-3">
              <div className="flex items-baseline gap-2 mb-1.5">
                <code className="font-mono text-emerald-300">contractiq-counterparty-default</code>
                <span className="text-[10px] text-slate-500">StandardScaler &rarr; Logistic Regression · 1.4 KB</span>
              </div>
              <p className="text-slate-300 mb-1.5">
                Logistic-regression 12-month probability of default. Cheap to call, easy to override. Returns a calibrated probability between 0 and 1 plus a four-level rating bucket (investment / speculative / sub-IG / distressed).
              </p>
              <p className="text-slate-400 text-[11px] mb-1">
                <strong>Used by:</strong> the credit_risk agent and the hedge_advisor. Called BEFORE the expensive sanctions + PEP + adverse-media sweep so cheap counterparties get screened fast and the deep-check budget goes to suspect names. If <code>PD &gt; 0.20</code> the recommended hedge structure must include credit-support sizing in the output.
              </p>
              <div className="text-slate-400 text-[11px] space-y-0.5">
                <div><strong>Features (11, ordered):</strong> <code>debt_to_equity</code>, <code>interest_coverage</code> (EBITDA / interest), <code>current_ratio</code>, <code>quick_ratio</code>, <code>return_on_assets</code>, <code>revenue_growth_yoy</code>, <code>altman_z</code>, <code>sector_oilgas</code> (0/1), <code>sector_power</code>, <code>sector_metals</code>, <code>is_public</code>.</div>
                <div><strong>Output:</strong> P(default within 12m). <strong>Hold-out accuracy:</strong> 89.47% on 4,000 synthetic counterparties. Base default rate: 10.92%.</div>
              </div>
            </div>

            <div className="rounded-md border border-amber-700/40 bg-amber-900/15 p-3">
              <div className="flex items-baseline gap-2 mb-1.5">
                <code className="font-mono text-amber-300">contractiq-price-anomaly</code>
                <span className="text-[10px] text-slate-500">IsolationForest · 200 trees · contamination=0.10 · 2.2 MB</span>
              </div>
              <p className="text-slate-300 mb-1.5">
                Anomaly detector over the joint distribution of contract features + price-vs-fair-value residual. Trained with 10% planted outliers so it learns the manifold of typical deals.
              </p>
              <p className="text-slate-400 text-[11px] mb-1">
                <strong>Used by:</strong> the portfolio_valuator agent. Called AFTER the analytical fair value is computed. If the score is anomalous AND the residual sign is unfavourable, the result card lights up red and a hedge_advisor follow-up is queued automatically.
              </p>
              <div className="text-slate-400 text-[11px] space-y-0.5">
                <div><strong>Features (8, ordered):</strong> <code>log_notional</code>, <code>tenor_years</code>, <code>price_residual_pct</code>, <code>forward_curve_slope</code>, <code>vol_z</code>, <code>counterparty_rating_num</code>, <code>indexation_strength</code>, <code>has_take_or_pay</code>.</div>
                <div><strong>Output:</strong> <code>+1</code> (typical) / <code>-1</code> (anomaly), raw score, threshold. <strong>Planted-outlier recall:</strong> 100% on the held-out validation set.</div>
              </div>
            </div>
          </div>

          <p className="text-[12px] text-slate-400 pt-2">
            <strong>Why synthetic training data is the right starting point:</strong> a contract intelligence platform has zero customer-labelled data on day one. Every model ships with a synthetic-but-realistic corpus matched to the linguistic and statistical shape of real ETRM contracts, then re-trains on approved-output history the moment enough labelled examples accumulate. The build scripts live in <code className="bg-slate-800 px-1 rounded">contractiq/aimodels/build_*.py</code> and rerun in &lt;30 seconds on a laptop.
          </p>

          <p className="text-[12px] text-slate-400">
            <strong>Risk modules are still analytical, not ML.</strong> The Python modules in <code className="bg-slate-800 px-1 rounded">contractiq/api/app/risk/</code> compute parametric / historical / FHS-EWMA VaR + CVaR + EWMA correlations + log-linear forward-curve interpolation directly in numpy because every run has to stamp a byte-reproducible <code>calc_signature</code> (SHA-256 over canonical inputs) for the audit trail. An ML-trained risk model (e.g. an FHS-EWMA neural net or a regime-switching mixture) plugs in by being registered as a model and called via its name. The calc-signature is then derived from the model's content-hash.
          </p>
        </Section>

        {/* ═══════════════ NEW · RBAC ═══════════════ */}
        <Section title="Access Control — 6 personas + 4-eyes" icon={Users}>
          <p>
            Six built-in roles map to the screenshot's persona surfaces. Every role has a permissions matrix that drives what the UI shows and what the API allows.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-[12px]">
            {[
              ["contract_officer", "Captures + maps signed contracts. Manages extraction + clause edits."],
              ["trader", "Prices, runs what-ifs, commits. Owns the live exposure view."],
              ["operations", "Provisional vs final settlement, reconciliations, dispute resolution."],
              ["credit_risk", "Pre-trade limits, counterparty exposure, KYC, sanctions."],
              ["market_risk", "VaR + CVaR + sensitivities + correlations. Owns the risk engine config."],
              ["sme_rule_owner", "Authors and approves rules in the rule library. Four-eyes enforced — author cannot approve."],
            ].map(([name, desc]) => (
              <div key={name} className="p-2.5 rounded-md bg-slate-800/40 border border-slate-800">
                <div className="text-emerald-300 font-mono text-[11px] mb-1">{name}</div>
                <div className="text-slate-400 text-[11px]">{desc}</div>
              </div>
            ))}
          </div>
          <p className="text-[12px] text-slate-400">
            Manage assignments at <code className="bg-slate-800 px-1 rounded">/admin/rbac</code>. Read your own permissions matrix any time at <code className="bg-slate-800 px-1 rounded">GET /api/contractiq/rbac/me</code>.
          </p>
        </Section>

        {/* ═══════════════ NEW · Rule library ═══════════════ */}
        <Section title="Rule Library (typed · versioned · four-eyes)" icon={BookOpen}>
          <p>
            Every domain rule a contract relies on (penalties, TC/RC, tolerance bands, indexation, franchises) lives in <code className="bg-slate-800 px-1 rounded">contractiq_rules</code>. Each row is typed, versioned, has an effective-from date, can be retired, and tracks who authored and who approved it.
          </p>
          <ul className="space-y-1 list-disc list-inside text-[12px]">
            <li><strong>Status flow:</strong> draft → active → retired.</li>
            <li><strong>Four-eyes:</strong> author cannot approve their own rule. Enforced server-side at <code className="bg-slate-800 px-1 rounded">POST /api/contractiq/rules/&#123;id&#125;/approve</code>.</li>
            <li><strong>Source-traceable:</strong> every rule can be anchored to a clause in a signed contract — proof the rule exists in the deal, not just the codebase.</li>
            <li><strong>Test corpus:</strong> each rule carries a regression-test set so changes never ship blind.</li>
          </ul>
        </Section>

        {/* ═══════════════ NEW · Audit log ═══════════════ */}
        <Section title="Audit Log — immutable event ledger" icon={FileText}>
          <p>
            Every rule change, role grant, dispute decision, what-if run, and risk computation is logged as an event with before/after state and a cryptographic calc-signature. Read at <code className="bg-slate-800 px-1 rounded">/admin/audit</code> or query directly at <code className="bg-slate-800 px-1 rounded">GET /api/contractiq/audit/events?kind=rule</code>.
          </p>
          <p className="text-[12px] text-slate-400">
            Combined with the calc-signature on every VaR / CVaR / what-if run, this is what makes "show me how you got this number, six months later" a one-click answer.
          </p>
        </Section>

        {/* ═══════════════ NEW · SDK direct tool execute ═══════════════ */}
        <Section title="SDK · direct tool execute" icon={Cpu}>
          <p>
            The Abenix SDK now lets you call any registered platform tool directly — skipping the LLM round-trip. Use it for lookups, deterministic calcs, and market-data fetches where the LLM is just routing.
          </p>
          <pre className="text-[11px] bg-slate-800/60 p-3 rounded font-mono overflow-x-auto">
{`from abenix_sdk import Abenix
async with Abenix(api_key=KEY, base_url=URL, act_as=subj) as forge:
    # 1. Universal tool catalogue (60+ tools)
    tools = await forge.tools.list()

    # 2. Direct execute — no agent, no LLM
    out = await forge.tools.execute(
        "yahoo_finance",
        arguments={"action": "commodity_future", "symbol": "gold"},
    )

    # 3. Presets — labelled (tool, args) bundles, configurable in UI
    presets = await forge.presets.list(asset_class="gold")
    quote = await forge.presets.run("lbma_gold_fix")  # one line, any app
    print(quote["content"])

    # 4. Save a new preset (any tool, any args)
    await forge.presets.upsert({
        "slug": "lbma_silver_5d",
        "label": "LBMA Silver 5-day",
        "tool_slug": "yahoo_finance",
        "default_args": {"action": "commodity_future",
                          "symbol": "silver", "history_days": 5},
        "ui_group": "metals", "asset_class": "silver",
    })`}
          </pre>
          <p className="text-[12px] text-slate-400">
            Every direct call is logged in <code className="bg-slate-800 px-1 rounded">tool_invocations</code> on the platform side — same place the agent-loop tool calls land. Direct vs agent calls are distinguished by the <code className="bg-slate-800 px-1 rounded">via</code> column (<code>direct | agent | pipeline</code>). Search by tool_slug at <code className="bg-slate-800 px-1 rounded">GET /api/tools/invocations?tool_slug=...</code>.
          </p>
          <p className="text-[12px] text-slate-400">
            Concurrency model: tools are instantiated per-call (no shared state), so direct calls and agent-loop calls run in parallel without contention. Heavy CPU-bound tools should still be routed through the agent-runtime pool — the inline endpoint on the api pod is appropriate for I/O-bound and sub-second calls only.
          </p>
        </Section>

        {/* ═══════════════ NEW · Scaling architecture ═══════════════ */}
        <Section title="Scaling — three layers, three admin pages" icon={Cpu}>
          <p>
            E&C-Copilot does not own its scaling. It rents from the Abenix platform's three-layer scaling system. As traffic grows you tune the right layer:
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-[12px]">
            <div className="p-2.5 rounded-md bg-violet-900/20 border border-violet-700/40">
              <div className="text-violet-300 font-semibold mb-1">Layer 1 · Agents</div>
              <div className="text-slate-300 mb-1 text-[11.5px]">
                Each E&C-Copilot agent (extractor, hedge advisor, force-majeure monitor, ...) has its own <code className="bg-slate-800 px-1 rounded">runtime_pool</code>, min/max replicas, and qps cap.
              </div>
              <div className="text-slate-400 text-[10.5px]">Tune at <code className="bg-slate-800 px-1 rounded">/admin/scaling</code> on Abenix.</div>
            </div>
            <div className="p-2.5 rounded-md bg-cyan-900/20 border border-cyan-700/40">
              <div className="text-cyan-300 font-semibold mb-1">Layer 2 · Tools</div>
              <div className="text-slate-300 mb-1 text-[11.5px]">
                Every shared tool — yahoo_finance, sanctions_screening, ml_model, knowledge_search — is wrapped in a Redis-backed gate that adds cache + qps + circuit-breaker + per-tenant fairness.
              </div>
              <div className="text-slate-400 text-[10.5px]">Tune at <code className="bg-slate-800 px-1 rounded">/admin/tool-scaling</code>.</div>
            </div>
            <div className="p-2.5 rounded-md bg-emerald-900/20 border border-emerald-700/40">
              <div className="text-emerald-300 font-semibold mb-1">Layer 3 · Pipelines</div>
              <div className="text-slate-300 mb-1 text-[11.5px]">
                The 5-pass extraction pipeline + the valuation pipeline compose Layer 1 (agent nodes) and Layer 2 (tool nodes). Each node shows its scaling routing.
              </div>
              <div className="text-slate-400 text-[10.5px]">View at <code className="bg-slate-800 px-1 rounded">/admin/pipeline-scaling</code>.</div>
            </div>
          </div>
          <p className="text-[12px] text-slate-400">
            <strong>What it means for E&C-Copilot specifically:</strong> if extractions slow down, the bottleneck is almost always at one of the layers above. The flow is: contractiq-api → SDK call → Abenix agent in runtime_pool → tool calls through the gate. Open <code className="bg-slate-800 px-1 rounded">/admin/pipeline-scaling</code> on the Abenix tenant, expand the extractor pipeline, and the slow node will point you to the right layer to tune.
          </p>
          <p className="text-[12px] text-slate-400">
            <strong>Why this matters for a contract-intelligence app:</strong> when 200 contracts are uploaded for batch extraction at quarter-end close, the same <code className="bg-slate-800 px-1 rounded">document_extractor</code> tool is called 200 times. The cache gives identical contracts a free pass. The semaphore protects the LLM provider from a thundering herd. The daily budget caps the per-tenant LLM spend. None of this was visible to you. It's just always-on.
          </p>
        </Section>

        {/* ═══════════════ NEW · Personas in the screenshot ═══════════════ */}
        <Section title="Personas — who uses what" icon={Users}>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-[12px]">
            <div className="p-3 rounded-md bg-slate-800/40 border border-slate-800">
              <div className="text-white font-semibold mb-1">Contract Officer</div>
              <div className="text-slate-400">Upload, extract, deep-extract, clause edits, version diff, contract families.</div>
            </div>
            <div className="p-3 rounded-md bg-slate-800/40 border border-slate-800">
              <div className="text-white font-semibold mb-1">Trader</div>
              <div className="text-slate-400">What-if, hedge advice, valuation, market board, simulations.</div>
            </div>
            <div className="p-3 rounded-md bg-slate-800/40 border border-slate-800">
              <div className="text-white font-semibold mb-1">Operations</div>
              <div className="text-slate-400">Settlement reconciliation, dispute resolution, anomaly review.</div>
            </div>
            <div className="p-3 rounded-md bg-slate-800/40 border border-slate-800">
              <div className="text-white font-semibold mb-1">Credit Risk</div>
              <div className="text-slate-400">Counterparty risk, KYC, force-majeure monitor, pre-trade exposure.</div>
            </div>
            <div className="p-3 rounded-md bg-slate-800/40 border border-slate-800">
              <div className="text-white font-semibold mb-1">Market Risk</div>
              <div className="text-slate-400">VaR/CVaR, correlations, stress test, IV surface, forward curves.</div>
            </div>
            <div className="p-3 rounded-md bg-slate-800/40 border border-slate-800">
              <div className="text-white font-semibold mb-1">SME / Rule Owner</div>
              <div className="text-slate-400">Rule library — author, approve (four-eyes), retire. Regression corpus owner.</div>
            </div>
          </div>
        </Section>

        {/* ═══════════════ Original Security ═══════════════ */}
        <Section title="Security & Operations" icon={Lock}>
          <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-4 text-[12px] text-slate-300 leading-relaxed">
            <ul className="space-y-1 list-disc list-inside">
              <li><strong className="text-white">One platform key</strong> — E&C-Copilot never sees individual user API keys.</li>
              <li><strong className="text-white">Row-level isolation</strong> enforced inside every tool (not just at the API).</li>
              <li><strong className="text-white">Every agent call</strong> logged in Abenix's <Code>executions</Code> table with subject metadata.</li>
              <li><strong className="text-white">Every direct tool call</strong> logged in Abenix's <Code>tool_invocations</Code> table with via=direct flag.</li>
              <li><strong className="text-white">Every rule + role change</strong> logged in <Code>contractiq_audit_events</Code> with before/after state.</li>
              <li><strong className="text-white">Calc-signature</strong> attached to every VaR / CVaR / what-if run — reproducible byte-for-byte from inputs.</li>
              <li><strong className="text-white">KYC suite</strong> runs 8 verification tools with HITL sign-off before any counterparty is cleared.</li>
            </ul>
          </div>
        </Section>

        {/* Footer */}
        <div className="text-center py-8 border-t border-slate-800/50">
          <p className="text-xs text-slate-500 mb-2">E&C-Copilot · PPA · Gas · Metals contract intelligence</p>
          <p className="text-[10px] text-slate-600">
            26 agents · 11 market-data adapters · 6 risk + analytics modules · 6 RBAC personas · 100% Abenix-native
          </p>
        </div>
      </div>
    </div>
  );
}
