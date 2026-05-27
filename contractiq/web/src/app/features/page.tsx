'use client';

import { motion } from 'framer-motion';
import Link from 'next/link';
import {
  Upload, FileText, BookOpen, Layers, Sparkles, RefreshCw, AlertOctagon, Wallet,
  Telescope, GitCompare, FlaskConical, Wind, Briefcase, GitBranch, Calendar,
  LineChart as LineChartIcon, Activity, Gauge, ShieldCheck, FileCheck2, MessageSquare,
  TrendingUp, Diamond, AlertTriangle, Truck, Globe, Radar, Cpu, Database, ArrowRight,
  Workflow, Zap, Network, Eye, Search,
} from 'lucide-react';

type Feature = {
  slug: string;
  href: string;
  icon: any;
  title: string;
  oneLiner: string;
  agent: string;
  how: string[];
  inputs: string;
  outputs: string;
  standards?: string[];
};

const FOUNDATION: Feature[] = [
  {
    slug: 'upload',
    href: '/upload',
    icon: Upload,
    title: 'Contract Upload',
    oneLiner: 'Drag a PDF or DOCX. The platform parses, fingerprints, and queues it for extraction.',
    agent: 'contractiq-extractor-agent',
    how: [
      'PDF / DOCX / TXT is parsed and split into clauses on contract-aware boundaries.',
      'Each section is fingerprinted so re-uploads of the same document are caught and version-linked.',
      'The extractor agent fires immediately and the live DAG is streamed back over SSE.',
    ],
    inputs: 'Any PDF, DOCX, or plain-text contract up to 50 MB',
    outputs: 'A contract row, ~30 first-pass fields, the clause set, an executions trace',
  },
  {
    slug: 'extract',
    href: '/contracts',
    icon: FileText,
    title: 'Standard Extraction',
    oneLiner: 'First-pass field extraction — counterparty, dates, notional, jurisdiction, key clauses.',
    agent: 'contractiq-extractor-agent · contractiq-pipeline',
    how: [
      'The extractor agent runs a structured-output prompt against the parsed text.',
      'Clauses are tagged by type (termination, force majeure, payment, performance, etc).',
      'Each field carries a citation span so you can click back to the exact paragraph.',
    ],
    inputs: 'Contract text',
    outputs: '30+ commercial fields + 8-15 typed clauses with citations',
  },
  {
    slug: 'deep-extract',
    href: '/contracts',
    icon: Search,
    title: 'Deep Extraction',
    oneLiner: 'Second-pass for the long tail — 100+ fields including obscure rate-resets and side-letter terms.',
    agent: 'contractiq-deep-extractor',
    how: [
      'Runs after standard extraction when a contract is judged complex enough.',
      'Sub-agents per clause family read the source text with extended context.',
      'Outputs are merged with the standard set and surfaced as one normalised record.',
    ],
    inputs: 'A contract that already has standard extraction',
    outputs: '100+ fields including indexation, escalation, FX, cure periods, ROFR / ROFO / option clauses',
  },
  {
    slug: 'clause-library',
    href: '/clauses',
    icon: BookOpen,
    title: 'Clause Library + Gap Heatmap',
    oneLiner: 'Every extracted clause across the portfolio with a heatmap of which contract types are missing what.',
    agent: 'contractiq-extractor-agent (data source)',
    how: [
      'Clauses are grouped by type and contract family.',
      'A heatmap surfaces which contract types are systematically missing each clause type.',
      'Click any cell to drill into the underlying clauses and contracts.',
    ],
    inputs: 'Extracted clauses across the portfolio',
    outputs: 'Filterable clause list + portfolio-wide gap heatmap',
  },
];

