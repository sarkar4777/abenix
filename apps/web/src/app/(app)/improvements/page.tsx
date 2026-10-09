'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { AlertTriangle, ArrowRight, Hourglass, Inbox, Loader2, MessageSquare, RefreshCw, Search, Sparkles, Sprout, Undo2, Wrench } from 'lucide-react';
import PageHeader from '@/components/layout/PageHeader';
import NoAccess from '@/components/layout/NoAccess';
import { usePageTitle } from '@/hooks/usePageTitle';
import { holds, useMyPermissions } from '@/lib/capabilities';
import { SeverityPill, TrendBars } from '@/components/improvements/TrendBars';
import BudgetMeter from '@/components/improvements/proposals/BudgetMeter';
import { improvementsApi, plural, type Overview } from '@/lib/improvements';

const IMPROVEMENT_STEPS = [
  'Thumbs, corrections, failed runs and reviews become lessons on their own.',
  'Similar lessons are grouped and turned into test cases.',
  'A fix is proposed and proven against those cases before anyone sees it.',
  'A person approves it, and it is watched after release and rolled back if worse.',
];

function sampleAgentId(d: Record<string, unknown> | null): string | null {
  if (!d) return null;
  const agent = d.agent as { id?: string } | undefined;
  return (agent?.id || (d.agent_id as string | undefined)) ?? null;
}

const PURPOSE = 'Agents get better from their own mistakes. Every change is proven first, approved by a person and watched after release. For builders and the people who approve their changes.';

