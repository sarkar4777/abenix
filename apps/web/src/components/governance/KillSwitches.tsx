'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Bot, Cpu, Globe, History, Loader2, OctagonX, Play, Radio, Scale, Search, Timer, Workflow, Wrench,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useApi } from '@/hooks/useApi';
import { fetchAllAgents } from '@/lib/fetch-all-agents';
import { useSelectableModels } from '@/lib/models';
import ConfirmModal from '@/components/ui/ConfirmModal';

type Scope = 'all' | 'agent' | 'pipeline' | 'tool' | 'model' | 'trigger' | 'decision' | 'source';

interface Switch {
  id: string;
  scope: Scope;
  target: string;
  active: boolean;
  reason: string;
  set_by: string | null;
  set_at: string | null;
  cleared_by: string | null;
  cleared_at: string | null;
}

interface Option {
  value: string;
  label: string;
  hint?: string;
}

const SCOPES: { value: Scope; label: string; icon: typeof Bot; help: string }[] = [
  { value: 'agent', label: 'An agent', icon: Bot, help: 'Stops one agent. New runs are refused and running ones stop at their next tool call.' },
  { value: 'pipeline', label: 'A pipeline', icon: Workflow, help: 'Stops one pipeline, including agents it is running.' },
  { value: 'tool', label: 'A tool', icon: Wrench, help: 'Every call to this tool is refused, in every agent and pipeline.' },
  { value: 'model', label: 'A model', icon: Cpu, help: 'Runs that would use this model are refused before any tokens are spent.' },
  { value: 'trigger', label: 'A trigger', icon: Timer, help: 'Schedules and webhooks for this trigger stop firing.' },
  { value: 'decision', label: 'A decision', icon: Scale, help: 'The decision model refuses evaluations until resumed.' },
  { value: 'source', label: 'A watched source', icon: Radio, help: 'Change detection for this source pauses.' },
  { value: 'all', label: 'Everything', icon: Globe, help: 'Stops every agent, pipeline and tool call in this tenant. Use for an incident.' },
];

