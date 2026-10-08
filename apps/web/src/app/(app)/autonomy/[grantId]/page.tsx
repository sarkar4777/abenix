'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import {
  AlertTriangle, ArrowDown, ArrowLeft, ArrowRight, Beaker, ChevronDown, ChevronRight, FlaskConical, Gauge, Loader2,
  Pause, Play, Power, RefreshCw, Rocket, Scale, Target, TrendingUp, Milestone, MessageSquare, ClipboardCheck,
} from 'lucide-react';
import { usePageTitle } from '@/hooks/usePageTitle';
import { holds, useMyPermissions } from '@/lib/capabilities';
import { apiFetch } from '@/lib/api-client';
import { toast } from '@/stores/toastStore';
import ConfirmModal from '@/components/ui/ConfirmModal';
import Ladder from '@/components/autonomy/Ladder';
import LevelPill from '@/components/autonomy/LevelPill';
import RequirementList from '@/components/autonomy/RequirementList';
import TrackRecordChart from '@/components/autonomy/TrackRecordChart';
import TimelineAction from '@/components/autonomy/TimelineAction';
import SampleRunSummary from '@/components/autonomy/SampleRunSummary';
import PageHeader from '@/components/layout/PageHeader';
import NoAccess from '@/components/layout/NoAccess';
import NextSteps from '@/components/shared/NextSteps';
import { AUTONOMY_STEPS, AutonomyLevels } from '../AutonomyHow';
import {
  autonomyApi, daysSince, executionIdsOf, levelLabel, LEVELS, missingRequirements, POLICY_FIELDS, policyForm,
  policyFromForm, probeText, relTime, RUN_DONE, scopeText, STATUS_FILTERS, summarizeRuns, worldModelText,
  type ActionRow, type GrantDetail, type Requirement, type RunResult, type RunSummary, type TestResult,
} from '@/lib/autonomy';

type Part = 'outcome_probe' | 'world_model' | 'limits';
const POLL_MS = 5000;
const RUN_WATCH_MS = 4 * 60 * 1000;

