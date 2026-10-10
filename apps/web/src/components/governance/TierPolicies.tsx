'use client';

import { useEffect, useMemo, useState } from 'react';
import { Check, Info, Loader2, RotateCcw, Save, X } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useSelectableModels } from '@/lib/models';
import ConfirmModal from '@/components/ui/ConfirmModal';

export type Tier = 'low' | 'medium' | 'high' | 'critical';

export interface Policy {
  publish_approvals: {
    min_approvers: number;
    exclude_author: boolean;
    capability: string;
    escalate_after_hours?: number;
    escalate_after_minutes?: number;
  };
  tool_call_action: 'allow' | 'approval' | 'block';
  allowed_models: string[];
  require_output_schema: boolean;
  require_eval_pass?: boolean;
}

export interface TierRow {
  tier: Tier;
  guide: string;
  default: Policy;
  overrides: Partial<Policy>;
  effective: Policy;
  updated_at: string | null;
}

export const TIER_STYLE: Record<Tier, { dot: string; chip: string; ring: string; label: string }> = {
  low: { dot: 'bg-emerald-400', chip: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30', ring: 'border-emerald-500/25', label: 'Low' },
  medium: { dot: 'bg-sky-400', chip: 'text-sky-300 bg-sky-500/10 border-sky-500/30', ring: 'border-sky-500/25', label: 'Medium' },
  high: { dot: 'bg-amber-400', chip: 'text-amber-300 bg-amber-500/10 border-amber-500/30', ring: 'border-amber-500/25', label: 'High' },
  critical: { dot: 'bg-rose-400', chip: 'text-rose-300 bg-rose-500/10 border-rose-500/30', ring: 'border-rose-500/25', label: 'Critical' },
};

const ACTIONS: { value: Policy['tool_call_action']; label: string; help: string }[] = [
  { value: 'allow', label: 'Allow', help: 'The call goes ahead and the run is recorded at this tier from then on.' },
  { value: 'approval', label: 'Ask a person', help: 'The run pauses on the Approvals page until someone approves or rejects the call.' },
  { value: 'block', label: 'Block', help: 'The call is refused with a message telling the agent to raise its tier.' },
];

const CAP_RE = /^approvals\.sign(:[a-z0-9_-]+)?$/;
const ESCALATE_MAX_MINUTES = 720 * 60;

type EscalateUnit = 'minutes' | 'hours';

// minutes win over hours, the same rule the server uses
function escalateUnit(pa: Policy['publish_approvals']): EscalateUnit {
  const m = pa.escalate_after_minutes;
  return m !== undefined && m > 0 && m % 60 !== 0 ? 'minutes' : 'hours';
}

function escalateValue(pa: Policy['publish_approvals'], unit: EscalateUnit): number {
  const m = pa.escalate_after_minutes;
  if (m !== undefined && Number.isNaN(m)) return NaN;
  if (m !== undefined && m > 0) return unit === 'minutes' ? m : m / 60;
  const h = pa.escalate_after_hours ?? 0;
  return unit === 'minutes' ? h * 60 : h;
}

function sameJson(a: unknown, b: unknown) {
  return JSON.stringify(a) === JSON.stringify(b);
}

// only what differs from the tier's default is stored, so later default changes still flow through
function overridesFrom(edit: Policy, def: Policy): Partial<Policy> {
  const out: Partial<Policy> = {};
  (Object.keys(def) as (keyof Policy)[]).forEach((k) => {
    if (!sameJson(edit[k], def[k])) (out as any)[k] = edit[k];
  });
  return out;
}

function problemsOf(p: Policy): Record<string, string> {
  const out: Record<string, string> = {};
  const n = p.publish_approvals.min_approvers;
  if (!Number.isInteger(n) || n < 0 || n > 10) out.min_approvers = 'Use a whole number from 0 to 10.';
  const m = p.publish_approvals.escalate_after_minutes;
  if (m !== undefined) {
    if (!Number.isInteger(m) || m < 0 || m > ESCALATE_MAX_MINUTES) out.escalate = `Use a whole number of minutes from 0 to ${ESCALATE_MAX_MINUTES}.`;
  } else {
    const h = p.publish_approvals.escalate_after_hours ?? 0;
    if (!Number.isInteger(h) || h < 0 || h > 720) out.escalate = 'Use a whole number of hours from 0 to 720.';
  }
  if (!CAP_RE.test(p.publish_approvals.capability)) {
    out.capability = 'Use approvals.sign, or approvals.sign:group such as approvals.sign:legal.';
  }
  return out;
}

export default function TierPolicies({
  tiers,
  canManage,
  onSaved,
}: {
  tiers: TierRow[];
  canManage: boolean;
  onSaved: () => void;
}) {
  return (
    <div className="space-y-5" data-testid="tier-policies">
      <p className="text-sm text-slate-400 max-w-3xl">
        Every agent, pipeline and tool carries a risk tier. A run starts at its agent&apos;s tier and rises when it uses a
        riskier tool. These policies say what each tier requires. Changes apply to new runs within five seconds.
      </p>
      {tiers.map((t) => (
        <TierCard key={t.tier} row={t} canManage={canManage} onSaved={onSaved} />
      ))}
    </div>
  );
}

function TierCard({ row, canManage, onSaved }: { row: TierRow; canManage: boolean; onSaved: () => void }) {
  const [edit, setEdit] = useState<Policy>(row.effective);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [modelDraft, setModelDraft] = useState('');
  const [unit, setUnit] = useState<EscalateUnit>(() => escalateUnit(row.effective.publish_approvals));
  const models = useSelectableModels();
  const style = TIER_STYLE[row.tier];

  useEffect(() => {
    setEdit(row.effective);
    setUnit(escalateUnit(row.effective.publish_approvals));
  }, [row.effective]);

  function setEscalate(raw: string, u: EscalateUnit) {
    const n = raw === '' ? NaN : Number(raw);
    if (u === 'hours') setApprovals({ escalate_after_hours: n, escalate_after_minutes: undefined });
    else setApprovals({ escalate_after_minutes: n, escalate_after_hours: 0 });
  }

  function switchUnit(u: EscalateUnit) {
    const minutes = escalateValue(edit.publish_approvals, 'minutes');
    setUnit(u);
    if (!Number.isFinite(minutes)) return;
    setEscalate(String(u === 'hours' ? Math.ceil(minutes / 60) : minutes), u);
  }

  const dirty = !sameJson(edit, row.effective);
  const customised = Object.keys(row.overrides || {}).length > 0;
  const problems = useMemo(() => problemsOf(edit), [edit]);
  const valid = Object.keys(problems).length === 0;

  function set<K extends keyof Policy>(k: K, v: Policy[K]) {
    setMsg(null);
    setEdit((e) => ({ ...e, [k]: v }));
  }
  function setApprovals(patch: Partial<Policy['publish_approvals']>) {
    setMsg(null);
    setEdit((e) => ({ ...e, publish_approvals: { ...e.publish_approvals, ...patch } }));
  }

  function addModel(raw: string) {
    const m = raw.trim();
    if (!m || edit.allowed_models.includes(m)) return setModelDraft('');
    set('allowed_models', [...edit.allowed_models, m]);
    setModelDraft('');
  }

  async function save() {
    setSaving(true);
    const r = await apiFetch<{ effective: Policy }>(`/api/governance/risk/${row.tier}`, {
      method: 'PUT',
      body: JSON.stringify(overridesFrom(edit, row.default)),
      throwOnError: false,
    });
    setSaving(false);
    if (r.data) {
      setMsg({ ok: true, text: 'Saved. New runs follow it within five seconds.' });
      onSaved();
    } else {
      setMsg({ ok: false, text: r.error || 'Could not save' });
    }
  }

  async function reset() {
    setSaving(true);
    const r = await apiFetch(`/api/governance/risk/${row.tier}`, { method: 'DELETE', throwOnError: false });
    setSaving(false);
    setConfirmReset(false);
    if (r.error) setMsg({ ok: false, text: r.error });
    else {
      setMsg({ ok: true, text: 'Back to the platform defaults.' });
      onSaved();
    }
  }

  const disabled = !canManage || saving;

  return (
    <section
      className={`rounded-xl border ${style.ring} bg-slate-900/50 p-5`}
      data-testid={`tier-card-${row.tier}`}
      aria-labelledby={`tier-${row.tier}-title`}
    >
      <header className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div className="min-w-0">
          <h2 id={`tier-${row.tier}-title`} className="flex items-center gap-2 text-lg font-semibold text-white">
            <span className={`w-2.5 h-2.5 rounded-full ${style.dot}`} aria-hidden />
            {style.label} risk
            {customised ? (
              <span className="text-[11px] font-normal px-2 py-0.5 rounded border border-cyan-500/30 bg-cyan-500/10 text-cyan-300">
                customised
              </span>
            ) : (
              <span className="text-[11px] font-normal px-2 py-0.5 rounded border border-slate-700 text-slate-400">
                platform defaults
              </span>
            )}
          </h2>
          <p className="text-sm text-slate-400 mt-1 max-w-2xl">{row.guide}</p>
        </div>
        {canManage && (
          <div className="flex items-center gap-2">
            {customised && (
              <button
                type="button"
                onClick={() => setConfirmReset(true)}
                disabled={saving}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs text-slate-300 border border-slate-700 hover:bg-slate-800 disabled:opacity-50"
                data-testid={`tier-reset-${row.tier}`}
              >
                <RotateCcw className="w-3.5 h-3.5" /> Use defaults
              </button>
            )}
            <button
              type="button"
              onClick={() => setEdit(row.effective)}
              disabled={!dirty || saving}
              className="px-3 py-1.5 rounded-md text-xs text-slate-300 border border-slate-700 hover:bg-slate-800 disabled:opacity-40"
            >
              Discard
            </button>
            <button
              type="button"
              onClick={save}
              disabled={!dirty || !valid || saving}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-cyan-500 text-white hover:bg-cyan-400 disabled:opacity-40 disabled:hover:bg-cyan-500"
              data-testid={`tier-save-${row.tier}`}
            >
              {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
              Save
            </button>
          </div>
        )}
      </header>

      <fieldset className="grid gap-5 md:grid-cols-2 min-w-0" disabled={!canManage} title={canManage ? undefined : 'View only. Changing this needs Manage risk.'}>
        <Field
          label="Sign-offs before a new version goes live"
          help="Applies when a decision model or an agent at this tier is published. 0 means no sign-off."
          error={problems.min_approvers}
        >
          <div className="flex items-center gap-3">
            <input
              type="number"
              min={0}
              max={10}
              value={edit.publish_approvals.min_approvers}
              onChange={(e) => setApprovals({ min_approvers: e.target.value === '' ? NaN : Number(e.target.value) })}
              disabled={disabled}
              aria-invalid={!!problems.min_approvers}
              className="w-20 bg-slate-950 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-white disabled:opacity-60"
              data-testid={`tier-min-approvers-${row.tier}`}
            />
            <label className="inline-flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={edit.publish_approvals.exclude_author}
                onChange={(e) => setApprovals({ exclude_author: e.target.checked })}
                disabled={disabled || edit.publish_approvals.min_approvers === 0}
                className="accent-cyan-500"
              />
              Author cannot sign their own change
            </label>
          </div>
        </Field>

        <Field
          label="Who can sign"
          help="People need this capability, granted under Admin, Permissions."
          error={problems.capability}
        >
          <input
            value={edit.publish_approvals.capability}
            onChange={(e) => setApprovals({ capability: e.target.value.trim() })}
            disabled={disabled || edit.publish_approvals.min_approvers === 0}
            aria-invalid={!!problems.capability}
            className="w-full bg-slate-950 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-white font-mono disabled:opacity-60"
            data-testid={`tier-capability-${row.tier}`}
          />
          <p className="mt-1 text-[11px] text-slate-400" data-testid={`tier-capability-words-${row.tier}`}>{capabilityWords(edit.publish_approvals.capability)}</p>
        </Field>

        <Field
          label="Tell admins when an approval waits longer than"
          help="Admins get one notification per approval left pending this long, checked every minute. 0 turns it off. Applies to approvals created after you save."
          error={problems.escalate}
        >
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={0}
              max={unit === 'hours' ? 720 : ESCALATE_MAX_MINUTES}
              value={(() => {
                const v = escalateValue(edit.publish_approvals, unit);
                return Number.isNaN(v) ? '' : v;
              })()}
              onChange={(e) => setEscalate(e.target.value, unit)}
              disabled={disabled}
              aria-invalid={!!problems.escalate}
              aria-label={`Escalate after, in ${unit}`}
              className="w-24 bg-slate-950 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-white disabled:opacity-60"
              data-testid={`tier-escalate-${row.tier}`}
            />
            <select
              value={unit}
              onChange={(e) => switchUnit(e.target.value as EscalateUnit)}
              disabled={disabled}
              aria-label="Escalation time unit"
              className="bg-slate-950 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-white disabled:opacity-60"
              data-testid={`tier-escalate-unit-${row.tier}`}
            >
              <option value="minutes">minutes</option>
              <option value="hours">hours</option>
            </select>
          </div>
        </Field>

        <Field
          label={`When a lower-tier run calls a ${style.label.toLowerCase()} risk tool`}
          help={ACTIONS.find((a) => a.value === edit.tool_call_action)?.help || ''}
        >
          <div className="inline-flex rounded-lg border border-slate-700 p-0.5 bg-slate-950" role="radiogroup">
            {ACTIONS.map((a) => (
              <button
                key={a.value}
                type="button"
                role="radio"
                aria-checked={edit.tool_call_action === a.value}
                onClick={() => set('tool_call_action', a.value)}
                disabled={disabled}
                className={`px-3 py-1.5 text-xs rounded-md transition disabled:opacity-60 ${
                  edit.tool_call_action === a.value ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'
                }`}
                data-testid={`tier-action-${row.tier}-${a.value}`}
              >
                {a.label}
              </button>
            ))}
          </div>
        </Field>

        <Field
          label="Output schema"
          help="An agent or pipeline at this tier cannot go live without a declared output shape, so its results can be checked."
        >
          <label className="inline-flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={edit.require_output_schema}
              onChange={(e) => set('require_output_schema', e.target.checked)}
              disabled={disabled}
              className="accent-cyan-500"
              data-testid={`tier-schema-${row.tier}`}
            />
            Required before going live
          </label>
        </Field>

        <Field
          label="Evaluation gate"
          help="A new version publishes only after each of its gating evaluation suites passes against that exact version."
        >
          <label className="inline-flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={!!edit.require_eval_pass}
              onChange={(e) => set('require_eval_pass', e.target.checked)}
              disabled={disabled}
              className="accent-cyan-500"
              data-testid={`tier-evals-${row.tier}`}
            />
            Gating suites must pass
          </label>
        </Field>

        <div className="md:col-span-2">
          <Field
            label="Allowed models"
            help="Leave empty to allow any model. End an entry with * to allow a family, for example claude-opus-*."
          >
            <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 min-h-[38px]">
              {edit.allowed_models.length === 0 && !canManage && <span className="text-sm text-slate-500">Any model</span>}
              {edit.allowed_models.map((m) => (
                <span key={m} className="inline-flex items-center gap-1 text-xs font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-200">
                  {m}
                  {canManage && (
                    <button
                      type="button"
                      onClick={() => set('allowed_models', edit.allowed_models.filter((x) => x !== m))}
                      aria-label={`Remove ${m}`}
                      className="text-slate-400 hover:text-white"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  )}
                </span>
              ))}
              {canManage && (
                <>
                  <input
                    list={`models-${row.tier}`}
                    value={modelDraft}
                    onChange={(e) => setModelDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ',') {
                        e.preventDefault();
                        addModel(modelDraft);
                      } else if (e.key === 'Backspace' && !modelDraft && edit.allowed_models.length) {
                        set('allowed_models', edit.allowed_models.slice(0, -1));
                      }
                    }}
                    onBlur={() => addModel(modelDraft)}
                    placeholder={edit.allowed_models.length ? 'Add another…' : 'Any model. Type to restrict…'}
                    className="flex-1 min-w-[160px] bg-transparent text-sm text-white outline-none placeholder:text-slate-500"
                    data-testid={`tier-models-${row.tier}`}
                  />
                  <datalist id={`models-${row.tier}`}>
                    {models.map((m) => (
                      <option key={m.value} value={m.value}>
                        {m.label}
                      </option>
                    ))}
                  </datalist>
                </>
              )}
            </div>
          </Field>
        </div>
      </fieldset>

      {msg && (
        <p
          role="status"
          className={`mt-4 text-sm inline-flex items-center gap-1.5 ${msg.ok ? 'text-emerald-300' : 'text-rose-300'}`}
          data-testid={`tier-msg-${row.tier}`}
        >
          {msg.ok ? <Check className="w-4 h-4" /> : <Info className="w-4 h-4" />} {msg.text}
        </p>
      )}
      {!canManage && (
        <p className="mt-4 text-xs text-slate-500">You can view these policies. Changing them needs Manage risk, which an admin can give you.</p>
      )}

      <ConfirmModal
        open={confirmReset}
        onClose={() => setConfirmReset(false)}
        onConfirm={reset}
        loading={saving}
        variant="warning"
        title={`Use the defaults for ${style.label.toLowerCase()} risk?`}
        description="Your changes to this tier are removed and the platform defaults apply to new runs within five seconds. The change is recorded in the audit log."
        confirmLabel="Use defaults"
      />
    </section>
  );
}

// the capability in words a rule owner knows
export function capabilityWords(cap: string): string {
  const [base, group] = String(cap || '').split(':');
  if (base !== 'approvals.sign') return `People granted ${cap} under Admin, Permissions.`;
  return group
    ? `People with Sign approvals for ${group}, granted under Admin, Permissions.`
    : 'Anyone with Sign approvals, which includes everyone in Decision reviewers.';
}

function Field({
  label,
  help,
  error,
  children,
}: {
  label: string;
  help?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="text-sm font-medium text-slate-200 mb-1.5">{label}</div>
      {children}
      {error ? (
        <p className="mt-1 text-xs text-rose-300" role="alert">
          {error}
        </p>
      ) : help ? (
        <p className="mt-1 text-xs text-slate-500">{help}</p>
      ) : null}
    </div>
  );
}
