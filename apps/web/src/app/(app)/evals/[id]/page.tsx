'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDashed,
  Cpu,
  FlaskConical,
  History,
  GitCompare,
  Loader2,
  Lock,
  Play,
  Plus,
  Save,
  Square,
  Trash2,
  X,
  XCircle,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useApi } from '@/hooks/useApi';
import { holds, useMyPermissions } from '@/lib/capabilities';
import { TIER_STYLE } from '@/components/governance/TierPolicies';
import ConfirmModal from '@/components/ui/ConfirmModal';
import PageHeader from '@/components/layout/PageHeader';
import NextSteps, { type NextStep } from '@/components/shared/NextSteps';
import AssertionBuilder, { ModelSelect, describe, useAssertionCatalog } from '@/components/evals/AssertionBuilder';
import RunsChart from '@/components/evals/RunsChart';
import {
  SCHEDULES,
  TRIGGER_LABEL,
  ago,
  pct,
  runVerdict,
  shortHash,
  type Assertion,
  type EvalCase,
  type EvalRun,
  type SuiteDetail,
  type Tier,
} from '@/lib/evals';

type Tab = 'cases' | 'runs' | 'settings';

export default function SuitePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { perms } = useMyPermissions();
  const canManage = holds(perms?.capabilities, 'evals.manage');
  const canRun = holds(perms?.capabilities, 'evals.run');
  const [tab, setTab] = useState<Tab>('cases');
  const [poll, setPoll] = useState(false);
  const { data: suite, error, isLoading, mutate } = useApi<SuiteDetail>(id ? `/api/evals/suites/${id}` : null, {
    refreshInterval: poll ? 3000 : 0,
  });
  const active = suite?.runs.find((r) => r.status === 'queued' || r.status === 'running') || null;
  useEffect(() => setPoll(!!active), [active]);
  const [runErr, setRunErr] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [modelDialog, setModelDialog] = useState(false);
  const [adding, setAdding] = useState(false);
  const [firstCase, setFirstCase] = useState(false);
  const [nextHidden, setNextHidden] = useState(false);

  async function runNow(model?: string) {
    setStarting(true);
    setRunErr(null);
    const r = await apiFetch<EvalRun>(`/api/evals/suites/${id}/run`, {
      method: 'POST',
      body: JSON.stringify({ model: model || null }),
      throwOnError: false,
    });
    setStarting(false);
    if (r.error || !r.data) return setRunErr(r.error || 'The run could not start.');
    setModelDialog(false);
    setPoll(true);
    mutate();
    if (model) router.push(`/evals/runs/${r.data.id}`);
  }

  async function cancel(runId: string) {
    await apiFetch(`/api/evals/runs/${runId}/cancel`, { method: 'POST', throwOnError: false });
    mutate();
  }

  if (error) return <div className="max-w-6xl mx-auto px-6 py-8"><div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-200">{error}</div></div>;
  if (isLoading || !suite) return <div className="max-w-6xl mx-auto px-6 py-8 space-y-3">{[0, 1, 2].map((i) => <div key={i} className="h-20 rounded-xl bg-slate-800/40 animate-pulse" />)}</div>;

  const tier = (suite.agent?.risk_tier || 'low') as Tier;
  const lastBaseline = suite.runs.find((r) => r.status === 'completed' && !r.model_override) || null;
  const stale = !!(lastBaseline && suite.current_config_hash && lastBaseline.config_hash !== suite.current_config_hash);
  const fresh = suite.cases.length === 0 && suite.runs.length === 0 && !!suite.created_at && Date.now() - new Date(suite.created_at).getTime() < 15 * 60 * 1000;
  const openAdd = () => { setTab('cases'); setAdding(true); };
  const pastRuns = suite.agent ? `/executions?agent=${suite.agent.id}&status=completed` : '/executions?status=completed';
  let nextSteps: { title: string; steps: NextStep[] } | null = null;
  if (!nextHidden && canManage && firstCase && suite.cases.length > 0 && suite.runs.length === 0) {
    nextSteps = {
      title: 'First case saved. What next?',
      steps: [
        ...(canRun ? [{ id: 'run', label: 'Run the suite', hint: 'Score the agent on this case now.', icon: Play, onClick: () => runNow() }] : []),
        { id: 'add-case', label: 'Add another case', hint: 'A few cases cover more of what the agent should do.', icon: Plus, onClick: openAdd },
        { id: 'from-run', label: 'Save a past run', hint: 'Open a good run and choose Save as eval case.', icon: History, href: pastRuns },
      ],
    };
  } else if (!nextHidden && canManage && fresh) {
    nextSteps = {
      title: 'Suite created. Add its first cases.',
      steps: [
        { id: 'add-case', label: 'Write a case', hint: 'One input and the checks its answer must pass.', icon: Plus, onClick: openAdd },
        { id: 'from-run', label: 'Save a past run', hint: 'Open a good run and choose Save as eval case.', icon: History, href: pastRuns },
      ],
    };
  }

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <PageHeader
        className="mb-5"
        title={suite.name}
        titleTestId="eval-suite-title"
        purpose="The golden cases one agent must keep passing, with every run of them and how it scored. For the people who own that agent."
        icon={FlaskConical}
        storageKey="eval-suite"
        docSlug="08-howto/10-evals"
        back={{ href: '/evals', label: 'Evaluations' }}
        meta={suite.gating ? <span className="inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded border border-amber-500/30 text-amber-300 bg-amber-500/10"><Lock className="w-3 h-3" /> Gates publishing</span> : null}
        primaryAction={canRun ? {
          label: 'Run now',
          onClick: () => runNow(),
          icon: starting ? Loader2 : Play,
          busy: starting,
          disabled: !!active || suite.cases.length === 0,
          title: suite.cases.length === 0 ? 'Add a case first' : undefined,
          testId: 'eval-run-now',
        } : undefined}
        secondaryAction={canRun && suite.agent?.kind === 'agent' ? {
          label: 'Try another model',
          onClick: () => setModelDialog(true),
          icon: Cpu,
          disabled: suite.cases.length === 0,
          testId: 'eval-compare-model',
        } : undefined}
        steps={[
          'A case is one input plus the checks its answer must pass. Add them by hand or save a past run as a case.',
          'Run now executes every case for real against the current version and scores it.',
          'Try another model reruns the same cases on a different model so you can compare.',
          'If the suite gates publishing, a new version can only go live once it passes.',
        ]}
      >
        <div className="flex flex-wrap items-center gap-2 text-sm text-slate-400">
          {suite.agent ? (
            <Link href={`/agents/${suite.agent.id}/info`} className="hover:text-white">{suite.agent.kind === 'pipeline' ? 'Pipeline' : 'Agent'} {suite.agent.name}</Link>
          ) : (
            <span>Agent deleted</span>
          )}
          <span className={`text-[11px] px-1.5 py-0.5 rounded border ${TIER_STYLE[tier].chip}`}>{TIER_STYLE[tier].label} risk</span>
          {suite.agent?.kind === 'agent' && <span className="text-xs font-mono text-slate-500 break-all">{suite.agent.model}</span>}
          <span className="text-xs text-slate-500">pass at {pct(suite.pass_threshold)}</span>
        </div>
        {suite.description && <p className="text-sm text-slate-400 max-w-3xl break-words">{suite.description}</p>}
      </PageHeader>
      {nextSteps && (
        <NextSteps
          className="mb-5"
          title={nextSteps.title}
          steps={nextSteps.steps}
          onDismiss={() => setNextHidden(true)}
          testId="eval-next-steps"
        />
      )}
      {runErr && <p className="mb-4 text-sm text-rose-300" role="alert">{runErr}</p>}

      {active && (
        <div className="mb-4 rounded-xl border border-sky-500/30 bg-sky-500/5 p-4 flex flex-wrap items-center gap-3" data-testid="eval-active-run">
          <Loader2 className="w-4 h-4 text-sky-300 animate-spin" />
          <div className="flex-1 min-w-0 text-sm text-sky-100">
            {active.status === 'queued' ? 'Starting' : 'Running'} {active.total} case{active.total === 1 ? '' : 's'}
            {active.model_override ? ` on ${active.model}` : ''}. Each one is a real run of the {suite.agent?.kind || 'agent'}, recorded under Executions.
          </div>
          <Link href={`/evals/runs/${active.id}`} className="text-sm text-sky-300 hover:underline">Watch</Link>
          <button type="button" onClick={() => cancel(active.id)} className="inline-flex items-center gap-1 text-sm text-slate-300 hover:text-white"><Square className="w-3.5 h-3.5" /> Stop</button>
        </div>
      )}

      <GateBanner suite={suite} stale={stale} onRun={() => runNow()} canRun={canRun && !active && suite.cases.length > 0} />

      <div className="flex items-center gap-1 border-b border-slate-800 mb-5" role="tablist">
        {(
          [
            ['cases', `Cases (${suite.cases.length})`],
            ['runs', `Runs (${suite.runs.length})`],
            ['settings', 'Settings'],
          ] as [Tab, string][]
        ).map(([t, label]) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className={`px-4 py-2 text-sm -mb-px border-b-2 ${tab === t ? 'border-cyan-400 text-white' : 'border-transparent text-slate-400 hover:text-white'}`} data-testid={`eval-tab-${t}`}>
            {label}
          </button>
        ))}
      </div>

      {tab === 'cases' && <CasesTab suite={suite} canManage={canManage} onChanged={mutate} adding={adding} setAdding={setAdding} onAdded={() => { if (suite.cases.length === 0) setFirstCase(true); }} />}
      {tab === 'runs' && <RunsTab suite={suite} />}
      {tab === 'settings' && <SettingsTab suite={suite} canManage={canManage} onChanged={mutate} />}

      {modelDialog && <ModelDialog current={suite.agent?.model || ''} busy={starting} err={runErr} onClose={() => setModelDialog(false)} onRun={(m) => runNow(m)} />}
    </div>
  );
}