export default function GrantPage() {
  const params = useParams<{ grantId: string }>();
  const grantId = String(params?.grantId || '');
  const { perms, loading: permLoading } = useMyPermissions();
  const caps = perms?.capabilities;
  const canView = holds(caps, 'autonomy.view');
  const canManage = holds(caps, 'autonomy.manage');
  const canGrant = holds(caps, 'autonomy.grant');
  const canReview = holds(caps, 'actions.review');

  const [grant, setGrant] = useState<GrantDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [loading, setLoading] = useState(true);

  const [status, setStatus] = useState('');
  const [actions, setActions] = useState<ActionRow[] | null>(null);
  const [actionsErr, setActionsErr] = useState<string | null>(null);
  const [nextBefore, setNextBefore] = useState<string | null>(null);
  const [moreLoading, setMoreLoading] = useState(false);

  const [promoteBusy, setPromoteBusy] = useState(false);
  const [promoteMsg, setPromoteMsg] = useState<{ tone: 'ok' | 'warn' | 'err'; text: string; href?: string; author?: boolean } | null>(null);
  const [selfApproval, setSelfApproval] = useState<{ approvalId: string; reason: string } | null>(null);
  const [selfBusy, setSelfBusy] = useState(false);
  const [repairBusy, setRepairBusy] = useState(false);
  const [notReady, setNotReady] = useState<Requirement[] | null>(null);

  const [demote, setDemote] = useState<null | 'demote' | 'off'>(null);
  const [demoteTo, setDemoteTo] = useState(1);
  const [reason, setReason] = useState('');
  const [demoteBusy, setDemoteBusy] = useState(false);
  const [demoteErr, setDemoteErr] = useState<string | null>(null);
  const [pauseBusy, setPauseBusy] = useState(false);

  const [tests, setTests] = useState<Partial<Record<Part, { busy: boolean; res?: TestResult; err?: string }>>>({});
  const [thresholds, setThresholds] = useState<Record<string, string> | null>(null);
  const [thresholdErrors, setThresholdErrors] = useState<Record<string, string>>({});
  const [thresholdBusy, setThresholdBusy] = useState(false);
  const [thresholdErr, setThresholdErr] = useState<string | null>(null);
  const [details, setDetails] = useState(false);

  const [runs, setRuns] = useState<string[]>([]);
  const [runBusy, setRunBusy] = useState(false);
  const [runErr, setRunErr] = useState<string | null>(null);
  const runStarted = useRef(0);
  const runIds = useRef<string[]>([]);
  const runResults = useRef<Record<string, RunResult>>({});
  const beforeIds = useRef<string[]>([]);
  const lastCount = useRef(1);
  const levelRef = useRef(0);
  const [summary, setSummary] = useState<RunSummary | null>(null);
  const [justEnrolled, setJustEnrolled] = useState(false);
  useEffect(() => {
    try {
      if (grantId && sessionStorage.getItem('autonomy.justEnrolled') === grantId) {
        sessionStorage.removeItem('autonomy.justEnrolled');
        setJustEnrolled(true);
      }
    } catch {
      // storage blocked, no next steps
    }
  }, [grantId]);

  usePageTitle(grant ? `${grant.action_type.label} · ${grant.agent.name}` : 'Autonomy');

  const loadGrant = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    const r = await autonomyApi.grant(grantId);
    setLoading(false);
    if (r.error) {
      if (r.status === 404) setNotFound(true);
      else if (!quiet) setError(r.error);
      return;
    }
    setError(null);
    setGrant(r.data);
    if (r.data) levelRef.current = r.data.level;
  }, [grantId]);

  const loadActions = useCallback(async (st: string) => {
    setActionsErr(null);
    const r = await autonomyApi.actions(grantId, { status: st || undefined, limit: 20 });
    if (r.error) { setActionsErr(r.error); return; }
    setActions(r.data?.items || []);
    setNextBefore(r.data?.next_before || null);
  }, [grantId]);

  useEffect(() => {
    if (permLoading) return;
    if (!canView) { setLoading(false); return; }
    loadGrant();
  }, [permLoading, canView, loadGrant]);

  useEffect(() => {
    if (!permLoading && canView) loadActions(status);
  }, [permLoading, canView, status, loadActions]);

  const finishRuns = useCallback(async (timedOut: boolean) => {
    setRuns([]);
    const r = await autonomyApi.actions(grantId, { limit: 200 });
    setSummary(summarizeRuns({
      runIds: runIds.current,
      results: runResults.current,
      beforeIds: beforeIds.current,
      after: r.data?.items || [],
      level: levelRef.current,
      timedOut,
    }));
  }, [grantId]);

  // live while sample runs are going
  useEffect(() => {
    if (runs.length === 0) return;
    let stopped = false;
    const t = setInterval(async () => {
      loadGrant(true);
      loadActions(status);
      const still: string[] = [];
      for (const id of runs) {
        if (id === 'pending') { still.push(id); continue; }
        const r = await apiFetch<{ status?: string; output_message?: string | null }>(`/api/executions/${encodeURIComponent(id)}`, { silent: true });
        const s = (r.data?.status || '').toLowerCase();
        if (RUN_DONE.includes(s)) runResults.current[id] = { id, status: s, output: r.data?.output_message };
        else still.push(id);
      }
      if (stopped) return;
      if (still.length === 0) { stopped = true; finishRuns(false); }
      else if (Date.now() - runStarted.current > RUN_WATCH_MS) { stopped = true; finishRuns(true); }
      else if (still.length !== runs.length) setRuns(still);
    }, POLL_MS);
    return () => { stopped = true; clearInterval(t); };
  }, [runs, status, loadGrant, loadActions, finishRuns]);

  async function runSample(count: number) {
    setRunBusy(true);
    setRunErr(null);
    setSummary(null);
    lastCount.current = count;
    const before = await autonomyApi.actions(grantId, { limit: 200 });
    beforeIds.current = (before.data?.items || []).map((a) => a.id);
    const r = await autonomyApi.sampleRun(count);
    setRunBusy(false);
    if (r.error) {
      setRunErr(r.status === 403 ? 'Running the sample needs the autonomy.manage permission.' : r.error);
      return;
    }
    const ids = executionIdsOf(r.data);
    runStarted.current = Date.now();
    runIds.current = ids;
    runResults.current = {};
    setRuns(ids.length ? ids : ['pending']);
    toast({ type: 'info', title: `Started ${count} sample run${count === 1 ? '' : 's'}`, message: 'New actions appear below as they come in.' });
  }

  function reviewHere(st: 'watching' | 'pending') {
    setStatus(st);
    try { document.querySelector('[data-testid="autonomy-timeline"]')?.scrollIntoView({ behavior: 'smooth' }); } catch { /* jsdom */ }
  }

  async function approveSelf() {
    if (!selfApproval) return;
    setSelfBusy(true);
    const r = await autonomyApi.approveSelf(selfApproval.approvalId);
    setSelfBusy(false);
    if (r.error) {
      setPromoteMsg({ tone: 'err', text: r.error, href: r.code === 'AUTHOR_CANNOT_GRANT' ? undefined : '/approvals', author: r.code === 'AUTHOR_CANNOT_GRANT' });
      setSelfApproval(null);
      return;
    }
    setSelfApproval(null);
    setPromoteMsg({ tone: 'ok', text: 'Approved and recorded as self-approved. The new level applies to the next action.' });
    toast({ type: 'success', title: 'Level raised', message: 'Recorded as self-approved in the history below.' });
    loadGrant(true);
  }

  // the sample setup is idempotent and republishes its limits
  async function repairSample() {
    setRepairBusy(true);
    const r = await autonomyApi.sample();
    setRepairBusy(false);
    if (r.error) {
      toast({ type: 'error', title: 'Could not repair the sample', message: r.error });
      return;
    }
    toast({ type: 'success', title: 'Sample repaired', message: 'Its limits are published again.' });
    loadGrant(true);
  }

  async function promote() {
    if (!grant) return;
    setPromoteBusy(true);
    setPromoteMsg(null);
    setNotReady(null);
    const r = await autonomyApi.promote(grant.id);
    setPromoteBusy(false);
    if (r.error) {
      if (r.code === 'AUTHOR_CANNOT_GRANT') {
        setPromoteMsg({ tone: 'warn', author: true, text: r.error || 'You built this agent, so someone else has to approve its promotion.' });
      } else if (r.code === 'NOT_READY') {
        const reqs = (r.details?.requirements as Requirement[] | undefined) || null;
        setNotReady(reqs);
        setPromoteMsg({ tone: 'warn', text: 'Not ready yet. The numbers changed since this page loaded.' });
        loadGrant(true);
      } else {
        setPromoteMsg({ tone: 'err', text: r.error });
      }
      return;
    }
    const selfReason = (r.data?.payload as { self_approval?: string } | undefined)?.self_approval;
    if (selfReason && r.data?.id) {
      setSelfApproval({ approvalId: String(r.data.id), reason: selfReason });
      return;
    }
    setPromoteMsg({ tone: 'ok', text: 'Sent for approval. Someone with the autonomy.grant permission who did not build this agent signs it off.', href: '/approvals' });
    toast({ type: 'success', title: 'Promotion sent for approval', message: `To ${levelLabel(grant.next?.next_level)}`, action: { label: 'Open in Approvals', href: '/approvals' } });
  }

  function openDemote(kind: 'demote' | 'off') {
    if (!grant) return;
    setDemote(kind);
    setDemoteTo(kind === 'off' ? 0 : Math.max(1, grant.level - 1));
    setReason('');
    setDemoteErr(null);
  }

  async function confirmDemote() {
    if (!grant || !demote || !reason.trim()) return;
    setDemoteBusy(true);
    setDemoteErr(null);
    const r = await autonomyApi.demote(grant.id, demote === 'off' ? 0 : demoteTo, reason.trim());
    setDemoteBusy(false);
    if (r.error) { setDemoteErr(r.error); return; }
    setDemote(null);
    toast({ type: 'success', title: demote === 'off' ? 'Turned off' : `Moved down to ${levelLabel(demoteTo)}` });
    loadGrant(true);
  }

  async function togglePause() {
    if (!grant) return;
    setPauseBusy(true);
    const r = await autonomyApi.patchGrant(grant.id, { state: grant.state === 'paused' ? 'active' : 'paused' });
    setPauseBusy(false);
    if (r.error) { toast({ type: 'error', title: 'Could not change it', message: r.error }); return; }
    loadGrant(true);
  }

  async function saveThresholds() {
    if (!grant || !thresholds) return;
    const { policy, errors } = policyFromForm(thresholds, grant.action_type.policy);
    setThresholdErrors(errors);
    if (Object.keys(errors).length) return;
    setThresholdBusy(true);
    setThresholdErr(null);
    const r = await autonomyApi.patchActionType(grant.action_type.id, { policy });
    setThresholdBusy(false);
    if (r.error) {
      setThresholdErr(r.status === 403 ? 'Changing thresholds needs the autonomy.manage permission.' : r.error);
      return;
    }
    setThresholds(null);
    toast({ type: 'success', title: 'Thresholds saved', message: 'The checklist above uses them now. The change is on the history.' });
    loadGrant(true);
  }

  async function runTest(part: Part) {
    if (!grant) return;
    setTests((t) => ({ ...t, [part]: { busy: true } }));
    const r = await autonomyApi.testActionType(grant.action_type.id, part);
    setTests((t) => ({ ...t, [part]: { busy: false, res: r.data || undefined, err: r.error || undefined } }));
  }

  if (!permLoading && !canView) {
    return (
      <NoAccess
        testId="autonomy-no-access"
        title="Autonomy"
        purpose="How far this agent may go on its own with this action, the evidence behind it, and every action it proposed or took. For the people who promote or hold it back."
        icon={Milestone}
        need={{ capability: 'autonomy.view', label: 'View autonomy' }}
        role={perms?.role}
        instead={{ text: 'Approvals lists any agent action waiting for a decision from you.', href: '/approvals', label: 'Open Approvals' }}
      />
    );
  }

  if (notFound) {
    return (
      <div className="mx-auto max-w-3xl p-6" data-testid="autonomy-grant-missing">
        <h1 className="text-xl font-semibold text-white">This action is not enrolled</h1>
        <p className="mt-2 text-sm text-slate-400">It may have been removed, or the link is wrong.</p>
        <Link href="/autonomy" className="mt-4 inline-flex items-center gap-1 text-sm text-cyan-300 hover:underline"><ArrowLeft className="h-4 w-4" /> Back to Autonomy</Link>
      </div>
    );
  }

  if (error && !grant) {
    return (
      <div className="mx-auto max-w-3xl p-6">
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200" role="alert" data-testid="autonomy-error">
          <AlertTriangle className="h-4 w-4" /> Could not load this action: {error}
          <button type="button" onClick={() => loadGrant()} className="ml-auto rounded border border-rose-500/40 px-2 py-1 text-xs">Try again</button>
        </div>
      </div>
    );
  }

  if (loading || !grant) {
    return (
      <div className="mx-auto max-w-6xl space-y-4" data-testid="autonomy-loading">
        <div className="h-8 w-64 animate-pulse rounded bg-slate-800" />
        <div className="h-24 animate-pulse rounded-xl bg-slate-800/50" />
        <div className="h-64 animate-pulse rounded-xl bg-slate-800/50" />
      </div>
    );
  }

  const at = grant.action_type;
  const next = grant.next || {};
  const nextLevel = typeof next.next_level === 'number' ? next.next_level : null;
  const missing = missingRequirements(next);
  const paused = grant.state === 'paused';

  const promoteBlockers: Array<{ text: string; href?: string; link?: string }> = [];
  if (!canGrant) promoteBlockers.push({ text: 'You need the autonomy.grant permission to promote.', href: '/admin/permissions', link: 'Permissions' });
  if (paused) promoteBlockers.push({ text: 'This action is paused. Resume it first.' });
  if (nextLevel === null) {
    promoteBlockers.push({
      text: next.blocked_by_ceiling
        ? `This agent's risk tier stops it at ${levelLabel(grant.ceiling ?? grant.level)}.`
        : 'This is already the highest level.',
      ...(next.blocked_by_ceiling ? { href: '/admin/risk', link: 'Risk and controls' } : {}),
    });
  } else if (!next.ready) {
    for (const r of missing) promoteBlockers.push({ text: r.label, href: r.fix?.href, link: r.fix?.label });
  }
  const canPromote = promoteBlockers.length === 0 && !promoteBusy;
  const demoteOptions = LEVELS.filter((l) => l.level >= 1 && l.level < grant.level);
  const days = daysSince(grant.level_since);
  const currentThresholds = policyForm(grant.policy || at.effective_policy);

  const settings: Array<{ part: Part; title: string; icon: typeof Target; text: string; extra?: React.ReactNode }> = [
    { part: 'outcome_probe', title: 'How we judge success', icon: Target, text: probeText(at.outcome_probe) },
    {
      part: 'world_model', title: 'How we predict', icon: TrendingUp, text: worldModelText(at.world_model),
      extra: typeof at.max_band_width === 'number' ? <p className="mt-1 text-xs text-slate-500">A band wider than {Math.round(at.max_band_width * 100)}% of the value counts as no prediction.</p> : null,
    },
    {
      part: 'limits', title: 'Hard limits', icon: Scale,
      text: at.limits_decision_key ? `Every call is checked against the rules in ${at.limits_decision_key}. A breach is blocked at any level.` : 'No hard limits are set. Kill switches still apply.',
      extra: at.limits_decision_key ? (
        <Link href={`/decisions/${encodeURIComponent(at.limits_decision_key)}`} className="mt-1 inline-flex items-center gap-1 text-xs text-cyan-300 hover:underline" data-testid="autonomy-limits-link">
          Open the limit rules <ArrowRight className="h-3 w-3" />
        </Link>
      ) : (
        <Link href="/decisions" className="mt-1 inline-flex items-center gap-1 text-xs text-cyan-300 hover:underline">Write limit rules in Decisions <ArrowRight className="h-3 w-3" /></Link>
      ),
    },
  ];

  return (
    <div className="mx-auto max-w-6xl space-y-6" data-testid="autonomy-grant-page" data-grant-id={grant.id}>
      <PageHeader
        title={at.label}
        purpose="How far this agent may go on its own with this action, the evidence behind it, and every action it proposed or took. For the people who promote or hold it back."
        icon={Milestone}
        storageKey="autonomy-grant"
        docSlug="08-howto/13-earned-autonomy"
        back={{ href: '/autonomy', label: 'Autonomy' }}
        steps={AUTONOMY_STEPS}
        howItWorks={<AutonomyLevels />}
        primaryAction={{
          label: 'Run the agent',
          href: `/agents/${grant.agent.id}/chat`,
          icon: MessageSquare,
          title: 'Each run adds to its track record',
        }}
        secondaryAction={
          <button
            type="button"
            disabled={!canManage || pauseBusy}
            title={canManage ? undefined : 'Needs the autonomy.manage permission'}
            onClick={togglePause}
            className="inline-flex items-center justify-center gap-1.5 rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
            data-testid="autonomy-pause"
          >
            {paused ? <Play className="h-4 w-4" /> : <Pause className="h-4 w-4" />} {paused ? 'Resume' : 'Pause'}
          </button>
        }
        extraActions={
          <>
            <button type="button" onClick={() => { loadGrant(true); loadActions(status); }} className="inline-flex items-center justify-center gap-1.5 rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:bg-slate-800" aria-label="Refresh">
              <RefreshCw className="h-4 w-4" />
            </button>
            <button
              type="button"
              disabled={!canManage || demoteOptions.length === 0}
              title={!canManage ? 'Needs the autonomy.manage permission' : demoteOptions.length === 0 ? 'Already at the lowest working level. Use Turn off to stop it.' : undefined}
              onClick={() => openDemote('demote')}
              className="inline-flex items-center justify-center gap-1.5 rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
              data-testid="autonomy-demote"
            >
              <ArrowDown className="h-4 w-4" /> Move down
            </button>
            <button
              type="button"
              disabled={!canManage || grant.level === 0}
              title={!canManage ? 'Needs the autonomy.manage permission' : grant.level === 0 ? 'It is already off' : undefined}
              onClick={() => openDemote('off')}
              className="inline-flex items-center justify-center gap-1.5 rounded-md border border-rose-500/40 px-3 py-2 text-sm text-rose-300 hover:bg-rose-500/10 disabled:cursor-not-allowed disabled:opacity-50"
              data-testid="autonomy-turn-off"
            >
              <Power className="h-4 w-4" /> Turn off
            </button>
          </>
        }
      >
        <p className="text-sm text-slate-400 break-words">
          <Link href={`/agents/${grant.agent.id}/info`} className="text-slate-300 hover:underline">{grant.agent.name}</Link>
          <span className="mx-1.5 text-slate-600">·</span>
          <span data-testid="autonomy-scope">{scopeText(grant.scope)}</span>
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <span data-testid="autonomy-grant-level" data-level={grant.level}><LevelPill level={grant.level} ceiling={grant.ceiling} testId="autonomy-grant-level-pill" /></span>
          {days !== null && <span className="text-xs text-slate-500">for {days} day{days === 1 ? '' : 's'}</span>}
          {paused && <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300" data-testid="autonomy-paused">Paused, acts as Asks first</span>}
          {grant.attention && <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-200">{grant.attention}</span>}
        </div>
        {!canManage && <p className="text-xs text-slate-500">Changing this needs autonomy.manage. <Link href="/admin/permissions" className="text-cyan-300 hover:underline">Permissions</Link></p>}
      </PageHeader>

      {justEnrolled && (
        <NextSteps
          title="Enrolled. It is watching now."
          onDismiss={() => setJustEnrolled(false)}
          testId="autonomy-next-steps"
          steps={[
            { id: 'run', label: 'Run the agent', hint: 'Each run gives it a chance to say what it would do.', icon: MessageSquare, href: `/agents/${grant.agent.id}/chat` },
            { id: 'reviews', label: 'Open reviews', hint: 'Agree or disagree with what it proposed. That is how it moves up.', icon: ClipboardCheck, href: '/approvals?tab=reviews' },
          ]}
        />
      )}

      {grant.limits_problem && (
        <div role="alert" className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200" data-testid="autonomy-limits-problem">
          {grant.limits_problem}{' '}
          {at.is_sample ? (
            <button onClick={repairSample} disabled={repairBusy} className="ml-1 rounded-md border border-rose-400/50 px-2 py-0.5 text-xs font-medium text-rose-100 hover:bg-rose-500/20 disabled:opacity-60" data-testid="autonomy-repair-sample">
              {repairBusy ? 'Repairing…' : 'Repair the sample'}
            </button>
          ) : at.limits_decision_key ? (
            <Link href={`/decisions/${encodeURIComponent(at.limits_decision_key)}`} className="underline">Open {at.limits_decision_key}</Link>
          ) : null}
        </div>
      )}

      {at.is_sample && (
        <section className="rounded-xl border border-violet-500/40 bg-violet-500/10 p-4" data-testid="autonomy-sample-banner">
          <div className="flex flex-col gap-3 md:flex-row md:items-center">
            <div className="min-w-0 flex-1">
              <p className="flex items-center gap-2 text-sm font-medium text-violet-100"><Beaker className="h-4 w-4" /> Sample plant</p>
              <p className="mt-1 text-xs text-violet-200/80">Sample thresholds are low so you can see the whole ladder in minutes. Run the agent, answer its reviews, then promote it.</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-violet-200">Run the sample agent</span>
              {[1, 3, 5].map((n) => (
                <button
                  key={n}
                  type="button"
                  disabled={!canManage || runBusy}
                  title={canManage ? `Start ${n} run${n === 1 ? '' : 's'}` : 'Needs the autonomy.manage permission'}
                  onClick={() => runSample(n)}
                  className="min-w-[44px] rounded-md bg-violet-500/30 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-500/50 disabled:cursor-not-allowed disabled:opacity-50"
                  data-testid={n === 1 ? 'autonomy-run-sample' : `autonomy-run-sample-${n}`}
                >
                  {n}×
                </button>
              ))}
            </div>
          </div>
          {runs.length > 0 && (
            <p className="mt-2 flex items-center gap-2 text-xs text-violet-100" data-testid="autonomy-run-status" aria-live="polite">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {runs[0] === 'pending' ? 'Runs started.' : `${runs.length} run${runs.length === 1 ? '' : 's'} in progress.`} New actions show below, checked every 5 seconds.
            </p>
          )}
          {runs.length === 0 && summary && (
            <SampleRunSummary
              summary={summary}
              canRun={canManage}
              runBusy={runBusy}
              onRunAgain={() => runSample(lastCount.current)}
              onReview={reviewHere}
            />
          )}
          {runErr && <p className="mt-2 text-xs text-rose-300" role="alert">{runErr}</p>}
          {grant.level === 1 && (
            <p className="mt-2 text-xs text-violet-200/80">
              While it watches, answer its proposals under <Link href="/approvals?tab=reviews" className="underline">Approvals, Watching reviews</Link>.
            </p>
          )}
        </section>
      )}

      <section className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-4">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-white">Ladder</h2>
        <Ladder level={grant.level} ceiling={grant.ceiling} />
      </section>

      <section className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-4" data-testid="autonomy-next-step">
        <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className="text-sm font-semibold text-white">
              {nextLevel === null ? 'No higher step' : `To move up to ${levelLabel(nextLevel)}`}
            </h2>
            <p className="mt-0.5 text-xs text-slate-400">
              {nextLevel === null
                ? next.blocked_by_ceiling ? `This agent's risk tier caps it at ${levelLabel(grant.ceiling ?? grant.level)}.` : 'It is at the top of the ladder.'
                : next.ready ? 'Every check is met. A person who did not build this agent approves the move.' : `${missing.length} check${missing.length === 1 ? '' : 's'} still to meet.`}
            </p>
          </div>
          {nextLevel !== null && (
            <div className="shrink-0">
              <button
                type="button"
                disabled={!canPromote}
                onClick={promote}
                title={promoteBlockers.length ? `Missing: ${promoteBlockers.map((b) => b.text).join('; ')}` : undefined}
                className="inline-flex w-full items-center justify-center gap-1.5 rounded-md bg-emerald-500 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400 sm:w-auto"
                data-testid="autonomy-promote"
              >
                {promoteBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />} Promote
              </button>
            </div>
          )}
        </div>
        <RequirementList requirements={notReady || next.requirements} />
        {promoteBlockers.length > 0 && nextLevel !== null && (
          <div className="mt-3 rounded-lg border border-slate-700 bg-slate-900/40 p-3 text-xs text-slate-400" data-testid="autonomy-promote-blockers">
            <p className="mb-1 font-medium text-slate-300">Promote is off because:</p>
            <ul className="list-disc space-y-0.5 pl-4">
              {promoteBlockers.map((b, i) => (
                <li key={i}>{b.text}{b.href && <> <Link href={b.href} className="text-cyan-300 hover:underline">{b.link || 'Fix it'}</Link></>}</li>
              ))}
            </ul>
          </div>
        )}
        {nextLevel === null && next.blocked_by_ceiling && (
          <p className="mt-3 text-xs text-slate-400">A ceiling comes from the agent's risk tier. <Link href="/admin/risk" className="text-cyan-300 hover:underline">Risk and controls</Link></p>
        )}
        {selfApproval && (
          <div className="mt-3 rounded-lg border border-cyan-500/40 bg-cyan-500/10 p-3 text-sm text-cyan-100" data-testid="autonomy-self-approval">
            <p>{selfApproval.reason}</p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <button
                onClick={approveSelf}
                disabled={selfBusy}
                className="rounded-lg bg-cyan-500 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-cyan-400 disabled:opacity-60"
                data-testid="autonomy-self-approve"
              >
                {selfBusy ? 'Approving…' : 'Approve now'}
              </button>
              <Link href="/approvals" className="text-xs underline">Leave it in Approvals for later</Link>
            </div>
          </div>
        )}
        {promoteMsg && (
          <div
            className={`mt-3 rounded-lg border p-3 text-sm ${promoteMsg.tone === 'ok' ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200' : promoteMsg.tone === 'warn' ? 'border-amber-500/40 bg-amber-500/10 text-amber-200' : 'border-rose-500/40 bg-rose-500/10 text-rose-200'}`}
            role={promoteMsg.tone === 'ok' ? 'status' : 'alert'}
            data-testid="autonomy-promote-message"
          >
            {promoteMsg.text}
            {promoteMsg.href && <> <Link href={promoteMsg.href} className="underline">Open in Approvals</Link></>}
            {promoteMsg.author && (
              <> <Link href="/settings/team" className="underline">See who can approve, or invite a teammate</Link></>
            )}
          </div>
        )}
      </section>

      <section className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-4">
        <h2 className="mb-1 text-sm font-semibold uppercase tracking-wider text-white">Track record</h2>
        <p className="mb-3 text-xs text-slate-400">
          {grant.stats?.scored ? `Held ${grant.stats.held ?? 0} of ${grant.stats.scored} scored actions` : 'No scored actions yet'}
          {typeof grant.stats?.reviews === 'number' && grant.stats.reviews > 0 ? `, ${grant.stats.agreement_pct ?? 0}% agreement over ${grant.stats.reviews} reviews` : ''}
          {grant.stats?.rejected ? `, ${grant.stats.rejected} rejected` : ''}
          {grant.stats?.unknown ? `, ${grant.stats.unknown} with no result` : ''}.
        </p>
        <TrackRecordChart points={grant.chart} metric={at.world_model?.metric || at.outcome_probe?.metric} />
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-white">Settings</h2>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {settings.map((s) => {
            const t = tests[s.part];
            return (
              <div key={s.part} className="flex flex-col rounded-xl border border-slate-700/50 bg-slate-800/30 p-4" data-testid={`autonomy-setting-${s.part}`}>
                <p className="flex items-center gap-2 text-sm font-medium text-white"><s.icon className="h-4 w-4 text-cyan-400" /> {s.title}</p>
                <p className="mt-2 text-sm text-slate-300">{s.text}</p>
                {s.extra}
                <div className="mt-auto pt-3">
                  <button
                    type="button"
                    disabled={t?.busy}
                    onClick={() => runTest(s.part)}
                    title="Runs it on the last real action and shows the answer"
                    className="inline-flex items-center gap-1.5 rounded-md border border-slate-600 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-700/50 disabled:opacity-50"
                    data-testid={`autonomy-test-${s.part}`}
                  >
                    {t?.busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FlaskConical className="h-3.5 w-3.5" />} Test
                  </button>
                  {t && !t.busy && (t.err || t.res) && (
                    <div className={`mt-2 rounded-md border p-2 text-xs ${t.err || t.res?.ok === false ? 'border-rose-500/40 bg-rose-500/10 text-rose-200' : 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'}`} data-testid={`autonomy-test-result-${s.part}`}>
                      {t.err || t.res?.message || (t.res?.ok ? 'It worked.' : 'It did not work.')}
                      {t.res?.result !== undefined && details && (
                        <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] text-slate-300">{JSON.stringify(t.res.result, null, 2)}</pre>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-4" data-testid="autonomy-thresholds">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <p className="flex items-center gap-2 text-sm font-medium text-white"><Gauge className="h-4 w-4 text-cyan-400" /> How fast it moves up</p>
            <p className="mt-1 text-xs text-slate-400">
              {at.policy ? 'This action has its own thresholds.' : 'This action uses the default thresholds for its risk tier.'}{' '}
              Lower numbers let it move up sooner. Every move up still needs a person who did not build the agent.
            </p>
          </div>
          {!thresholds && (
            <button
              type="button"
              disabled={!canManage}
              title={canManage ? undefined : 'Needs the autonomy.manage permission'}
              onClick={() => { setThresholds(policyForm(grant.policy || at.effective_policy)); setThresholdErrors({}); setThresholdErr(null); }}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-slate-600 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-700/50 disabled:cursor-not-allowed disabled:opacity-50"
              data-testid="autonomy-thresholds-edit"
            >
              Change thresholds
            </button>
          )}
        </div>
        {!thresholds ? (
          <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-1 text-xs sm:grid-cols-2" data-testid="autonomy-thresholds-summary">
            {POLICY_FIELDS.map((f) => {
              const v = currentThresholds[`${f.step}.${f.key}`];
              return (
                <div key={`${f.step}.${f.key}`} className="flex justify-between gap-3">
                  <dt className="text-slate-500">{f.step === 'to_asks_first' ? 'To Asks first' : 'To Acts within limits'}: {f.label.replace(' (%)', '')}</dt>
                  <dd className="text-slate-300">{v === '' ? 'not set' : f.kind === 'pct' ? `${v}%` : v}</dd>
                </div>
              );
            })}
          </dl>
        ) : (
          <div className="mt-3">
            {(['to_asks_first', 'to_within_limits'] as const).map((step) => (
              <fieldset key={step} className="mb-3">
                <legend className="mb-2 text-xs font-medium text-slate-300">{step === 'to_asks_first' ? 'Watching to Asks first' : 'Asks first to Acts within limits'}</legend>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  {POLICY_FIELDS.filter((f) => f.step === step).map((f) => {
                    const id = `${f.step}.${f.key}`;
                    return (
                      <div key={id}>
                        <label htmlFor={`thr-${id}`} className="mb-1 block text-[11px] text-slate-400">{f.label}</label>
                        <input
                          id={`thr-${id}`}
                          type="number"
                          inputMode="decimal"
                          min={f.min}
                          max={f.max}
                          step={f.kind === 'pct' ? 'any' : 1}
                          value={thresholds[id] ?? ''}
                          onChange={(e) => setThresholds((t) => ({ ...(t || {}), [id]: e.target.value }))}
                          className={`w-full rounded-md border bg-slate-950/60 px-2 py-1.5 text-sm text-white ${thresholdErrors[id] ? 'border-rose-500/60' : 'border-slate-700'}`}
                          aria-invalid={!!thresholdErrors[id]}
                          data-testid={`autonomy-threshold-${id}`}
                        />
                        {thresholdErrors[id] && <p className="mt-1 text-[11px] text-rose-300" role="alert">{thresholdErrors[id]}</p>}
                      </div>
                    );
                  })}
                </div>
              </fieldset>
            ))}
            {thresholdErr && <p className="mb-2 text-xs text-rose-300" role="alert" data-testid="autonomy-thresholds-error">{thresholdErr}</p>}
            <div className="flex flex-col gap-2 sm:flex-row">
              <button type="button" disabled={thresholdBusy} onClick={saveThresholds} className="inline-flex items-center justify-center gap-1.5 rounded-md bg-cyan-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-cyan-400 disabled:opacity-50" data-testid="autonomy-thresholds-save">
                {thresholdBusy && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Save thresholds
              </button>
              <button type="button" onClick={() => setThresholds(null)} className="rounded-md border border-slate-600 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-700/50">Cancel</button>
            </div>
          </div>
        )}
      </section>

      <section data-testid="autonomy-timeline">
        <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-white">Actions</h2>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by status">
            {STATUS_FILTERS.map((f) => (
              <button
                key={f.value || 'all'}
                type="button"
                onClick={() => setStatus(f.value)}
                aria-pressed={status === f.value}
                className={`rounded-full border px-2.5 py-1 text-xs ${status === f.value ? 'border-cyan-500/50 bg-cyan-500/15 text-cyan-200' : 'border-slate-700 text-slate-400 hover:text-white'}`}
                data-testid={`autonomy-filter-${f.value || 'all'}`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
        {actionsErr ? (
          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200" role="alert">
            <AlertTriangle className="h-4 w-4" /> Could not load actions: {actionsErr}
            <button type="button" onClick={() => loadActions(status)} className="ml-auto text-xs underline">Try again</button>
          </div>
        ) : actions === null ? (
          <div className="space-y-2">{[0, 1].map((i) => <div key={i} className="h-32 animate-pulse rounded-xl bg-slate-800/40" />)}</div>
        ) : actions.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-700 p-6 text-center text-sm text-slate-400" data-testid="autonomy-timeline-empty">
            {status ? 'No actions with this status.' : at.is_sample ? 'No actions yet. Run the sample agent above to see its first proposal.' : 'No actions yet. They show here the next time the agent takes this action.'}
          </div>
        ) : (
          <div className="space-y-3">
            {actions.map((a) => (
              <TimelineAction
                key={a.id}
                action={a}
                canFollowUp={canReview}
                onChanged={(row) => {
                  setActions((list) => (list || []).map((x) => (x.id === row.id ? { ...x, ...row } : x)));
                  loadGrant(true);
                }}
                onRefresh={() => { loadActions(status); loadGrant(true); }}
              />
            ))}
            {nextBefore && (
              <button
                type="button"
                disabled={moreLoading}
                onClick={async () => {
                  setMoreLoading(true);
                  const r = await autonomyApi.actions(grantId, { status: status || undefined, before: nextBefore, limit: 20 });
                  setMoreLoading(false);
                  if (r.error) { setActionsErr(r.error); return; }
                  setActions((list) => [...(list || []), ...(r.data?.items || [])]);
                  setNextBefore(r.data?.next_before || null);
                }}
                className="w-full rounded-lg border border-slate-700 py-2 text-sm text-slate-300 hover:bg-slate-800 disabled:opacity-50"
              >
                {moreLoading ? 'Loading' : 'Show older actions'}
              </button>
            )}
          </div>
        )}
      </section>

      <section className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-4" data-testid="autonomy-history">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-white">History</h2>
        {(grant.changes || []).length === 0 ? (
          <p className="text-sm text-slate-400">No level changes yet. It was enrolled at Watching.</p>
        ) : (
          <ul className="space-y-2">
            {(grant.changes || []).map((c, i) => (
              <li key={c.id || i} className="text-sm text-slate-300">
                {c.to_level === c.from_level ? (
                  <span className="text-slate-200">Settings changed at {levelLabel(c.to_level)}</span>
                ) : (
                  <span className={c.to_level > c.from_level ? 'text-emerald-300' : 'text-rose-300'}>
                    {c.to_level > c.from_level ? 'Moved up' : 'Moved down'} from {levelLabel(c.from_level)} to {levelLabel(c.to_level)}
                  </span>
                )}
                <span className="text-slate-500"> · {c.actor_type === 'system' ? 'automatically' : c.actor_name ? `by ${c.actor_name}` : 'by a person'} · {relTime(c.created_at)}</span>
                {c.reason && <p className="text-xs text-slate-400">{c.reason}</p>}
                {details && c.evidence && <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950/60 p-2 font-mono text-[10px] text-slate-400">{JSON.stringify(c.evidence, null, 2)}</pre>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <button type="button" onClick={() => setDetails((d) => !d)} className="flex items-center gap-1 text-xs text-slate-400 hover:text-white" data-testid="autonomy-details-toggle" aria-expanded={details}>
          {details ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />} Details
        </button>
        {details && (
          <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 rounded-xl border border-slate-800 bg-slate-900/40 p-4 text-xs sm:grid-cols-2" data-testid="autonomy-details">
            <div><dt className="inline text-slate-500">Grant id </dt><dd className="inline break-all font-mono text-slate-300">{grant.id}</dd></div>
            <div><dt className="inline text-slate-500">Action type </dt><dd className="inline break-all font-mono text-slate-300">{at.key}</dd></div>
            <div><dt className="inline text-slate-500">Tool </dt><dd className="inline font-mono text-slate-300">{at.tool_name || 'not set'}</dd></div>
            <div><dt className="inline text-slate-500">Agent config hash </dt><dd className="inline break-all font-mono text-slate-300">{grant.agent_config_hash || 'not recorded'}</dd></div>
            <div><dt className="inline text-slate-500">Accuracy, Wilson 95% lower bound </dt><dd className="inline text-slate-300">{typeof grant.stats?.accuracy_lb_pct === 'number' ? `${grant.stats.accuracy_lb_pct}%` : 'not enough data'}</dd></div>
            <div><dt className="inline text-slate-500">Ceiling </dt><dd className="inline text-slate-300">{levelLabel(grant.ceiling ?? 4)}</dd></div>
            <div className="sm:col-span-2"><dt className="text-slate-500">Stats</dt><dd><pre className="mt-1 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] text-slate-400">{JSON.stringify(grant.stats || {}, null, 2)}</pre></dd></div>
            {at.policy && <div className="sm:col-span-2"><dt className="text-slate-500">Thresholds</dt><dd><pre className="mt-1 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] text-slate-400">{JSON.stringify(at.policy, null, 2)}</pre></dd></div>}
          </dl>
        )}
      </section>

      <ConfirmModal
        open={demote !== null}
        onClose={() => setDemote(null)}
        onConfirm={confirmDemote}
        title={demote === 'off' ? 'Turn this action off?' : 'Move this action down?'}
        description={demote === 'off'
          ? `${grant.agent.name} will not be able to ${at.label.charAt(0).toLowerCase() + at.label.slice(1)} at all. Its record is kept. This takes effect at once and needs no approval.`
          : 'This takes effect at once and needs no approval. Moving back up needs the checks again and a sign-off.'}
        confirmLabel={demote === 'off' ? 'Turn off' : 'Move down'}
        variant={demote === 'off' ? 'danger' : 'warning'}
        loading={demoteBusy}
        confirmDisabled={!reason.trim()}
        confirmTestId="autonomy-demote-confirm"
        icon={demote === 'off' ? Power : ArrowDown}
      >
        {demote === 'demote' && (
          <div className="mb-3">
            <label htmlFor="demote-to" className="text-xs font-medium text-slate-300">Move down to</label>
            <select id="demote-to" value={demoteTo} onChange={(e) => setDemoteTo(Number(e.target.value))} className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950/60 px-2 py-1.5 text-sm text-white" data-testid="autonomy-demote-to">
              {demoteOptions.map((l) => <option key={l.level} value={l.level}>{l.label}</option>)}
            </select>
          </div>
        )}
        <label htmlFor="demote-reason" className="text-xs font-medium text-slate-300">Reason</label>
        <textarea id="demote-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Kept on the record and shown to the owners" className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950/60 px-2 py-1.5 text-sm text-white" data-testid="autonomy-demote-reason" />
        {!reason.trim() && <p className="mt-1 text-[11px] text-slate-500">A reason is needed.</p>}
        {demoteErr && <p className="mt-1 text-xs text-rose-300" role="alert">{demoteErr}</p>}
      </ConfirmModal>
    </div>
  );
}
