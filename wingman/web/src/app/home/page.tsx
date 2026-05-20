'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import {
  Activity, Crosshair, LineChart, Ship, Beaker, Network, ShieldCheck,
  Inbox, ArrowRight, Sparkles, Wrench, Cpu, Database, Wifi, Workflow,
  TrendingUp, Anchor, Gauge, BookOpen, BarChart3, MapPin,
  type LucideIcon,
} from 'lucide-react';

// Empty string so all fetches go to relative /api/wingman/* and hit the
// Next.js rewrite which proxies to wingman-api. The previous fallback
// pointed at abenix-api:8000 which 404s on wingman endpoints.
const API = process.env.NEXT_PUBLIC_API_URL ?? '';

const HERO_NAV = [
  { href: '/desk',       label: 'Wingman Copilot',     icon: Sparkles,     primary: true,  blurb: 'Ask the desk anything' },
  { href: '/workbench',  label: 'Arbitrage Workbench', icon: Activity,     blurb: 'Live corridor scans' },
  { href: '/mispricing', label: 'Price at Risk Lens',  icon: Crosshair,    blurb: 'Bayesian fair-value + HITL' },
  { href: '/lab',        label: 'Market & Freight Lab', icon: Anchor,      blurb: 'Vessel · freight · options' },
  { href: '/scenarios',  label: 'Forward Scenarios',   icon: LineChart,    blurb: 'Probability fan chart' },
  { href: '/inbox',      label: 'Broker Inbox',        icon: Inbox,        blurb: 'Live broker emails, parsed' },
  { href: '/ops',        label: 'Operations Watch',    icon: Ship,         blurb: 'AIS-tracked vessels' },
  { href: '/strategy',   label: 'Strategy Lab',        icon: Beaker,       blurb: 'NL → backtest → VaR' },
  { href: '/graph',      label: 'Knowledge Graph',     icon: Network,      blurb: 'Atlas, queryable' },
  { href: '/approvals',  label: 'Approvals',           icon: ShieldCheck,  blurb: 'HITL gate' },
];

const PRODUCT_PILLARS = [
  {
    href: '/workbench',
    title: 'Arbitrage Workbench',
    blurb: 'Live corridor cards — open, stretched, closed. Click any to fire a multi-agent analyse with citations.',
    icon: Activity,
    accent: 'from-emerald-400 to-cyan-400',
  },
  {
    href: '/mispricing',
    title: 'Price at Risk Lens',
    blurb: 'Bayesian fair-value model (15 features incl. options skew + Baltic freight + density-corrected Worldscale) with sigma-banded verdict and HITL trade card.',
    icon: Crosshair,
    accent: 'from-fuchsia-400 to-pink-400',
  },
  {
    href: '/lab',
    title: 'Market & Freight Lab',
    blurb: 'NEW — interactive surface for vessel specs, density, Baltic BLPG, Worldscale, port constraints, refined-product forwards and options market data.',
    icon: Anchor,
    accent: 'from-amber-400 to-rose-400',
  },
  {
    href: '/scenarios',
    title: 'Forward Scenarios',
    blurb: 'GaussianNB prior + LLM posterior — drag the seasonality + supply-shock sliders and watch the fan chart re-shape.',
    icon: LineChart,
    accent: 'from-amber-300 to-orange-400',
  },
  {
    href: '/inbox',
    title: 'Broker Inbox',
    blurb: 'Email-stream of broker indications, auto-classified by a fine-tuned LLM. One-click attach to a corridor.',
    icon: Inbox,
    accent: 'from-sky-400 to-indigo-400',
  },
  {
    href: '/ops',
    title: 'Operations Watch',
    blurb: 'AIS-stream of live LPG / CPP tankers, terminal status, port-constraint warnings on the corridor cargo.',
    icon: Ship,
    accent: 'from-cyan-400 to-teal-400',
  },
  {
    href: '/strategy',
    title: 'Strategy Lab',
    blurb: 'Monte Carlo VaR simulator (Go code-asset) over the portfolio. P&L distribution + scenario re-runs.',
    icon: Beaker,
    accent: 'from-violet-400 to-fuchsia-400',
  },
  {
    href: '/graph',
    title: 'Knowledge Graph',
    blurb: 'Atlas — every counterparty, vessel, port, contract, agent run linked. Click any node to see history.',
    icon: Network,
    accent: 'from-emerald-300 to-teal-400',
  },
  {
    href: '/approvals',
    title: 'HITL Approvals',
    blurb: 'Trades flagged by the agents queue here. Human-in-the-loop gate before any large position goes live.',
    icon: ShieldCheck,
    accent: 'from-rose-400 to-amber-400',
  },
];

