'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  CheckCircle2, Users, DollarSign, Zap, TrendingUp, Cpu, BookOpen, ClipboardList,
  Sparkles, Shield, Search, UserCircle2, ArrowRight, HelpCircle, X, Loader2, Play,
} from 'lucide-react';
import { useResolveAIFetch, resolveAIPost } from '@/lib/api';

type Metrics = {
  total_cases?: number;
  auto_resolved?: number;
  handed_to_human?: number;
  deflection_rate?: number;
  total_cost_usd?: number;
  avg_cost_per_case?: number;
};

const WELCOME_KEY = 'resolveai.welcome.v1';

export default function Dashboard() {
  const { data: m, error, refetch } = useResolveAIFetch<Metrics>('/api/resolveai/metrics');
  const router = useRouter();
  const [dismissed, setDismissed] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false;
    try { return window.localStorage.getItem(WELCOME_KEY) === 'done'; } catch { return false; }
  });
  const [tryingIt, setTryingIt] = useState(false);
  const [tryErr, setTryErr] = useState<string | null>(null);

  function dismissWelcome() {
    setDismissed(true);
    try { window.localStorage.setItem(WELCOME_KEY, 'done'); } catch {}
  }

  async function tryItNow() {
    setTryingIt(true); setTryErr(null);
    const { data, error } = await resolveAIPost<{ id?: string }>(
      '/api/resolveai/cases',
      {
        customer_id: 'cust_tour',
        channel: 'chat',
        subject: 'My order #DEMO-1 arrived damaged — need a replacement',
        body: 'The package was crushed in transit and the product inside is broken. Anniversary dinner is tomorrow, please help fast.',
        order_id: 'DEMO-1',
        sku: 'SKU-DEMO',
        customer_tier: 'gold',
        jurisdiction: 'US',
      },
    );
    setTryingIt(false);
    if (error) { setTryErr(error); return; }
    dismissWelcome();
    if (data?.id) router.push(`/cases/${data.id}`);
    else router.push('/cases');
    void refetch();
  }

  const dr = typeof m?.deflection_rate === 'number' ? m!.deflection_rate : 0;
  const stats = [
    { label: 'Total cases',     value: m?.total_cases ?? 0,                   icon: Users,        color: 'text-cyan-400'    },
    { label: 'Auto-resolved',   value: m?.auto_resolved ?? 0,                 icon: CheckCircle2, color: 'text-emerald-400' },
    { label: 'Handed to human', value: m?.handed_to_human ?? 0,               icon: Zap,          color: 'text-amber-400'   },
    { label: 'Deflection rate', value: `${(dr * 100).toFixed(1)}%`,            icon: TrendingUp,   color: 'text-violet-400'  },
    { label: 'Total spend',     value: `$${Number(m?.total_cost_usd ?? 0).toFixed(4)}`, icon: DollarSign, color: 'text-rose-400' },
  ];

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-8">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">ResolveAI · overview</p>
          <h1 className="text-3xl font-bold text-white">Dashboard</h1>
          <p className="text-sm text-slate-400 mt-1">
            Resolution-first customer service. Each ticket runs through the Inbound
            Resolution pipeline; under-threshold auto-refunds fire automatically,
            everything else hands to a human with the draft + citations pre-loaded.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Link
            href="/help"
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs rounded-lg border border-slate-700/60 bg-slate-800/30 hover:bg-slate-800/60 text-slate-300"
          >
            <HelpCircle className="w-3.5 h-3.5" /> Walkthrough
          </Link>
          <Link
            href="/cases"
            data-testid="dashboard-open-cases"
            className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-medium rounded-lg"
          >
            Open cases queue <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
      </div>

      {/* First-visit onboarding banner */}
      {!dismissed && (
        <section className="relative rounded-xl border border-emerald-500/30 bg-gradient-to-br from-emerald-500/10 via-cyan-500/5 to-violet-500/10 p-5" data-testid="welcome-banner">
          <button
            onClick={dismissWelcome}
            className="absolute top-3 right-3 text-slate-500 hover:text-white"
            aria-label="Dismiss welcome"
          >
            <X className="w-4 h-4" />
          </button>
          <div className="flex items-start gap-4">
            <div className="shrink-0 w-10 h-10 rounded-lg bg-emerald-500/15 flex items-center justify-center">
              <Sparkles className="w-5 h-5 text-emerald-300" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-[10px] uppercase tracking-wider text-emerald-300">New here?</p>
              <h2 className="text-lg font-semibold text-white">
                Run your first ticket end-to-end in ~30 seconds.
              </h2>
              <p className="text-sm text-slate-300 mt-1.5 leading-relaxed">
                ResolveAI chains 10 Abenix agents to turn a customer message into a
                cited resolution + action plan. Click <strong>Try it now</strong> and
                we&apos;ll drop in a sample ticket, run the Inbound Resolution pipeline
                against it, and take you to the case detail with the AI-drafted
                resolution and policy citations pre-loaded.
              </p>
              {tryErr && (
                <p className="mt-2 text-xs text-rose-300">Ticket submit failed: {tryErr}</p>
              )}
              <div className="mt-3 flex items-center gap-2 flex-wrap">
                <button
                  onClick={() => void tryItNow()}
                  disabled={tryingIt}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 text-sm font-semibold disabled:opacity-60"
                >
                  {tryingIt ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                  {tryingIt ? 'Running pipeline…' : 'Try it now'}
                </button>
                <Link
                  href="/help"
                  className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-700/60 bg-slate-800/30 hover:bg-slate-800/60 text-slate-200 text-sm"
                >
                  <HelpCircle className="w-3.5 h-3.5" /> Take the full walkthrough
                </Link>
                <button
                  onClick={dismissWelcome}
                  className="text-xs text-slate-500 hover:text-slate-300 underline"
                >
                  Skip — I&apos;ll figure it out
                </button>
              </div>
            </div>
          </div>
        </section>
      )}

      {error && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
          Couldn&apos;t load dashboard metrics: {error}. The navigation and per-page views still work — click{' '}
          <button className="underline" onClick={() => void refetch()}>refresh</button>.
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {stats.map((s) => (
          <div key={s.label} className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-4">
            <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-slate-500 mb-1">
              <s.icon className={`w-3.5 h-3.5 ${s.color}`} />
              {s.label}
            </div>
            <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
          </div>
        ))}
      </div>

      {/* What you're seeing */}
      <section className="rounded-xl border border-cyan-500/20 bg-gradient-to-br from-cyan-500/5 via-violet-500/5 to-emerald-500/5 p-5">
        <h2 className="text-sm font-semibold text-white mb-1 flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-cyan-400" /> How ResolveAI actually works
        </h2>
        <p className="text-xs text-slate-400 mb-4">
          ResolveAI is a thin app — the UI, case lifecycle, and integrations live here; every
          reasoning step delegates to an Abenix agent or pipeline via the bundled SDK.
          No Abenix credential ever leaves the server.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <FlowStep n={1} title="Ticket lands" who="Channel"
            text="Chat / email / voice arrives via webhook. We PII-redact before anything else."
            tone="cyan" />
          <FlowStep n={2} title="Triage classifies" who="Triage Agent"
            text="Returns strict JSON: intent, urgency 1–5, sentiment, PII + risk flags."
            tone="cyan" />
          <FlowStep n={3} title="Context is loaded" who="Customer Context Agent"
            text="Order history, LTV, prior tickets, churn risk — from Shopify + Zendesk."
            tone="violet" />
          <FlowStep n={4} title="Policies are cited" who="Policy Research Agent"
            text="Hybrid search over the Policy KB. Every action must carry policy_id@version."
            tone="violet" />
          <FlowStep n={5} title="Plan + approval" who="Resolution Planner"
            text="Concrete action plan. Auto if ≤ tier ceiling, else blocks on human_approval."
            tone="emerald" />
          <FlowStep n={6} title="Tone rewrite + moderation" who="Tone Agent"
            text="Rewrites to match sentiment/tier; post-LLM moderation gate before send."
            tone="emerald" />
          <FlowStep n={7} title="Deflection decision" who="Deflection Scorer"
            text="Confidence < 0.6 → human takes over with the draft + ceilings pre-loaded."
            tone="amber" />
          <FlowStep n={8} title="Action executes" who="Action Executor"
            text="Refund via Stripe, return label via ShipEngine, ticket comment via Zendesk."
            tone="rose" />
        </div>
        <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
          <SidePipeline title="SLA Sweep" icon={Shield}
            text="Cron (every 5 min) re-scores open cases, files SLABreach rows, pings Slack." />
          <SidePipeline title="Post-Resolution QA" icon={CheckCircle2}
            text="On close, rates tone + correctness, predicts CSAT, queues proactive outreach if <3.5." />
          <SidePipeline title="Trend Mining" icon={TrendingUp}
            text="Nightly cluster on the last 72h of cases. Anomaly? VoCInsight row + Slack alert." />
        </div>
      </section>

      {/* Agent inventory */}
      <section className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5">
        <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
          <Cpu className="w-4 h-4 text-emerald-400" /> 10 specialised Abenix agents
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs text-slate-300">
          <AgentRow icon={Search}        name="Triage"              desc="Classifies intent, urgency, sentiment, PII flags." />
          <AgentRow icon={UserCircle2}   name="Customer Context"    desc="LTV, order history, churn signal from external CRM." />
          <AgentRow icon={BookOpen}      name="Policy Research"     desc="Hybrid search → policy citations with policy_id@version." />
          <AgentRow icon={ClipboardList} name="Resolution Planner"  desc="Action plan with approval tiers + $ ceilings." />
          <AgentRow icon={Sparkles}      name="Tone Agent"          desc="Sentiment-aware rewrite + moderation gate." />
          <AgentRow icon={Zap}           name="Deflection Scorer"   desc="Confidence 0..1 — under 0.6 hands off to a human." />
          <AgentRow icon={CheckCircle2}  name="Action Executor"     desc="Stripe/Shopify/ShipEngine + human_approval gate." />
          <AgentRow icon={Shield}        name="QA Reviewer"         desc="Predicted CSAT + red-flag extraction post-close." />
          <AgentRow icon={TrendingUp}    name="Trend Miner"         desc="Nightly cluster over 72h → VoC insights." />
          <AgentRow icon={Users}         name="Live Copilot"        desc="Streams next-sentence + ceilings while a human types." />
        </div>
      </section>

      {/* Pipelines */}
      <section className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5" data-testid="pipeline-list">
        <h2 className="text-sm font-semibold text-white mb-3">4 pipelines (Abenix-managed)</h2>
        <ul className="space-y-2 text-sm text-slate-300">
          <li>▸ <span className="text-white font-medium">Inbound Resolution</span> — Triage → Context → Policy → Plan → Deflection → Tone → Execute.</li>
          <li>▸ <span className="text-white font-medium">SLA Sweep</span> — cron (/5m) reprioritising stalled cases.</li>
          <li>▸ <span className="text-white font-medium">Post-Resolution QA</span> — on close, CSAT prediction.</li>
          <li>▸ <span className="text-white font-medium">Trend Mining / VoC</span> — nightly pattern detection, Slack escalation.</li>
        </ul>
      </section>
    </div>
  );
}

