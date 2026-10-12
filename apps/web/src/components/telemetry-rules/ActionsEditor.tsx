'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { AlertTriangle, Bell, Bot, Plus, Scale, Send, Siren, Trash2, type LucideIcon } from 'lucide-react';
import { ACTION_INFO, answeringSteps, type Action, type ActionKind, type Condition, type Options, type Scope } from './lib';
import RunStepPanel from './RunStepPanel';
import SignalPicker from './SignalPicker';
import { Field, cls } from './ui';

const ICONS: Record<ActionKind, LucideIcon> = { alert: Siren, notify: Bell, run: Bot, decision: Scale, command: Send };
const KINDS = Object.keys(ACTION_INFO) as ActionKind[];
const PLACEHOLDERS = '{{rule}}, {{asset}}, {{signal}}, {{value}} and {{detail}} are filled in when it fires.';

function blank(kind: ActionKind): Action {
  switch (kind) {
    case 'alert': return { kind, severity: null };
    case 'notify': return { kind, channel: 'in_app', to: [], message: '' };
    case 'run': return { kind, agent_id: '', message: '', wait: true };
    case 'decision': return { kind, key: '', facts: {} };
    case 'command': return { kind, signal: 'Safety/Hold', value: 'true' };
  }
}

function People({ value, onChange, options, disabled }: { value: string[]; onChange: (v: string[]) => void; options: Options['people']; disabled?: boolean }) {
  const [q, setQ] = useState('');
  const list = useMemo(() => {
    const ql = q.toLowerCase();
    return options.filter((p) => !ql || p.name.toLowerCase().includes(ql) || p.email.toLowerCase().includes(ql)).slice(0, 50);
  }, [options, q]);
  const picked = new Set(value);
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-2">
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search people" disabled={disabled} className={`${cls()} mb-2 min-h-[36px] py-1.5`} aria-label="Search people" />
      <div className="max-h-40 space-y-0.5 overflow-auto">
        {list.map((p) => (
          <label key={p.id} className="flex min-h-[32px] cursor-pointer items-center gap-2 rounded px-1.5 text-sm text-slate-200 hover:bg-slate-800">
            <input type="checkbox" className="accent-cyan-500" checked={picked.has(p.id)} disabled={disabled}
              onChange={(e) => onChange(e.target.checked ? [...value, p.id] : value.filter((x) => x !== p.id))} />
            <span className="min-w-0 flex-1 truncate">{p.name}</span>
            <span className="hidden truncate text-xs text-slate-500 sm:inline">{p.email}</span>
          </label>
        ))}
        {!list.length && <p className="px-1.5 py-1 text-xs text-slate-500">Nobody matches.</p>}
      </div>
    </div>
  );
}

