'use client';

import Link from 'next/link';
import PageHeader from '@/components/layout/PageHeader';
import { Activity, AlertTriangle, GitBranch, Radio, Server, ExternalLink, ArrowRight } from 'lucide-react';

const GRAFANA = (process.env.NEXT_PUBLIC_GRAFANA_URL || 'http://localhost:3010').replace(/\/$/, '');

interface Phase {
  num: number;
  title: string;
  Icon: React.ComponentType<{ className?: string }>;
  oneLine: string;
  whatItAnswers: string;
  surfaces: { label: string; href: string; external?: boolean }[];
  accent: string;
}

const PHASES: Phase[] = [
  {
    num: 1,
    title: 'Activity log',
    Icon: Activity,
    oneLine: 'Every agent run, tool call, and pipeline step writes one row.',
    whatItAnswers: 'What ran in this tenant in the last hour, day, week? Which agent, which user, what was the input?',
    surfaces: [
      { label: 'Open Executions', href: '/executions' },
      { label: 'Open Analytics', href: '/analytics' },
    ],
    accent: 'cyan',
  },
  {
    num: 2,
    title: 'Live updates',
    Icon: Radio,
    oneLine: 'Server-Sent-Events feed broadcasts runs as they happen — no refresh.',
    whatItAnswers: 'Is the latest chat actually running right now? Did the tool call I just fired return yet?',
    surfaces: [
      { label: 'Live Debug stream', href: '/executions/live' },
      { label: 'Watch a specific execution', href: '/executions' },
    ],
    accent: 'emerald',
  },
  {
    num: 3,
    title: 'Alerts',
    Icon: AlertTriangle,
    oneLine: 'Failures are grouped by stable failure_code so a 50-row mess collapses into 4 buckets.',
    whatItAnswers: 'What is breaking right now and what shape is it? Is this an LLM rate-limit, a moderation block, or a tool crash?',
    surfaces: [
      { label: 'Open Alerts', href: '/alerts' },
      { label: 'Review Queue', href: '/review-queue' },
    ],
    accent: 'amber',
  },
  {
    num: 4,
    title: 'Distributed tracing',
    Icon: GitBranch,
    oneLine: 'OpenTelemetry traces every execution + every tool call; spans flow into Grafana Tempo.',
    whatItAnswers: 'WHY was that run slow? Which tool took 8s of the 12s total? Was it the LLM, the DB, the MCP call?',
    surfaces: [
      { label: 'View any execution → click "View Trace"', href: '/executions' },
      GRAFANA
        ? { label: 'Open Grafana Tempo Explore', href: `${GRAFANA}/explore?orgId=1&left=${encodeURIComponent(JSON.stringify({datasource:'tempo',queries:[{query:'',queryType:'search'}],range:{from:'now-1h',to:'now'}}))}`, external: true }
        : { label: 'Grafana not configured', href: '#' },
    ],
    accent: 'fuchsia',
  },
];

const ACCENT_CLASSES: Record<string, { ring: string; bg: string; text: string }> = {
  cyan:    { ring: 'ring-cyan-500/40',    bg: 'bg-cyan-500/10',    text: 'text-cyan-300' },
  emerald: { ring: 'ring-emerald-500/40', bg: 'bg-emerald-500/10', text: 'text-emerald-300' },
  amber:   { ring: 'ring-amber-500/40',   bg: 'bg-amber-500/10',   text: 'text-amber-300' },
  fuchsia: { ring: 'ring-fuchsia-500/40', bg: 'bg-fuchsia-500/10', text: 'text-fuchsia-300' },
};

export default function ObservabilityHubPage() {
  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="observability-hub">
      <PageHeader
        className="mb-6"
        title="Observability"
        purpose="Four views that tell you what ran, what is running now, what is breaking and why. For builders and operators."
        icon={Server}
        storageKey="observability"
        docSlug="06-deployment/04-observability"
        primaryAction={{ label: 'Open runs', icon: Activity, href: '/executions' }}
        secondaryAction={{ label: 'Cluster health', icon: Server, href: '/admin/cluster', testId: 'observability-cluster-link' }}
        steps={[
          { title: 'What ran', body: 'Runs and Analytics list every run with its agent, user and input.' },
          { title: 'What is running', body: 'Runs tick live as they happen, no refresh needed.' },
          { title: 'What broke', body: 'A failed run joins a group on the Alerts page with others of the same cause.' },
          { title: 'Why it was slow', body: 'View Trace on any run opens the full timing tree in Grafana.' },
        ]}
      />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {PHASES.map(p => {
          const A = ACCENT_CLASSES[p.accent];
          return (
            <div key={p.num} className={`rounded-2xl border border-slate-700/60 bg-slate-900/40 backdrop-blur p-5 ring-1 ${A.ring}`}>
              <div className="flex items-start gap-3 mb-3">
                <div className={`w-10 h-10 rounded-xl ${A.bg} ring-1 ${A.ring} flex items-center justify-center shrink-0`}>
                  <p.Icon className={`w-5 h-5 ${A.text}`} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-0.5">Phase {p.num}</div>
                  <h2 className="text-lg font-semibold text-white">{p.title}</h2>
                </div>
              </div>
              <p className="text-sm text-slate-300 mb-3">{p.oneLine}</p>
              <div className="text-xs text-slate-400 mb-4">
                <span className="text-slate-500 uppercase tracking-wider mr-2">Answers:</span>
                {p.whatItAnswers}
              </div>
              <div className="flex flex-wrap gap-2">
                {p.surfaces.map(s => (
                  s.external ? (
                    <a
                      key={s.href}
                      href={s.href}
                      target="_blank"
                      rel="noreferrer"
                      className={`inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border ${A.ring.replace('ring-','border-')} ${A.bg} ${A.text} hover:brightness-110`}
                    >
                      {s.label} <ExternalLink className="w-3 h-3" />
                    </a>
                  ) : (
                    <Link
                      key={s.href}
                      href={s.href}
                      className={`inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border ${A.ring.replace('ring-','border-')} ${A.bg} ${A.text} hover:brightness-110`}
                    >
                      {s.label} <ArrowRight className="w-3 h-3" />
                    </Link>
                  )
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
