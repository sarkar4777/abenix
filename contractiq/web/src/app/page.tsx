'use client';

import { useState } from 'react';
import { motion } from 'framer-motion';
import {
  Mail, Lock, ArrowRight, Sparkles, Eye, EyeOff, Shield, Zap,
  FileText, TrendingUp, AlertOctagon, Handshake, Sunrise, Receipt,
  Layers, Telescope, GitCompareArrows, Activity, ShieldCheck,
  MessageSquare, Brain, Database, CheckCircle2, Building2, Flame,
  Calculator, Globe, Scale, DollarSign, Gauge, Target, BookOpen,
  Lightbulb, Network, Clock,
} from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';

type Tab = 'login' | 'register';

const SUPPORTED_CONTRACTS = [
  {
    type: 'Power Purchase Agreements (PPA)',
    icon: Zap,
    gradient: 'from-emerald-500 to-teal-600',
    subtypes: ['Solar PV', 'Onshore Wind', 'Offshore Wind', 'Hydro', 'Hybrid', 'Storage-coupled'],
    description: 'Long-term (10-25y) physical or virtual contracts for renewable generation. Analyzes strike prices, escalation, curtailment, COD milestones.',
  },
  {
    type: 'Gas Supply Agreements',
    icon: Flame,
    gradient: 'from-amber-500 to-orange-600',
    subtypes: ['Pipeline Gas', 'LNG (FOB/DES/CIF)', 'Hub-Indexed', 'Oil-Indexed', 'Take-or-Pay'],
    description: 'Short, medium, and long-term natural gas supply contracts. Handles take-or-pay, MDQ/ACQ, indexation formulas, destination clauses.',
  },
  {
    type: 'Tolling Agreements',
    icon: Gauge,
    gradient: 'from-cyan-500 to-blue-600',
    subtypes: ['Power Tolling', 'LNG Regas', 'Processing', 'Storage'],
    description: 'Fuel-conversion structures where toller supplies fuel and offtaker pays capacity + variable fee.',
  },
  {
    type: 'Virtual PPAs (vPPA)',
    icon: Network,
    gradient: 'from-purple-500 to-fuchsia-600',
    subtypes: ['CfD Swaps', 'Synthetic PPAs', 'Proxy Revenue Swaps'],
    description: 'Financial settlements that decouple physical delivery from the price hedge. Fully modelled for MtM.',
  },
  {
    type: 'Carbon & RECs',
    icon: Globe,
    gradient: 'from-lime-500 to-green-600',
    subtypes: ['EU ETS Allowances', 'UK ETS', 'I-RECs', 'GOs', 'Voluntary Credits'],
    description: 'Certificate trades, offtake, and pass-through clauses. Full price-tracking via Ember.',
  },
  {
    type: 'Energy Derivatives',
    icon: TrendingUp,
    gradient: 'from-pink-500 to-rose-600',
    subtypes: ['Forwards', 'Futures', 'Swaps', 'Collars', 'Caps / Floors'],
    description: 'Standalone hedges plus embedded optionality inside physical contracts. Extracts strike, tenor, counterparty.',
  },
];