const OPERATIONS: Feature[] = [
  {
    slug: 'briefing',
    href: '/insights/briefing',
    icon: Sparkles,
    title: 'Daily Briefing',
    oneLiner: 'One-page synthesis of everything that changed in the portfolio overnight.',
    agent: 'contractiq-executive-briefing',
    how: [
      'Pulls the day-over-day delta on renewals, force-majeure notices, anomalies, market moves, and approvals.',
      'A reasoning model writes a tight exec-style brief with citations back to each insight.',
      'Cached for 24h, regenerable on demand.',
    ],
    inputs: 'Latest portfolio state across every insight module',
    outputs: 'A 5-minute read covering everything you should know before standup',
  },
  {
    slug: 'renewals',
    href: '/insights/renewals',
    icon: RefreshCw,
    title: 'Renewals Copilot',
    oneLiner: 'Generates the negotiation packet for every contract approaching renewal.',
    agent: 'contractiq-renewal-copilot',
    how: [
      'Identifies contracts with renewal windows opening in the next 90 days.',
      'Pulls the original clauses, benchmark comparisons, counterparty risk, and recent market moves.',
      'Drafts a position-paper packet: what to push, what to accept, what to walk away from.',
    ],
    inputs: 'Contract clauses + benchmark cohort + recent market data',
    outputs: 'A renewal packet per contract with recommended terms and walk-away thresholds',
  },
  {
    slug: 'force-majeure',
    href: '/insights/force-majeure',
    icon: AlertOctagon,
    title: 'Force Majeure Monitor',
    oneLiner: 'Watches the news + counterparty notices and pre-screens every clause for whether the event qualifies.',
    agent: 'contractiq-force-majeure-monitor',
    how: [
      'Ingests counterparty FM notices and external event feeds.',
      'For each notice, evaluates the contract\'s FM clause against the claimed event.',
      'Returns a qualify / probably-not / clarify verdict with the cited clause text and counterargument.',
    ],
    inputs: 'FM notice from counterparty + the relevant contract',
    outputs: 'Verdict, cited clauses, suggested response, downstream impact',
    standards: ['ICC Force Majeure Clause 2020', 'UNIDROIT Principles Art. 7.1.7'],
  },
  {
    slug: 'reconciliation',
    href: '/insights/reconciliation',
    icon: Wallet,
    title: 'Settlement Reconciliation',
    oneLiner: 'Compares counterparty invoices against the contract\'s pricing formula and flags mismatches.',
    agent: 'contractiq-settlement-reconciler',
    how: [
      'Upload a counterparty invoice or settlement statement.',
      'The agent rebuilds the expected amount from the contract\'s pricing formula and inputs.',
      'Variance is surfaced line-by-line with a confidence band.',
    ],
    inputs: 'Counterparty invoice or settlement statement',
    outputs: 'Reconciliation report — matched, off-by, missing, extra',
  },
];

const RISK: Feature[] = [
  {
    slug: 'anomalies',
    href: '/insights/anomalies',
    icon: Telescope,
    title: 'Clause Anomaly Detector',
    oneLiner: 'Surfaces clauses that materially differ from the portfolio average for their type.',
    agent: 'contractiq-clause-anomaly',
    how: [
      'For every clause type, computes the portfolio distribution of the key terms (caps, windows, thresholds).',
      'Scores each clause 0..1 by distance from the median.',
      'Anything above 0.7 is flagged with a plain-English why and a benchmark comparison.',
    ],
    inputs: 'All extracted clauses with at least 5 cohort peers',
    outputs: 'Ranked anomaly list with severity and benchmark context',
  },
  {
    slug: 'stress-test',
    href: '/insights/stress-test',
    icon: FlaskConical,
    title: 'Stress Test Simulator',
    oneLiner: 'Monte-Carlo the portfolio under price shocks, demand shocks, and counterparty defaults.',
    agent: 'contractiq-stress-test',
    how: [
      'Runs 1000+ scenarios with stochastic moves on the user-selected risk drivers.',
      'Each scenario feeds the contracts\' pricing + termination + force-majeure logic.',
      'Tail outcomes (P95, P99) surface the contracts driving the loss.',
    ],
    inputs: 'A portfolio + chosen scenario (price -30%, gas-supply outage, FX -15%, etc)',
    outputs: 'Loss distribution, top-loss contracts, hedging recommendations',
  },
  {
    slug: 'hedge',
    href: '/insights/hedge',
    icon: Wind,
    title: 'Hedge Idea Generator',
    oneLiner: 'Per-contract hedging recommendations grounded in the live market curve.',
    agent: 'contractiq-hedge-advisor',
    how: [
      'Reads the contract\'s open exposure (volume × residual term × indexation).',
      'Cross-checks against the live forward curve and existing hedges.',
      'Proposes one or two instruments with cost, residual basis risk, and counterparty options.',
    ],
    inputs: 'Contract + market curves',
    outputs: 'Recommended hedges with cost, basis risk, and impact on portfolio VAR',
  },
  {
    slug: 'credit-risk',
    href: '/credit-risk',
    icon: ShieldCheck,
    title: 'Counterparty Risk',
    oneLiner: 'A live credit picture for every counterparty across your contracts.',
    agent: 'contractiq-credit-risk',
    how: [
      'Pulls public credit signals — ratings, CDS spreads, news, sanctions, financials.',
      'Combines with internal exposure (notional × time × concentration).',
      'Outputs PD, LGD, EAD, and an explainable risk grade per counterparty.',
    ],
    inputs: 'Counterparty identity + the portfolio of contracts they hold',
    outputs: 'Probability of default, expected loss, concentration warnings, watch tier',
  },
  {
    slug: 'kyc',
    href: '/credit-risk/kyc',
    icon: FileCheck2,
    title: 'KYC Standard Checks',
    oneLiner: 'Three-indicator KYC against sanctions, PEP, adverse media, sector risk, geography.',
    agent: 'kyc-standard-check',
    how: [
      'Submit counterparty (name, country, industry, annual notional).',
      'The agent fetches sanctions lists, registry data, adverse media, ownership chain.',
      'Three indicators (legal-form, materiality, transparency) aggregate into a tier I/II/III review.',
      'Items can be reviewed line-by-line and the case signed off when complete.',
    ],
    inputs: 'Counterparty name, country, industry, annual notional',
    outputs: 'Per-indicator score, item-level review queue, signoff trail',
    standards: ['FATF 40 Recommendations', 'EU AMLD6', 'OFAC SDN screening'],
  },
];

