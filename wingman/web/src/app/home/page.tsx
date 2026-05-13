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

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

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
    title: 'Mispricing Lens',
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
      { id: 'yahoo_finance',             desc: 'Yahoo futures: front-month + history' },
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
  { label: 'Mispricing Extractor', kind: 'agent', icon: 'sparkles' },
  { label: 'EIA spot',             kind: 'tool',  icon: 'db' },
  { label: 'Yahoo forwards',       kind: 'tool',  icon: 'db' },
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
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.25em] text-emerald-300 mb-4">
            <Sparkles className="w-3.5 h-3.5" />
            Wingman · Trader Workbench
            <span className="text-slate-500">|</span>
            <span className="text-slate-400 normal-case tracking-normal">{now}</span>
          </div>

          <h1 className="text-5xl lg:text-6xl font-bold tracking-tight leading-[1.15] pb-2 bg-gradient-to-r from-white via-emerald-100 to-cyan-200 bg-clip-text text-transparent">
            Energy arbitrage you can actually trust.
          </h1>
          <p className="mt-5 text-lg text-slate-300 max-w-3xl leading-relaxed">
            An agentic copilot for the LPG and clean-products desk. Every corridor, every trade idea, every recommendation is grounded in real EIA prints, Baltic + Worldscale freight, Yahoo futures, options skew, vessel + port reality, and live news — synthesised by a Bayesian model that knows when it doesn't know.
          </p>

          <div className="mt-7 flex flex-wrap gap-3">
            <Link
              href="/workbench"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold text-sm transition-colors"
            >
              Open Arb Workbench
              <ArrowRight className="w-4 h-4" />
            </Link>
            <Link
              href="/mispricing"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl border border-emerald-500/40 text-emerald-200 hover:bg-emerald-500/10 font-semibold text-sm transition-colors"
            >
              Mispricing Lens
              <Crosshair className="w-4 h-4" />
            </Link>
            <Link
              href="/approvals"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl border border-slate-700 text-slate-300 hover:bg-slate-800/60 font-semibold text-sm transition-colors"
            >
              Pending HITL
              <ShieldCheck className="w-4 h-4" />
            </Link>
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

      {/* ── EVERY MARKET, EVERY FREIGHT, EVERY PORT ───────────────────── */}
      <section className="mt-12">
        <SectionHeader
          eyebrow="Every market signal a desk reads"
          title="From the tank at Mont Belvieu to the berth at Chiba."
          subtitle="Spot, forwards, options, Baltic + Worldscale freight, vessel specs, port constraints, weather, news — all live, all interrogable, all consumed by the Mispricing model on every scan. Open the Lab to drive each one yourself."
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
            value="WTI $76.18 / RBOB $95/bbl / 3-2-1 ~$28"
          />
          <NewToolCard
            icon={<TrendingUp className="w-4 h-4 text-fuchsia-300" />}
            href="/mispricing"
            tool="options_data"
            title="Options market signals"
            blurb="Brent + HH implied vol, 25-delta risk reversal (skew), put/call OI, regime label. Powers 4 of the 15 Mispricing features."
            value="CL=F: IV 34.5% · RR +0.06 → skewed_up"
          />
        </div>
        <div className="mt-5 flex items-center gap-3 flex-wrap">
          <Link href="/lab" className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold text-[12px] transition-colors">
            Open the Market &amp; Freight Lab
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>
          <Link href="/mispricing" className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-emerald-500/40 text-emerald-200 hover:bg-emerald-500/10 font-semibold text-[12px] transition-colors">
            See them feeding the Mispricing Lens
            <Crosshair className="w-3.5 h-3.5" />
          </Link>
        </div>
      </section>

      {/* ── BUSINESS VALUE STRIP ──────────────────────────────────────── */}
      <section className="mt-10 grid grid-cols-1 md:grid-cols-3 gap-4">
        <ValueCard
          icon={<TrendingUp className="w-5 h-5 text-emerald-300" />}
          title="Find the arb in 30 seconds, not 30 minutes"
          body="Open a corridor card and an autonomous agent pipeline gathers EIA, Yahoo, Baltic, options, weather and news in parallel. You read a single sigma-banded verdict instead of pasting numbers into a spreadsheet."
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
          subtitle="Every page on Wingman is a thin client over the same agentic engine. The pipeline below is what runs when you click Analyze on Arb Workbench or Re-score on Mispricing Lens — every step is a real tool or model call."
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
            The orchestration is just a YAML agent — <span className="font-mono text-slate-300">wingman-mispricing-extractor</span> — that lists the 13 tools above. The runtime calls them in parallel where it can, builds a 15-feature vector, evaluates two ML models, asks an LLM to draft the thesis citing live Tavily headlines, and emits a structured JSON the page reads. Add a new tool to the YAML and it shows up here instantly.
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