function Facts({ value, onChange, disabled }: { value: Record<string, string>; onChange: (v: Record<string, string>) => void; disabled?: boolean }) {
  const rows = Object.entries(value);
  return (
    <div className="space-y-1.5">
      {rows.map(([k, v], i) => (
        <div key={i} className="flex items-center gap-2">
          <input value={k} disabled={disabled} aria-label="Fact name" placeholder="limit_bar"
            onChange={(e) => { const next: Record<string, string> = {}; rows.forEach(([kk, vv], j) => { next[j === i ? e.target.value : kk] = vv; }); onChange(next); }}
            className={`${cls()} min-h-[36px] py-1.5 font-mono`} />
          <input value={v} disabled={disabled} aria-label="Fact value" placeholder="{{value}}"
            onChange={(e) => onChange({ ...value, [k]: e.target.value })}
            className={`${cls()} min-h-[36px] py-1.5 font-mono`} />
          {!disabled && (
            <button type="button" aria-label={`Remove fact ${k}`} onClick={() => { const next = { ...value }; delete next[k]; onChange(next); }} className="rounded p-1.5 text-slate-400 hover:bg-slate-800 hover:text-rose-300">
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      ))}
      {!disabled && (
        <button type="button" onClick={() => onChange({ ...value, [`fact_${rows.length + 1}`]: '{{value}}' })} className="inline-flex min-h-[32px] items-center gap-1 rounded-md border border-slate-700 px-2 text-xs text-slate-300 hover:bg-slate-800" data-testid="action-add-fact">
          <Plus className="h-3.5 w-3.5" /> Add a fact
        </button>
      )}
    </div>
  );
}

function stepsHelp(actions: Action[], i: number): string {
  const earlier = answeringSteps(actions, i);
  if (!earlier.length) return '';
  const n = earlier[earlier.length - 1].n;
  return ` An earlier step's answer goes in as {steps.${n}.output}, or one field of it like {steps.${n}.output.severity}.`;
}

function ActionBody({ a, i, set, errors, options, scope, disabled, actions, condition, ruleId, ruleName }: {
  a: Action; i: number; set: (p: Partial<Action>) => void; errors: Record<string, string>; options: Options | null; scope: Scope; disabled?: boolean;
  actions: Action[]; condition?: Condition; ruleId?: string; ruleName?: string;
}) {
  const e = (k: string) => errors[`actions.${i}.${k}`];
  const refs = stepsHelp(actions, i);
  if (a.kind === 'alert') {
    return (
      <Field label="Severity" htmlFor={`a${i}-sev`} help="The alert clears by itself when the rule clears.">
        <select id={`a${i}-sev`} value={a.severity || ''} disabled={disabled} onChange={(ev) => set({ severity: (ev.target.value || null) as Action['severity'] })} className={cls()} data-testid={`action-${i}-severity`}>
          <option value="">Same as the rule</option>
          <option value="info">Info</option>
          <option value="warning">Warning</option>
          <option value="critical">Critical</option>
        </select>
      </Field>
    );
  }
  if (a.kind === 'notify') {
    return (
      <div className="space-y-3">
        <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="How to tell them">
          {(['in_app', 'email', 'slack'] as const).map((ch) => (
            <label key={ch} className={`flex min-h-[40px] cursor-pointer items-center gap-2 rounded-lg border px-3 text-sm ${a.channel === ch ? 'border-cyan-500/70 bg-cyan-500/10 text-cyan-100' : 'border-slate-700 text-slate-300'}`}>
              <input type="radio" className="accent-cyan-500" checked={a.channel === ch} disabled={disabled} onChange={() => set({ channel: ch })} data-testid={`action-${i}-channel-${ch}`} />
              {ch === 'in_app' ? 'In Abenix' : ch === 'email' ? 'By email' : 'Workspace Slack'}
            </label>
          ))}
        </div>
        {a.channel !== 'slack' ? (
          <Field label="Who" error={e('to')} help={a.to?.length ? `${a.to.length} picked.` : 'Nobody picked means the workspace admins.'}>
            <People value={a.to || []} onChange={(to) => set({ to })} options={options?.people || []} disabled={disabled} />
          </Field>
        ) : (
          <p className="text-xs text-slate-400">Posts to the Slack channel set under <Link href="/settings/notifications" className="text-cyan-300 hover:underline">Settings, Notifications</Link>.</p>
        )}
        <Field label="Message" htmlFor={`a${i}-msg`} error={e('message')} help={`Optional. Without one it says why the rule fired. ${PLACEHOLDERS}${refs}`}>
          <textarea id={`a${i}-msg`} rows={2} value={a.message || ''} disabled={disabled} onChange={(ev) => set({ message: ev.target.value })} placeholder="{{asset}}: {{detail}}" className={cls()} data-testid={`action-${i}-message`} />
        </Field>
      </div>
    );
  }
  if (a.kind === 'run') {
    const agents = options?.agents || [];
    return (
      <div className="space-y-3">
        <Field label="Agent or pipeline" htmlFor={`a${i}-agent`} error={e('agent_id')} help="It runs as the person who saves the rule, with the firing as its context.">
          <select id={`a${i}-agent`} value={a.agent_id || ''} disabled={disabled} onChange={(ev) => set({ agent_id: ev.target.value })} className={cls(e('agent_id'))} data-testid={`action-${i}-agent`}>
            <option value="">{options ? (agents.length ? 'Pick one' : 'No agents yet') : 'Loading'}</option>
            <optgroup label="Pipelines">{agents.filter((x) => x.kind === 'pipeline').map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</optgroup>
            <optgroup label="Agents">{agents.filter((x) => x.kind === 'agent').map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</optgroup>
          </select>
        </Field>
        <Field label="Message to it" htmlFor={`a${i}-runmsg`} error={e('message')} help={`Optional. Without one it gets the rule, the asset key, the signal, its value and the recent trend. ${PLACEHOLDERS}${refs} The full firing is also in its context under telemetry.`}>
          <textarea id={`a${i}-runmsg`} rows={2} value={a.message || ''} disabled={disabled} onChange={(ev) => set({ message: ev.target.value })} placeholder="Signal rule {{rule}} fired: {{detail}}" className={cls(e('message'))} data-testid={`action-${i}-run-message`} />
        </Field>
        <RunStepPanel a={a} i={i} set={set} errors={errors} options={options} scope={scope} condition={condition} ruleId={ruleId} ruleName={ruleName} disabled={disabled} />
      </div>
    );
  }
  if (a.kind === 'decision') {
    const ds = options?.decisions || [];
    return (
      <div className="space-y-3">
        <Field label="Decision table" htmlFor={`a${i}-dec`} error={e('key')} help={ds.length || !options ? 'The result is kept with the firing.' : undefined}>
          <select id={`a${i}-dec`} value={a.key || ''} disabled={disabled} onChange={(ev) => set({ key: ev.target.value })} className={cls(e('key'))} data-testid={`action-${i}-decision`}>
            <option value="">{options ? (ds.length ? 'Pick one' : 'No decision tables yet') : 'Loading'}</option>
            {ds.map((d) => <option key={d.key} value={d.key}>{d.name} ({d.key})</option>)}
          </select>
        </Field>
        {options && !ds.length && <p className="text-xs text-slate-400"><Link href="/decisions" className="text-cyan-300 hover:underline">Make a decision table</Link> first, then pick it here.</p>}
        <Field label="Extra facts" error={e('facts')} help={`It already gets signal, value, group, node, device, asset, asset_type, tags, rule, severity and the asset's details. Add facts the table needs here, with placeholders.${refs}`}>
          <Facts value={a.facts || {}} onChange={(facts) => set({ facts })} disabled={disabled} />
        </Field>
      </div>
    );
  }
  // command
  const other = !!a.node;
  const target: Scope = other
    ? { kind: 'asset', group: a.group || scope.group, node: a.node, device: a.device ?? '' }
    : scope.kind === 'asset' ? { ...scope } : scope;
  return (
    <div className="space-y-3">
      <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-100" role="note">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>Commands go out at once, without an approval, through the asset&apos;s source. The audit log keeps the rule as the reason. Send a safe value, like a hold.</span>
      </div>
      {e('kind') && <p className="text-xs text-rose-300" role="alert">{e('kind')}</p>}
      <Field label="Send it to" htmlFor={`a${i}-tgt`}>
        <select id={`a${i}-tgt`} value={other ? 'other' : 'same'} disabled={disabled}
          onChange={(ev) => set(ev.target.value === 'same' ? { group: undefined, node: undefined, device: undefined } : { group: scope.group, node: scope.node || '', device: '' })}
          className={cls()} data-testid={`action-${i}-target`}>
          <option value="same">The asset that fired</option>
          <option value="other" disabled={scope.kind !== 'asset'}>One named asset</option>
        </select>
      </Field>
      {other && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Asset id" htmlFor={`a${i}-node`}><input id={`a${i}-node`} value={a.node || ''} disabled={disabled} onChange={(ev) => set({ node: ev.target.value })} className={cls()} /></Field>
          <Field label="Part (empty for the asset itself)" htmlFor={`a${i}-dev`}><input id={`a${i}-dev`} value={a.device || ''} disabled={disabled} onChange={(ev) => set({ device: ev.target.value })} className={cls()} /></Field>
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <SignalPicker value={a.signal || ''} onChange={(v) => set({ signal: v })} scope={target} label="Signal to set" error={e('signal')} testId={`action-${i}-signal`} disabled={disabled} prefer="any" />
        <Field label="Value" htmlFor={`a${i}-val`} error={e('value')} help={`true, false, a number or text.${refs}`}>
          <input id={`a${i}-val`} value={a.value === null || a.value === undefined ? '' : String(a.value)} disabled={disabled} onChange={(ev) => set({ value: ev.target.value })} className={cls(e('value'))} data-testid={`action-${i}-value`} />
        </Field>
      </div>
    </div>
  );
}

export default function ActionsEditor({
  actions, onChange, errors, options, scope, disabled, condition, ruleId, ruleName,
}: { actions: Action[]; onChange: (a: Action[]) => void; errors: Record<string, string>; options: Options | null; scope: Scope; disabled?: boolean; condition?: Condition; ruleId?: string; ruleName?: string }) {
  const canCommand = !!options?.can_command;
  return (
    <div className="space-y-3">
      {actions.length === 0 && (
        <p className="rounded-lg border border-dashed border-slate-700 px-3 py-3 text-sm text-slate-400" data-testid="actions-empty">
          No steps yet. The rule still keeps a history of firings and sends the telemetry.rule_fired event to webhooks. Add a step to act on it.
        </p>
      )}
      {actions.map((a, i) => {
        const Icon = ICONS[a.kind];
        return (
          <div key={i} className="rounded-lg border border-slate-700/70 bg-slate-950/40 p-3" data-testid={`action-${i}`} data-kind={a.kind}>
            <div className="mb-2 flex items-center gap-2">
              <span className="inline-flex h-6 w-6 items-center justify-center rounded bg-slate-800 text-[11px] text-slate-400">{i + 1}</span>
              <Icon className="h-4 w-4 text-cyan-300" aria-hidden />
              <span className="min-w-0 flex-1 truncate text-sm font-medium text-white">{ACTION_INFO[a.kind].label}</span>
              {!disabled && (
                <button type="button" onClick={() => onChange(actions.filter((_, j) => j !== i))} className="inline-flex min-h-[32px] items-center gap-1 rounded-md px-2 text-xs text-slate-400 hover:bg-slate-800 hover:text-rose-300" aria-label={`Remove step ${i + 1}`} data-testid={`action-${i}-remove`}>
                  <Trash2 className="h-3.5 w-3.5" /> Remove
                </button>
              )}
            </div>
            <ActionBody a={a} i={i} set={(p) => onChange(actions.map((x, j) => (j === i ? { ...x, ...p } : x)))} errors={errors} options={options} scope={scope} disabled={disabled}
              actions={actions} condition={condition} ruleId={ruleId} ruleName={ruleName} />
          </div>
        );
      })}
      {errors.actions && <p className="text-xs text-rose-300" role="alert">{errors.actions}</p>}
      {!disabled && actions.length < 8 && (
        <div>
          <p className="mb-1.5 text-xs font-medium text-slate-300">Add a step</p>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {KINDS.map((k) => {
              const Icon = ICONS[k];
              const blocked = k === 'command' && !canCommand;
              return (
                <button
                  key={k}
                  type="button"
                  disabled={blocked}
                  title={blocked ? 'Sending commands needs Send machine commands. An admin can add you to Machine operators under Admin, Permissions.' : ACTION_INFO[k].help}
                  onClick={() => onChange([...actions, blank(k)])}
                  className="flex min-h-[44px] items-start gap-2 rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2 text-left hover:border-slate-500 disabled:cursor-not-allowed disabled:opacity-50"
                  data-testid={`add-action-${k}`}
                >
                  <Icon className="mt-0.5 h-4 w-4 shrink-0 text-cyan-300" aria-hidden />
                  <span className="min-w-0">
                    <span className="block text-sm text-slate-100">{ACTION_INFO[k].label}</span>
                    <span className="block text-xs text-slate-500">{blocked ? 'Needs Send machine commands' : ACTION_INFO[k].help}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