const TOOL_GROUPS = [
  {
    label: 'Market & price data',
    items: [
      { id: 'eia_open_data',             desc: 'EIA: Mont Belvieu propane, WTI/Brent, HH natgas, refined products' },
      { id: 'yahoo_finance',             desc: 'ICE futures: front-month + history' },
      { id: 'refined_products_forwards', desc: 'NYMEX/ICE futures + 3-2-1 crack spreads' },
      { id: 'options_data',              desc: 'IV, 25-delta skew, put/call OI, regime label' },
    ],
  },
  {
    label: 'Freight',
    items: [
      { id: 'freight_baltic_blpg',  desc: 'Baltic BLPG1 / BLPG2 / BLPG3 for LPG ($/MT)' },
      { id: 'freight_worldscale',   desc: 'Worldscale TC1/TC2/TC5/TC6/TC14/TC17 (CPP)' },
      { id: 'vessel_specs',         desc: 'VLGC/MGC/VLCC/LR2/MR2 + density + m^3<->MT conv' },
      { id: 'bunker_fuel',          desc: 'VLSFO at major ports + corridor estimate' },
    ],
  },
  {
    label: 'Ports & vessels',
    items: [
      { id: 'port_constraints',  desc: '~25 UN/LOCODE ports + draught/LOA/beam/air-draught checks' },
      { id: 'ais_stream',        desc: 'Live AIS feed (filter by ship-type 80 / 84)' },
      { id: 'open_meteo',        desc: 'Marine + atmosphere forecasts on the corridor hubs' },
    ],
  },
  {
    label: 'Narrative & ops',
    items: [
      { id: 'tavily_search',         desc: 'Real-time news search (supply/demand/geo)' },
      { id: 'news_feed',             desc: 'NewsAPI/MediaStack feed' },
      { id: 'financial_calculator',  desc: 'NPV / IRR / spread arithmetic' },
      { id: 'ml_model',              desc: 'Call any deployed model (BayesianRidge / IsoForest)' },
    ],
  },
];

const ML_MODELS = [
  {
    name: 'wingman-mispricing-fairvalue',
    family: 'Bayesian Ridge regression — fair-value spread',
    purpose: '15 features: 8 base market signals + 4 options-market signals (IV / skew / OI) + 3 freight-quality signals (Baltic + Worldscale + density-corrected vessel size).',
    metric: 'R² 0.665 · RMSE 7.49 $/MT · posterior std ~8.5',
    lift: 'Posterior std bands the credible interval; sigma-residual triggers the verdict',
  },
  {
    name: 'wingman-mispricing-anomaly',
    family: 'Isolation Forest — regime-break detector',
    purpose: '9 features (the 8 base plus spread_4w_mean_z). Flags out-of-distribution corridor states the regression can\'t adapt to fast enough.',
    metric: 'Decision threshold tuned to ~5% false-positive on calm regime',
    lift: 'Hard gate — no trade card is drafted while an anomaly is firing',
  },
  {
    name: 'wingman-scenario-prior',
    family: 'Gaussian Naive Bayes — forward-spread prior',
    purpose: 'Class probabilities over P50 / P10 / P90 forward spread given today\'s regime + season.',
    metric: 'Holdout accuracy 90.8% on five-regime classification',
    lift: 'The LLM posterior layers narrative on top — together they produce the fan chart on Forward Scenarios',
  },
  {
    name: 'wingman-broker-intent-classifier',
    family: 'TF-IDF + Logistic Regression — email classifier',
    purpose: 'Buckets every inbound broker email into indication / firm-offer / market-chatter / fixture-confirmed.',
    metric: 'Macro F1 0.91 on the held-out broker-email set',
    lift: 'Auto-routes broker traffic into the right Inbox bucket so the trader sees firms first',
  },
];

const AGENT_PIPELINE = [
  { label: 'Price at Risk Extractor', kind: 'agent', icon: 'sparkles' },
  { label: 'EIA spot',             kind: 'tool',  icon: 'db' },
  { label: 'ICE forwards',         kind: 'tool',  icon: 'db' },
  { label: 'Baltic BLPG',          kind: 'tool',  icon: 'anchor' },
  { label: 'Worldscale',           kind: 'tool',  icon: 'anchor' },
  { label: 'Vessel specs',         kind: 'tool',  icon: 'gauge' },
  { label: 'Options data',         kind: 'tool',  icon: 'trend' },
  { label: 'Open-Meteo',           kind: 'tool',  icon: 'tool' },
  { label: 'Tavily news',          kind: 'tool',  icon: 'tool' },
  { label: 'BR fair-value',        kind: 'model', icon: 'cpu' },
  { label: 'IsoForest anomaly',    kind: 'model', icon: 'cpu' },
  { label: 'Trade card',           kind: 'agent', icon: 'shield' },
  { label: 'HITL approval',        kind: 'human', icon: 'shield' },
];

interface BriefIndicator { label: string; unit: string; latest: number | null; wow_change_pct: number | null; }