function FlowStep({ n, title, who, text, tone }: { n: number; title: string; who: string; text: string; tone: 'cyan' | 'violet' | 'emerald' | 'amber' | 'rose' }) {
  const toneClass = {
    cyan:    'border-cyan-500/30 bg-cyan-500/[0.04] text-cyan-300',
    violet:  'border-violet-500/30 bg-violet-500/[0.04] text-violet-300',
    emerald: 'border-emerald-500/30 bg-emerald-500/[0.04] text-emerald-300',
    amber:   'border-amber-500/30 bg-amber-500/[0.04] text-amber-300',
    rose:    'border-rose-500/30 bg-rose-500/[0.04] text-rose-300',
  }[tone];
  return (
    <div className={`rounded-lg border ${toneClass.split(' ').slice(0, 2).join(' ')} p-3 flex gap-3`}>
      <div className={`shrink-0 w-6 h-6 rounded-full border flex items-center justify-center text-[10px] font-bold ${toneClass}`}>{n}</div>
      <div>
        <p className="text-sm font-medium text-white">{title}</p>
        <p className={`text-[10px] uppercase tracking-wider ${toneClass.split(' ').slice(-1)[0]}`}>{who}</p>
        <p className="text-xs text-slate-400 mt-0.5">{text}</p>
      </div>
    </div>
  );
}

function SidePipeline({ title, icon: Icon, text }: { title: string; icon: any; text: string }) {
  return (
    <div className="rounded-lg border border-slate-700/50 bg-slate-900/40 p-3">
      <p className="text-white font-medium flex items-center gap-1.5"><Icon className="w-3.5 h-3.5 text-cyan-400" /> {title}</p>
      <p className="text-xs text-slate-400 mt-1">{text}</p>
    </div>
  );
}

function AgentRow({ icon: Icon, name, desc }: { icon: any; name: string; desc: string }) {
  return (
    <div className="flex items-start gap-2 py-1">
      <Icon className="w-3.5 h-3.5 text-slate-500 mt-0.5 shrink-0" />
      <div>
        <span className="text-white font-medium">{name}</span>
        <span className="text-slate-500"> — {desc}</span>
      </div>
    </div>
  );
}
