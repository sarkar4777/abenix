'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Sparkles, Sunrise, Handshake, AlertOctagon, Receipt,
  Layers, Telescope, GitCompareArrows, Activity, ShieldCheck,
  ArrowRight, Zap, LineChart as LineChartIcon, Gauge, Scale,
} from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

interface Overview {
  briefings_today: number;
  renewals_upcoming: number;
  fm_notices_pending: number;
  reconciliations_total: number;
  families_total: number;
  anomalies_active: number;
  diffs_total: number;
  stress_tests_total: number;
  hedge_recs_total: number;
  valuations_total: number;
  benchmarks_total: number;
}

const FEATURES = [
  {
    id: 'briefing',
    href: '/insights/briefing',
    icon: Sunrise,
    title: 'Daily Executive Briefing',
    tagline: 'Your portfolio in 1 page, every morning',
    description: 'Overnight MtM movement, alerts crossed, top action items. Read it on your phone over coffee.',
    color: 'from-amber-500 to-orange-600',
    border: 'border-amber-500/30',
    glow: 'hover:shadow-amber-500/20',
    countKey: 'briefings_today' as const,
    countLabel: 'Generated today',
    pipeline: 'contractiq-executive-briefing',
  },
  {
    id: 'renewals',
    href: '/insights/renewals',
    icon: Handshake,
    title: 'Renewal Negotiation Copilot',
    tagline: 'Walk into the room ready to close',
    description: 'Historical pricing, market context, counterparty intel, and a 3-position term sheet with NPV uplift.',
    color: 'from-emerald-500 to-teal-600',
    border: 'border-emerald-500/30',
    glow: 'hover:shadow-emerald-500/20',
    countKey: 'renewals_upcoming' as const,
    countLabel: 'Renewals in 180 days',
    pipeline: 'contractiq-renewal-copilot',
  },
  {
    id: 'force-majeure',
    href: '/insights/force-majeure',
    icon: AlertOctagon,
    title: 'Force Majeure Monitor',
    tagline: "Don't miss the 24h notice window",
    description: 'Auto-detects FM-triggering events, drafts notices referencing exact clause numbers, queues for legal review.',
    color: 'from-red-500 to-pink-600',
    border: 'border-red-500/30',
    glow: 'hover:shadow-red-500/20',
    countKey: 'fm_notices_pending' as const,
    countLabel: 'Awaiting review',
    pipeline: 'contractiq-force-majeure-monitor',
  },
  {
    id: 'reconciliation',
    href: '/insights/reconciliation',
    icon: Receipt,
    title: 'Settlement Reconciliation',
    tagline: 'Recover the 1-3% nobody verifies',
    description: 'Recompute invoices against contract pricing, escalation, indexation. Drafts dispute letters when variance > 1%.',
    color: 'from-cyan-500 to-blue-600',
    border: 'border-cyan-500/30',
    glow: 'hover:shadow-cyan-500/20',
    countKey: 'reconciliations_total' as const,
    countLabel: 'Reconciled',
    pipeline: 'contractiq-settlement-reconciler',
  },
  {
    id: 'families',
    href: '/insights/families',
    icon: Layers,
    title: 'Contract Families',
    tagline: 'Reason across master + amendments',
    description: 'Group related contracts. Resolve "what is the effective curtailment cap after Amendment 4?" automatically.',
    color: 'from-indigo-500 to-purple-600',
    border: 'border-indigo-500/30',
    glow: 'hover:shadow-indigo-500/20',
    countKey: 'families_total' as const,
    countLabel: 'Families',
    pipeline: '(data model)',
  },
  {
    id: 'anomalies',
    href: '/insights/anomalies',
    icon: Telescope,
    title: 'Clause Anomaly Detector',
    tagline: 'Find the buried risks reviewers miss',
    description: 'Statistical outlier detection across your portfolio surfaces clauses that materially differ from your baseline.',
    color: 'from-purple-500 to-fuchsia-600',
    border: 'border-purple-500/30',
    glow: 'hover:shadow-purple-500/20',
    countKey: 'anomalies_active' as const,
    countLabel: 'Active anomalies',
    pipeline: 'contractiq-clause-anomaly',
  },
  {
    id: 'version-diff',
    href: '/insights/version-diff',
    icon: GitCompareArrows,
    title: 'Version Diff',
    tagline: 'Semantic redline review',
    description: 'Compare two contract versions clause-by-clause. Each change classified as tightened/loosened/added/removed with impact rating.',
    color: 'from-pink-500 to-rose-600',
    border: 'border-pink-500/30',
    glow: 'hover:shadow-pink-500/20',
    countKey: 'diffs_total' as const,
    countLabel: 'Diffs run',
    pipeline: 'contractiq-version-diff',
  },
  {
    id: 'stress-test',
    href: '/insights/stress-test',
    icon: Activity,
    title: 'Stress Test Simulator',
    tagline: 'Monte Carlo against market shocks',
    description: 'Run 1k+ scenarios across power price, FX, and credit shocks. Get VaR(95%), expected shortfall, worst-case scenarios.',
    color: 'from-orange-500 to-red-600',
    border: 'border-orange-500/30',
    glow: 'hover:shadow-orange-500/20',
    countKey: 'stress_tests_total' as const,
    countLabel: 'Tests run',
    pipeline: 'contractiq-stress-test',
  },
  {
    id: 'hedge',
    href: '/insights/hedge',
    icon: ShieldCheck,
    title: 'Hedge Advisor',
    tagline: 'Right-sized hedges, automatically',
    description: 'For each floating exposure, designs swap / collar / option structures with cost and residual risk. Recommends best fit.',
    color: 'from-teal-500 to-emerald-600',
    border: 'border-teal-500/30',
    glow: 'hover:shadow-teal-500/20',
    countKey: 'hedge_recs_total' as const,
    countLabel: 'Recommendations',
    pipeline: 'contractiq-hedge-advisor',
  },
  {
    id: 'valuation',
    href: '/valuation',
    icon: LineChartIcon,
    title: 'Portfolio Valuation & Forecast',
    tagline: 'Forward curves → MtM → T-o-P alerts',
    description: 'Self-updating price curves (power, gas, LNG, carbon, FX), full-portfolio mark-to-market with per-cluster breakdown, and Take-or-Pay shortfall monitoring.',
    color: 'from-indigo-500 to-violet-600',
    border: 'border-indigo-500/30',
    glow: 'hover:shadow-indigo-500/20',
    countKey: 'valuations_total' as const,
    countLabel: 'Valuations',
    pipeline: 'contractiq-portfolio-valuator + contractiq-price-forecaster + contractiq-top-monitor',
  },
  {
    id: 'benchmark',
    href: '/insights/benchmark',
    icon: Scale,
    title: 'Clause Benchmarking',
    tagline: 'Market standard + your portfolio, clause by clause',
    description: 'Pick any clause. The benchmarker reads market standard (Tavily + model contracts) AND your own peer clauses, then returns a stance, deviation score, recommendations, and concrete redline-ready suggested language.',
    color: 'from-indigo-500 to-purple-600',
    border: 'border-indigo-500/30',
    glow: 'hover:shadow-indigo-500/20',
    countKey: 'benchmarks_total' as const,
    countLabel: 'Benchmarks',
    pipeline: 'contractiq-clause-benchmarker',
  },
];