export default function ImprovementsPage() {
  usePageTitle('Improvements');
  const router = useRouter();
  const { perms, loading: permLoading } = useMyPermissions();
  const canView = holds(perms?.capabilities, 'improvements.view');
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');
  const [sampleBusy, setSampleBusy] = useState(false);
  const [sampleMsg, setSampleMsg] = useState<string | null>(null);

  const load = useCallback(async (needle?: string) => {
    setLoading(true);
    const r = await improvementsApi.overview(needle);
    setLoading(false);
    if (r.error || !r.data) { setError(r.error || 'Nothing came back'); return; }
    setError(null);
    setData(r.data);
  }, []);

  useEffect(() => {
    if (!permLoading && !canView) setLoading(false);
  }, [permLoading, canView]);

  // first load at once, typing waits a moment
  useEffect(() => {
    if (permLoading || !canView) return;
    const needle = q.trim();
    const t = setTimeout(() => load(needle || undefined), needle ? 300 : 0);
    return () => clearTimeout(t);
  }, [q, permLoading, canView, load]);

  async function trySample() {
    setSampleBusy(true);
    setSampleMsg(null);
    const r = await improvementsApi.sample();
    setSampleBusy(false);
    if (r.status === 404 || r.status === 405) {
      setSampleMsg('The sample agent arrives with the next update. Until then, give a thumbs down with a correction on any agent answer in chat and come back here.');
      return;
    }
    if (r.error) { setSampleMsg(`The sample did not start: ${r.error}`); return; }
    const id = sampleAgentId(r.data);
    if (id) router.push(`/agents/${encodeURIComponent(id)}/improvements`);
    else load();
  }

  if (!permLoading && !canView) {
    return (
      <NoAccess
        testId="improvements-no-access"
        title="Improvements"
        purpose={PURPOSE}
        icon={Sprout}
        need={{ capability: 'improvements.view', label: 'View improvements' }}
        role={perms?.role}
        instead={{ text: 'You can still open the Improvements tab on agents you built, from the agent page.', href: '/agents', label: 'Open your agents' }}
      />
    );
  }

  const counts = data?.counts;
  const empty = !!data && !q.trim() && data.agents.length === 0 && !counts?.open_lessons;
  const tiles = [
    { id: 'lessons', label: 'Open lessons', value: counts?.open_lessons, icon: Inbox, hint: 'Not fixed or dismissed yet' },
    { id: 'waiting', label: 'Proposals waiting', value: counts?.proposals_waiting, icon: Wrench, hint: 'Proven and waiting for approval', href: '/approvals' },
    { id: 'watching', label: 'Releases in watch', value: counts?.releases_watching, icon: Hourglass, hint: 'Compared with the old version' },
    { id: 'rolled', label: 'Rolled back, 30 days', value: counts?.rolled_back_30d, icon: Undo2, hint: 'Did worse and were reverted' },
  ];

  return (
    <div className="mx-auto max-w-6xl space-y-6" data-testid="improvements-page">
      <PageHeader
        title="Improvements"
        icon={Sprout}
        purpose={PURPOSE}
        storageKey="improvements"
        docSlug="08-howto/16-self-improvement"
        steps={IMPROVEMENT_STEPS}
        primaryAction={
          empty
            ? { label: 'Give feedback in chat', href: '/chat', icon: MessageSquare, testId: 'improvements-go-chat' }
            : { label: 'Try the sample agent', onClick: trySample, icon: sampleBusy ? Loader2 : Sparkles, busy: sampleBusy, disabled: sampleBusy, testId: 'improvements-sample' }
        }
      />
      <div className="-mt-3 flex items-center gap-2">
        <BudgetMeter />
        <button type="button" onClick={() => load(q.trim() || undefined)} aria-label="Refresh" title="Refresh" className="inline-flex shrink-0 items-center rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:bg-slate-800">
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>
      {sampleMsg && !empty && <p className="-mt-3 text-sm text-amber-200" role="status" data-testid="improvements-sample-message">{sampleMsg}</p>}

      {error ? (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200" role="alert" data-testid="improvements-error">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span className="min-w-0 flex-1">Could not load improvements: {error}. Check your connection and try again.</span>
          <button type="button" onClick={() => load(q.trim() || undefined)} className="rounded border border-rose-500/40 px-2 py-1 text-xs hover:bg-rose-500/20">Try again</button>
        </div>
      ) : loading && !data ? (
        <div className="space-y-3" data-testid="improvements-loading">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[0, 1, 2, 3].map((i) => <div key={i} className="h-24 animate-pulse rounded-xl bg-slate-800/40" />)}</div>
          <div className="h-48 animate-pulse rounded-xl bg-slate-800/40" />
        </div>
      ) : data ? (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="improvements-counts">
            {tiles.map((t) => {
              const body = (
                <>
                  <div className="flex items-center gap-2 text-xs text-slate-400"><t.icon className="h-4 w-4 text-cyan-300" /> {t.label}</div>
                  <div className="mt-1 text-2xl font-semibold text-white" data-testid={`improvements-count-${t.id}`}>{t.value ?? 0}</div>
                  <div className="mt-0.5 text-[11px] text-slate-500">{t.hint}</div>
                </>
              );
              return t.href && (t.value || 0) > 0 ? (
                <Link key={t.id} href={t.href} className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-3 hover:border-slate-600 sm:p-4">{body}</Link>
              ) : (
                <div key={t.id} className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-3 sm:p-4">{body}</div>
              );
            })}
          </div>

          {empty ? (
            <section className="rounded-2xl border border-cyan-500/30 bg-gradient-to-br from-cyan-500/10 to-slate-900/40 p-5 sm:p-6" data-testid="improvements-empty">
              <Sparkles className="h-7 w-7 text-cyan-300" />
              <h2 className="mt-2 text-lg font-semibold text-white">No lessons yet</h2>
              <p className="mt-1 max-w-2xl text-sm text-slate-300">
                When someone gives an answer a thumbs down, writes what it should have said, or a run fails, it becomes a lesson here. Similar lessons are grouped and turned into test cases, and a proposed fix is proven against them before anyone approves it.
              </p>
              <ol className="mt-3 list-decimal space-y-1 pl-5 text-xs text-slate-400">
                {IMPROVEMENT_STEPS.map((s) => <li key={s}>{s}</li>)}
              </ol>
              <div className="mt-4 flex flex-wrap items-center gap-3">
                <button type="button" onClick={trySample} disabled={sampleBusy} className="inline-flex items-center gap-1.5 rounded-md bg-cyan-500 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-400 disabled:opacity-50" data-testid="improvements-sample">
                  {sampleBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />} Try it on the sample agent
                </button>
                <Link href="/chat" className="text-sm text-cyan-300 hover:underline">Or give feedback in chat</Link>
              </div>
              {sampleMsg && <p className="mt-3 text-sm text-amber-200" role="status" data-testid="improvements-sample-message">{sampleMsg}</p>}
            </section>
          ) : (
            <section className="space-y-3" aria-labelledby="improvements-agents-title">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <h2 id="improvements-agents-title" className="text-base font-semibold text-white">Agents with open lessons, worst first</h2>
                <label className="relative block w-full sm:w-64">
                  <span className="sr-only">Find an agent</span>
                  <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-slate-500" />
                  <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find an agent" className="w-full rounded-md border border-slate-700 bg-slate-900/60 py-2 pl-8 pr-3 text-sm text-white placeholder:text-slate-500 focus:border-cyan-500 focus:outline-none" data-testid="improvements-search" />
                </label>
              </div>
              {data.agents.length === 0 ? (
                <p className="rounded-xl border border-dashed border-slate-700 p-4 text-sm text-slate-400" data-testid="improvements-no-agents">
                  {q.trim() ? `No agent with open lessons matches "${q.trim()}".` : 'No agent has open lessons right now. New ones are grouped every two minutes.'}
                </p>
              ) : (
                <ul className="space-y-2" data-testid="improvements-agents">
                  {data.agents.map((a) => (
                    <li key={a.agent.id}>
                      <Link
                        href={`/agents/${encodeURIComponent(a.agent.id)}/improvements`}
                        className="flex flex-col gap-2 rounded-xl border border-slate-700/50 bg-slate-800/30 p-3 hover:border-slate-600 sm:flex-row sm:items-center sm:justify-between sm:p-4"
                        data-testid="improvements-agent-row"
                      >
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <SeverityPill severity={a.worst_severity} />
                            <span className="break-words font-medium text-white">{a.agent.name}</span>
                          </div>
                          <p className="mt-0.5 text-xs text-slate-400">{plural(a.open_lessons, 'open lesson')} in {plural(a.open_clusters, 'group')}</p>
                        </div>
                        <div className="flex items-center justify-between gap-3 sm:justify-end">
                          <TrendBars values={a.trend} />
                          <ArrowRight className="h-4 w-4 shrink-0 text-slate-500" />
                        </div>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
              {data.total_agents > data.agents.length && (
                <p className="text-xs text-slate-500">Showing the worst {data.agents.length} of {data.total_agents}. Search to find the rest.</p>
              )}
            </section>
          )}
        </>
      ) : null}
    </div>
  );
}