const PORTFOLIO: Feature[] = [
  {
    slug: 'deal-clusters',
    href: '/deal-clusters',
    icon: GitBranch,
    title: 'Deal Clusters',
    oneLiner: 'Functional clustering of contracts by economic shape, not by document title.',
    agent: 'contractiq-functional-analysis-agent',
    how: [
      'Embeds each contract on its functional features (asset type, tenor, indexation, optionality).',
      'Clusters into deal families with similar economic behaviour.',
      'Surfaces the cluster\'s anchor contract and outlier members.',
    ],
    inputs: 'Extracted commercial fields across the portfolio',
    outputs: 'Cluster map + anchor + outliers per cluster',
  },
  {
    slug: 'families',
    href: '/insights/families',
    icon: Layers,
    title: 'Contract Families',
    oneLiner: 'Manual + auto-discovered groupings — e.g. all UK CFDs, all Spanish solar PPAs.',
    agent: 'contractiq-functional-analysis-agent (assist)',
    how: [
      'Heuristics + LLM tagging propose families.',
      'You curate them, give them business names, and pin contracts in or out.',
      'Used everywhere — dashboards, benchmarks, briefings filter by family.',
    ],
    inputs: 'Portfolio + your family definitions',
    outputs: 'Named families, membership, family-level rollups',
  },
  {
    slug: 'valuation',
    href: '/valuation',
    icon: LineChartIcon,
    title: 'Portfolio Valuation',
    oneLiner: 'NPV + risk-adjusted value of every contract under the current and forward curves.',
    agent: 'contractiq-portfolio-valuator · contractiq-price-forecaster · contractiq-top-monitor',
    how: [
      'Forecast curves: a price-forecaster agent builds the user-tenant forward curve from market data.',
      'Valuator: each contract is valued under the curve with its specific indexation + optionality.',
      'Top monitor: a streaming top-of-portfolio view that re-prices on every curve refresh.',
    ],
    inputs: 'Portfolio + market data + scenario assumptions',
    outputs: 'NPV, VAR, P95 loss, top-of-portfolio contributions, sensitivity grid',
  },
  {
    slug: 'benchmarks',
    href: '/insights/benchmark',
    icon: Briefcase,
    title: 'Clause Benchmarks',
    oneLiner: 'For each clause, how do your terms compare to the cohort?',
    agent: 'contractiq-clause-benchmarker',
    how: [
      'For each clause, builds the cohort (same family, same jurisdiction, same tenor band).',
      'Reports your term, the cohort median, the P25 / P75, and the percentile.',
      'Flags clauses where you are materially worse than the cohort.',
    ],
    inputs: 'A clause + its peer cohort',
    outputs: 'Percentile, cohort distribution, recommendation, walk-back terms',
  },
];