function when(iso: string | null) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export default function KillSwitches({
  canManage,
  tools,
}: {
  canManage: boolean;
  tools: { tool: string; tier: string }[];
}) {
  const [showHistory, setShowHistory] = useState(false);
  const { data, isLoading, error, mutate } = useApi<{ switches: Switch[] }>(
    `/api/governance/kill-switches${showHistory ? '?include_cleared=true' : ''}`,
  );
  const [agents, setAgents] = useState<{ id: string; name: string; mode: string }[]>([]);
  const models = useSelectableModels(true);
  const { data: triggers } = useApi<any[]>('/api/triggers');

  useEffect(() => {
    let live = true;
    fetchAllAgents<any>()
      .then(({ agents }) => {
        if (!live) return;
        setAgents(
          agents.map((a) => ({
            id: String(a.id),
            name: a.name,
            mode: (a.model_config?.mode || a.model_config_?.mode || 'agent') === 'pipeline' ? 'pipeline' : 'agent',
          })),
        );
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  const names = useMemo(() => {
    const m = new Map<string, string>();
    agents.forEach((a) => m.set(a.id, a.name));
    (Array.isArray(triggers) ? triggers : []).forEach((t: any) => m.set(String(t.id), t.name || String(t.id)));
    return m;
  }, [agents, triggers]);

  const optionsFor = (scope: Scope): Option[] => {
    if (scope === 'agent' || scope === 'pipeline') {
      return agents.filter((a) => a.mode === scope).map((a) => ({ value: a.id, label: a.name }));
    }
    if (scope === 'tool') return tools.map((t) => ({ value: t.tool, label: t.tool, hint: `${t.tier} risk` }));
    if (scope === 'model') return models.map((m) => ({ value: m.value, label: m.label, hint: m.provider }));
    if (scope === 'trigger') {
      return (Array.isArray(triggers) ? triggers : []).map((t: any) => ({ value: String(t.id), label: t.name || String(t.id), hint: t.trigger_type }));
    }
    return [];
  };

  const active = (data?.switches || []).filter((s) => s.active);
  const cleared = (data?.switches || []).filter((s) => !s.active);

  return (
    <div className="space-y-6" data-testid="kill-switches">
      <p className="text-sm text-slate-400 max-w-3xl">
        A kill switch stops something straight away, across every pod, within five seconds. Nothing is deleted. Resume it
        when the problem is fixed. Every stop and resume is written to the audit log with its reason.
      </p>

      {canManage ? (
        <NewSwitch optionsFor={optionsFor} onDone={mutate} />
      ) : (
        <p className="text-xs text-slate-500">Setting or resuming a kill switch needs the killswitch.manage capability.</p>
      )}

      <section aria-labelledby="active-switches">
        <div className="flex items-center justify-between mb-3">
          <h3 id="active-switches" className="text-sm font-semibold text-white">
            Stopped now {active.length > 0 && <span className="ml-1 text-rose-300">({active.length})</span>}
          </h3>
          <button
            type="button"
            onClick={() => setShowHistory((v) => !v)}
            className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-white"
            aria-pressed={showHistory}
            data-testid="kill-switch-history-toggle"
          >
            <History className="w-3.5 h-3.5" /> {showHistory ? 'Hide resumed' : 'Show resumed'}
          </button>
        </div>
        {isLoading && !data ? (
          <div className="h-20 rounded-lg bg-slate-800/40 animate-pulse" />
        ) : error ? (
          <p className="text-sm text-rose-300">{error}</p>
        ) : active.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-700 p-6 text-center text-sm text-slate-400" data-testid="kill-switch-empty">
            Nothing is stopped. Everything runs normally.
          </div>
        ) : (
          <ul className="space-y-2">
            {active.map((s) => (
              <SwitchRow key={s.id} s={s} name={names.get(s.target)} canManage={canManage} onDone={mutate} />
            ))}
          </ul>
        )}
        {showHistory && cleared.length > 0 && (
          <ul className="space-y-2 mt-4 opacity-80">
            {cleared.map((s) => (
              <SwitchRow key={s.id} s={s} name={names.get(s.target)} canManage={false} onDone={mutate} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function SwitchRow({ s, name, canManage, onDone }: { s: Switch; name?: string; canManage: boolean; onDone: () => void }) {
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const meta = SCOPES.find((x) => x.value === s.scope);
  const Icon = meta?.icon || OctagonX;
  const what = s.scope === 'all' ? 'Everything in this tenant' : `${meta?.label.replace(/^An? /, '') || s.scope} ${name || s.target}`;

  async function resume() {
    setBusy(true);
    const r = await apiFetch(`/api/governance/kill-switches/${s.id}/clear`, { method: 'POST', throwOnError: false });
    setBusy(false);
    setConfirm(false);
    if (r.error) setErr(r.error);
    else onDone();
  }

  return (
    <li
      className={`rounded-lg border px-4 py-3 flex flex-wrap items-center gap-3 ${
        s.active ? 'border-rose-500/30 bg-rose-500/5' : 'border-slate-700 bg-slate-900/40'
      }`}
      data-testid={`kill-switch-${s.scope}-${s.target}`}
    >
      <Icon className={`w-4 h-4 ${s.active ? 'text-rose-300' : 'text-slate-500'}`} aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="text-sm text-white truncate">
          {what}
          {name && s.target !== '*' && <span className="ml-2 text-xs font-mono text-slate-500">{s.target}</span>}
        </div>
        <div className="text-xs text-slate-400 mt-0.5">
          {s.reason} · stopped {when(s.set_at)}
          {!s.active && s.cleared_at && <> · resumed {when(s.cleared_at)}</>}
        </div>
        {err && <div className="text-xs text-rose-300 mt-1">{err}</div>}
      </div>
      {s.active && canManage && (
        <button
          type="button"
          onClick={() => setConfirm(true)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/10"
          data-testid={`kill-switch-resume-${s.id}`}
        >
          <Play className="w-3.5 h-3.5" /> Resume
        </button>
      )}
      <ConfirmModal
        open={confirm}
        onClose={() => setConfirm(false)}
        onConfirm={resume}
        loading={busy}
        variant="warning"
        icon={Play}
        title={`Resume ${what}?`}
        description="It starts running again within five seconds. Runs that were refused are not retried by themselves."
        confirmLabel="Resume"
      />
    </li>
  );
}

function NewSwitch({ optionsFor, onDone }: { optionsFor: (s: Scope) => Option[]; onDone: () => void }) {
  const [scope, setScope] = useState<Scope>('agent');
  const [target, setTarget] = useState('');
  const [query, setQuery] = useState('');
  const [reason, setReason] = useState('');
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const options = optionsFor(scope);
  const freeText = scope === 'decision' || scope === 'source';
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q ? options.filter((o) => o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q)) : options;
    return list.slice(0, 50);
  }, [options, query]);
  const chosen = options.find((o) => o.value === target);
  const needsTarget = scope !== 'all';
  const reasonOk = reason.trim().length >= 3;
  const ready = (!needsTarget || target.trim()) && reasonOk;
  const meta = SCOPES.find((s) => s.value === scope)!;
  const what = scope === 'all' ? 'everything in this tenant' : `${meta.label.replace(/^An? /, '').toLowerCase()} ${chosen?.label || target}`;

  function pickScope(s: Scope) {
    setScope(s);
    setTarget('');
    setQuery('');
    setMsg(null);
  }

  async function submit() {
    setBusy(true);
    const r = await apiFetch(`/api/governance/kill-switches`, {
      method: 'POST',
      body: JSON.stringify({ scope, target: needsTarget ? target.trim() : '*', reason: reason.trim() }),
      throwOnError: false,
    });
    setBusy(false);
    setConfirm(false);
    if (r.error) setMsg({ ok: false, text: r.error });
    else {
      setMsg({ ok: true, text: `Stopped ${what}. It takes effect everywhere within five seconds.` });
      setTarget('');
      setQuery('');
      setReason('');
      onDone();
    }
  }

  return (
    <section className="rounded-xl border border-slate-700 bg-slate-900/50 p-5" aria-labelledby="new-switch" data-testid="kill-switch-new">
      <h3 id="new-switch" className="text-sm font-semibold text-white mb-3">Stop something</h3>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-2" role="radiogroup" aria-label="What to stop">
        {SCOPES.map((s) => {
          const Icon = s.icon;
          const on = scope === s.value;
          return (
            <button
              key={s.value}
              type="button"
              role="radio"
              aria-checked={on}
              onClick={() => pickScope(s.value)}
              className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-sm text-left transition ${
                on
                  ? s.value === 'all'
                    ? 'border-rose-500/60 bg-rose-500/10 text-white'
                    : 'border-cyan-500/60 bg-cyan-500/10 text-white'
                  : 'border-slate-700 text-slate-300 hover:border-slate-500'
              }`}
              data-testid={`kill-switch-scope-${s.value}`}
            >
              <Icon className="w-4 h-4 shrink-0" /> {s.label}
            </button>
          );
        })}
      </div>
      <p className="text-xs text-slate-400 mb-4">{meta.help}</p>

      {needsTarget && (
        <div className="mb-4">
          <label className="block text-sm font-medium text-slate-200 mb-1.5" htmlFor="ks-target">
            Which one
          </label>
          {freeText ? (
            <input
              id="ks-target"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              placeholder={scope === 'decision' ? 'Decision key, for example fertiliser-cbam-eligibility' : 'Source id'}
              className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white"
              data-testid="kill-switch-target"
            />
          ) : (
            <div className="rounded-md border border-slate-700 bg-slate-950">
              <div className="flex items-center gap-2 px-3 border-b border-slate-800">
                <Search className="w-4 h-4 text-slate-500" />
                <input
                  id="ks-target"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={options.length ? `Search ${options.length} ${scope}s…` : `Loading ${scope}s…`}
                  className="flex-1 bg-transparent py-2 text-sm text-white outline-none"
                  data-testid="kill-switch-search"
                />
              </div>
              <ul className="max-h-48 overflow-y-auto py-1" role="listbox" aria-label={`${scope}s`}>
                {filtered.length === 0 && (
                  <li className="px-3 py-2 text-sm text-slate-500">
                    {options.length ? 'Nothing matches.' : `No ${scope}s in this tenant yet.`}
                  </li>
                )}
                {filtered.map((o) => (
                  <li key={o.value}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={target === o.value}
                      onClick={() => setTarget(o.value)}
                      className={`w-full flex items-center justify-between gap-2 px-3 py-1.5 text-sm text-left ${
                        target === o.value ? 'bg-cyan-500/15 text-white' : 'text-slate-300 hover:bg-slate-800'
                      }`}
                    >
                      <span className="truncate">{o.label}</span>
                      {o.hint && <span className="text-xs text-slate-500 shrink-0">{o.hint}</span>}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      <div className="mb-4">
        <label className="block text-sm font-medium text-slate-200 mb-1.5" htmlFor="ks-reason">
          Reason
        </label>
        <input
          id="ks-reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="What went wrong. People who hit the stop will see this."
          className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white"
          data-testid="kill-switch-reason"
        />
        {reason && !reasonOk && <p className="mt-1 text-xs text-rose-300">Give a reason of at least three characters.</p>}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => setConfirm(true)}
          disabled={!ready || busy}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-rose-600 text-white hover:bg-rose-500 disabled:opacity-40 disabled:hover:bg-rose-600"
          data-testid="kill-switch-submit"
        >
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <OctagonX className="w-4 h-4" />}
          Stop {needsTarget ? (chosen?.label || target || 'it') : 'everything'}
        </button>
        {!ready && (
          <span className="text-xs text-slate-500">
            {needsTarget && !target.trim() ? 'Pick what to stop, then give a reason.' : 'Give a reason.'}
          </span>
        )}
        {msg && (
          <span role="status" className={`text-sm ${msg.ok ? 'text-emerald-300' : 'text-rose-300'}`} data-testid="kill-switch-msg">
            {msg.text}
          </span>
        )}
      </div>

      <ConfirmModal
        open={confirm}
        onClose={() => setConfirm(false)}
        onConfirm={submit}
        loading={busy}
        icon={OctagonX}
        title={`Stop ${what}?`}
        description={`${meta.help} This is recorded in the audit log with your reason.`}
        confirmLabel="Stop it"
      />
    </section>
  );
}