function GateBanner({ suite, stale, onRun, canRun }: { suite: SuiteDetail; stale: boolean; onRun: () => void; canRun: boolean }) {
  const gate = suite.gate;
  if (!suite.gating) {
    return stale ? (
      <div className="mb-5 rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-3 text-sm text-slate-300 flex items-center gap-2">
        <AlertTriangle className="w-4 h-4 text-amber-300" /> The agent changed since the last run. Run again to see how this version does.
      </div>
    ) : null;
  }
  const mine = gate?.suites.find((s) => s.suite_id === suite.id);
  if (!gate || !gate.required) {
    return (
      <div className="mb-5 rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-3 text-sm text-slate-300" data-testid="eval-gate-banner">
        This suite is marked as a gate, but the {suite.agent?.risk_tier || 'low'} risk policy does not require passing evaluations to publish. An admin can turn that on under{' '}
        <Link href="/admin/risk" className="text-cyan-300 hover:underline">Risk &amp; Controls</Link>.
      </div>
    );
  }
  const state = mine?.state || 'not_run';
  const style =
    state === 'passed' ? 'border-emerald-500/30 bg-emerald-500/5 text-emerald-100' : state === 'failed' ? 'border-rose-500/30 bg-rose-500/5 text-rose-100' : 'border-amber-500/30 bg-amber-500/5 text-amber-100';
  return (
    <div className={`mb-5 rounded-xl border px-4 py-3 text-sm flex flex-wrap items-center gap-3 ${style}`} data-testid="eval-gate-banner" data-state={state}>
      {state === 'passed' ? <CheckCircle2 className="w-4 h-4 text-emerald-300" /> : state === 'failed' ? <XCircle className="w-4 h-4 text-rose-300" /> : <Lock className="w-4 h-4 text-amber-300" />}
      <div className="flex-1 min-w-0">
        {state === 'passed' && <>This version (config {shortHash(suite.current_config_hash)}) passed with {pct(mine?.score)}. It can be published.</>}
        {state === 'failed' && (
          <>
            This version scored {pct(mine?.score)}, below {pct(suite.pass_threshold)}, so publishing is blocked.
            {mine && mine.failing_cases.length > 0 && <> Failing: {mine.failing_cases.slice(0, 5).join(', ')}{mine.failing_cases.length > 5 ? ` and ${mine.failing_cases.length - 5} more` : ''}.</>}
          </>
        )}
        {state === 'not_run' && <>Publishing is blocked until this suite passes against the current version (config {shortHash(suite.current_config_hash)}).</>}
      </div>
      {state !== 'passed' && canRun && (
        <button type="button" onClick={onRun} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-white/10 hover:bg-white/20" data-testid="eval-gate-run">
          <Play className="w-3.5 h-3.5" /> Run the suite now
        </button>
      )}
    </div>
  );
}