const INSIGHTS: Feature[] = [
  {
    slug: 'market',
    href: '/market',
    icon: Activity,
    title: 'Market & Risk',
    oneLiner: 'Live market view sized to the portfolio — what moves matter.',
    agent: 'contractiq-market-monitor',
    how: [
      'Sources curves, fixings, FX, and indexation underlyings for everything in the portfolio.',
      'Highlights moves that change > 1% of portfolio NPV.',
      'Cross-links into the contracts driving the sensitivity.',
    ],
    inputs: 'Portfolio composition + market data feeds',
    outputs: 'Top-moving underliers, impact per contract, action prompts',
  },
  {
    slug: 'simulations',
    href: '/simulations',
    icon: Gauge,
    title: 'Simulations',
    oneLiner: 'Monte-Carlo, weather, sentiment, price-sensitivity — interactive what-ifs.',
    agent: 'contractiq-market-simulator · contractiq-stress-test',
    how: [
      'Pick a simulation type and a contract or family.',
      'The agent stochastically draws inputs, runs the contract logic, and rolls up the outcomes.',
      'Histograms, tail tables, and the top-pain contracts are shown live.',
    ],
    inputs: 'Contract / family + scenario parameters',
    outputs: 'Distribution + percentile readouts + tail-driver breakdown',
  },
  {
    slug: 'timeline',
    href: '/timeline',
    icon: Calendar,
    title: 'Event Timeline',
    oneLiner: 'A chronological view of every material event across the portfolio.',
    agent: 'contractiq-extractor-agent (data source)',
    how: [
      'Each contract\'s milestones (notice dates, renewals, options, true-up dates) feed one timeline.',
      'Filter by family, counterparty, or event kind.',
      'Click any event to jump to the underlying clause.',
    ],
    inputs: 'Contract event dates extracted at upload',
    outputs: 'Filterable timeline with deep-links',
  },
  {
    slug: 'version-diff',
    href: '/insights/version-diff',
    icon: GitCompare,
    title: 'Version Diff',
    oneLiner: 'Semantic comparison between two versions — what actually changed, not just where.',
    agent: 'contractiq-version-diff',
    how: [
      'Aligns clauses across the two versions on type + semantic similarity.',
      'For each pair, reports the change kind (added, removed, materially changed, cosmetic).',
      'Each material change is scored as favourable, neutral, or adverse for you.',
    ],
    inputs: 'Two versions of the same contract',
    outputs: 'Per-clause delta table + overall direction (favourable / mixed / adverse)',
  },
  {
    slug: 'compare',
    href: '/compare',
    icon: TrendingUp,
    title: 'Compare',
    oneLiner: 'Side-by-side comparison of any two contracts on the same canvas.',
    agent: 'contractiq-clause-benchmarker (assist)',
    how: [
      'Pick two contracts. The view aligns common clauses and highlights divergences.',
      'Color-codes which contract has the more favourable term per clause.',
      'Exports as a comparison memo.',
    ],
    inputs: 'Two contracts',
    outputs: 'Aligned comparison + memo export',
  },
  {
    slug: 'chat',
    href: '/chat',
    icon: MessageSquare,
    title: 'Contract Chat',
    oneLiner: 'Ask anything about your portfolio — the chat agent has access to every other module as a tool.',
    agent: 'contractiq-chat-agent',
    how: [
      'A reasoning model holds your portfolio context.',
      'It calls the other agents as tools (invoke_agent) when it needs computation, not memory.',
      'Every answer includes the citations and the agent runs that backed it.',
    ],
    inputs: 'A natural-language question',
    outputs: 'An answer with cited clauses, contracts, and agent traces',
  },
];