const FEATURES = [
  {
    icon: Sunrise,
    title: 'Daily Executive Briefing',
    tagline: 'Your portfolio in 1 page, every morning',
    desc: 'Overnight MtM movement, alerts crossed, critical actions. CFO-ready, mobile-first.',
    color: 'text-amber-400',
    bg: 'bg-amber-500/10',
  },
  {
    icon: Handshake,
    title: 'Renewal Negotiation Copilot',
    tagline: 'Walk in ready to close',
    desc: 'Historical pricing, market context, counterparty intel, 3-position term sheet with NPV uplift.',
    color: 'text-emerald-400',
    bg: 'bg-emerald-500/10',
  },
  {
    icon: AlertOctagon,
    title: 'Force Majeure Monitor',
    tagline: 'Never miss the 24h notice window',
    desc: 'Auto-detects FM-triggering events from ENTSO-E, Ember, regulatory feeds. Drafts notices for legal review.',
    color: 'text-red-400',
    bg: 'bg-red-500/10',
  },
  {
    icon: Receipt,
    title: 'Settlement Reconciliation',
    tagline: 'Recover the 1-3% nobody verifies',
    desc: 'Recomputes invoices against contract pricing, escalation, indexation. Drafts dispute letters on variance.',
    color: 'text-cyan-400',
    bg: 'bg-cyan-500/10',
  },
  {
    icon: Layers,
    title: 'Contract Families',
    tagline: 'Reason across amendments',
    desc: 'Group master + amendments + side letters. "What is the effective curtailment cap after Amendment 4?"',
    color: 'text-indigo-400',
    bg: 'bg-indigo-500/10',
  },
  {
    icon: Telescope,
    title: 'Clause Anomaly Detection',
    tagline: 'Find buried risks reviewers miss',
    desc: 'Statistical outlier detection surfaces clauses materially different from your portfolio baseline.',
    color: 'text-purple-400',
    bg: 'bg-purple-500/10',
  },
  {
    icon: GitCompareArrows,
    title: 'Semantic Version Diff',
    tagline: 'Redline review that thinks',
    desc: 'Compares two contract versions clause-by-clause. Classifies each change: tightened / loosened / added / removed.',
    color: 'text-pink-400',
    bg: 'bg-pink-500/10',
  },
  {
    icon: Activity,
    title: 'Stress Test Simulator',
    tagline: 'Monte Carlo against market shocks',
    desc: 'Run 1k-10k scenarios across power, FX, credit shocks. VaR(95%), expected shortfall, worst-case P&Ls.',
    color: 'text-orange-400',
    bg: 'bg-orange-500/10',
  },
  {
    icon: ShieldCheck,
    title: 'Hedge Advisor',
    tagline: 'Right-sized hedges, automatically',
    desc: 'Designs swap / collar / option structures for each floating exposure. Recommends best fit for your risk tolerance.',
    color: 'text-teal-400',
    bg: 'bg-teal-500/10',
  },
];

const STACK = [
  { icon: Brain, label: 'Claude Sonnet 4.5', desc: 'Frontier reasoning model for extraction, risk analysis, and negotiation intelligence' },
  { icon: Database, label: 'Knowledge Graph', desc: 'Neo4j graph of entities, relationships, clauses — powers cross-contract semantic queries' },
  { icon: Network, label: 'Hybrid Vector Search', desc: 'Pinecone + graph traversal via Cognify for "find contracts like this" questions' },
  { icon: Globe, label: 'Live Market Data', desc: 'ENTSO-E (EU power), Ember (UK+carbon), ECB (FX, rates), EIA (US gas)' },
  { icon: Calculator, label: 'Financial Engine', desc: 'NPV, IRR, LCOE, Black-Scholes, payback period, amortization, WACC — all built-in' },
  { icon: Shield, label: 'Strict RBAC', desc: 'Row-level isolation. Each user only sees their own contracts. actAs delegation pattern.' },
];

const STATS = [
  { number: '100-200', label: 'page contracts analyzed per upload', sub: 'in ~60 seconds' },
  { number: '9', label: 'agentic workflows', sub: 'from briefing to hedging' },
  { number: '12+', label: 'market data sources', sub: 'live, not stale' },
  { number: '~$0.90', label: 'cost per contract extracted', sub: 'with full risk analysis' },
];

