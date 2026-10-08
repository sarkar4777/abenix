'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowLeft, ArrowRight, Bot, CheckCircle2, Eye, Loader2, Milestone, Search, Wrench } from 'lucide-react';
import ResponsiveModal from '@/components/ui/ResponsiveModal';
import LevelPill from './LevelPill';
import { apiFetch } from '@/lib/api-client';
import { fetchAllAgents } from '@/lib/fetch-all-agents';
import { toast } from '@/stores/toastStore';
import {
  autonomyApi, PROBE_KINDS, WORLD_MODEL_KINDS,
  type ActionType, type EnrolOptions, type EnrolTool, type GrantRow,
} from '@/lib/autonomy';

type Step = 'agent' | 'action' | 'judge' | 'predict' | 'limits';
const STEP_TITLES: Record<Step, string> = {
  agent: 'Pick an agent',
  action: 'Pick an action',
  judge: 'How we judge success',
  predict: 'How we predict',
  limits: 'Hard limits',
};

interface AgentLite { id: string; name: string; description?: string | null }

interface Form {
  label: string;
  probeKind: string;
  afterS: string;
  probeTool: string;
  probePath: string;
  probeMetric: string;
  probeArgs: string;
  wmKind: string;
  wmRef: string;
  wmMetric: string;
  wmTimeout: string;
  bandPct: string;
  limitsKey: string;
  matchParam: string;
  matchGlob: string;
  // set when this enrols on an action that already exists, its settings are kept
  reuseKey: string;
}

export function formFromTool(t: EnrolTool): Form {
  const p = t.prefill || {};
  const probe = p.outcome_probe || { kind: 'manual' };
  const wm = p.world_model || { kind: 'agent_stated' };
  return {
    label: p.label || t.effect?.label || t.tool_name,
    probeKind: probe.kind || 'manual',
    afterS: String(probe.after_s ?? 900),
    probeTool: probe.tool || '',
    probePath: probe.path || '',
    probeMetric: probe.metric || wm.metric || '',
    probeArgs: JSON.stringify(probe.arguments || {}, null, 2),
    wmKind: wm.kind || 'agent_stated',
    wmRef: wm.ref || '',
    wmMetric: wm.metric || probe.metric || '',
    wmTimeout: String(wm.timeout_s ?? 10),
    bandPct: p.max_band_width === null || p.max_band_width === undefined ? '' : String(Math.round(p.max_band_width * 100)),
    limitsKey: p.limits_decision_key || '',
    matchParam: p.match_param || t.effect?.target_param || '',
    matchGlob: '',
    reuseKey: '',
  };
}

export function formFromType(at: ActionType): Form {
  const probe = at.outcome_probe || { kind: 'manual' };
  const wm = at.world_model || { kind: 'agent_stated' };
  return {
    label: at.label,
    probeKind: probe.kind || 'manual',
    afterS: String(probe.after_s ?? 900),
    probeTool: probe.tool || '',
    probePath: probe.path || '',
    probeMetric: probe.metric || wm.metric || '',
    probeArgs: JSON.stringify(probe.arguments || {}, null, 2),
    wmKind: wm.kind || 'agent_stated',
    wmRef: wm.ref || '',
    wmMetric: wm.metric || probe.metric || '',
    wmTimeout: String(wm.timeout_s ?? 10),
    bandPct: at.max_band_width === null || at.max_band_width === undefined ? '' : String(Math.round(at.max_band_width * 100)),
    limitsKey: at.limits_decision_key || '',
    matchParam: at.match?.param || '',
    matchGlob: at.match?.glob || '',
    reuseKey: at.key,
  };
}