const METALS: Feature[] = [
  {
    slug: 'metals-extract',
    href: '/metals/extract',
    icon: Diamond,
    title: 'Metals Extraction',
    oneLiner: 'Second-pass extraction for precious-metals contracts — purity, bar specs, loco, pricing, assay, vaulting.',
    agent: 'contractiq-metals-extractor',
    how: [
      'Operates after standard extraction. Reads contract text + the first-pass output.',
      'Pulls 35+ metals-specific fields including material class, fineness, Good Delivery standard, accepted refiner list, assay tolerance, vaulting type, settlement currency, and concentrate-economics (TC/RC, payable %).',
      'Outputs are persisted per contract and feed every downstream metals module.',
    ],
    inputs: 'A contract that already passed standard extraction',
    outputs: '35+ structured metals fields + sanctions clauses + compliance-references map',
    standards: ['LBMA Good Delivery v1.1', 'LPPM Good Delivery', 'ISO 22368'],
  },
  {
    slug: 'metals-compliance',
    href: '/metals/compliance',
    icon: ShieldCheck,
    title: 'Compliance Audit',
    oneLiner: 'Sixteen-item industry checklist — LBMA, LPPM, OECD, RJC, Dodd-Frank, EU 2017/821, ISO, Swiss PMCA, HMRC VAT, REACH, sanctions.',
    agent: 'contractiq-metals-compliance-auditor',
    how: [
      'Walks the checklist item by item. For each, decides applicable / not applicable.',
      'For each applicable item, finds the citation in the contract and verdicts pass / fail / unclear.',
      'Flags superseded references (e.g. GOFO post-2023, old RGG version) as automatic findings.',
      'Outputs an overall compliance score plus block-level and clarification counts.',
    ],
    inputs: 'A metals contract',
    outputs: '16 verdicts with citations + superseded-reference list + 0..1 overall score',
    standards: [
      'LBMA Responsible Gold Guidance',
      'LPPM Good Delivery',
      'OECD Due Diligence Guidance 3rd ed',
      'RJC Code of Practices + CoC',
      'Dodd-Frank §1502',
      'EU 2017/821',
      'ISO 9001 / 14001 / 22368',
      'Swiss PMCA',
      'HMRC Notice 701/14',
      'REACH (EC 1907/2006)',
    ],
  },
  {
    slug: 'metals-disputes',
    href: '/metals/disputes',
    icon: AlertTriangle,
    title: 'Dispute Risk Scorer',
    oneLiner: 'Quantifies the assay, weight, brand, delivery, and sanctions exposure as an expected $ loss.',
    agent: 'contractiq-metals-dispute-scorer',
    how: [
      'Scores eight dimensions 0..1 — assay tolerance, weight variance, brand rigidity, late-delivery exposure, sanctions indemnity scope, loco/FX risk, lease-rate volatility, list dependency.',
      'Each dimension carries an expected $ exposure based on industry dispute rates at the contract\'s tolerance band.',
      'Aggregates into a low / elevated / high tier with expected loss as % of notional.',
      'Top recommendations point at the specific clause language to amend.',
    ],
    inputs: 'A metals contract with extraction',
    outputs: 'Dimensions + aggregate score + expected $ loss + remediation recommendations',
  },
  {
    slug: 'metals-loco',
    href: '/metals/loco',
    icon: Truck,
    title: 'Loco + Delivery',
    oneLiner: 'Implied loco premium vs benchmark, insurance allocation, customs exposure, chain-of-integrity rating.',
    agent: 'contractiq-metals-loco-analyzer',
    how: [
      'Computes the loco premium vs loco London for the contract\'s reference price.',
      'Verifies who arranges insurance, the carrier-count gap, and policy alignment with vault handover.',
      'Maps the contract\'s trade lane to a customs / VAT picture (Swiss-EU, EU-US, China import quota).',
      'Rates chain-of-integrity (serialisation, RFID, bonded transport, Doré Integrity protocol).',
    ],
    inputs: 'A metals contract',
    outputs: 'Loco premium, insurance gap rating, customs exposure, chain-of-integrity score',
  },
  {
    slug: 'metals-sourcing',
    href: '/metals/sourcing',
    icon: Globe,
    title: 'Responsible Sourcing',
    oneLiner: 'OECD 5-step + LBMA RGG 5-step + RJC Chain of Custody evidence map per contract.',
    agent: 'contractiq-metals-sourcing-tracker',
    how: [
      'For each of the OECD due-diligence steps, captures evidence in the contract + classifies the gap.',
      'Same for the LBMA RGG five steps and the RJC CoC certificate reference.',
      'Detects high-risk geographies (DRC, CAR, Sudan, Myanmar, post-2022 Russian metal) and demands explicit exclusions.',
      'Outputs an audit-readiness score and a remediation list to close gaps before the next external audit.',
    ],
    inputs: 'A metals contract + counterparty identity',
    outputs: 'Per-step evidence map, gap list with remediation, audit-readiness 0..1',
    standards: [
      'OECD Due Diligence 3rd ed',
      'LBMA Responsible Gold Guidance',
      'RJC Chain of Custody Standard',
      'LBMA Doré Integrity Protocol (2020)',
    ],
  },
  {
    slug: 'metals-refiners',
    href: '/metals/refiners',
    icon: Radar,
    title: 'Refiner Watch',
    oneLiner: 'Every refiner in your portfolio against the live LBMA + LPPM Good Delivery lists and OFAC SDN.',
    agent: 'contractiq-metals-refiner-watch',
    how: [
      'On every run, pulls the union of refiners across your contracts.',
      'Checks each one\'s current LBMA gold / silver / LPPM platinum / palladium status and OFAC SDN listing.',
      'Diffs against the last run — status changes become alerts with your exposure and a recommended action.',
      'Tracks next-audit dates and the last LBMA RGG audit findings.',
    ],
    inputs: 'All refiners referenced across the metals portfolio',
    outputs: 'Watchlist with statuses, alerts on changes, exposure per affected refiner',
  },
];