export default function ContractIQLandingPage() {
  const [tab, setTab] = useState<Tab>('login');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [form, setForm] = useState({ email: '', password: '', full_name: '', organization: '' });
  const [showAuth, setShowAuth] = useState(false);

  function updateField(field: string, value: string) {
    setForm(prev => ({ ...prev, [field]: value }));
    setError('');
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
      const endpoint = tab === 'register' ? '/api/contractiq/auth/register' : '/api/contractiq/auth/login';
      const body = tab === 'register'
        ? { email: form.email, password: form.password, full_name: form.full_name, organization: form.organization }
        : { email: form.email, password: form.password };

      const res = await fetch(`${API_URL}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      const json = await res.json();
      if (json.error) {
        setError(typeof json.error === 'string' ? json.error : json.error.message || 'Authentication failed');
        return;
      }

      if (json.data?.access_token) {
        localStorage.setItem('contractiq_token', json.data.access_token);
        localStorage.setItem('contractiq_refresh_token', json.data.refresh_token);
        localStorage.setItem('contractiq_user', JSON.stringify(json.data.user));
        window.location.href = '/dashboard';
      }
    } catch {
      setError('Connection failed. Is the API running?');
    } finally {
      setLoading(false);
    }
  }

  function fillDemo() {
    setForm({ ...form, email: 'test@contractiq.com', password: 'TestPass123!' });
    setTab('login');
  }

  return (
    <div className="min-h-screen bg-[#0B0F19] text-white overflow-x-hidden">
      {/* Animated background */}
      <div className="fixed inset-0 pointer-events-none">
        <div className="absolute inset-0" style={{
          backgroundImage: `
            radial-gradient(circle at 15% 20%, rgba(16,185,129,0.12), transparent 45%),
            radial-gradient(circle at 85% 60%, rgba(6,182,212,0.10), transparent 45%),
            radial-gradient(circle at 50% 100%, rgba(139,92,246,0.08), transparent 50%)
          `,
        }} />
        <div className="absolute inset-0 opacity-[0.03]" style={{
          backgroundImage: 'linear-gradient(to right, #10b981 1px, transparent 1px), linear-gradient(to bottom, #10b981 1px, transparent 1px)',
          backgroundSize: '48px 48px',
        }} />
      </div>

      {/* Nav */}
      <nav className="relative z-20 border-b border-slate-800/50 backdrop-blur-sm bg-slate-950/40">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center">
              <img src="/contractiq-logo.svg" alt="ContractIQ" className="w-6 h-6" />
            </div>
            <div>
              <div className="text-lg font-bold">ContractIQ</div>
              <div className="text-[10px] text-slate-500 uppercase tracking-wider">PPA &amp; Gas Contract Intelligence</div>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <a href="#features" className="text-xs text-slate-400 hover:text-white transition-colors hidden sm:block">Features</a>
            <a href="#contracts" className="text-xs text-slate-400 hover:text-white transition-colors hidden sm:block">Supported</a>
            <a href="#stack" className="text-xs text-slate-400 hover:text-white transition-colors hidden sm:block">Stack</a>
            <button onClick={() => setShowAuth(true)}
              className="px-4 py-2 rounded-lg bg-gradient-to-r from-emerald-500 to-cyan-600 text-white text-xs font-semibold hover:shadow-lg hover:shadow-emerald-500/25 transition-all">
              Sign In
            </button>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="relative z-10 max-w-7xl mx-auto px-6 pt-20 pb-16">
        <div className="grid grid-cols-1 lg:grid-cols-[1.2fr_1fr] gap-12 items-center">
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6 }}>
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/30 mb-6">
              <Sparkles className="w-3.5 h-3.5 text-emerald-400" />
              <span className="text-xs text-emerald-300 font-medium">Powered by Abenix · 9 agentic workflows</span>
            </div>
            <h1 className="text-4xl md:text-6xl font-bold leading-tight mb-6">
              Upload your PPA.<br />
              <span className="bg-gradient-to-r from-emerald-400 via-cyan-400 to-purple-400 bg-clip-text text-transparent">In 60 seconds, know every risk.</span>
            </h1>
            <p className="text-lg text-slate-300 leading-relaxed mb-8 max-w-2xl">
              ContractIQ ingests 100-200 page energy contracts, extracts every clause, asset, and risk factor via
              multi-pass LLM analysis, builds a knowledge graph of relationships, and lets you <strong className="text-white">chat with your entire portfolio</strong>.
              Purpose-built for PPAs, gas supply agreements, tolling, and virtual PPAs.
            </p>
            <div className="flex flex-wrap gap-4">
              <button onClick={() => setShowAuth(true)}
                className="px-6 py-3 rounded-xl bg-gradient-to-r from-emerald-500 to-cyan-600 text-white text-sm font-semibold hover:shadow-2xl hover:shadow-emerald-500/30 transition-all flex items-center gap-2">
                Get Started <ArrowRight className="w-4 h-4" />
              </button>
              <button onClick={() => { fillDemo(); setShowAuth(true); }}
                className="px-6 py-3 rounded-xl border border-slate-700 text-slate-300 text-sm font-semibold hover:border-emerald-500/50 hover:text-white transition-all">
                Try the Demo
              </button>
              <a href="#features" className="px-6 py-3 rounded-xl border border-slate-800 text-slate-400 text-sm hover:text-white transition-all flex items-center gap-2">
                <BookOpen className="w-4 h-4" /> See what it does
              </a>
            </div>

            {/* Trust strip */}
            <div className="mt-10 flex flex-wrap items-center gap-6 text-xs text-slate-500">
              <div className="flex items-center gap-1.5"><Shield className="w-3.5 h-3.5 text-emerald-400" /> Row-level RBAC</div>
              <div className="flex items-center gap-1.5"><Lock className="w-3.5 h-3.5 text-emerald-400" /> Your contracts, your data</div>
              <div className="flex items-center gap-1.5"><Network className="w-3.5 h-3.5 text-emerald-400" /> actAs delegation</div>
              <div className="flex items-center gap-1.5"><CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> SOC2-ready architecture</div>
            </div>
          </motion.div>

          {/* Hero card — live stats */}
          <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.6, delay: 0.2 }}
            className="relative">
            <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/20 to-cyan-500/20 blur-3xl rounded-full" />
            <div className="relative rounded-2xl border border-slate-800/50 bg-slate-900/70 backdrop-blur-xl p-6 shadow-2xl">
              <div className="flex items-center gap-2 mb-4 pb-4 border-b border-slate-800/50">
                <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                <span className="text-[10px] uppercase tracking-wider text-emerald-400 font-semibold">Live Dashboard Preview</span>
              </div>
              <div className="grid grid-cols-2 gap-3">
                {STATS.map(s => (
                  <div key={s.label} className="rounded-xl bg-slate-800/40 border border-slate-700/30 p-4">
                    <div className="text-2xl font-bold bg-gradient-to-r from-emerald-300 to-cyan-300 bg-clip-text text-transparent">{s.number}</div>
                    <div className="text-[10px] text-slate-400 mt-1 leading-tight">{s.label}</div>
                    <div className="text-[10px] text-slate-600 mt-0.5">{s.sub}</div>
                  </div>
                ))}
              </div>
              <div className="mt-4 pt-4 border-t border-slate-800/50">
                <div className="flex items-center justify-between text-[11px]">
                  <div className="flex items-center gap-1.5 text-slate-400">
                    <Activity className="w-3 h-3 text-emerald-400" />
                    <span>Pipelines running</span>
                  </div>
                  <span className="text-emerald-300 font-mono">contractiq-extraction-pipeline</span>
                </div>
              </div>
            </div>
          </motion.div>
        </div>
      </section>

      {/* Supported contracts */}
      <section id="contracts" className="relative z-10 max-w-7xl mx-auto px-6 py-16 border-t border-slate-800/50">
        <div className="text-center mb-12">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-cyan-500/10 border border-cyan-500/30 mb-4">
            <FileText className="w-3.5 h-3.5 text-cyan-400" />
            <span className="text-xs text-cyan-300 font-medium">What you can analyze</span>
          </div>
          <h2 className="text-3xl md:text-4xl font-bold mb-3">Every flavour of energy contract</h2>
          <p className="text-slate-400 max-w-2xl mx-auto">
            ContractIQ is purpose-built for the energy industry. It doesn't just parse words — it
            understands the commercial structures specific to each contract type.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {SUPPORTED_CONTRACTS.map((c, idx) => (
            <motion.div
              key={c.type}
              initial={{ opacity: 0, y: 15 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: idx * 0.05 }}
              className="group relative rounded-2xl border border-slate-800/50 bg-slate-900/30 backdrop-blur-sm p-6 hover:border-slate-600/50 transition-all overflow-hidden"
            >
              <div className={`absolute inset-0 bg-gradient-to-br ${c.gradient} opacity-0 group-hover:opacity-10 transition-opacity`} />
              <div className="relative">
                <div className={`w-12 h-12 rounded-xl bg-gradient-to-br ${c.gradient} bg-opacity-20 flex items-center justify-center mb-4`}>
                  <c.icon className="w-6 h-6 text-white" />
                </div>
                <h3 className="text-lg font-bold mb-2">{c.type}</h3>
                <p className="text-xs text-slate-400 leading-relaxed mb-4">{c.description}</p>
                <div className="flex flex-wrap gap-1.5">
                  {c.subtypes.map(st => (
                    <span key={st} className="px-2 py-0.5 rounded text-[10px] bg-slate-800/60 border border-slate-700/50 text-slate-300">{st}</span>
                  ))}
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      </section>

      {/* Features grid */}
      <section id="features" className="relative z-10 max-w-7xl mx-auto px-6 py-16 border-t border-slate-800/50">
        <div className="text-center mb-12">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/30 mb-4">
            <Sparkles className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-xs text-emerald-300 font-medium">9 Agentic Workflows</span>
          </div>
          <h2 className="text-3xl md:text-4xl font-bold mb-3">Not just extraction. Real work.</h2>
          <p className="text-slate-400 max-w-2xl mx-auto">
            Each workflow is a complete Abenix pipeline. They use only generic platform tools —
            database_query, financial_calculator, entso_e, ember_climate, ecb_rates, tavily_search —
            with domain knowledge encoded in the prompts, not the tools.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {FEATURES.map((f, idx) => (
            <motion.div
              key={f.title}
              initial={{ opacity: 0, y: 15 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: idx * 0.04 }}
              className="rounded-2xl border border-slate-800/50 bg-slate-900/30 backdrop-blur-sm p-5 hover:border-slate-600/50 transition-all"
            >
              <div className={`w-10 h-10 rounded-xl ${f.bg} border border-slate-700/50 flex items-center justify-center mb-3`}>
                <f.icon className={`w-5 h-5 ${f.color}`} />
              </div>
              <h3 className="font-bold mb-1">{f.title}</h3>
              <p className={`text-[11px] italic mb-2 ${f.color}`}>{f.tagline}</p>
              <p className="text-xs text-slate-400 leading-relaxed">{f.desc}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section className="relative z-10 max-w-7xl mx-auto px-6 py-16 border-t border-slate-800/50">
        <div className="text-center mb-12">
          <h2 className="text-3xl md:text-4xl font-bold mb-3">From upload to insight in 4 steps</h2>
          <p className="text-slate-400">Zero prompting required. ContractIQ does the work.</p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-5">
          {[
            { step: '01', icon: FileText, title: 'Drop the PDF', desc: 'Drag your 100-200 page PPA, gas agreement, or tolling contract. Multi-pass extraction starts automatically.' },
            { step: '02', icon: Brain, title: 'AI extraction', desc: 'Claude Sonnet 4.5 extracts commercial terms, technical specs, clauses, assets, events. Builds Neo4j graph.' },
            { step: '03', icon: Gauge, title: 'Risk scoring', desc: 'Multi-category risk model: market, credit, operational, regulatory, legal, technology. Live market data overlay.' },
            { step: '04', icon: MessageSquare, title: 'Chat + Insights', desc: 'Ask questions across your portfolio. Run 9 agentic workflows. Generate briefings, hedge recommendations, renewal packets.' },
          ].map((s, i) => (
            <motion.div key={s.step} initial={{ opacity: 0, y: 15 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ delay: i * 0.08 }}
              className="relative rounded-2xl border border-slate-800/50 bg-slate-900/30 p-5">
              <div className="absolute -top-3 left-5 px-2 py-0.5 rounded-full bg-emerald-500/20 border border-emerald-500/40 text-[10px] font-mono text-emerald-300">{s.step}</div>
              <s.icon className="w-8 h-8 text-emerald-400 mb-3 mt-2" />
              <h3 className="font-bold mb-1.5">{s.title}</h3>
              <p className="text-xs text-slate-400 leading-relaxed">{s.desc}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* Stack */}
      <section id="stack" className="relative z-10 max-w-7xl mx-auto px-6 py-16 border-t border-slate-800/50">
        <div className="text-center mb-12">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-purple-500/10 border border-purple-500/30 mb-4">
            <Cpu className="w-3.5 h-3.5 text-purple-400" />
            <span className="text-xs text-purple-300 font-medium">Technical Stack</span>
          </div>
          <h2 className="text-3xl md:text-4xl font-bold mb-3">Built on Abenix</h2>
          <p className="text-slate-400 max-w-2xl mx-auto">
            ContractIQ uses a single Abenix platform API key with <code className="text-emerald-300 text-sm">can_delegate</code> scope
            and the <code className="text-emerald-300 text-sm">actAs</code> pattern — every end-user call is scoped to their own data
            via strict row-level RBAC. One key, many users, zero leakage.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {STACK.map((s, i) => (
            <motion.div key={s.label} initial={{ opacity: 0, y: 10 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ delay: i * 0.04 }}
              className="rounded-xl border border-slate-800/50 bg-slate-900/20 p-5 flex items-start gap-3">
              <div className="w-9 h-9 rounded-lg bg-slate-800/60 border border-slate-700/50 flex items-center justify-center shrink-0">
                <s.icon className="w-4 h-4 text-cyan-400" />
              </div>
              <div>
                <h4 className="text-sm font-semibold text-white mb-0.5">{s.label}</h4>
                <p className="text-[11px] text-slate-400 leading-relaxed">{s.desc}</p>
              </div>
            </motion.div>
          ))}
        </div>
      </section>

      {/* Final CTA */}
      <section className="relative z-10 max-w-5xl mx-auto px-6 py-20 border-t border-slate-800/50">
        <motion.div initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}
          className="rounded-3xl border border-emerald-500/30 bg-gradient-to-br from-emerald-500/10 via-cyan-500/5 to-purple-500/10 p-12 text-center">
          <Lightbulb className="w-10 h-10 text-emerald-400 mx-auto mb-4" />
          <h2 className="text-3xl md:text-4xl font-bold mb-3">Stop reading contracts. Start using them.</h2>
          <p className="text-slate-300 max-w-2xl mx-auto mb-8">
            Your portfolio has hundreds of pages of value buried in PDFs nobody opens. ContractIQ turns them
            into a queryable, actionable, always-fresh intelligence layer.
          </p>
          <button onClick={() => setShowAuth(true)}
            className="px-8 py-3.5 rounded-xl bg-gradient-to-r from-emerald-500 to-cyan-600 text-white text-sm font-semibold hover:shadow-2xl hover:shadow-emerald-500/30 transition-all inline-flex items-center gap-2">
            Start Analyzing Now <ArrowRight className="w-4 h-4" />
          </button>
          <p className="text-[11px] text-slate-500 mt-6">
            Demo credentials: <code className="text-emerald-300">test@contractiq.com</code> / <code className="text-emerald-300">TestPass123!</code>
          </p>
        </motion.div>
      </section>

      {/* Footer */}
      <footer className="relative z-10 border-t border-slate-800/50 py-8 text-center">
        <div className="max-w-7xl mx-auto px-6">
          <p className="text-xs text-slate-500">
            ContractIQ · PPA &amp; Gas Contract Intelligence ·
            <span className="mx-2">Built on <a href="http://localhost:3000" target="_blank" rel="noopener noreferrer" className="text-emerald-400 hover:text-emerald-300">Abenix</a></span>
          </p>
        </div>
      </footer>

      {/* Auth modal overlay */}
      {showAuth && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}
          className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-4"
          onClick={(e) => { if (e.target === e.currentTarget) setShowAuth(false); }}
        >
          <motion.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ duration: 0.2 }}
            className="w-full max-w-md"
          >
            <div className="bg-slate-900/95 border border-slate-700/50 rounded-2xl p-8 shadow-2xl">
              <div className="flex items-center justify-center gap-3 mb-6">
                <div className="w-12 h-12 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center">
                  <img src="/contractiq-logo.svg" alt="ContractIQ" className="w-8 h-8" />
                </div>
                <div>
                  <h1 className="text-xl font-bold text-white">ContractIQ</h1>
                  <p className="text-xs text-slate-500">PPA & Gas Contract Intelligence</p>
                </div>
              </div>

              <div className="flex border-b border-slate-700/50 mb-6">
                {(['login', 'register'] as Tab[]).map(t => (
                  <button key={t} onClick={() => { setTab(t); setError(''); }}
                    className={`flex-1 pb-3 text-sm font-medium transition-colors ${tab === t ? 'text-emerald-400 border-b-2 border-emerald-400' : 'text-slate-500 hover:text-slate-300'}`}>
                    {t === 'login' ? 'Sign In' : 'Register'}
                  </button>
                ))}
              </div>

              <form onSubmit={handleSubmit} className="space-y-4">
                {tab === 'register' && (
                  <>
                    <div className="relative">
                      <Building2 className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                      <input type="text" value={form.full_name} onChange={e => updateField('full_name', e.target.value)}
                        placeholder="Full name" required
                        className="w-full bg-slate-800/50 border border-slate-700 rounded-lg pl-10 pr-4 py-3 text-white text-sm placeholder-slate-500 focus:border-emerald-500 focus:outline-none transition-colors" />
                    </div>
                    <div className="relative">
                      <Building2 className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                      <input type="text" value={form.organization} onChange={e => updateField('organization', e.target.value)}
                        placeholder="Organization (optional)"
                        className="w-full bg-slate-800/50 border border-slate-700 rounded-lg pl-10 pr-4 py-3 text-white text-sm placeholder-slate-500 focus:border-emerald-500 focus:outline-none transition-colors" />
                    </div>
                  </>
                )}
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                  <input type="email" value={form.email} onChange={e => updateField('email', e.target.value)}
                    placeholder="Email address" required
                    className="w-full bg-slate-800/50 border border-slate-700 rounded-lg pl-10 pr-4 py-3 text-white text-sm placeholder-slate-500 focus:border-emerald-500 focus:outline-none transition-colors" />
                </div>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                  <input type={showPassword ? 'text' : 'password'} value={form.password} onChange={e => updateField('password', e.target.value)}
                    placeholder="Password" required
                    className="w-full bg-slate-800/50 border border-slate-700 rounded-lg pl-10 pr-10 py-3 text-white text-sm placeholder-slate-500 focus:border-emerald-500 focus:outline-none transition-colors" />
                  <button type="button" onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300">
                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>

                {error && <p className="text-red-400 text-xs text-center">{error}</p>}

                <button type="submit" disabled={loading}
                  className="w-full bg-gradient-to-r from-emerald-500 to-cyan-600 text-white font-semibold py-3 rounded-lg text-sm hover:shadow-lg hover:shadow-emerald-500/25 transition-all flex items-center justify-center gap-2 disabled:opacity-50">
                  {loading ? 'Loading...' : <>{tab === 'login' ? 'Sign In' : 'Create Account'} <ArrowRight className="w-4 h-4" /></>}
                </button>
              </form>

              {tab === 'login' && (
                <div className="mt-4 pt-4 border-t border-slate-800/50 text-center">
                  <button onClick={fillDemo} className="text-[11px] text-slate-500 hover:text-emerald-400 transition-colors">
                    Use demo credentials →
                  </button>
                </div>
              )}

              <button onClick={() => setShowAuth(false)} className="mt-4 w-full text-[11px] text-slate-600 hover:text-slate-400 text-center">
                Close
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </div>
  );
}

// Missing icon import — inline SVG stand-in
function Cpu(props: any) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" {...props}>
      <rect x="4" y="4" width="16" height="16" rx="2"/>
      <rect x="9" y="9" width="6" height="6"/>
      <path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/>
    </svg>
  );
}