export default function HomePage() {
  const [brief, setBrief] = useState<BriefIndicator[]>([]);
  const [now, setNow] = useState<string>('—');

  useEffect(() => {
    const tick = () => setNow(new Date().toUTCString().replace(' GMT', ' UTC'));
    tick();
    const i = setInterval(tick, 1000);
    return () => clearInterval(i);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${API}/api/wingman/market-brief`, { cache: 'no-store' });
        if (!r.ok) return;
        const j = await r.json();
        const inds: BriefIndicator[] = j.indicators || j.data?.indicators || [];
        if (!cancelled) setBrief(inds.slice(0, 6));
      } catch {
        /* ignore — brief is optional on the home page */
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="px-8 py-8 max-w-7xl mx-auto">
      {/* ── HERO ───────────────────────────────────────────────────────── */}
      <motion.section
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        className="relative overflow-hidden rounded-3xl border border-emerald-500/30 bg-gradient-to-br from-slate-900 via-slate-900 to-emerald-950/40 px-10 py-14"
      >
        <div className="absolute -top-32 -right-32 w-96 h-96 rounded-full bg-emerald-500/10 blur-3xl pointer-events-none" />
        <div className="absolute -bottom-32 -left-32 w-96 h-96 rounded-full bg-cyan-500/10 blur-3xl pointer-events-none" />

        <div className="relative">
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2.5">
            {HERO_NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                data-testid={`home-cta-${n.href.replace('/', '')}`}
                className={`group inline-flex flex-col gap-0.5 px-3 py-2.5 rounded-xl text-sm transition-colors ${
                  n.primary
                    ? 'bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold border border-emerald-500'
                    : 'border border-emerald-500/30 bg-slate-950/40 text-emerald-100 hover:bg-emerald-500/10 hover:border-emerald-500/60 font-medium'
                }`}
              >
                <span className="flex items-center gap-2">
                  <n.icon className="w-3.5 h-3.5" />
                  {n.label}
                </span>
                <span className={`text-[10px] font-normal leading-tight ${n.primary ? 'text-slate-900/70' : 'text-slate-500'}`}>
                  {n.blurb}
                </span>
              </Link>
            ))}
          </div>

          {/* Live tickers (best-effort) */}
          {brief.length > 0 && (
            <div className="mt-8 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
              {brief.map((b, i) => {
                const delta = b.wow_change_pct ?? 0;
                const tone = delta >= 0 ? 'text-emerald-300' : 'text-rose-300';
                return (
                  <div key={i} className="rounded-xl bg-slate-950/60 border border-slate-800 px-3 py-2.5">
                    <div className="text-[10px] uppercase tracking-wider text-slate-500">{b.label}</div>
                    <div className="text-sm font-mono text-white mt-0.5">
                      {b.latest == null ? '—' : `${Number(b.latest).toFixed(2)} ${b.unit}`}
                    </div>
                    <div className={`text-[10px] mt-0.5 ${tone}`}>
                      {b.wow_change_pct == null ? '·' : `${delta >= 0 ? '+' : ''}${delta.toFixed(2)}% WoW`}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </motion.section>

      {/* ── TODAY'S SIGNALS — every active corridor at a glance ───────── */}
      <TodaysSignals />

      {/* ── EVERY MARKET, EVERY FREIGHT, EVERY PORT ───────────────────── */}
      <section className="mt-12">
        <SectionHeader
          eyebrow="Every market signal a desk reads"
          title="From the tank at Mont Belvieu to the berth at Chiba."
          subtitle="Spot, forwards, options, Baltic + Worldscale freight, vessel specs, port constraints, weather, news — all live, all interrogable, all consumed by the Price at Risk model on every scan. Open the Lab to drive each one yourself."
        />
        <div className="mt-6 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          <NewToolCard
            icon={<Ship className="w-4 h-4 text-cyan-300" />}
            href="/lab"
            tool="vessel_specs"
            title="Vessel-class registry + density table"
            blurb="12 vessel classes, 14 product densities, m³↔MT and $/MT↔$/bbl converters. Single source of truth for freight math."
            value="VLGC 84 000 m³ → 42 672 MT propane"
          />
          <NewToolCard
            icon={<Anchor className="w-4 h-4 text-cyan-300" />}
            href="/lab"
            tool="freight_baltic_blpg"
            title="Baltic BLPG indices"
            blurb="BLPG1 / BLPG2 / BLPG3 LPG freight in $/MT propane VLGC. Live override via BALTIC_API_KEY."
            value="BLPG2 mid $49.20/MT (USGC→NWE)"
          />
          <NewToolCard
            icon={<Anchor className="w-4 h-4 text-amber-300" />}
            href="/lab"
            tool="freight_worldscale"
            title="Worldscale freight (CPP)"
            blurb="Worldscale TC1/2/5/6/7/14/17 with the 2025 flat-rate schedule. ws_points/100 × flat → $/MT."
            value="TC2 @ WS180 = $33.57/MT freight"
          />
          <NewToolCard
            icon={<MapPin className="w-4 h-4 text-rose-300" />}
            href="/lab"
            tool="port_constraints"
            title="Port × vessel compatibility"
            blurb="~25 UN/LOCODE ports + Suez/Panama transits. Draught, LOA, beam, air-draught, product flags."
            value="VLGC→Panama: transit_only (beam 49 m)"
          />
          <NewToolCard
            icon={<TrendingUp className="w-4 h-4 text-violet-300" />}
            href="/lab"
            tool="refined_products_forwards"
            title="Refined-product futures + cracks"
            blurb="NYMEX/ICE continuous front-month (RB / HO / CL / BZ / NG / PG) + 3-2-1 Gulf Coast crack."
            value="WTI $800/MT · RBOB $1,186/MT · 3-2-1 crack $48/bbl"
          />
          <NewToolCard
            icon={<TrendingUp className="w-4 h-4 text-fuchsia-300" />}
            href="/mispricing"
            tool="options_data"
            title="Options market signals"
            blurb="Brent + HH implied vol, 25-delta risk reversal (skew), put/call OI, regime label. Powers 4 of the 15 Price at Risk features."
            value="CL=F: IV 34.5% · RR +0.06 → skewed_up"
          />
        </div>
        <div className="mt-5 flex items-center gap-3 flex-wrap">
          <Link href="/lab" className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold text-[12px] transition-colors">
            Open the Market &amp; Freight Lab
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>
          <Link href="/mispricing" className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-emerald-500/40 text-emerald-200 hover:bg-emerald-500/10 font-semibold text-[12px] transition-colors">
            See them feeding the Price at Risk Lens
            <Crosshair className="w-3.5 h-3.5" />
          </Link>
        </div>
      </section>

      {/* ── BUSINESS VALUE STRIP ──────────────────────────────────────── */}
      <section className="mt-10 grid grid-cols-1 md:grid-cols-3 gap-4">
        <ValueCard
          icon={<TrendingUp className="w-5 h-5 text-emerald-300" />}
          title="Find the arb in 30 seconds, not 30 minutes"
          body="Open a corridor card and an autonomous agent pipeline gathers EIA, ICE, Baltic, options, weather and news in parallel. You read a single sigma-banded verdict instead of pasting numbers into a spreadsheet."
        />
        <ValueCard
          icon={<ShieldCheck className="w-5 h-5 text-cyan-300" />}
          title="Trade ideas every desk policy can defend"
          body="Every recommended trade carries a citable feature vector, the model and inputs that produced it, a posterior std-banded credible interval, and a HITL gate. Compliance sees the same evidence the trader does."
          />
        <ValueCard
          icon={<Workflow className="w-5 h-5 text-fuchsia-300" />}
          title="Composable, not closed"
          body="The same vessel-specs, freight, options and refined-products tools are first-class platform primitives. Spin up a new agent or pipeline in Abenix and it sees the whole toolbox out of the box."
        />
      </section>

      {/* ── 8 PILLARS ─────────────────────────────────────────────────── */}
      <section className="mt-12">
        <SectionHeader
          eyebrow="The product, eight pages"
          title="Everything a propane / CPP desk needs in one workspace"
          subtitle="From the live arb scan to the HITL approval — designed so a single trader can run the desk end-to-end."
        />
        <div className="mt-6 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {PRODUCT_PILLARS.map((p) => (
            <Link
              key={p.href}
              href={p.href}
              className="group rounded-2xl border border-slate-800 bg-slate-900/40 hover:bg-slate-900/70 hover:border-emerald-500/40 px-5 py-5 transition-all"
            >
              <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${p.accent} flex items-center justify-center mb-3`}>
                <p.icon className="w-5 h-5 text-slate-950" />
              </div>
              <div className="text-sm font-semibold text-white">{p.title}</div>
              <div className="text-[12px] text-slate-400 mt-1.5 leading-relaxed">{p.blurb}</div>
              <div className="text-[11px] text-emerald-300 mt-3 inline-flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                Open <ArrowRight className="w-3 h-3" />
              </div>
            </Link>
          ))}
        </div>
      </section>

      {/* ── HOW IT WORKS — TECH ───────────────────────────────────────── */}
      <section className="mt-16">
        <SectionHeader
          eyebrow="Under the hood"
          title="How a corridor scan actually executes"
          subtitle="Every page on Wingman is a thin client over the same agentic engine. The pipeline below is what runs when you click Analyze on Arb Workbench or Re-score on Price at Risk Lens — every step is a real tool or model call."
        />
        <div className="mt-6 rounded-2xl border border-slate-800 bg-slate-950/60 p-6">
          <div className="flex flex-wrap items-center gap-2">
            {AGENT_PIPELINE.map((step, idx) => (
              <div key={idx} className="flex items-center gap-2">
                <PipelineNode label={step.label} kind={step.kind} icon={step.icon} />
                {idx < AGENT_PIPELINE.length - 1 && (
                  <ArrowRight className="w-3 h-3 text-slate-600" />
                )}
              </div>
            ))}
          </div>
          <p className="text-[12px] text-slate-400 mt-5 leading-relaxed max-w-3xl">
            The orchestration is just a YAML agent — <span className="font-mono text-slate-300">wingman-mispricing-extractor</span> — that lists the 13 tools above. The runtime calls them in parallel where it can, builds a 15-feature vector, evaluates two ML models, asks an LLM to draft the hypothesis citing live Tavily headlines, and emits a structured JSON the page reads. Add a new tool to the YAML and it shows up here instantly.
          </p>
        </div>
      </section>

      {/* ── ML MODEL CARDS ────────────────────────────────────────────── */}
      <section className="mt-16">
        <SectionHeader
          eyebrow="ML models"
          title="Four deployed models, every one is auditable"
          subtitle="No black boxes. Every model carries its feature-list, holdout metric, and an honest ablation against the simpler baseline. Re-train any model from build_*.py — the wingman/ml-models folder ships with the platform."
        />
        <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-4">
          {ML_MODELS.map((m) => (
            <div key={m.name} className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5">
              <div className="flex items-center gap-2 mb-1">
                <Cpu className="w-4 h-4 text-fuchsia-300" />
                <span className="font-mono text-fuchsia-200 text-sm">{m.name}</span>
              </div>
              <div className="text-[11px] uppercase tracking-wider text-slate-500 mt-1">{m.family}</div>
              <div className="text-[12px] text-slate-300 mt-2 leading-relaxed">{m.purpose}</div>
              <div className="text-[11px] text-emerald-300 mt-3 font-mono">{m.metric}</div>
              <div className="text-[11px] text-slate-400 mt-1 leading-relaxed">{m.lift}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ── TOOLBOX ──────────────────────────────────────────────────── */}
      <section className="mt-16">
        <SectionHeader
          eyebrow="Composable toolbox"
          title="Every signal a propane / CPP desk reads, exposed as a tool"
          subtitle="The trader checklist — market data, freight curves, ports, vessel specs, density math — every one is a platform tool. Any agent or pipeline in Abenix can use them. No upload, no rebuild, no hand-rolled SDK."
        />
        <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-4">
          {TOOL_GROUPS.map((g) => (
            <div key={g.label} className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5">
              <div className="flex items-center gap-2 mb-3">
                <Wrench className="w-4 h-4 text-amber-300" />
                <span className="text-sm font-semibold text-white">{g.label}</span>
              </div>
              <ul className="space-y-1.5">
                {g.items.map((it) => (
                  <li key={it.id} className="flex items-baseline gap-2 text-[12px] leading-snug">
                    <span className="font-mono text-emerald-300">{it.id}</span>
                    <span className="text-slate-400">— {it.desc}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      {/* ── BRING YOUR OWN CODE ──────────────────────────────────────── */}
      <section className="mt-16">
        <SectionHeader
          eyebrow="Bring your own code"
          title="Drop in a model the desk already trusts"
          subtitle="Tools are for shared primitives. For desk-proprietary risk models, pricing libs, custom analytics — upload a repo or zip via Abenix and it becomes a code-asset usable from any agent or pipeline. Wingman's Strategy Lab already runs a Go-based VaR simulator this way."
        />
        <div className="mt-6 grid grid-cols-1 md:grid-cols-3 gap-4">
          <CodeAssetSlot
            title="Python / sklearn"
            blurb="Pickle file + pyproject.toml. Runtime loads, runs in-pod under the same model-serving pattern as wingman-mispricing-*."
          />
          <CodeAssetSlot
            title="Go / Rust"
            blurb="Static binary or compile-on-upload. Runs in a sandbox for hard-real-time math (Strategy Lab VaR is a Go binary)."
          />
          <CodeAssetSlot
            title="Node / Java"
            blurb="Repo with a single entrypoint. Same code-asset interface — input JSON via stdin, structured JSON on stdout."
          />
        </div>
      </section>

      {/* ── ARCHITECTURE MATRIX — page-by-page tools/features/models map */}
      <ArchitectureMatrix />

      {/* ── FOOTER LINE ──────────────────────────────────────────────── */}
      <section className="mt-16 mb-8 rounded-2xl border border-emerald-500/20 bg-emerald-500/5 p-6">
        <div className="flex items-center justify-between flex-wrap gap-4">
          <div className="flex items-center gap-3">
            <BookOpen className="w-5 h-5 text-emerald-300" />
            <div>
              <div className="text-sm font-semibold text-white">Every page carries a "Show explainer" panel.</div>
              <div className="text-[12px] text-slate-300">Open it on any screen and Wingman tells you which agents, tools, models, inputs and outputs that page uses. Built for the desk, not the data scientist.</div>
            </div>
          </div>
          <Link
            href="/workbench"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold text-sm transition-colors"
          >
            Start scanning corridors
            <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
      </section>
    </div>
  );
}

function SectionHeader({ eyebrow, title, subtitle }: { eyebrow: string; title: string; subtitle: string }) {
  return (
    <div className="max-w-3xl">
      <div className="text-[11px] uppercase tracking-[0.25em] text-emerald-300 mb-2">{eyebrow}</div>
      <h2 className="text-2xl lg:text-3xl font-bold tracking-tight text-white">{title}</h2>
      <p className="text-[13px] text-slate-400 mt-2 leading-relaxed">{subtitle}</p>
    </div>
  );
}

function ValueCard({ icon, title, body }: { icon: React.ReactNode; title: string; body: string }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5">
      <div className="flex items-center gap-2 mb-2">
        {icon}
        <span className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">Why traders use it</span>
      </div>
      <div className="text-sm font-semibold text-white">{title}</div>
      <div className="text-[12px] text-slate-300 mt-2 leading-relaxed">{body}</div>
    </div>
  );
}

function PipelineNode({ label, kind, icon }: { label: string; kind: string; icon: string }) {
  const Icon = ICON_MAP[icon] || Wrench;
  const tone = TONE_MAP[kind] || 'border-slate-700 text-slate-300 bg-slate-900/50';
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border ${tone} text-[11px] font-mono`}>
      <Icon className="w-3 h-3" />
      {label}
    </span>
  );
}

const ICON_MAP: Record<string, LucideIcon> = {
  sparkles: Sparkles, db: Database, tool: Wrench, cpu: Cpu, anchor: Anchor,
  gauge: Gauge, trend: TrendingUp, shield: ShieldCheck, wifi: Wifi, chart: BarChart3,
};

const TONE_MAP: Record<string, string> = {
  agent: 'border-emerald-500/40 text-emerald-200 bg-emerald-500/10',
  tool:  'border-amber-500/30 text-amber-200 bg-amber-500/5',
  model: 'border-fuchsia-500/30 text-fuchsia-200 bg-fuchsia-500/5',
  human: 'border-rose-500/30 text-rose-200 bg-rose-500/5',
};

function CodeAssetSlot({ title, blurb }: { title: string; blurb: string }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5">
      <div className="flex items-center gap-2 mb-2">
        <Wrench className="w-4 h-4 text-violet-300" />
        <span className="text-sm font-semibold text-white">{title}</span>
      </div>
      <div className="text-[12px] text-slate-300 leading-relaxed">{blurb}</div>
    </div>
  );
}

// ── Today's signals: single roll-up endpoint that returns every active
// corridor's cached verdict, fair-value gap, regime and freshness.
// Cached on the backend (same TTL as the mispricing cache), so the home
// page paints instantly with no agent fire. Polls every 60s.
interface CorridorSignal {
  id: string; label: string; product?: string;
  origin_port?: string; destination_port?: string;
  verdict?: string; direction?: string;
  observed_spread_usd_mt?: number;
  fair_value_spread_usd_mt?: number;
  fair_value_p10_usd_mt?: number;
  fair_value_p90_usd_mt?: number;
  residual_usd_mt?: number;
  residual_sigma?: number;
  market_regime?: string;
  anomaly_flag?: boolean;
  age_seconds?: number;
  fresh?: boolean;
  data_quality?: string;
}

function TodaysSignals() {
  const [rows, setRows] = useState<CorridorSignal[]>([]);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const j = await fetch(`${API}/api/wingman/signals`).then((r) => r.json());
        const sigs: CorridorSignal[] = j?.data?.signals || [];
        if (!cancelled) {
          setRows(sigs);
          setLoaded(true);
        }
      } catch { if (!cancelled) setLoaded(true); }
    };
    load();
    const t = setInterval(load, 60_000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  if (!loaded) return null;
  const haveAny = rows.some((r) => r.observed_spread_usd_mt != null);
  return (
    <section className="mt-8" data-testid="todays-signals">
      <div className="flex items-end justify-between mb-3">
        <div>
          <div className="text-[10px] uppercase tracking-[0.25em] text-emerald-300 font-bold mb-1">Today's signals</div>
          <h2 className="text-lg font-bold text-white">Every active corridor at a glance</h2>
          <p className="text-[11px] text-slate-500 mt-0.5">Cached verdicts from the Price at Risk Lens · refreshes every 60s · click a card to deep-dive</p>
        </div>
        <Link href="/mispricing" className="text-[11px] text-cyan-300 hover:text-cyan-200 flex items-center gap-1">
          Open Price at Risk Lens <ArrowRight className="w-3 h-3" />
        </Link>
      </div>
      {!haveAny ? (
        <div className="rounded-xl border border-dashed border-slate-700 p-6 text-center text-[12px] text-slate-500">
          No corridor scans cached yet — open <Link href="/mispricing" className="text-emerald-300 hover:underline">Price at Risk Lens</Link> and hit Score on any corridor to populate.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          {rows.map((r) => <SignalCard key={r.id} sig={r} />)}
        </div>
      )}
    </section>
  );
}

function SignalCard({ sig }: { sig: CorridorSignal }) {
  const v = (sig.verdict || '').toLowerCase();
  const tone =
    v === 'dislocated' ? 'border-rose-500/40 bg-rose-500/[0.06]' :
    v === 'stretched'  ? 'border-amber-500/40 bg-amber-500/[0.06]' :
    v === 'aligned'    ? 'border-emerald-500/40 bg-emerald-500/[0.06]' :
                         'border-slate-700/60 bg-slate-900/40';
  const verdictTone =
    v === 'dislocated' ? 'text-rose-200 border-rose-500/50 bg-rose-500/15' :
    v === 'stretched'  ? 'text-amber-200 border-amber-500/50 bg-amber-500/15' :
    v === 'aligned'    ? 'text-emerald-200 border-emerald-500/50 bg-emerald-500/15' :
                         'text-slate-400 border-slate-700/50 bg-slate-800/30';
  const dir = (sig.direction || '').toLowerCase();
  const ageMin = sig.age_seconds != null ? Math.round(sig.age_seconds / 60) : null;
  const ageStr =
    ageMin == null ? 'never' :
    ageMin < 1 ? 'just now' :
    ageMin < 60 ? `${ageMin}m ago` :
    `${Math.round(ageMin / 60)}h ago`;
  const regime = (sig.market_regime || '').toLowerCase();
  const sigma = sig.residual_sigma;
  const sigmaTone = sigma == null ? 'text-slate-500' : Math.abs(sigma) >= 2 ? 'text-rose-200' : Math.abs(sigma) >= 1 ? 'text-amber-200' : 'text-emerald-200';
  return (
    <Link
      href={`/mispricing?corridor=${sig.id}`}
      className={`group block rounded-xl border p-4 hover:bg-emerald-500/[0.04] transition-colors ${tone}`}
      data-testid={`signal-${sig.id}`}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="min-w-0">
          <div className="text-[12px] font-semibold text-white truncate">{sig.label}</div>
          <div className="text-[10px] text-slate-500 truncate">{sig.origin_port} → {sig.destination_port}</div>
        </div>
        {sig.verdict ? (
          <span className={`text-[9px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded border ${verdictTone}`}>
            {sig.verdict}
          </span>
        ) : (
          <span className="text-[9px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded border border-slate-700 text-slate-500">no scan</span>
        )}
      </div>
      {sig.observed_spread_usd_mt != null ? (
        <>
          <div className="grid grid-cols-3 gap-2 text-[11px]">
            <div>
              <div className="text-[9px] uppercase text-slate-500">Observed</div>
              <div className="font-mono font-bold text-white">${sig.observed_spread_usd_mt.toFixed(1)}<span className="text-[9px] text-slate-500">/MT</span></div>
            </div>
            <div>
              <div className="text-[9px] uppercase text-slate-500">Fair value</div>
              <div className="font-mono text-slate-300">${(sig.fair_value_spread_usd_mt ?? 0).toFixed(1)}</div>
            </div>
            <div>
              <div className="text-[9px] uppercase text-slate-500">Residual σ</div>
              <div className={`font-mono font-bold ${sigmaTone}`}>
                {sigma != null ? `${sigma >= 0 ? '+' : ''}${sigma.toFixed(2)}σ` : '—'}
              </div>
            </div>
          </div>
          <div className="mt-2.5 flex items-center justify-between text-[10px] font-mono text-slate-500">
            <span className="inline-flex items-center gap-2">
              {dir && <span className={dir === 'rich' ? 'text-rose-300' : 'text-emerald-300'}>{dir}</span>}
              {regime && regime !== 'unknown' && (
                <span className="px-1.5 py-0.5 rounded border border-slate-700/40 bg-slate-900/60">{regime}</span>
              )}
              {sig.anomaly_flag && <span className="px-1.5 py-0.5 rounded border border-rose-500/40 bg-rose-500/10 text-rose-200">anomaly</span>}
            </span>
            <span className={sig.fresh ? 'text-emerald-400' : 'text-amber-300'}>{ageStr}</span>
          </div>
        </>
      ) : (
        <div className="text-[11px] text-slate-500 italic">
          No recent scan — open Price at Risk Lens to score.
        </div>
      )}
    </Link>
  );
}

// ── Architecture matrix: collapsed by default. Maps every page to the
// data sources, feature vectors, ML models, and AI agents it uses, so a
// new trader (or analyst) can audit the whole platform in one place.
const PAGE_ARCH: Array<{
  page: string; href: string; agent: string; tools: string[];
  features?: string[]; models?: string[]; outputs: string[];
}> = [
  {
    page: 'Wingman Copilot', href: '/desk', agent: 'wingman-desk-copilot (Haiku 4.5, meta-agent)',
    tools: ['recall_trajectory', 'invoke_agent (fans out to specialists)'],
    models: ['Haiku 4.5 planner', 'past-trajectory memory'],
    outputs: ['Brief · Plan · Drivers · Confidence · Recommended action'],
  },
  {
    page: 'Arbitrage Workbench', href: '/workbench', agent: 'wingman-arb-analyzer v1.1 (Haiku 4.5)',
    tools: ['eia_open_data', 'yahoo_finance', 'bunker_fuel', 'open_meteo', 'tavily_search', 'options_data', 'vessel_specs', 'freight_baltic_blpg', 'freight_worldscale', 'financial_calculator'],
    models: ['Haiku 4.5 narrative'],
    outputs: ['Net-arb $/MT', 'forward curve', 'cost stack', 'hedge recipe', 'cargo optimizer', 'IV overlay', 'storage carry'],
  },
  {
    page: 'Price at Risk Lens', href: '/mispricing', agent: 'wingman-mispricing-extractor v1.2 (Haiku 4.5)',
    tools: ['eia_open_data', 'yahoo_finance', 'bunker_fuel', 'options_data', 'freight_baltic_blpg', 'freight_worldscale', 'vessel_specs', 'open_meteo', 'tavily_search', 'ml_model'],
    features: [
      'origin_spot_z · dest_spot_z · freight_per_mt_z · inventory_z (4 base)',
      'exports_4w_pct · fx_eur_usd_z · weather_dest_gust_z · season_q (4 base)',
      'crude_iv_atm_z · crude_risk_reversal · nat_gas_iv_atm_z · oil_put_call_ratio (4 options)',
      'freight_baltic_z · freight_ws_per_mt_z · route_vessel_size_norm (3 freight-quality)',
    ],
    models: ['wingman-mispricing-fairvalue (BayesianRidge, 15 feat)', 'wingman-mispricing-anomaly (IsolationForest, 9 feat)', 'Haiku 4.5 hypothesis'],
    outputs: ['Verdict (aligned/stretched/dislocated)', 'fair value + P10/P90 band', 'residual z-score', 'options regime', 'trade card → HITL gate'],
  },
  {
    page: 'Market & Freight Lab', href: '/lab', agent: '— sandbox, no agent fires',
    tools: ['vessel_specs', 'freight_baltic_blpg', 'freight_worldscale', 'port_constraints', 'refined_products_forwards', 'options_data'],
    outputs: ['Tool-level explorer: vessel registry · density math · Baltic mid · Worldscale flat × points · port × vessel compat · futures snapshot · IV/skew'],
  },
  {
    page: 'Forward Scenarios', href: '/scenarios', agent: 'wingman-scenario-forecaster (Haiku 4.5)',
    tools: ['eia_open_data', 'yahoo_finance', 'tavily_search', 'ml_model', 'financial_calculator'],
    features: ['8 normalised market signals fed to GaussianNB classifier'],
    models: ['wingman-scenario-prior (GaussianNB, 5-regime, 90.8% holdout)', 'Haiku 4.5 posterior refinement'],
    outputs: ['5 scenario curves with probabilities', 'P10/P50/P90 fan', 'driver-by-driver $/MT attribution'],
  },
  {
    page: 'Broker Inbox', href: '/inbox', agent: 'wingman-broker-classifier + wingman-broker-parser',
    tools: ['ml_model (TF-IDF)', 'text_analyzer', 'date_calculator'],
    models: ['wingman-broker-intent-classifier (TF-IDF + LogReg, Macro F1 0.91)', 'Haiku 4.5 structured-offer extractor'],
    outputs: ['intent (RFQ/IOI/done/chatter)', 'structured offer JSON', '→ Approvals gate (broker.ack)'],
  },
  {
    page: 'Operations Watch', href: '/ops', agent: 'wingman-ops-monitor (Haiku 4.5 thin orchestrator)',
    tools: ['ais_stream (AISStream.io WebSocket)', 'open_meteo'],
    outputs: ['Live vessel scatter (LPG tankers, ship-type 84)', 'port weather + alerts'],
  },
  {
    page: 'Strategy Lab', href: '/strategy', agent: 'wingman-strategy-encoder → wingman-backtester → wingman-var-simulator',
    tools: ['ml_model', 'financial_calculator', 'risk_analyzer', 'code_asset (Go VaR binary)'],
    outputs: ['Encoded rule JSON', 'hit-rate', '90-day P&L equity curve', 'Monte Carlo VaR loss distribution'],
  },
  {
    page: 'Knowledge Graph', href: '/graph', agent: 'wingman-graph-query (Haiku 4.5)',
    tools: ['knowledge_search (Atlas)'],
    outputs: ['Subgraph traversal', 'natural-language answer over typed ontology (corridor·vessel·counterparty·news·offer)'],
  },
  {
    page: 'Approvals', href: '/approvals', agent: '— SDK gate, no agent (HITL)',
    tools: ['approval_gate (SDK)'],
    outputs: ['trade.execute · broker.ack · strategy.activate · scenario.publish gates'],
  },
];

function ArchitectureMatrix() {
  const [open, setOpen] = useState(false);
  return (
    <section className="mt-10" data-testid="architecture-matrix">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-5 py-3 rounded-xl border border-cyan-500/20 bg-slate-950/40 hover:bg-cyan-500/[0.04] transition-colors"
      >
        <div className="flex items-center gap-3">
          <Workflow className="w-4 h-4 text-cyan-300" />
          <div className="text-left">
            <div className="text-[10px] uppercase tracking-[0.25em] text-cyan-300 font-bold mb-0.5">How it works</div>
            <div className="text-sm font-semibold text-white">Architecture map · every page → tools → features → models</div>
          </div>
        </div>
        <ArrowRight className={`w-4 h-4 text-cyan-300 transition-transform ${open ? 'rotate-90' : ''}`} />
      </button>
      {open && (
        <div className="mt-3 overflow-hidden rounded-xl border border-cyan-500/20">
          <table className="w-full text-[11px]">
            <thead className="bg-slate-900/80 text-slate-300 uppercase text-[9px] tracking-wider">
              <tr>
                <th className="text-left px-3 py-2.5">Page</th>
                <th className="text-left px-3 py-2.5">Agent</th>
                <th className="text-left px-3 py-2.5">Data sources / tools</th>
                <th className="text-left px-3 py-2.5">Feature vectors</th>
                <th className="text-left px-3 py-2.5">ML / AI models</th>
                <th className="text-left px-3 py-2.5">Outputs</th>
              </tr>
            </thead>
            <tbody>
              {PAGE_ARCH.map((row, i) => (
                <tr key={row.page} className={i % 2 === 0 ? 'bg-slate-950/40' : 'bg-slate-900/40'}>
                  <td className="align-top px-3 py-3">
                    <Link href={row.href} className="font-semibold text-white hover:text-emerald-300 inline-flex items-center gap-1">
                      {row.page} <ArrowRight className="w-3 h-3" />
                    </Link>
                  </td>
                  <td className="align-top px-3 py-3 text-slate-400 font-mono text-[10px] leading-snug">{row.agent}</td>
                  <td className="align-top px-3 py-3 leading-snug">
                    <div className="flex flex-wrap gap-1">
                      {row.tools.map((t) => (
                        <span key={t} className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 border border-amber-500/20 text-amber-200">{t}</span>
                      ))}
                    </div>
                  </td>
                  <td className="align-top px-3 py-3 text-slate-300 text-[10px] leading-snug">
                    {row.features ? (
                      <ul className="space-y-0.5">
                        {row.features.map((f, k) => <li key={k}>{f}</li>)}
                      </ul>
                    ) : <span className="text-slate-600 italic">—</span>}
                  </td>
                  <td className="align-top px-3 py-3 leading-snug">
                    {row.models ? (
                      <div className="flex flex-col gap-1">
                        {row.models.map((m) => (
                          <span key={m} className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-fuchsia-500/10 border border-fuchsia-500/20 text-fuchsia-200">{m}</span>
                        ))}
                      </div>
                    ) : <span className="text-slate-600 italic">—</span>}
                  </td>
                  <td className="align-top px-3 py-3 text-slate-300 text-[10px] leading-snug">
                    <ul className="space-y-0.5">
                      {row.outputs.map((o, k) => <li key={k}>{o}</li>)}
                    </ul>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function NewToolCard({
  icon, href, tool, title, blurb, value,
}: {
  icon: React.ReactNode;
  href: string;
  tool: string;
  title: string;
  blurb: string;
  value: string;
}) {
  return (
    <Link
      href={href}
      className="group rounded-xl border border-slate-800 bg-slate-950/40 hover:bg-slate-900/60 hover:border-emerald-500/40 p-4 transition-all flex flex-col"
    >
      <div className="flex items-center gap-2 mb-2">
        {icon}
        <span className="text-sm font-semibold text-white">{title}</span>
      </div>
      <div className="text-[10px] font-mono text-emerald-300 mb-2">{tool}</div>
      <div className="text-[11px] text-slate-300 leading-relaxed mb-3 flex-1">{blurb}</div>
      <div className="text-[11px] font-mono text-slate-400 border-t border-slate-800/60 pt-2 mt-auto">
        {value}
      </div>
    </Link>
  );
}