const PILLARS = [
  { icon: Workflow, title: 'Every interesting calculation is an agent', body: 'No business logic lives in the E&C-Copilot app code. Each module is a thin wrapper that calls an agent on the platform. This is what keeps the answers consistent, auditable, and improvable in one place.' },
  { icon: Database, title: 'Every answer is cited',                       body: 'Every extracted field, every clause, every recommendation, every dispute finding points back to a contract span. You can click any number and land on the line of contract text that produced it.' },
  { icon: Network, title: 'Everything is portfolio-aware',                  body: 'No module reads a single contract in isolation. Anomalies use cohort distributions. Renewals reference benchmark cohorts. Sourcing audits cross-reference the refiner watchlist. The whole is more than the sum.' },
  { icon: Eye, title: 'Every run is observable',                            body: 'Every agent call is an Abenix execution. You can replay it, see the tool calls, inspect the inputs, watch the cost. The runs that produce your numbers are first-class artefacts.' },
  { icon: Zap, title: 'Live updates over SSE',                              body: 'Long-running extractions and audits stream their DAG events live. You see the agent working — and you can cancel mid-flight if you want.' },
];

const SECTIONS = [
  { title: 'Foundation',          desc: 'The four primitives every other module is built on.',           items: FOUNDATION, accent: 'cyan' },
  { title: 'Daily Operations',    desc: 'What the team uses every morning.',                              items: OPERATIONS, accent: 'emerald' },
  { title: 'Risk & Compliance',   desc: 'Find the bombs before they go off.',                             items: RISK, accent: 'amber' },
  { title: 'Portfolio Intelligence', desc: 'How the book sits, valued and benchmarked.',                  items: PORTFOLIO, accent: 'violet' },
  { title: 'Markets & Insight',   desc: 'Live market context and side-by-side analysis.',                 items: INSIGHTS, accent: 'orange' },
  { title: 'Precious Metals',     desc: 'Refiner-grade contract intelligence — six dedicated modules.',   items: METALS, accent: 'amber' },
];

const ACCENT: Record<string, string> = {
  cyan: 'from-cyan-500/10 to-cyan-700/5 border-cyan-500/30',
  emerald: 'from-emerald-500/10 to-emerald-700/5 border-emerald-500/30',
  amber: 'from-amber-500/10 to-amber-700/5 border-amber-500/30',
  violet: 'from-violet-500/10 to-violet-700/5 border-violet-500/30',
  orange: 'from-orange-500/10 to-orange-700/5 border-orange-500/30',
};
const ACCENT_TEXT: Record<string, string> = {
  cyan: 'text-cyan-300',
  emerald: 'text-emerald-300',
  amber: 'text-amber-300',
  violet: 'text-violet-300',
  orange: 'text-orange-300',
};

