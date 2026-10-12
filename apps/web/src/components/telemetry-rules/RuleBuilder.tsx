'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import useSWR from 'swr';
import { FlaskConical, Loader2, Save, Send, Trash2 } from 'lucide-react';
import ConfirmModal from '@/components/ui/ConfirmModal';
import { apiFetch } from '@/lib/api-client';
import { toastError, toastSuccess } from '@/stores/toastStore';
import ActionsEditor from './ActionsEditor';
import ConditionEditor from './ConditionEditor';
import PreviewPanel from './PreviewPanel';
import ScopePicker, { useAssets } from './ScopePicker';
import {
  SEVERITY_INFO, draftPayload, draftProblems, fieldErrors, ruleSentence, sameDraft, type Options, type Rule, type RuleDraft, type Severity,
} from './lib';
import { Field, Section, cls } from './ui';

function fetcher(url: string) {
  return apiFetch<Options>(url, { silent: true });
}

export default function RuleBuilder({
  initial, ruleId, readOnly, otherNames, onSaved,
}: {
  initial: RuleDraft;
  ruleId?: string;
  readOnly?: boolean;
  otherNames: string[];
  onSaved?: (r: Rule) => void;
}) {
  const router = useRouter();
  const [draft, setDraft] = useState<RuleDraft>(initial);
  const [saved, setSaved] = useState<RuleDraft>(initial);
  const [tried, setTried] = useState(false);
  const [server, setServer] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [confirmCmd, setConfirmCmd] = useState(false);
  const [confirmLeave, setConfirmLeave] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [testing, setTesting] = useState(false);
  const optRes = useSWR('/api/telemetry/rules/options', fetcher, { revalidateOnFocus: false });
  const options = (optRes.data?.data ?? null) as Options | null;
  const canCommand = !!options?.can_command;
  const { names } = useAssets();
  const labels = useMemo(() => Object.fromEntries((options?.agents || []).map((a) => [a.id, a.name])), [options]);

  useEffect(() => { setDraft(initial); setSaved(initial); }, [initial]);
  const dirty = !sameDraft(draft, saved) || draft.name !== saved.name || draft.description !== saved.description;
  useEffect(() => {
    if (!dirty || readOnly) return;
    const h = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ''; };
    window.addEventListener('beforeunload', h);
    return () => window.removeEventListener('beforeunload', h);
  }, [dirty, readOnly]);

  const problems = useMemo(() => draftProblems(draft, canCommand || !draft.actions.some((a) => a.kind === 'command'), otherNames), [draft, canCommand, otherNames]);
  // field errors show after the first save attempt, server ones always
  const shown = useMemo(() => ({ ...(tried ? problems : {}), ...server }), [tried, problems, server]);
  const sentence = ruleSentence(draft, names, labels);
  const set = (patch: Partial<RuleDraft>) => { setDraft((d) => ({ ...d, ...patch })); setServer({}); };

  const leave = (href: string) => (dirty && !readOnly ? setConfirmLeave(href) : router.push(href));

  async function save(confirmed = false) {
    setTried(true);
    if (Object.keys(problems).length) {
      toastError('Some fields need a fix before the rule can be saved. They are marked in red.');
      setTimeout(() => document.querySelector('[role="alert"]')?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 50);
      return;
    }
    if (!confirmed && draft.enabled && draft.actions.some((a) => a.kind === 'command')) { setConfirmCmd(true); return; }
    setBusy(true);
    const body = JSON.stringify(draftPayload(draft));
    const res = ruleId
      ? await apiFetch<Rule>(`/api/telemetry/rules/${ruleId}`, { method: 'PATCH', body, silent: true })
      : await apiFetch<Rule>('/api/telemetry/rules', { method: 'POST', body, silent: true });
    setBusy(false);
    setConfirmCmd(false);
    if (res.error || !res.data) {
      const f = fieldErrors(res);
      setServer(f);
      toastError(Object.keys(f).length ? 'The rule was not saved. The fields marked in red say why.' : res.error || 'The rule was not saved. Try again.');
      return;
    }
    toastSuccess(ruleId ? 'Rule saved. It applies to new readings within a couple of seconds.' : 'Rule created. It is watching the stream now.');
    setSaved(draft);
    onSaved?.(res.data);
    if (!ruleId) router.replace(`/telemetry/rules/${res.data.id}`);
  }

  async function del() {
    if (!ruleId) return;
    setBusy(true);
    const res = await apiFetch(`/api/telemetry/rules/${ruleId}`, { method: 'DELETE', silent: true });
    setBusy(false);
    setConfirmDelete(false);
    if (res.error) { toastError(res.error); return; }
    toastSuccess('Rule deleted, with its firing history.');
    setSaved(draft);
    router.push('/telemetry/rules');
  }

  async function test() {
    if (!ruleId) return;
    setTesting(true);
    const res = await apiFetch(`/api/telemetry/rules/${ruleId}/test`, { method: 'POST', silent: true });
    setTesting(false);
    if (res.error) { toastError(res.error); return; }
    toastSuccess('Test sent. Its steps run now, commands are skipped. It shows in the history below as a test.');
  }

  return (
    <div className="space-y-4" data-testid="rule-builder" data-mode={readOnly ? 'view' : ruleId ? 'edit' : 'new'}>
      <div className="rounded-xl border border-cyan-500/30 bg-cyan-500/5 px-4 py-3" data-testid="rule-sentence">
        <p className="text-[11px] uppercase tracking-wide text-cyan-300/80">In plain words</p>
        <p className="mt-0.5 text-sm text-white [overflow-wrap:anywhere]">{sentence}</p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
        <div className="min-w-0 space-y-4">
          <Section n={1} title="What to watch" help="One asset, or every asset of a type or with a tag, including ones that start streaming later." testId="rule-scope">
            <ScopePicker scope={draft.scope} onChange={(scope) => set({ scope })} errors={shown} disabled={readOnly} />
          </Section>
          <Section n={2} title="When" help="The condition is checked on every reading as it streams in." testId="rule-condition">
            <ConditionEditor cond={draft.condition} scope={draft.scope} onChange={(condition) => set({ condition })} errors={shown} disabled={readOnly} assetNames={names} />
          </Section>
          <Section n={3} title="Then" help="Steps run one after another each time the rule fires. The history shows what each one did." testId="rule-actions">
            <ActionsEditor actions={draft.actions} onChange={(actions) => set({ actions })} errors={shown} options={options} scope={draft.scope} disabled={readOnly}
              condition={draft.condition} ruleId={ruleId} ruleName={draft.name} />
          </Section>
          <Section n={4} title="Name and settings" testId="rule-settings">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Name" htmlFor="rule-name" error={shown.name} className="sm:col-span-2">
                <input id="rule-name" value={draft.name} maxLength={160} disabled={readOnly} onChange={(e) => set({ name: e.target.value })} placeholder="EX1 pump pressure high" className={cls(shown.name)} data-testid="rule-name" />
              </Field>
              <Field label="Description" htmlFor="rule-desc" error={shown.description} help="Optional. Why the rule exists and what to do when it fires." className="sm:col-span-2">
                <textarea id="rule-desc" rows={2} value={draft.description} disabled={readOnly} onChange={(e) => set({ description: e.target.value })} className={cls(shown.description)} data-testid="rule-description" />
              </Field>
              <Field label="Severity" htmlFor="rule-sev">
                <select id="rule-sev" value={draft.severity} disabled={readOnly} onChange={(e) => set({ severity: e.target.value as Severity })} className={cls()} data-testid="rule-severity">
                  {(Object.keys(SEVERITY_INFO) as Severity[]).map((s) => <option key={s} value={s}>{SEVERITY_INFO[s]}</option>)}
                </select>
              </Field>
              <Field label="Quiet time after firing (seconds)" htmlFor="rule-cooldown" error={shown.cooldown_s} help="It will not fire again on the same asset for this long, even if it clears and comes back.">
                <input id="rule-cooldown" type="number" min={0} max={86400} value={String(draft.cooldown_s)} disabled={readOnly} onChange={(e) => set({ cooldown_s: e.target.value })} className={cls(shown.cooldown_s)} data-testid="rule-cooldown" />
              </Field>
              <Field label="Team" htmlFor="rule-team" help="Optional. Only that team and admins see a team's rule.">
                <select id="rule-team" value={draft.team_id || ''} disabled={readOnly} onChange={(e) => set({ team_id: e.target.value || null })} className={cls(shown.team_id)} data-testid="rule-team">
                  <option value="">Whole workspace</option>
                  {(options?.teams || []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
              </Field>
              <label className="flex min-h-[40px] items-center gap-2 self-end rounded-lg border border-slate-700 px-3 text-sm text-slate-200">
                <input type="checkbox" className="accent-cyan-500" checked={draft.enabled} disabled={readOnly} onChange={(e) => set({ enabled: e.target.checked })} data-testid="rule-enabled" />
                On, watching the stream
              </label>
            </div>
          </Section>
        </div>
        <div className="min-w-0 space-y-3 lg:sticky lg:top-4 lg:self-start">
          <PreviewPanel draft={draft} />
          {!readOnly && (
            <div className="flex flex-col gap-2 rounded-xl border border-slate-700/60 bg-slate-900/60 p-3" data-testid="rule-save-bar">
              {tried && Object.keys(problems).length > 0 && (
                <p className="text-xs text-rose-300" role="alert">{Object.keys(problems).length} {Object.keys(problems).length === 1 ? 'field needs' : 'fields need'} a fix.</p>
              )}
              <div className="flex flex-col gap-2 sm:flex-row">
                <button type="button" onClick={() => void save()} disabled={busy || (!!ruleId && !dirty)} className="inline-flex min-h-[40px] flex-1 items-center justify-center gap-2 rounded-lg bg-cyan-500 px-4 text-sm font-medium text-white hover:bg-cyan-400 disabled:opacity-50" data-testid="rule-save">
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  {ruleId ? (dirty ? 'Save changes' : 'Saved') : 'Create rule'}
                </button>
                <button type="button" onClick={() => leave(ruleId ? '/telemetry/rules' : '/telemetry/rules')} className="inline-flex min-h-[40px] items-center justify-center rounded-lg border border-slate-700 px-4 text-sm text-slate-300 hover:bg-slate-800" data-testid="rule-cancel">
                  {dirty ? 'Cancel' : 'Back to rules'}
                </button>
              </div>
              {ruleId && (
                <div className="flex flex-col gap-2 sm:flex-row">
                  <button type="button" onClick={() => void test()} disabled={testing || dirty || !draft.actions.length} title={dirty ? 'Save first, the test runs the saved steps' : !draft.actions.length ? 'Add a step to test' : 'Run the steps once now with the latest reading, commands are skipped'} className="inline-flex min-h-[36px] flex-1 items-center justify-center gap-1.5 rounded-lg border border-slate-700 px-3 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-50" data-testid="rule-test">
                    {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FlaskConical className="h-3.5 w-3.5" />} Test the steps
                  </button>
                  <button type="button" onClick={() => setConfirmDelete(true)} className="inline-flex min-h-[36px] items-center justify-center gap-1.5 rounded-lg border border-rose-500/40 px-3 text-xs text-rose-200 hover:bg-rose-500/10" data-testid="rule-delete">
                    <Trash2 className="h-3.5 w-3.5" /> Delete
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <ConfirmModal
        open={confirmCmd}
        onClose={() => setConfirmCmd(false)}
        onConfirm={() => void save(true)}
        title="Send commands automatically?"
        description={`When this rule fires it will ${draft.actions.filter((a) => a.kind === 'command').map((a) => `set ${a.signal} to ${a.value}`).join(' and ')} at once, without an approval. The audit log records the rule as the reason.`}
        confirmLabel={ruleId ? 'Save with commands' : 'Create with commands'}
        variant="warning"
        icon={Send}
        loading={busy}
        confirmTestId="rule-confirm-command"
      />
      <ConfirmModal
        open={!!confirmLeave}
        onClose={() => setConfirmLeave(null)}
        onConfirm={() => { const h = confirmLeave!; setConfirmLeave(null); setSaved(draft); router.push(h); }}
        title="Discard your changes?"
        description="The rule keeps working as it was saved. What you changed here is lost."
        confirmLabel="Discard"
        variant="warning"
        confirmTestId="rule-confirm-discard"
      />
      <ConfirmModal
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={() => void del()}
        title={`Delete ${saved.name || 'this rule'}?`}
        description="It stops watching at once and its firing history is removed. Alerts it raised clear by themselves."
        confirmLabel="Delete rule"
        loading={busy}
        confirmTestId="rule-confirm-delete"
      />
    </div>
  );
}