export default function InsightsHubPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    fetch(`${API_URL}/api/contractiq/insights/overview`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.json())
      .then(b => { setOverview(b.data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  return (
    <div className="min-h-screen bg-[#0B0F19]">
      {/* Hero */}
      <div className="relative overflow-hidden border-b border-slate-800/50">
        <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/5 via-transparent to-cyan-500/5" />
        <div className="absolute inset-0" style={{
          backgroundImage: 'radial-gradient(circle at 20% 20%, rgba(16,185,129,0.08), transparent 40%), radial-gradient(circle at 80% 60%, rgba(6,182,212,0.08), transparent 40%)',
        }} />
        <div className="relative max-w-7xl mx-auto px-8 py-12">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
          >
            <div className="flex items-center gap-3 mb-3">
              <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-emerald-500/20 to-cyan-500/20 border border-emerald-500/30 flex items-center justify-center">
                <Sparkles className="w-6 h-6 text-emerald-400" />
              </div>
              <div>
                <h1 className="text-3xl font-bold bg-gradient-to-r from-white via-emerald-100 to-cyan-100 bg-clip-text text-transparent">
                  Insights Hub
                </h1>
                <p className="text-sm text-slate-400">9 agentic workflows powered by Abenix</p>
              </div>
            </div>
            <p className="text-slate-300 text-base max-w-3xl mt-4 leading-relaxed">
              Each card below is a complete agentic workflow. They use the same generic Abenix platform tools
              <span className="text-emerald-300"> (database_query, financial_calculator, entso_e, ember_climate, ecb_rates, tavily_search, code_executor)</span> —
              with domain knowledge encoded in the prompts, not the tools.
            </p>
          </motion.div>
        </div>
      </div>

      {/* Feature grid */}
      <div className="max-w-7xl mx-auto px-8 py-10">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {FEATURES.map((f, idx) => {
            const count = overview?.[f.countKey] ?? 0;
            return (
              <motion.a
                key={f.id}
                href={f.href}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: idx * 0.05, duration: 0.4 }}
                whileHover={{ y: -2 }}
                className={`group relative overflow-hidden rounded-2xl border ${f.border} bg-slate-900/30 backdrop-blur-sm hover:bg-slate-900/50 transition-all p-6 ${f.glow} hover:shadow-xl`}
              >
                {/* Gradient overlay */}
                <div className={`absolute inset-0 bg-gradient-to-br ${f.color} opacity-0 group-hover:opacity-5 transition-opacity`} />

                {/* Top: icon + count */}
                <div className="relative flex items-start justify-between mb-4">
                  <div className={`w-12 h-12 rounded-xl bg-gradient-to-br ${f.color} bg-opacity-20 flex items-center justify-center shadow-lg`}>
                    <f.icon className="w-6 h-6 text-white" />
                  </div>
                  {!loading && (
                    <div className="text-right">
                      <div className="text-2xl font-bold text-white tabular-nums">{count}</div>
                      <div className="text-[10px] text-slate-500 uppercase tracking-wider">{f.countLabel}</div>
                    </div>
                  )}
                </div>

                {/* Title */}
                <h3 className="text-lg font-bold text-white mb-1">{f.title}</h3>
                <p className="text-xs text-emerald-300/80 mb-3 italic">{f.tagline}</p>

                {/* Description */}
                <p className="text-sm text-slate-400 leading-relaxed mb-4">{f.description}</p>

                {/* Footer */}
                <div className="relative flex items-center justify-between pt-3 border-t border-slate-800/50">
                  <div className="flex items-center gap-1.5 text-[10px] text-slate-500">
                    <Zap className="w-3 h-3" />
                    <code className="font-mono">{f.pipeline}</code>
                  </div>
                  <div className="flex items-center gap-1 text-xs text-emerald-400 group-hover:gap-2 transition-all">
                    Open <ArrowRight className="w-3.5 h-3.5" />
                  </div>
                </div>
              </motion.a>
            );
          })}
        </div>

        {/* Bottom info strip */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6 }}
          className="mt-10 rounded-xl border border-slate-800/50 bg-slate-900/30 p-6"
        >
          <div className="flex items-start gap-4">
            <div className="w-10 h-10 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center shrink-0">
              <Sparkles className="w-5 h-5 text-cyan-400" />
            </div>
            <div>
              <h4 className="text-sm font-semibold text-white mb-1">Built on Abenix — generic, auditable, replayable</h4>
              <p className="text-xs text-slate-400 leading-relaxed">
                Every workflow above runs as an OOB agent on Abenix with strict <code className="text-emerald-300">actAs</code> delegation —
                ContractIQ holds one platform key but each call is scoped to <em>your</em> user. All AI work is logged in the Abenix
                executions table with full input/output, cost, latency, and tool-call trace. Click any agent slug to view its definition
                in the Abenix "My Agents" page.
              </p>
            </div>
          </div>
        </motion.div>
      </div>
    </div>
  );
}