export default function FeaturesPage() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <div className="max-w-7xl mx-auto p-6 lg:p-10">
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="mb-12"
        >
          <div className="text-xs uppercase tracking-wide text-cyan-400 mb-2">E&C-Copilot — capabilities</div>
          <h1 className="text-4xl md:text-5xl font-bold text-white mb-3">Every feature, every agent, every output</h1>
          <p className="text-base text-slate-400 max-w-3xl leading-relaxed">
            E&C-Copilot is a portfolio-aware contract intelligence platform. Every meaningful answer is produced by a named agent, every number is cited back to a contract span, and every run is observable.
            This page is the long-form tour — what each module does, which agent backs it, what goes in, what comes out.
          </p>
        </motion.div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-3 mb-12">
          {PILLARS.map((p, i) => (
            <motion.div
              key={p.title}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: i * 0.05 }}
              className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80"
            >
              <p.icon className="w-5 h-5 text-cyan-400 mb-2" />
              <div className="text-sm font-semibold text-white mb-1.5">{p.title}</div>
              <div className="text-xs text-slate-400 leading-relaxed">{p.body}</div>
            </motion.div>
          ))}
        </div>

        {SECTIONS.map((section, sIdx) => (
          <section key={section.title} className="mb-12">
            <div className="flex items-end justify-between mb-4">
              <div>
                <div className={`text-xs uppercase tracking-wide ${ACCENT_TEXT[section.accent]} mb-1`}>{sIdx + 1}. {section.title}</div>
                <div className="text-2xl font-bold text-white">{section.title}</div>
                <div className="text-sm text-slate-400 mt-1">{section.desc}</div>
              </div>
              <div className="text-xs text-slate-500">{section.items.length} module{section.items.length > 1 ? 's' : ''}</div>
            </div>
            <div className="space-y-3">
              {section.items.map((f, fIdx) => (
                <motion.div
                  key={f.slug}
                  initial={{ opacity: 0, x: -10 }}
                  whileInView={{ opacity: 1, x: 0 }}
                  viewport={{ once: true, margin: '-40px' }}
                  transition={{ duration: 0.3, delay: fIdx * 0.03 }}
                  className={`p-5 rounded-xl bg-gradient-to-br ${ACCENT[section.accent]} border`}
                >
                  <div className="flex items-start justify-between gap-4 mb-3">
                    <div className="flex items-start gap-3">
                      <div className={`p-2 rounded-lg bg-slate-900/60 ${ACCENT_TEXT[section.accent]}`}>
                        <f.icon className="w-5 h-5" />
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="text-lg font-bold text-white">{f.title}</h3>
                          <Link href={f.href} className="text-[10px] uppercase tracking-wide text-slate-400 hover:text-slate-200 flex items-center gap-0.5">
                            open <ArrowRight className="w-3 h-3" />
                          </Link>
                        </div>
                        <div className="text-sm text-slate-300 mt-0.5">{f.oneLiner}</div>
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-4">
                    <div>
                      <div className="flex items-center gap-1 text-[10px] uppercase tracking-wide text-slate-500 mb-1.5">
                        <Cpu className="w-3 h-3" /> agent
                      </div>
                      <div className="text-xs font-mono text-cyan-300 break-all">{f.agent}</div>
                    </div>
                    <div>
                      <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1.5">inputs</div>
                      <div className="text-xs text-slate-300">{f.inputs}</div>
                    </div>
                    <div>
                      <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1.5">outputs</div>
                      <div className="text-xs text-slate-300">{f.outputs}</div>
                    </div>
                  </div>

                  <div className="mt-4">
                    <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-2">how it works</div>
                    <ol className="space-y-1.5">
                      {f.how.map((h, i) => (
                        <li key={i} className="text-xs text-slate-300 leading-relaxed flex gap-2">
                          <span className={`shrink-0 inline-flex items-center justify-center w-4 h-4 rounded-full bg-slate-800/80 ${ACCENT_TEXT[section.accent]} text-[9px] font-bold mt-0.5`}>{i + 1}</span>
                          <span>{h}</span>
                        </li>
                      ))}
                    </ol>
                  </div>

                  {f.standards && f.standards.length > 0 && (
                    <div className="mt-4 flex flex-wrap gap-1.5">
                      <div className="text-[10px] uppercase tracking-wide text-slate-500 mr-1 self-center">standards</div>
                      {f.standards.map((s) => (
                        <span key={s} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-900/80 border border-slate-700 text-slate-400">{s}</span>
                      ))}
                    </div>
                  )}
                </motion.div>
              ))}
            </div>
          </section>
        ))}

        <div className="mt-16 p-6 rounded-xl bg-gradient-to-br from-cyan-500/5 to-violet-500/5 border border-cyan-500/20 text-center">
          <Diamond className="w-8 h-8 text-amber-300 mx-auto mb-3" />
          <div className="text-lg font-bold text-white mb-1">Every module above is wired to a real agent on Abenix.</div>
          <div className="text-sm text-slate-400 max-w-2xl mx-auto">
            Click into any feature and the agent fires for real. The DAG, the tool calls, the citations, the cost — all live, all observable in the executions view.
          </div>
        </div>
      </div>
    </div>
  );
}
