'use client';

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { useParams, useSearchParams } from 'next/navigation';
import { AlertTriangle, BellRing, Sparkles, FlaskConical, Layers, MessageSquare, RefreshCw, Rocket, Sprout, Wrench } from 'lucide-react';
import PageHeader from '@/components/layout/PageHeader';
import { usePageTitle } from '@/hooks/usePageTitle';
import ClusterCard from '@/components/improvements/ClusterCard';
import SuggestedCases from '@/components/improvements/SuggestedCases';
import GateToggle from '@/components/improvements/GateToggle';
import ProposalList from '@/components/improvements/proposals/ProposalList';
import ReleaseWatch from '@/components/improvements/proposals/ReleaseWatch';
import BudgetMeter from '@/components/improvements/proposals/BudgetMeter';
import NextSteps from '@/components/shared/NextSteps';
import { proposalsApi } from '@/lib/improvement-proposals';
import { toastError } from '@/stores/toastStore';
import { improvementsApi, plural, type AgentImprovements, type ClusterRow } from '@/lib/improvements';

const SHUT_KEY = 'improvements.proposeOffer.shut';

function readShut(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(SHUT_KEY) || '[]');
    return Array.isArray(v) ? v.map(String) : [];
  } catch {
    return [];
  }
}

function writeShut(ids: string[]) {
  try {
    localStorage.setItem(SHUT_KEY, JSON.stringify(ids.slice(-50)));
  } catch {
    // storage blocked, the offer just shows again
  }
}

function Section({ id, icon: Icon, title, hint, count, children }: {
  id: string; icon: typeof Layers; title: string; hint: string; count?: number; children: ReactNode;
}) {
  return (
    <section className="space-y-3" data-testid={`improvements-section-${id}`} aria-labelledby={`improvements-${id}-title`}>
      <div>
        <h2 id={`improvements-${id}-title`} className="flex items-center gap-2 text-base font-semibold text-white">
          <Icon className="h-4 w-4 text-cyan-400" /> {title}
          {typeof count === 'number' && <span className="rounded-full bg-slate-700/60 px-2 py-0.5 text-[11px] font-normal text-slate-300">{count}</span>}
        </h2>
        <p className="mt-0.5 text-xs text-slate-500">{hint}</p>
      </div>
      {children}
    </section>
  );
}

