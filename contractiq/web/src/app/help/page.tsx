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
    title: 'Functional Analysis (MET / SEE-BV template)',
    icon: Network,
    accent: 'purple',
    model: 'gemini-2.0-flash',
    surface: 'Contract detail · Functional Analysis tab',
    oneLiner: 'Maps every clause into the MET Group SEE-BV taxonomy: 11 functional categories (Electricity Delivery, Gas Delivery, Payment, Volumetric, Price, Imbalance, Termination, Credit & Collateral, Force Majeure, Constraint, Events) with a cross-clause DAG.',
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
              <h1 className="text-2xl font-bold text-white">ContractIQ — The Agent Atlas</h1>
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
        <Section title="How ContractIQ Uses Abenix — One Page" icon={Cpu}>
          <p className="text-slate-300">
            ContractIQ is a <strong className="text-white">fully standalone</strong> Next.js + FastAPI app. It does NOT
            run any LLM code itself. Every AI action is a call into Abenix via the SDK with <Code>actAs</Code>
            delegation. The agent YAMLs live in <Code>packages/db/seeds/agents/contractiq_*.yaml</Code> and are
            registered in Abenix's <Code>agents</Code> table.
          </p>
          <div className="rounded-xl border border-slate-700/50 bg-slate-900/50 p-5 space-y-3">
            {[
              ['ContractIQ user clicks "Run ..."', 'JWT issued by ContractIQ\'s own auth service.'],
              ['API calls Abenix SDK', 'One platform API key, X-Abenix-Subject: contractiq:{user_id} on every call.'],
              ['Abenix runs the agent YAML', 'Executes tools in sandbox. Logs cost, latency, tokens, tool calls.'],
              ['Tools enforce row-level RBAC', 'portfolio_energy_contracts + knowledge_search + graph_explorer all scoped to this user_id.'],
              ['Agent returns strict JSON', 'API parses, persists to the ContractIQ DB, returns to the UI.'],
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
            the same platform can drive ContractIQ (energy contracts), Mideast Tourism (travel forecasting), OracleNet
            (intelligence analysis), and others with no platform-level changes.
          </p>
          <div className="space-y-3">
            {INSIGHTS_AGENTS.map(a => <AgentCard key={a.slug} a={a} />)}
          </div>
        </Section>

        {/* ═══════════════ Orchestration ═══════════════ */}
        <Section title="Orchestration & Chat — The Long-Running Workflows" icon={GitBranch}>
          <p className="text-slate-300">
            These agents chain other agents or run long-running scans. They are the "runtime" of ContractIQ — what
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
            not ContractIQ. Same tools power all vertical apps.
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
              ContractIQ now runs as a polymorphic contract platform. The same UI, same calculation engine, same audit ledger — three commodity families with their own specialised data sources, agents, and what-if scenarios.
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
            Market-data feeds are <strong>not</strong> hand-written adapters in ContractIQ. They are <strong>presets</strong> in Abenix — labelled, per-tenant bundles of <code className="bg-slate-800 px-1 rounded">(tool_slug, default_args)</code> over a single generic <code className="bg-slate-800 px-1 rounded">yahoo_finance</code> tool. One engine, many configured shortcuts. Add or edit any preset from <code className="bg-slate-800 px-1 rounded">/admin/tool-presets</code> in Abenix; ContractIQ reads them via the SDK.
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
            <strong>Aspirational vs real today:</strong> the marketing names (LBMA, LPPM, COMEX) are aspirational — every preset currently resolves to a Yahoo Finance futures symbol via the friendly-alias map in the abenix tool. No API keys today. Promoting any preset to a paid feed (LBMA, ICE, Refinitiv) means editing the <code className="bg-slate-800 px-1 rounded">tool_slug</code> field to the new paid-feed tool (or editing the preset's <code className="bg-slate-800 px-1 rounded">config</code> to carry the API key) — <em>zero ContractIQ deploy</em>. The schema is built for it.
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

          <h4 className="text-white font-semibold pt-4 pb-1">Four ContractIQ-shipped models</h4>
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
            ContractIQ does not own its scaling. It rents from the Abenix platform's three-layer scaling system. As traffic grows you tune the right layer:
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-[12px]">
            <div className="p-2.5 rounded-md bg-violet-900/20 border border-violet-700/40">
              <div className="text-violet-300 font-semibold mb-1">Layer 1 · Agents</div>
              <div className="text-slate-300 mb-1 text-[11.5px]">
                Each ContractIQ agent (extractor, hedge advisor, force-majeure monitor, ...) has its own <code className="bg-slate-800 px-1 rounded">runtime_pool</code>, min/max replicas, and qps cap.
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
            <strong>What it means for ContractIQ specifically:</strong> if extractions slow down, the bottleneck is almost always at one of the layers above. The flow is: contractiq-api → SDK call → Abenix agent in runtime_pool → tool calls through the gate. Open <code className="bg-slate-800 px-1 rounded">/admin/pipeline-scaling</code> on the Abenix tenant, expand the extractor pipeline, and the slow node will point you to the right layer to tune.
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
              <li><strong className="text-white">One platform key</strong> — ContractIQ never sees individual user API keys.</li>
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
          <p className="text-xs text-slate-500 mb-2">ContractIQ · PPA · Gas · Metals contract intelligence</p>
          <p className="text-[10px] text-slate-600">
            26 agents · 11 market-data adapters · 6 risk + analytics modules · 6 RBAC personas · 100% Abenix-native
          </p>
        </div>
      </div>
    </div>
  );
}
