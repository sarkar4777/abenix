'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  BookOpen, CheckCircle2, Inbox, AlertTriangle, Star, TrendingUp,
  Headphones, Settings, Play, Loader2, ExternalLink, ArrowRight,
} from 'lucide-react';
import { resolveAIPost } from '@/lib/api';

export default function HelpPage() {
  const router = useRouter();
  const [trying, setTrying] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function tryTicket() {
    setTrying(true); setErr(null);
    const { data, error } = await resolveAIPost<{ id?: string }>('/api/resolveai/cases', {
      customer_id: 'cust_help',
      channel: 'chat',
      subject: 'Help walkthrough — damaged order replacement',
      body: 'Order #HELP-1 arrived damaged and I need a replacement quickly. Please help.',
      order_id: 'HELP-1',
      sku: 'SKU-HELP',
      customer_tier: 'gold',
      jurisdiction: 'US',
    });
    setTrying(false);
    if (error) { setErr(error); return; }
    if (data?.id) router.push(`/cases/${data.id}`);
    else router.push('/cases');
  }

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-8">
      <div>
        <p className="text-[10px] uppercase tracking-wider text-slate-500">ResolveAI · walkthrough</p>
        <h1 className="text-3xl font-bold text-white">What is ResolveAI?</h1>
        <p className="text-base text-slate-300 mt-3 leading-relaxed">
          A <strong>resolution-first</strong> customer service app. Instead of routing
          tickets to a human queue, every incoming ticket runs through an AI
          pipeline that <em>tries to resolve it</em> — citing policy, drafting a
          reply, and executing low-risk actions (refund, replacement) automatically.
          Anything above a confidence or dollar threshold hands off to a human
          with the draft + citations pre-loaded.
        </p>
        <p className="text-sm text-slate-400 mt-3 leading-relaxed">
          It&apos;s also a <strong>reference implementation</strong> of how to build
          a thin vertical app on top of Abenix. The UI, case lifecycle, and
          integrations live in this app; every reasoning step delegates to an
          Abenix agent or pipeline via the bundled SDK — the Abenix
          credential never leaves the server.
        </p>
      </div>

      {/* Try it — the fastest way to understand the product */}
      <section className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-5">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <Play className="w-5 h-5 text-emerald-400" /> 30-second tour
        </h2>
        <ol className="mt-3 space-y-2 text-sm text-slate-200 list-decimal list-inside">
          <li>Click <strong>Run a sample ticket</strong> below.</li>
          <li>We POST a damaged-order scenario to the Inbound Resolution pipeline.</li>
          <li>
            You land on the <em>case detail</em> page. Watch it fill in:
            customer message, AI-drafted resolution, cited policies, proposed
            action plan, and a timeline of pipeline events.
          </li>
          <li>
            Then explore the other pages — each one controls a specific
            pipeline or surface. See the walkthrough below.
          </li>
        </ol>
        {err && <p className="mt-3 text-xs text-rose-300">Couldn&apos;t submit ticket: {err}</p>}
        <div className="mt-4 flex items-center gap-2">
          <button
            onClick={() => void tryTicket()}
            disabled={trying}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold text-sm disabled:opacity-60"
          >
            {trying ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            {trying ? 'Running pipeline (~30s)…' : 'Run a sample ticket'}
          </button>
          <Link href="/cases" className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-700/60 bg-slate-800/30 hover:bg-slate-800/60 text-slate-200 text-sm">
            Just show me the cases queue <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      </section>

      {/* Page-by-page walkthrough */}
      <section className="space-y-4">
        <h2 className="text-xl font-semibold text-white flex items-center gap-2">
          <BookOpen className="w-5 h-5 text-cyan-400" /> The app, page by page
        </h2>

        <PageCard
          href="/"
          icon={<CheckCircle2 className="w-4 h-4 text-cyan-400" />}
          title="Dashboard"
          what="Deflection rate, total cases, auto-resolved vs. handed-to-human, spend. Refreshes whenever you land here."
          status="full"
        />
        <PageCard
          href="/cases"
          icon={<Inbox className="w-4 h-4 text-emerald-400" />}
          title="Cases"
          what={
            <>
              Every ticket that entered the pipeline. Click <em>Simulate a ticket</em>
              to feed a synthetic scenario through the Inbound Resolution pipeline end-to-end
              (~30s with live LLM calls). Click any row to open the case detail
              with the AI-drafted resolution, policy citations, and action plan.
            </>
          }
          status="full"
        />
        <PageCard
          href="/sla"
          icon={<AlertTriangle className="w-4 h-4 text-amber-400" />}
          title="SLA Board"
          what="Runs the SLA Sweep pipeline on demand, surfaces breaches. In production it fires automatically on a 5-minute cron via Abenix triggers; here you can trigger it yourself."
          status="full"
        />
        <PageCard
          href="/qa"
          icon={<Star className="w-4 h-4 text-violet-400" />}
          title="QA & CSAT"
          what="Closed cases go through the Post-Resolution QA pipeline: it predicts a CSAT score, extracts red flags, and buckets the case as detractor / passive / promoter. Predicted detractors get proactive outreach — saves the NPS dip before it lands."
          status="full"
        />
        <PageCard
          href="/trends"
          icon={<TrendingUp className="w-4 h-4 text-violet-400" />}
          title="Trends / VoC"
          what="Clusters the last 72h of cases and files insights when an SKU / carrier / policy starts spiking. Run it on demand here; in production it runs nightly."
          status="full"
        />
        <PageCard
          href="/admin"
          icon={<Settings className="w-4 h-4 text-slate-400" />}
          title="Admin"
          what="Approval ceilings (auto-approve threshold, T1 lead ceiling, manager ceiling), SLA targets, Slack escalation webhook, and the pending-approvals queue where a human signs off actions above the auto tier."
          status="full"
        />
        <PageCard
          href="/live-console"
          icon={<Headphones className="w-4 h-4 text-amber-400" />}
          title="Live Console"
          what="Agent-assist copilot surface — streams next-sentence suggestions + cited refund ceilings while a human CSM types. Phase-2 placeholder; the SSE endpoint is wired but the UI is stub."
          status="preview"
        />
      </section>

      {/* How the pipeline works */}
      <section className="rounded-xl border border-cyan-500/20 bg-gradient-to-br from-cyan-500/5 via-violet-500/5 to-emerald-500/5 p-5 space-y-3">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <BookOpen className="w-5 h-5 text-cyan-400" /> Under the hood
        </h2>
        <p className="text-sm text-slate-300 leading-relaxed">
          The <strong>Inbound Resolution</strong> pipeline chains six Abenix
          agents. You can see the DAG in the Abenix builder — open{' '}
          <Link href="http://localhost:3000" target="_blank" rel="noreferrer" className="text-cyan-400 hover:underline inline-flex items-center gap-0.5">
            Abenix <ExternalLink className="w-3 h-3" />
          </Link>
          {' '}and search for <code className="bg-slate-900/60 px-1 rounded text-xs text-cyan-300">resolveai-inbound-resolution</code>.
        </p>
        <ol className="text-sm text-slate-300 space-y-1.5 list-decimal list-inside">
          <li><strong>Triage</strong> — classifies intent, urgency, sentiment, PII/risk flags.</li>
          <li><strong>Policy Research</strong> — hybrid search over the Policy KB; every action must carry a <code className="bg-slate-900/60 px-1 rounded text-xs">policy_id@version</code>.</li>
          <li><strong>Resolution Planner</strong> — picks actions (refund, replacement, explain…) with approval tiers + dollar ceilings.</li>
          <li><strong>Approval Gate</strong> — skips when no action requires approval; otherwise blocks for human sign-off.</li>
          <li><strong>Moderation</strong> — OpenAI moderation on the final reply.</li>
          <li><strong>Final Report</strong> — structured output the UI reads: reply, citations, action_plan, deflection_score, triage.</li>
        </ol>
        <p className="text-xs text-slate-500 mt-2">
          Deflection score ≥ 0.6 → <span className="text-emerald-400">auto_resolved</span>. Below → <span className="text-amber-400">handed_to_human</span>.
        </p>
      </section>

      {/* Things that can go wrong + what to do */}
      <section className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5 space-y-3">
        <h2 className="text-lg font-semibold text-white">If something breaks</h2>
        <dl className="text-sm space-y-3">
          <div>
            <dt className="text-slate-200 font-medium">A page shows an inline error card.</dt>
            <dd className="text-slate-400 mt-0.5">Click the Retry button in the card — one fetch hiccup during a deploy is the most common cause. The rest of the app stays usable.</dd>
          </div>
          <div>
            <dt className="text-slate-200 font-medium">A case sits in <code className="bg-slate-900/60 px-1 rounded text-xs">pipeline_error</code>.</dt>
            <dd className="text-slate-400 mt-0.5">The Abenix API was unreachable when the pipeline fired, typically during a rolling image update. Click <em>Simulate a ticket</em> again — the new one will run on the healthy pod.</dd>
          </div>
          <div>
            <dt className="text-slate-200 font-medium">The sample ticket takes longer than 30 seconds.</dt>
            <dd className="text-slate-400 mt-0.5">Cold LLM paths can take 60–90s on the first run of a fresh pod. Subsequent runs reuse warmed connections and come back in ~25s.</dd>
          </div>
          <div>
            <dt className="text-slate-200 font-medium">Many people are in the demo at once.</dt>
            <dd className="text-slate-400 mt-0.5">Cases are tenant-scoped so concurrent users don&apos;t see each other&apos;s tickets. The pipeline is rate-limited at the LLM provider; if you see a 429 in the inline error just retry.</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}

function PageCard({
  href, icon, title, what, status,
}: {
  href: string;
  icon: React.ReactNode;
  title: string;
  what: React.ReactNode;
  status: 'full' | 'preview';
}) {
  return (
    <Link href={href} className="block rounded-xl border border-slate-700/50 bg-slate-800/30 hover:border-cyan-500/40 hover:bg-slate-800/50 transition-colors p-4">
      <div className="flex items-start gap-3">
        <div className="shrink-0 w-8 h-8 rounded-lg bg-slate-900/50 flex items-center justify-center">{icon}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <p className="text-sm font-semibold text-white">{title}</p>
            <span className={`text-[10px] px-1.5 py-0.5 rounded border ${
              status === 'full'
                ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-300'
                : 'bg-amber-500/10 border-amber-500/40 text-amber-300'
            }`}>
              {status === 'full' ? 'full' : 'preview'}
            </span>
            <code className="text-[10px] font-mono text-slate-500 ml-auto">{href}</code>
          </div>
          <p className="text-xs text-slate-400 mt-1 leading-relaxed">{what}</p>
        </div>
      </div>
    </Link>
  );
}