export default function AgentImprovementsPage() {
  const params = useParams();
  const agentId = params.id as string;
  const [data, setData] = useState<AgentImprovements | null>(null);
  const [error, setError] = useState<{ text: string; status?: number } | null>(null);
  const [loading, setLoading] = useState(true);
  usePageTitle(data ? `Improvements, ${data.agent.name}` : 'Improvements');
  const [shut, setShut] = useState<string[]>([]);
  const [proposing, setProposing] = useState(false);

  useEffect(() => { setShut(readShut()); }, []);

  const load = useCallback(async () => {
    setLoading(true);
    const r = await improvementsApi.agent(agentId);
    setLoading(false);
    if (r.error || !r.data) { setError({ text: r.error || 'Nothing came back', status: r.status }); return; }
    setError(null);
    setData(r.data);
  }, [agentId]);

  useEffect(() => { load(); }, [load]);

  // See the proof links here with ?proposal=, a proposal made after the last load needs a fresh one
  const focus = useSearchParams().get('proposal');
  const fetchedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!data || !focus || fetchedFor.current === focus) return;
    if ([...data.proposals, ...data.releases].some((p) => p.id === focus)) return;
    fetchedFor.current = focus;
    load();
  }, [data, focus, load]);

  const header = (
    <PageHeader
      title={data ? `Improvements for ${data.agent.name}` : 'Improvements'}
      icon={Sprout}
      purpose="What this agent gets wrong, the test cases that came from it, and the fixes proven against them. For the agent's owner and the people who approve its changes."
      back={{ href: `/agents/${encodeURIComponent(agentId)}/info`, label: 'Back to the agent' }}
      primaryAction={{ label: 'Chat with the agent', href: `/agents/${encodeURIComponent(agentId)}/chat`, icon: MessageSquare, testId: 'agent-improvements-chat' }}
      secondaryAction={{ label: 'Fixes waiting on you', href: '/inbox?tab=proposals', icon: BellRing, testId: 'agent-improvements-inbox' }}
      steps={[
        'Thumbs down, corrections, failed runs and reviews become lessons. Similar ones are grouped so one fix covers them.',
        'Each group suggests test cases. Accept the ones that describe what the agent should do.',
        'Propose a fix. It is proven against the cases and recent real inputs before anyone sees it.',
        'A person approves it, and the release is watched and rolled back on its own if it does worse.',
      ]}
      docSlug="08-howto/16-self-improvement"
      storageKey="agent-improvements"
    />
  );

  if (error) {
    const forbidden = error.status === 403;
    return (
      <div className="mx-auto max-w-4xl space-y-4" data-testid="agent-improvements-error">
        {header}
        <div className="flex flex-wrap items-start gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200" role="alert">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span className="min-w-0 flex-1">
            {forbidden
              ? "Only the agent's owner, people it is shared with and admins see its lessons. Ask the owner to share the agent with you."
              : error.status === 404 ? 'This agent was not found. It may have been deleted.'
              : `Could not load the improvements: ${error.text}. Check your connection and try again.`}
          </span>
          {!forbidden && error.status !== 404 && (
            <button type="button" onClick={load} className="rounded border border-rose-500/40 px-2 py-1 text-xs hover:bg-rose-500/20">Try again</button>
          )}
        </div>
      </div>
    );
  }

  if (loading && !data) {
    return (
      <div className="mx-auto max-w-4xl space-y-4" data-testid="agent-improvements-loading">
        {header}
        <div className="h-8 w-64 animate-pulse rounded bg-slate-800/50" />
        {[0, 1, 2].map((i) => <div key={i} className="h-32 animate-pulse rounded-xl bg-slate-800/40" />)}
      </div>
    );
  }
  if (!data) return null;

  const { counts } = data;
  // a new group with nothing proposed yet, worst first
  const fresh: ClusterRow | undefined = data.can_manage
    ? data.clusters.find((c) => c.state === 'open' && !c.proposal && !shut.includes(c.id))
    : undefined;
  const shutOffer = (id: string) => {
    const ids = [...shut, id];
    setShut(ids);
    writeShut(ids);
  };
  const proposeFresh = async (c: ClusterRow) => {
    if (proposing) return;
    setProposing(true);
    const r = await proposalsApi.propose(c.id);
    setProposing(false);
    if (r.error || !r.data) {
      toastError('The fix could not be proposed', r.error || undefined);
      return;
    }
    load();
  };
  return (
    <div className="mx-auto max-w-4xl space-y-8" data-testid="agent-improvements">
      <div className="space-y-3">
        {header}
        <div className="flex items-center gap-2">
          <BudgetMeter />
          <button type="button" onClick={load} aria-label="Refresh" title="Refresh" className="inline-flex shrink-0 items-center rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:bg-slate-800">
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
        <p className="text-xs text-slate-500" data-testid="agent-improvements-counts">
          {plural(counts.good_examples, 'answer')} people liked, kept as examples. {plural(counts.closed_clusters, 'group')} fixed or dismissed.
          {counts.waiting_to_group > 0 && ` ${plural(counts.waiting_to_group, 'new lesson')} waiting to be grouped, usually within two minutes.`}
        </p>
      </div>

      {fresh && (
        <NextSteps
          title={`New group of lessons: ${fresh.title}`}
          testId="improvements-propose-next"
          onDismiss={() => shutOffer(fresh.id)}
          steps={[
            {
              id: 'propose',
              label: proposing ? 'Proposing a fix' : 'Propose a fix',
              hint: `${plural(fresh.count, 'lesson')} point the same way. The fix is proven against the test cases before anyone approves it.`,
              icon: Sparkles,
              onClick: () => proposeFresh(fresh),
            },
          ]}
        />
      )}

      <Section id="clusters" icon={Layers} title="What it gets wrong" hint="Groups of similar lessons, worst first." count={data.clusters.length}>
        {data.clusters.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-700 p-5 text-sm text-slate-400" data-testid="agent-improvements-no-clusters">
            {counts.waiting_to_group > 0
              ? 'New lessons are being grouped. Refresh in a minute.'
              : 'Nothing to fix yet. Give a thumbs down with a correction on any of its answers in chat or on a run, and it shows up here.'}
            <div className="mt-2">
              <Link href={`/agents/${encodeURIComponent(agentId)}/chat`} className="text-cyan-300 hover:underline">Chat with the agent</Link>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {data.clusters.map((c) => <ClusterCard key={c.id} cluster={c} canManage={data.can_manage} onChanged={load} />)}
          </div>
        )}
      </Section>

      <Section id="cases" icon={FlaskConical} title="Suggested test cases" hint="Written from the lessons. Accepted cases run every time a fix is proven, so a fix cannot break what already works." count={data.suggested_cases.length}>
        {data.gate && (
          <GateToggle agentId={data.agent.id} gate={data.gate} canManage={data.can_manage} onChanged={(g) => setData((d) => (d ? { ...d, gate: g } : d))} />
        )}
        <SuggestedCases key={data.suggested_cases.map((c) => c.id).join(',')} cases={data.suggested_cases} canManage={data.can_manage} onChanged={load} />
      </Section>

      <Section id="proposals" icon={Wrench} title="Proposed fixes" hint="A fix is shown only after it is proven against the test cases and recent real inputs." count={data.proposals.length}>
        <ProposalList agentId={data.agent.id} proposals={data.proposals} focusId={focus} />
      </Section>

      <Section id="releases" icon={Rocket} title="Releases" hint="Approved fixes, watched against the old version and rolled back on their own if they do worse." count={data.releases.length}>
        {data.releases.length === 0 ? (
          <p className="rounded-xl border border-dashed border-slate-700 p-4 text-sm text-slate-400" data-testid="agent-improvements-no-releases">
            No releases yet. An approved fix shows here with its watch period.
          </p>
        ) : (
          <div className="space-y-3">
            {data.releases.map((p) => <ReleaseWatch key={p.id} proposal={p} />)}
          </div>
        )}
      </Section>
    </div>
  );
}