// which calls of the tool this action covers, in words
export function matchText(param: string, glob: string): string {
  if (!glob.trim()) return 'Every call of this tool';
  const exact = !/[*?[]/.test(glob);
  return `Calls where ${param || 'the target'} ${exact ? 'is' : 'matches'} ${glob.trim()}`;
}

export function validateStep(step: Step, f: Form): Record<string, string> {
  const e: Record<string, string> = {};
  if (step === 'judge') {
    if (!f.label.trim()) e.label = 'Give the action a short name';
    const a = Number(f.afterS);
    if (!Number.isFinite(a) || a < 0) e.afterS = 'Enter a number of seconds, 0 or more';
    if (f.probeKind === 'tool' && !f.probeTool.trim()) e.probeTool = 'Name the tool that reads the result';
    if (f.probeKind === 'tool') {
      try { JSON.parse(f.probeArgs || '{}'); } catch { e.probeArgs = 'This is not valid JSON'; }
    }
    if (f.matchGlob.trim() && !f.matchParam.trim()) e.matchParam = 'Name the argument to look at, for example topic';
  }
  if (step === 'predict') {
    if ((f.wmKind === 'decision' || f.wmKind === 'ml_model') && !f.wmRef.trim()) {
      e.wmRef = f.wmKind === 'decision' ? 'Pick the decision model' : 'Name the ML model';
    }
    if (f.bandPct.trim()) {
      const b = Number(f.bandPct);
      if (!Number.isFinite(b) || b <= 0 || b > 500) e.bandPct = 'Enter a percent between 1 and 500, or leave it empty';
    }
    const t = Number(f.wmTimeout);
    if (!Number.isFinite(t) || t <= 0 || t > 120) e.wmTimeout = 'Between 1 and 120 seconds';
  }
  return e;
}

export default function EnrolWizard({
  open, onClose, presetAgent, presetTool, onEnrolled,
}: {
  open: boolean;
  onClose: () => void;
  presetAgent?: AgentLite | null;
  presetTool?: string | null;
  onEnrolled?: (g: GrantRow) => void;
}) {
  const router = useRouter();
  const [step, setStep] = useState<Step>(presetAgent ? 'action' : 'agent');
  const [agent, setAgent] = useState<AgentLite | null>(presetAgent || null);
  const [agents, setAgents] = useState<AgentLite[] | null>(null);
  const [agentsErr, setAgentsErr] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const [opts, setOpts] = useState<EnrolOptions | null>(null);
  const [optsErr, setOptsErr] = useState<string | null>(null);
  const [optsLoading, setOptsLoading] = useState(false);
  const [tool, setTool] = useState<EnrolTool | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [decisions, setDecisions] = useState<Array<{ key: string; name: string }>>([]);
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // reset each time it opens
  useEffect(() => {
    if (!open) return;
    setStep(presetAgent ? 'action' : 'agent');
    setAgent(presetAgent || null);
    setTool(null);
    setForm(null);
    setOpts(null);
    setErrors({});
    setSaveErr(null);
    setQ('');
  }, [open, presetAgent?.id]);

  useEffect(() => {
    if (!open || agents !== null || presetAgent) return;
    let live = true;
    fetchAllAgents<AgentLite>()
      .then((r) => { if (live) setAgents(r.agents); })
      .catch(() => { if (live) setAgentsErr('Could not load your agents. Check your connection and try again.'); });
    return () => { live = false; };
  }, [open, agents, presetAgent]);

  useEffect(() => {
    if (!open) return;
    apiFetch<Array<{ key: string; name: string }>>('/api/decisions', { silent: true }).then((r) => {
      if (Array.isArray(r.data)) setDecisions(r.data.map((d) => ({ key: d.key, name: d.name })));
    });
  }, [open]);

  useEffect(() => {
    if (!open || !agent) return;
    let live = true;
    setOptsLoading(true);
    setOptsErr(null);
    autonomyApi.enrolOptions(agent.id).then((r) => {
      if (!live) return;
      setOptsLoading(false);
      if (r.error) {
        setOptsErr(r.status === 403 ? 'You need the autonomy.manage permission to enrol agents. An admin can grant it under Admin, Permissions.' : r.error);
        return;
      }
      setOpts(r.data);
      if (presetTool && r.data) {
        const t = r.data.tools.find((x) => x.tool_name === presetTool);
        if (t && !t.grant) pick(t);
      }
    });
    return () => { live = false; };
  }, [open, agent?.id]);

  const filtered = useMemo(() => {
    const n = q.trim().toLowerCase();
    const list = agents || [];
    return (n ? list.filter((a) => a.name?.toLowerCase().includes(n) || a.id.includes(n)) : list).slice(0, 60);
  }, [agents, q]);

  function pick(t: EnrolTool) {
    setTool(t);
    setForm(formFromTool(t));
    setErrors({});
    setSaveErr(null);
    setStep('judge');
  }

  function reuse(t: EnrolTool, at: ActionType) {
    setTool(t);
    setForm(formFromType(at));
    setErrors({});
    setSaveErr(null);
    setStep('judge');
  }

  const set = (k: keyof Form) => (v: string) => setForm((f) => (f ? { ...f, [k]: v } : f));

  function next() {
    if (!form) return;
    const e = validateStep(step, form);
    setErrors(e);
    if (Object.keys(e).length) return;
    setStep(step === 'judge' ? 'predict' : 'limits');
  }

  function back() {
    if (step === 'limits') setStep('predict');
    else if (step === 'predict') setStep('judge');
    else if (step === 'judge') setStep('action');
    else if (step === 'action' && !presetAgent) setStep('agent');
  }

  async function start() {
    if (!form || !tool || !agent) return;
    setSaving(true);
    setSaveErr(null);
    let probeArgs: Record<string, unknown> = {};
    try { probeArgs = JSON.parse(form.probeArgs || '{}'); } catch { /* checked in validateStep */ }
    const r = await autonomyApi.enrol({
      agent_id: agent.id,
      tool_name: tool.tool_name,
      action_type: {
        ...(form.reuseKey ? { key: form.reuseKey } : {}),
        ...(form.matchGlob.trim() ? { match: { param: form.matchParam.trim(), glob: form.matchGlob.trim() } } : {}),
        label: form.label.trim(),
        world_model: {
          kind: form.wmKind,
          ref: form.wmRef.trim() || null,
          metric: form.wmMetric.trim() || null,
          timeout_s: Number(form.wmTimeout) || 10,
        },
        outcome_probe: {
          kind: form.probeKind,
          after_s: Number(form.afterS),
          ...(form.probeKind === 'tool' ? { tool: form.probeTool.trim(), arguments: probeArgs, path: form.probePath.trim() || null } : {}),
          metric: form.probeMetric.trim() || form.wmMetric.trim() || null,
        },
        limits_decision_key: form.limitsKey.trim() || null,
        max_band_width: form.bandPct.trim() ? Number(form.bandPct) / 100 : null,
      },
    });
    setSaving(false);
    if (r.error || !r.data) {
      setSaveErr(r.status === 403 ? 'You need the autonomy.manage permission to enrol agents.' : r.error || 'Enrolling failed. Try again.');
      return;
    }
    toast({ type: 'success', title: 'Now watching', message: `${agent.name} will say what it would do. Nothing runs yet.`, action: { label: 'Open its page', href: `/autonomy/${r.data.id}` } });
    onEnrolled?.(r.data);
    onClose();
    router.push(`/autonomy/${encodeURIComponent(r.data.id)}`);
  }

  const steps: Step[] = presetAgent ? ['action', 'judge', 'predict', 'limits'] : ['agent', 'action', 'judge', 'predict', 'limits'];
  const idx = steps.indexOf(step);
  const input = (err?: string) => `w-full rounded-md border bg-slate-950/60 px-2.5 py-2 text-sm text-white focus:outline-none focus:border-cyan-500/60 ${err ? 'border-rose-500/60' : 'border-slate-700'}`;
  const Err = ({ k }: { k: string }) => (errors[k] ? <p className="mt-1 text-xs text-rose-300" role="alert">{errors[k]}</p> : null);

  return (
    <ResponsiveModal open={open} onClose={onClose} title="Enrol an agent action" icon={<Milestone className="h-4 w-4" />} maxWidth="max-w-2xl">
      <div data-testid="autonomy-enrol-wizard">
        <ol className="mb-5 flex flex-wrap gap-1.5 text-[11px]" aria-label="Steps">
          {steps.map((s, i) => (
            <li key={s} className={`rounded-full border px-2 py-0.5 ${i === idx ? 'border-cyan-500/50 bg-cyan-500/15 text-cyan-200' : i < idx ? 'border-slate-600 text-slate-300' : 'border-slate-800 text-slate-500'}`} aria-current={i === idx ? 'step' : undefined}>
              {i + 1}. {STEP_TITLES[s]}
            </li>
          ))}
        </ol>

        {step === 'agent' && (
          <div>
            <p className="mb-3 text-sm text-slate-400">Which agent should earn the right to act?</p>
            <div className="mb-3 flex items-center gap-2 rounded-md border border-slate-700 bg-slate-950 px-3">
              <Search className="h-4 w-4 text-slate-500" />
              <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search agents by name" className="flex-1 bg-transparent py-2 text-sm text-white outline-none" aria-label="Search agents" data-testid="autonomy-enrol-agent-search" />
            </div>
            {agentsErr ? (
              <p className="text-sm text-rose-300">{agentsErr}</p>
            ) : agents === null ? (
              <div className="flex items-center gap-2 py-6 text-sm text-slate-400"><Loader2 className="h-4 w-4 animate-spin" /> Loading agents</div>
            ) : agents.length === 0 ? (
              <p className="py-6 text-sm text-slate-400">You have no agents yet. <Link href="/builder" className="text-cyan-300 hover:underline">Build one</Link> or try the sample plant on the Autonomy page.</p>
            ) : filtered.length === 0 ? (
              <p className="py-6 text-sm text-slate-400">No agent matches “{q}”.</p>
            ) : (
              <ul className="max-h-80 space-y-1 overflow-y-auto">
                {filtered.map((a) => (
                  <li key={a.id}>
                    <button type="button" onClick={() => { setAgent(a); setStep('action'); }} className="flex w-full items-center gap-2 rounded-lg border border-transparent px-3 py-2 text-left hover:border-slate-700 hover:bg-slate-800/50" data-testid="autonomy-enrol-agent">
                      <Bot className="h-4 w-4 shrink-0 text-cyan-400" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm text-white">{a.name}</span>
                        {a.description && <span className="block truncate text-xs text-slate-500">{a.description}</span>}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {step === 'action' && (
          <div>
            <p className="mb-3 text-sm text-slate-400">
              Which action of <strong className="text-white">{agent?.name}</strong> should it earn? Only tools that change something are listed.
            </p>
            {optsLoading ? (
              <div className="flex items-center gap-2 py-6 text-sm text-slate-400"><Loader2 className="h-4 w-4 animate-spin" /> Looking at its tools</div>
            ) : optsErr ? (
              <p className="text-sm text-rose-300" role="alert">{optsErr}</p>
            ) : !opts || opts.tools.length === 0 ? (
              <p className="py-6 text-sm text-slate-400" data-testid="autonomy-enrol-no-tools">
                This agent has no tools that change anything, so there is nothing to enrol. Add a tool that sends, writes or sets something in the <Link href={agent ? `/builder?agent=${agent.id}` : '/builder'} className="text-cyan-300 hover:underline">Agent Builder</Link>.
              </p>
            ) : (
              <ul className="space-y-2">
                {opts.tools.map((t) => {
                  const grants = t.grants || (t.grant ? [t.grant] : []);
                  const enrolledKeys = new Set(grants.map((g) => g.action_type.key));
                  const others = (t.existing_action_types || []).filter((at) => !enrolledKeys.has(at.key));
                  return (
                    <li key={t.tool_name} className="rounded-lg border border-slate-700/60 bg-slate-900/40 p-3" data-testid={`autonomy-enrol-tool-${t.tool_name}`}>
                      <div className="flex flex-wrap items-center gap-2">
                        <Wrench className="h-4 w-4 text-cyan-400" />
                        <span className="text-sm font-medium text-white">{t.effect?.label || t.tool_name}</span>
                        <span className="font-mono text-[11px] text-slate-500">{t.tool_name}</span>
                        {t.risk_tier && <span className="rounded border border-slate-700 px-1.5 text-[10px] text-slate-400">{t.risk_tier} risk</span>}
                        <button type="button" onClick={() => pick(t)} className="ml-auto rounded-md bg-cyan-500 px-3 py-1 text-xs font-medium text-white hover:bg-cyan-400" data-testid="autonomy-enrol-pick">
                          {grants.length || others.length ? 'New action' : 'Choose'}
                        </button>
                      </div>
                      {grants.length > 0 && (
                        <ul className="mt-2 space-y-1">
                          {grants.map((g) => (
                            <li key={g.id} className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                              <LevelPill level={g.level} size="sm" />
                              <span className="min-w-0 truncate">{g.action_type.label}</span>
                              <Link href={`/autonomy/${g.id}`} className="ml-auto text-cyan-300 hover:underline" onClick={onClose} data-testid="autonomy-enrol-open-grant">Enrolled, open</Link>
                            </li>
                          ))}
                        </ul>
                      )}
                      {others.length > 0 && (
                        <div className="mt-2">
                          <p className="text-[11px] text-slate-500">Existing actions for this tool, with their settings:</p>
                          <ul className="mt-1 space-y-1">
                            {others.map((at) => (
                              <li key={at.id} className="flex flex-wrap items-center gap-2 text-xs" data-testid="autonomy-enrol-existing" data-key={at.key}>
                                <span className="min-w-0 flex-1 truncate text-slate-200" title={at.key}>{at.label}</span>
                                <span className="text-slate-500">{matchText(at.match?.param || '', at.match?.glob || '')}</span>
                                <button type="button" onClick={() => reuse(t, at)} className="rounded border border-cyan-500/40 px-2 py-0.5 text-cyan-300 hover:bg-cyan-500/10" data-testid="autonomy-enrol-use-existing">
                                  Use it
                                </button>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        )}

        {form && step === 'judge' && (
          <div className="space-y-4">
            {form.reuseKey ? (
              <p className="rounded-lg border border-cyan-500/30 bg-cyan-500/5 p-2.5 text-xs text-cyan-100" data-testid="autonomy-enrol-reuse-note">
                This enrols on the existing action “{form.label}”, so its settings below apply to this agent too. Change them on that action’s page.
              </p>
            ) : (
              <p className="text-sm text-slate-400">How do we find out whether the action did what was expected? The defaults come from the tool and work as they are.</p>
            )}
            <fieldset disabled={!!form.reuseKey} className="space-y-4 disabled:opacity-70">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-300" htmlFor="en-label">What to call this action</label>
              <input id="en-label" value={form.label} onChange={(e) => set('label')(e.target.value)} className={input(errors.label)} data-testid="autonomy-enrol-label" />
              <Err k="label" />
            </div>
            <div>
              <span className="mb-1 block text-xs font-medium text-slate-300">Which calls it covers</span>
              <div className="grid gap-2 sm:grid-cols-[minmax(0,10rem)_1fr]">
                <input value={form.matchParam} onChange={(e) => set('matchParam')(e.target.value)} placeholder="topic" aria-label="Argument to look at" className={input(errors.matchParam)} data-testid="autonomy-enrol-match-param" />
                <input value={form.matchGlob} onChange={(e) => set('matchGlob')(e.target.value)} placeholder="Leave empty for every call, or for example controls.*" aria-label="Value or pattern" className={input()} data-testid="autonomy-enrol-match-glob" />
              </div>
              <p className="mt-1 text-xs text-slate-500">{matchText(form.matchParam, form.matchGlob)}. A pattern keeps this action apart from other uses of the same tool.</p>
              <Err k="matchParam" />
            </div>
            <div>
              <span className="mb-1 block text-xs font-medium text-slate-300">Where the result comes from</span>
              <div className="grid gap-2 sm:grid-cols-3">
                {PROBE_KINDS.map((k) => (
                  <label key={k.value} className={`cursor-pointer rounded-lg border p-2.5 text-xs ${form.probeKind === k.value ? 'border-cyan-500/60 bg-cyan-500/10 text-white' : 'border-slate-700 text-slate-300'}`}>
                    <input type="radio" name="probe-kind" value={k.value} checked={form.probeKind === k.value} onChange={() => set('probeKind')(k.value)} className="sr-only" />
                    <span className="block font-medium">{k.label}</span>
                    <span className="mt-0.5 block text-slate-500">{k.help}</span>
                  </label>
                ))}
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-300" htmlFor="en-after">Check after (seconds)</label>
                <input id="en-after" type="number" min={0} value={form.afterS} onChange={(e) => set('afterS')(e.target.value)} className={input(errors.afterS)} />
                <Err k="afterS" />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-300" htmlFor="en-pmetric">What is measured</label>
                <input id="en-pmetric" value={form.probeMetric} onChange={(e) => set('probeMetric')(e.target.value)} placeholder="For example pressure_bar" className={input()} />
              </div>
            </div>
            {form.probeKind === 'tool' && (
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-300" htmlFor="en-ptool">Tool that reads it</label>
                  <input id="en-ptool" value={form.probeTool} onChange={(e) => set('probeTool')(e.target.value)} className={input(errors.probeTool)} />
                  <Err k="probeTool" />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-300" htmlFor="en-ppath">Field in its answer</label>
                  <input id="en-ppath" value={form.probePath} onChange={(e) => set('probePath')(e.target.value)} placeholder="For example pressure_bar" className={input()} />
                </div>
              </div>
            )}
            {form.probeKind === 'tool' && (
              <div>
                <button type="button" onClick={() => setShowAdvanced((v) => !v)} className="text-xs text-slate-400 hover:text-white">{showAdvanced ? 'Hide' : 'Show'} details</button>
                {(showAdvanced || errors.probeArgs) && (
                  <div className="mt-2">
                    <label className="mb-1 block text-xs font-medium text-slate-300" htmlFor="en-pargs">Arguments for the tool (JSON)</label>
                    <textarea id="en-pargs" rows={3} value={form.probeArgs} onChange={(e) => set('probeArgs')(e.target.value)} className={`${input(errors.probeArgs)} font-mono text-xs`} />
                    <Err k="probeArgs" />
                  </div>
                )}
              </div>
            )}
            </fieldset>
          </div>
        )}

        {form && step === 'predict' && (
          <div className="space-y-4">
            <p className="text-sm text-slate-400">Before it acts, what does the agent expect to happen? A prediction is what lets it earn trust.</p>
            <fieldset disabled={!!form.reuseKey} className="space-y-4 disabled:opacity-70">
            <div className="grid gap-2 sm:grid-cols-2">
              {WORLD_MODEL_KINDS.map((k) => (
                <label key={k.value} className={`cursor-pointer rounded-lg border p-2.5 text-xs ${form.wmKind === k.value ? 'border-cyan-500/60 bg-cyan-500/10 text-white' : 'border-slate-700 text-slate-300'}`}>
                  <input type="radio" name="wm-kind" value={k.value} checked={form.wmKind === k.value} onChange={() => set('wmKind')(k.value)} className="sr-only" />
                  <span className="block font-medium">{k.label}</span>
                  <span className="mt-0.5 block text-slate-500">{k.help}</span>
                </label>
              ))}
            </div>
            {form.wmKind === 'decision' && (
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-300" htmlFor="en-wmref">Decision model</label>
                <select id="en-wmref" value={form.wmRef} onChange={(e) => set('wmRef')(e.target.value)} className={input(errors.wmRef)}>
                  <option value="">Pick one</option>
                  {decisions.map((d) => <option key={d.key} value={d.key}>{d.name} ({d.key})</option>)}
                </select>
                {decisions.length === 0 && <p className="mt-1 text-xs text-slate-500">No decision models yet. <Link href="/decisions" className="text-cyan-300 hover:underline">Create one in Decisions</Link>.</p>}
                <Err k="wmRef" />
              </div>
            )}
            {form.wmKind === 'ml_model' && (
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-300" htmlFor="en-wmref2">ML model name</label>
                <input id="en-wmref2" value={form.wmRef} onChange={(e) => set('wmRef')(e.target.value)} className={input(errors.wmRef)} />
                <p className="mt-1 text-xs text-slate-500">Deployed models are listed under <Link href="/ml-models" className="text-cyan-300 hover:underline">ML Models</Link>.</p>
                <Err k="wmRef" />
              </div>
            )}
            {form.wmKind !== 'none' && (
              <div className="grid gap-3 sm:grid-cols-3">
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-300" htmlFor="en-wmmetric">What is predicted</label>
                  <input id="en-wmmetric" value={form.wmMetric} onChange={(e) => set('wmMetric')(e.target.value)} className={input()} />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-300" htmlFor="en-band">Widest band allowed (%)</label>
                  <input id="en-band" type="number" min={1} max={500} value={form.bandPct} onChange={(e) => set('bandPct')(e.target.value)} placeholder="No limit" className={input(errors.bandPct)} />
                  <Err k="bandPct" />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-300" htmlFor="en-timeout">Give up after (seconds)</label>
                  <input id="en-timeout" type="number" min={1} max={120} value={form.wmTimeout} onChange={(e) => set('wmTimeout')(e.target.value)} className={input(errors.wmTimeout)} />
                  <Err k="wmTimeout" />
                </div>
              </div>
            )}
            </fieldset>
            <p className="text-xs text-slate-500">A band wider than the limit counts as no prediction, so an agent cannot win by predicting everything. If the prediction fails, the action asks first.</p>
          </div>
        )}

        {form && step === 'limits' && (
          <div className="space-y-4">
            <p className="text-sm text-slate-400">Hard limits are lines the action can never cross, at any level. They are rules from Decisions, tested and versioned.</p>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-300" htmlFor="en-limits">Limit rules</label>
              <select id="en-limits" value={form.limitsKey} disabled={!!form.reuseKey} onChange={(e) => set('limitsKey')(e.target.value)} className={`${input()} disabled:opacity-70`} data-testid="autonomy-enrol-limits">
                <option value="">No hard limits</option>
                {form.limitsKey && !decisions.some((d) => d.key === form.limitsKey) && <option value={form.limitsKey}>{form.limitsKey}</option>}
                {decisions.map((d) => <option key={d.key} value={d.key}>{d.name} ({d.key})</option>)}
              </select>
              <p className="mt-1 text-xs text-slate-500">
                You can add limits later. <Link href="/decisions" className="text-cyan-300 hover:underline">Write limit rules in Decisions</Link>.
              </p>
            </div>
            <div className="rounded-lg border border-sky-500/30 bg-sky-500/5 p-3 text-sm text-sky-100">
              <p className="flex items-center gap-2 font-medium"><Eye className="h-4 w-4" /> It starts at Watching</p>
              <p className="mt-1 text-xs text-sky-200/80">The agent says what it would do and nothing runs. You compare it with what you would have done under Approvals, Watching reviews.</p>
            </div>
          </div>
        )}

        {saveErr && <p className="mt-4 text-sm text-rose-300" role="alert" data-testid="autonomy-enrol-error">{saveErr}</p>}

        {(step === 'judge' || step === 'predict' || step === 'limits' || (step === 'action' && !presetAgent)) && (
          <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-between">
            <button type="button" onClick={back} className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800">
              <ArrowLeft className="h-4 w-4" /> Back
            </button>
            {step === 'limits' ? (
              <button type="button" disabled={saving} onClick={start} className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-400 disabled:opacity-50" data-testid="autonomy-enrol-start">
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />} Start watching
              </button>
            ) : step !== 'action' ? (
              <button type="button" onClick={next} className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-400" data-testid="autonomy-enrol-next">
                Next <ArrowRight className="h-4 w-4" />
              </button>
            ) : null}
          </div>
        )}
      </div>
    </ResponsiveModal>
  );
}