function CasesTab({ suite, canManage, onChanged, adding, setAdding, onAdded }: { suite: SuiteDetail; canManage: boolean; onChanged: () => void; adding: boolean; setAdding: (v: boolean) => void; onAdded: () => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const catalog = useAssertionCatalog();
  return (
    <div className="space-y-3" data-testid="eval-cases">
      {canManage && !adding && (
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" onClick={() => setAdding(true)} className="inline-flex items-center gap-1.5 px-3 py-2 rounded-md text-sm text-cyan-300 border border-cyan-500/30 hover:bg-cyan-500/10" data-testid="eval-add-case">
            <Plus className="w-4 h-4" /> Add case
          </button>
          <span className="text-xs text-slate-500">Or open any run under <Link href="/executions" className="text-cyan-300 hover:underline">Executions</Link> and choose Save as eval case.</span>
        </div>
      )}
      {adding && (
        <div className="rounded-xl border border-cyan-500/30 bg-slate-900/60 p-4">
          <CaseEditor suiteId={suite.id} onDone={() => { setAdding(false); onAdded(); onChanged(); }} onCancel={() => setAdding(false)} />
        </div>
      )}
      {suite.cases.length === 0 && !adding && (
        <p className="text-sm text-slate-500 rounded-xl border border-dashed border-slate-700 p-6 text-center">No cases yet. A case is one input with the checks its answer must pass.</p>
      )}
      {suite.cases.map((c) => {
        const isOpen = open === c.id;
        const lr = c.last_result;
        return (
          <div key={c.id} className="rounded-xl border border-slate-800 bg-slate-900/50" data-testid={`eval-case-${c.id}`}>
            <button type="button" onClick={() => setOpen(isOpen ? null : c.id)} className="w-full flex items-start gap-3 px-4 py-3 text-left" aria-expanded={isOpen}>
              {isOpen ? <ChevronDown className="w-4 h-4 text-slate-500 mt-0.5" /> : <ChevronRight className="w-4 h-4 text-slate-500 mt-0.5" />}
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-white">{c.name}</span>
                  {c.weight !== 1 && <span className="text-[11px] text-slate-500">weight {c.weight}</span>}
                  {c.tags.map((t) => <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">{t}</span>)}
                </div>
                <div className="text-xs text-slate-500 truncate mt-0.5">{c.input_message || 'No input'}</div>
                {!isOpen && c.assertions.length > 0 && (
                  <div className="text-[11px] text-slate-400 mt-1 truncate">{c.assertions.map((a) => describe(a, catalog?.types)).join(' · ')}</div>
                )}
              </div>
              {lr ? (
                lr.passed ? <span className="inline-flex items-center gap-1 text-xs text-emerald-300"><CheckCircle2 className="w-3.5 h-3.5" /> Passed last run</span> : <span className="inline-flex items-center gap-1 text-xs text-rose-300"><XCircle className="w-3.5 h-3.5" /> {lr.status === 'error' ? 'Did not run' : 'Failed last run'}</span>
              ) : (
                <span className="inline-flex items-center gap-1 text-xs text-slate-500"><CircleDashed className="w-3.5 h-3.5" /> Not run</span>
              )}
            </button>
            {isOpen && (
              <div className="border-t border-slate-800 px-4 py-4">
                <CaseEditor suiteId={suite.id} existing={c} readOnly={!canManage} onDone={() => { setOpen(null); onChanged(); }} onCancel={() => setOpen(null)} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function CaseEditor({ suiteId, existing, readOnly, onDone, onCancel }: { suiteId: string; existing?: EvalCase; readOnly?: boolean; onDone: () => void; onCancel: () => void }) {
  const [name, setName] = useState(existing?.name || '');
  const [input, setInput] = useState(existing?.input_message || '');
  const [ctxText, setCtxText] = useState(existing && Object.keys(existing.context || {}).length ? JSON.stringify(existing.context, null, 2) : '');
  const [weight, setWeight] = useState(existing?.weight ?? 1);
  const [tags, setTags] = useState((existing?.tags || []).join(', '));
  const [assertions, setAssertions] = useState<Assertion[]>(existing?.assertions || []);
  const [sample, setSample] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const ctx = useMemo(() => {
    if (!ctxText.trim()) return { ok: true, value: {} as Record<string, any> };
    try {
      const v = JSON.parse(ctxText);
      return v && typeof v === 'object' && !Array.isArray(v) ? { ok: true, value: v } : { ok: false, value: {}, msg: 'Context must be a JSON object.' };
    } catch (e: any) {
      return { ok: false, value: {}, msg: `Not valid JSON: ${e.message}` };
    }
  }, [ctxText]);

  async function save() {
    setBusy(true);
    setErr(null);
    const body = {
      name: name.trim(),
      input_message: input,
      context: ctx.value,
      weight,
      tags: tags.split(',').map((t) => t.trim()).filter(Boolean),
      assertions,
    };
    const r = existing
      ? await apiFetch(`/api/evals/cases/${existing.id}`, { method: 'PATCH', body: JSON.stringify(body), throwOnError: false })
      : await apiFetch(`/api/evals/suites/${suiteId}/cases`, { method: 'POST', body: JSON.stringify(body), throwOnError: false });
    setBusy(false);
    if (r.error) return setErr(r.error);
    onDone();
  }

  async function remove() {
    if (!existing) return;
    setBusy(true);
    await apiFetch(`/api/evals/cases/${existing.id}`, { method: 'DELETE', throwOnError: false });
    setBusy(false);
    setConfirmDelete(false);
    onDone();
  }

  return (
    <div className="space-y-4" data-testid="eval-case-editor">
      <div className="grid gap-4 md:grid-cols-[1fr_8rem]">
        <div>
          <label htmlFor="ec-name" className="block text-sm font-medium text-slate-200 mb-1.5">Case name</label>
          <input id="ec-name" value={name} onChange={(e) => setName(e.target.value)} disabled={readOnly} placeholder="Sanctioned counterparty is refused" className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white" data-testid="eval-case-name" />
        </div>
        <div>
          <label htmlFor="ec-weight" className="block text-sm font-medium text-slate-200 mb-1.5">Weight</label>
          <input id="ec-weight" type="number" min={0} max={100} step={0.5} value={weight} onChange={(e) => setWeight(Number(e.target.value))} disabled={readOnly} className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white" />
        </div>
      </div>
      <div>
        <label htmlFor="ec-input" className="block text-sm font-medium text-slate-200 mb-1.5">Input message</label>
        <textarea id="ec-input" value={input} onChange={(e) => setInput(e.target.value)} disabled={readOnly} rows={3} placeholder="What the agent is asked" className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white" data-testid="eval-case-input" />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <label htmlFor="ec-ctx" className="block text-sm font-medium text-slate-200 mb-1.5">Context <span className="text-slate-500 font-normal">optional JSON, the run&apos;s input variables</span></label>
          <textarea id="ec-ctx" value={ctxText} onChange={(e) => setCtxText(e.target.value)} disabled={readOnly} rows={3} spellCheck={false} placeholder='{"region": "EU"}' className={`w-full bg-slate-950 border rounded-md px-3 py-2 text-xs font-mono text-slate-200 ${ctx.ok ? 'border-slate-700' : 'border-rose-500/60'}`} />
          {!ctx.ok && <p className="mt-1 text-xs text-rose-300">{(ctx as any).msg}</p>}
        </div>
        <div>
          <label htmlFor="ec-tags" className="block text-sm font-medium text-slate-200 mb-1.5">Tags <span className="text-slate-500 font-normal">comma separated</span></label>
          <input id="ec-tags" value={tags} onChange={(e) => setTags(e.target.value)} disabled={readOnly} placeholder="edge-case, sanctions" className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white" />
          {existing?.source_execution_id && (
            <p className="mt-2 text-xs text-slate-500">Captured from <Link href={`/executions/${existing.source_execution_id}`} className="text-cyan-300 hover:underline font-mono">{existing.source_execution_id.slice(0, 8)}</Link></p>
          )}
        </div>
      </div>
      {!existing && (
        <details className="rounded-lg border border-slate-800 px-3 py-2">
          <summary className="text-xs text-slate-400 cursor-pointer">Try the assertions on a sample answer before the first run</summary>
          <textarea value={sample} onChange={(e) => setSample(e.target.value)} rows={4} spellCheck={false} placeholder='{"decision": "refuse", "reason": "..."}' className="mt-2 w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-xs font-mono text-slate-200" data-testid="eval-case-sample" />
        </details>
      )}
      <AssertionBuilder value={assertions} onChange={setAssertions} caseId={existing?.id} output={existing ? null : sample || null} disabled={readOnly} />
      {existing?.reference_output && (
        <details className="rounded-lg border border-slate-800 px-3 py-2">
          <summary className="text-xs text-slate-400 cursor-pointer">Answer of the run this case was captured from</summary>
          <pre className="mt-2 max-h-60 overflow-auto text-xs text-slate-300 whitespace-pre-wrap">{existing.reference_output}</pre>
        </details>
      )}
      {err && <p className="text-sm text-rose-300" role="alert">{err}</p>}
      {!readOnly && (
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={save} disabled={busy || !name.trim() || !ctx.ok} className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400 disabled:opacity-40" data-testid="eval-case-save">
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />} {existing ? 'Save case' : 'Add case'}
          </button>
          <button type="button" onClick={onCancel} className="px-4 py-2 rounded-md text-sm text-slate-300 hover:bg-slate-800">Cancel</button>
          {existing && (
            <button type="button" onClick={() => setConfirmDelete(true)} className="ml-auto inline-flex items-center gap-1.5 px-3 py-2 rounded-md text-sm text-rose-300 hover:bg-rose-500/10">
              <Trash2 className="w-4 h-4" /> Delete
            </button>
          )}
        </div>
      )}
      <ConfirmModal open={confirmDelete} onClose={() => setConfirmDelete(false)} onConfirm={remove} title="Delete this case?" description="Past run results keep its name, but later runs no longer include it." confirmLabel="Delete case" variant="danger" loading={busy} />
    </div>
  );
}

function RunsTab({ suite }: { suite: SuiteDetail }) {
  const router = useRouter();
  const [picked, setPicked] = useState<string[]>([]);
  const toggle = (rid: string) => setPicked((p) => (p.includes(rid) ? p.filter((x) => x !== rid) : [...p.slice(-1), rid]));
  return (
    <div className="space-y-5" id="runs">
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <div className="text-sm font-medium text-white mb-2">Score per run</div>
        <RunsChart runs={suite.runs} threshold={suite.pass_threshold} />
      </div>
      {suite.runs.length === 0 ? (
        <p className="text-sm text-slate-500">No runs yet.</p>
      ) : (
        <>
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-slate-500">Tick two runs to compare them side by side.</p>
            <button type="button" disabled={picked.length !== 2} onClick={() => router.push(`/evals/compare?a=${picked[0]}&b=${picked[1]}`)} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs text-slate-200 border border-slate-700 hover:bg-slate-800 disabled:opacity-40" data-testid="eval-compare-runs">
              <GitCompare className="w-3.5 h-3.5" /> Compare
            </button>
          </div>
          <div className="overflow-x-auto rounded-xl border border-slate-800">
            <table className="w-full text-sm" data-testid="eval-runs-table">
              <thead className="bg-slate-900/80 text-xs text-slate-400">
                <tr>
                  <th className="px-3 py-2 w-8"><span className="sr-only">Compare</span></th>
                  <th className="px-3 py-2 text-left font-medium">When</th>
                  <th className="px-3 py-2 text-left font-medium">Result</th>
                  <th className="px-3 py-2 text-right font-medium">Score</th>
                  <th className="px-3 py-2 text-right font-medium">Cases</th>
                  <th className="px-3 py-2 text-left font-medium">Model</th>
                  <th className="px-3 py-2 text-left font-medium">Version</th>
                  <th className="px-3 py-2 text-right font-medium">Cost</th>
                </tr>
              </thead>
              <tbody>
                {suite.runs.map((r) => {
                  const v = runVerdict(r);
                  return (
                    <tr key={r.id} className="border-t border-slate-800 hover:bg-slate-800/30">
                      <td className="px-3 py-2"><input type="checkbox" checked={picked.includes(r.id)} onChange={() => toggle(r.id)} className="accent-cyan-500" aria-label="Pick for comparison" /></td>
                      <td className="px-3 py-2">
                        <Link href={`/evals/runs/${r.id}`} className="text-cyan-300 hover:underline">{ago(r.created_at)}</Link>
                        <div className="text-[11px] text-slate-500">{TRIGGER_LABEL[r.triggered_by]}</div>
                      </td>
                      <td className="px-3 py-2"><span className={`text-[11px] px-1.5 py-0.5 rounded border ${v.cls}`}>{v.label}</span></td>
                      <td className="px-3 py-2 text-right tabular-nums text-white">{pct(r.score)}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-slate-300">{r.passed}/{r.total}</td>
                      <td className="px-3 py-2 text-xs font-mono text-slate-300">
                        {r.model}
                        {r.model_override && <span className="ml-1 text-[10px] px-1 py-0.5 rounded border border-violet-500/30 text-violet-300 font-sans">override</span>}
                      </td>
                      <td className="px-3 py-2 text-xs font-mono text-slate-500">{shortHash(r.config_hash)}{r.agent_revision ? ` r${r.agent_revision}` : ''}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-slate-400">${r.cost.toFixed(4)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function SettingsTab({ suite, canManage, onChanged }: { suite: SuiteDetail; canManage: boolean; onChanged: () => void }) {
  const router = useRouter();
  const [form, setForm] = useState({
    name: suite.name,
    description: suite.description,
    pass_threshold: suite.pass_threshold,
    gating: suite.gating,
    schedule_cron: suite.schedule_cron,
    rerun_on_model_change: suite.rerun_on_model_change,
    concurrency: suite.concurrency,
    judge_model: suite.judge_model || '',
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirm, setConfirm] = useState(false);
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }));
  const custom = form.schedule_cron && !SCHEDULES.some((s) => s.cron === form.schedule_cron);

  async function save() {
    setBusy(true);
    const r = await apiFetch(`/api/evals/suites/${suite.id}`, { method: 'PATCH', body: JSON.stringify({ ...form, judge_model: form.judge_model || null }), throwOnError: false });
    setBusy(false);
    setMsg(r.error ? { ok: false, text: r.error } : { ok: true, text: 'Saved.' });
    if (!r.error) onChanged();
  }

  async function remove() {
    setBusy(true);
    await apiFetch(`/api/evals/suites/${suite.id}`, { method: 'DELETE', throwOnError: false });
    router.push('/evals');
  }

  const dis = !canManage;
  return (
    <div className="max-w-2xl space-y-4" data-testid="eval-settings">
      <div>
        <label htmlFor="ss-name" className="block text-sm font-medium text-slate-200 mb-1.5">Name</label>
        <input id="ss-name" value={form.name} onChange={(e) => set('name', e.target.value)} disabled={dis} className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white" />
      </div>
      <div>
        <label htmlFor="ss-desc" className="block text-sm font-medium text-slate-200 mb-1.5">Description</label>
        <input id="ss-desc" value={form.description} onChange={(e) => set('description', e.target.value)} disabled={dis} className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white" />
      </div>
      <div>
        <label htmlFor="ss-th" className="flex items-center justify-between text-sm font-medium text-slate-200 mb-1.5">Pass threshold <span className="text-cyan-300 tabular-nums">{pct(form.pass_threshold)}</span></label>
        <input id="ss-th" type="range" min={0} max={1} step={0.05} value={form.pass_threshold} onChange={(e) => set('pass_threshold', Number(e.target.value))} disabled={dis} className="w-full accent-cyan-500" data-testid="eval-settings-threshold" />
      </div>
      <label className="flex items-start gap-2 rounded-lg border border-slate-700 p-3">
        <input type="checkbox" checked={form.gating} onChange={(e) => set('gating', e.target.checked)} disabled={dis} className="accent-cyan-500 mt-0.5" data-testid="eval-settings-gating" />
        <span>
          <span className="block text-sm text-white">Gate publishing on this suite</span>
          <span className="block text-xs text-slate-400">Applies when the tier policy requires passing evaluations. Publishing then needs a passing run against the exact version being published.</span>
        </span>
      </label>
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <label htmlFor="ss-cron" className="block text-sm font-medium text-slate-200 mb-1.5">Schedule</label>
          <select id="ss-cron" value={custom ? '__custom' : form.schedule_cron ?? ''} onChange={(e) => set('schedule_cron', e.target.value === '__custom' ? form.schedule_cron || '0 6 * * *' : e.target.value || null)} disabled={dis} className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white">
            {SCHEDULES.map((s) => <option key={s.label} value={s.cron ?? ''}>{s.label}</option>)}
            <option value="__custom">Custom cron…</option>
          </select>
          {(custom || form.schedule_cron === '__custom') && (
            <input value={form.schedule_cron || ''} onChange={(e) => set('schedule_cron', e.target.value)} disabled={dis} className="mt-2 w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white font-mono" placeholder="0 6 * * 1" aria-label="Cron expression" />
          )}
          {suite.next_run_at && <p className="mt-1 text-xs text-slate-500">Next run {new Date(suite.next_run_at).toLocaleString()}.</p>}
        </div>
        <div>
          <label htmlFor="ss-conc" className="block text-sm font-medium text-slate-200 mb-1.5">Cases at once</label>
          <input id="ss-conc" type="number" min={1} max={16} value={form.concurrency} onChange={(e) => set('concurrency', Math.max(1, Math.min(16, Number(e.target.value) || 1)))} disabled={dis} className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white" />
        </div>
      </div>
      {suite.agent?.kind === 'agent' && (
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input type="checkbox" checked={form.rerun_on_model_change} onChange={(e) => set('rerun_on_model_change', e.target.checked)} disabled={dis} className="accent-cyan-500" />
          Run again whenever the agent&apos;s model changes
        </label>
      )}
      <div>
        <label className="block text-sm font-medium text-slate-200 mb-1.5">Judge model for judged assertions</label>
        <ModelSelect value={form.judge_model} onChange={(v) => set('judge_model', v)} disabled={dis} placeholder="Default, Claude Haiku 4.5" />
      </div>
      {msg && <p className={`text-sm ${msg.ok ? 'text-emerald-300' : 'text-rose-300'}`} role="status">{msg.text}</p>}
      {canManage && (
        <div className="flex items-center gap-2 pt-2">
          <button type="button" onClick={save} disabled={busy || !form.name.trim()} className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400 disabled:opacity-40" data-testid="eval-settings-save">
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />} Save settings
          </button>
          <button type="button" onClick={() => setConfirm(true)} className="ml-auto inline-flex items-center gap-1.5 px-3 py-2 rounded-md text-sm text-rose-300 hover:bg-rose-500/10">
            <Trash2 className="w-4 h-4" /> Delete suite
          </button>
        </div>
      )}
      <ConfirmModal open={confirm} onClose={() => setConfirm(false)} onConfirm={remove} title="Delete this suite?" description="Its cases and run history are deleted too. If it gates publishing, that gate goes away." confirmLabel="Delete suite" variant="danger" loading={busy} />
    </div>
  );
}

function ModelDialog({ current, busy, err, onClose, onRun }: { current: string; busy: boolean; err: string | null; onClose: () => void; onRun: (m: string) => void }) {
  const [model, setModel] = useState('');
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-labelledby="model-run-title">
      <div className="w-full max-w-md rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800">
          <h2 id="model-run-title" className="text-base font-semibold text-white">Run on another model</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1 rounded text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
        </div>
        <div className="px-5 py-4 space-y-3">
          <p className="text-sm text-slate-400">Runs every case on the chosen model for this run only. The agent keeps <span className="font-mono text-slate-300">{current}</span>. The result opens next to the last regular run.</p>
          <ModelSelect value={model} onChange={setModel} placeholder="Pick a model…" id="eval-model-pick" />
          {model === current && <p className="text-xs text-amber-300">That is the agent&apos;s own model, so this is a regular run.</p>}
          {err && <p className="text-sm text-rose-300" role="alert">{err}</p>}
        </div>
        <div className="flex justify-end gap-2 px-5 py-4 border-t border-slate-800">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-md text-sm text-slate-300 hover:bg-slate-800">Cancel</button>
          <button type="button" onClick={() => onRun(model)} disabled={!model || busy} className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400 disabled:opacity-40" data-testid="eval-model-run">
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />} Run
          </button>
        </div>
      </div>
    </div>
  );
}
