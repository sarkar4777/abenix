'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Bell, Bot, Check, ChevronDown, ChevronRight, Copy, Globe, Loader2, Pause, Play, Plus, RotateCcw, Send, Trash2, Workflow, X,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useApi } from '@/hooks/useApi';
import { holds, useMyPermissions } from '@/lib/capabilities';
import { fetchAllAgents } from '@/lib/fetch-all-agents';
import ConfirmModal from '@/components/ui/ConfirmModal';

interface CatalogItem { type: string; description: string; sample: Record<string, unknown> }
interface Sub {
  id: string; name: string; url: string | null; events: string[]; filter: Record<string, unknown>;
  target_type: 'webhook' | 'agent' | 'pipeline'; target: { agent_id?: string; message?: string };
  is_active: boolean; consecutive_failures: number; disabled_reason: string | null; last_delivery_at: string | null;
}
interface Delivery {
  id: string; event: string; status: 'pending' | 'retrying' | 'delivered' | 'dead'; response_status_code: number | null;
  attempts: number; error_message: string | null; execution_id: string | null; next_attempt_at: string | null; created_at: string | null;
}

const STATUS: Record<Delivery['status'], string> = {
  pending: 'text-slate-300 border-slate-600',
  retrying: 'text-amber-300 border-amber-500/40',
  delivered: 'text-emerald-300 border-emerald-500/40',
  dead: 'text-rose-300 border-rose-500/40',
};
const TARGET_ICON = { webhook: Globe, agent: Bot, pipeline: Workflow } as const;

function ago(iso: string | null) {
  if (!iso) return '';
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.max(s, 0)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

function Deliveries({ sub, canManage }: { sub: Sub; canManage: boolean }) {
  const { data, mutate, isLoading } = useApi<Delivery[]>(`/api/webhooks/${sub.id}/deliveries?limit=25`, { refreshInterval: 4000 });
  const [open, setOpen] = useState<string | null>(null);
  async function redeliver(id: string) {
    await apiFetch(`/api/webhooks/deliveries/${id}/redeliver`, { method: 'POST', throwOnError: false });
    mutate();
  }
  if (isLoading && !data) return <div className="h-12 rounded bg-slate-800/40 animate-pulse" />;
  if (!data?.length) return <p className="text-xs text-slate-500">Nothing delivered yet. Send a test to see one here within seconds.</p>;
  return (
    <ul className="divide-y divide-slate-800" data-testid={`deliveries-${sub.id}`}>
      {data.map((d) => (
        <li key={d.id} className="py-1.5">
          <button type="button" onClick={() => setOpen(open === d.id ? null : d.id)} className="w-full flex flex-wrap items-center gap-2 text-xs text-left">
            {open === d.id ? <ChevronDown className="w-3 h-3 text-slate-500" /> : <ChevronRight className="w-3 h-3 text-slate-500" />}
            <span className={`px-1.5 py-0.5 rounded border ${STATUS[d.status]}`}>{d.status}</span>
            <span className="font-mono text-slate-300">{d.event}</span>
            {d.response_status_code && <span className="text-slate-500">HTTP {d.response_status_code}</span>}
            {d.attempts > 1 && <span className="text-slate-500">{d.attempts} attempts</span>}
            {d.status === 'retrying' && d.next_attempt_at && <span className="text-amber-300/80">next try {new Date(d.next_attempt_at).toLocaleTimeString()}</span>}
            <span className="ml-auto text-slate-500">{ago(d.created_at)}</span>
          </button>
          {open === d.id && (
            <div className="mt-1.5 ml-5 space-y-1 text-xs">
              {d.error_message && <p className="text-rose-300">{d.error_message}</p>}
              {d.execution_id && <a href={`/executions/${d.execution_id}`} className="text-cyan-300 hover:underline">Open the run it started</a>}
              {canManage && (d.status === 'dead' || d.status === 'retrying' || d.status === 'delivered') && (
                <button type="button" onClick={() => redeliver(d.id)} className="inline-flex items-center gap-1 text-cyan-300 hover:text-cyan-200" data-testid={`redeliver-${d.id}`}>
                  <RotateCcw className="w-3 h-3" /> Send again now
                </button>
              )}
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

function SubCard({ sub, catalog, agents, canManage, onChanged }: { sub: Sub; catalog: CatalogItem[]; agents: Map<string, string>; canManage: boolean; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [confirmDel, setConfirmDel] = useState(false);
  const Icon = TARGET_ICON[sub.target_type] || Globe;
  const where = sub.target_type === 'webhook' ? sub.url : `${sub.target_type === 'agent' ? 'Agent' : 'Pipeline'} ${agents.get(sub.target.agent_id || '') || sub.target.agent_id}`;

  async function test() {
    setBusy(true);
    const r = await apiFetch<{ event: string }>(`/api/webhooks/${sub.id}/test`, { method: 'POST', throwOnError: false });
    setBusy(false);
    setOpen(true);
    setMsg(r.error || `A sample ${r.data?.event} event is on its way. It shows in the log below within a few seconds.`);
  }
  async function toggle() {
    await apiFetch(`/api/webhooks/${sub.id}`, { method: 'PUT', body: JSON.stringify({ is_active: !sub.is_active }), throwOnError: false });
    onChanged();
  }
  async function del() {
    await apiFetch(`/api/webhooks/${sub.id}`, { method: 'DELETE', throwOnError: false });
    setConfirmDel(false);
    onChanged();
  }

  return (
    <article className={`rounded-xl border p-4 ${sub.is_active ? 'border-slate-800 bg-slate-900/50' : 'border-slate-800 bg-slate-900/20'}`} data-testid={`sub-${sub.name || sub.id}`}>
      <div className="flex flex-wrap items-start gap-3">
        <Icon className="w-5 h-5 text-cyan-400 mt-0.5" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-white">{sub.name || where}</span>
            {!sub.is_active && <span className="text-[10px] px-1.5 py-0.5 rounded border border-slate-600 text-slate-400">paused</span>}
            {sub.consecutive_failures > 0 && sub.is_active && <span className="text-[10px] text-amber-300">{sub.consecutive_failures} failed in a row</span>}
          </div>
          <div className="text-xs text-slate-400 truncate">{where}</div>
          <div className="flex flex-wrap gap-1 mt-1.5">
            {sub.events.map((e) => <span key={e} className="text-[11px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-300" title={catalog.find((c) => c.type === e)?.description}>{e}</span>)}
            {Object.entries(sub.filter || {}).map(([k, v]) => <span key={k} className="text-[11px] px-1.5 py-0.5 rounded border border-slate-700 text-slate-400">only when {k} = {Array.isArray(v) ? v.join(' or ') : String(v)}</span>)}
          </div>
          {sub.disabled_reason && <p className="mt-1.5 text-xs text-rose-300">{sub.disabled_reason} Resume it once the receiver is fixed.</p>}
        </div>
        {canManage && (
          <div className="flex items-center gap-1">
            <button type="button" onClick={test} disabled={busy || !sub.is_active} className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs border border-slate-700 text-slate-200 hover:bg-slate-800 disabled:opacity-40" data-testid={`sub-test-${sub.name || sub.id}`}>
              {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />} Send test
            </button>
            <button type="button" onClick={toggle} className="p-1.5 rounded text-slate-400 hover:text-white" aria-label={sub.is_active ? 'Pause' : 'Resume'} title={sub.is_active ? 'Pause' : 'Resume'}>
              {sub.is_active ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
            </button>
            <button type="button" onClick={() => setConfirmDel(true)} className="p-1.5 rounded text-slate-400 hover:text-rose-300" aria-label="Delete"><Trash2 className="w-4 h-4" /></button>
          </div>
        )}
      </div>
      {msg && <p className="mt-2 text-xs text-cyan-200" role="status">{msg}</p>}
      <button type="button" onClick={() => setOpen((o) => !o)} className="mt-2 inline-flex items-center gap-1 text-xs text-slate-400 hover:text-white">
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />} Delivery log
      </button>
      {open && <div className="mt-2"><Deliveries sub={sub} canManage={canManage} /></div>}
      <ConfirmModal open={confirmDel} onClose={() => setConfirmDel(false)} onConfirm={del} title={`Delete ${sub.name || 'this subscription'}?`} description="No further events are sent to it. Deliveries already made stay in the log until they age out." />
    </article>
  );
}

function CreateDialog({ catalog, agents, onClose, onCreated }: { catalog: CatalogItem[]; agents: { id: string; name: string; mode: string }[]; onClose: () => void; onCreated: (secret: string | null) => void }) {
  const [name, setName] = useState('');
  const [targetType, setTargetType] = useState<'webhook' | 'agent' | 'pipeline'>('webhook');
  const [url, setUrl] = useState('');
  const [agentId, setAgentId] = useState('');
  const [message, setMessage] = useState('A {{type}} event happened: {{data}}');
  const [events, setEvents] = useState<string[]>([]);
  const [filters, setFilters] = useState<{ k: string; v: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const groups = useMemo(() => {
    const m = new Map<string, CatalogItem[]>();
    catalog.forEach((c) => { const g = c.type.split('.')[0]; m.set(g, [...(m.get(g) || []), c]); });
    return Array.from(m.entries());
  }, [catalog]);
  const choices = agents.filter((a) => (targetType === 'pipeline' ? a.mode === 'pipeline' : a.mode !== 'pipeline'));
  const urlOk = targetType !== 'webhook' || /^https?:\/\/[^\s/$.?#].[^\s]*$/i.test(url.trim());
  const ready = events.length > 0 && urlOk && (targetType === 'webhook' ? url.trim() : agentId);
  const toggle = (t: string) => setEvents((e) => (e.includes(t) ? e.filter((x) => x !== t) : [...e, t]));
  const toggleGroup = (g: string) => setEvents((e) => (e.includes(`${g}.*`) ? e.filter((x) => x !== `${g}.*`) : [...e.filter((x) => !x.startsWith(`${g}.`)), `${g}.*`]));

  async function create() {
    setBusy(true);
    setErr(null);
    const filter = Object.fromEntries(filters.filter((f) => f.k.trim() && f.v.trim()).map((f) => [f.k.trim(), f.v.includes(',') ? f.v.split(',').map((s) => s.trim()) : f.v.trim()]));
    const r = await apiFetch<{ signing_secret?: string }>('/api/webhooks', {
      method: 'POST',
      body: JSON.stringify({ name, target_type: targetType, url: url.trim(), target: { agent_id: agentId, message }, events, filter }),
      throwOnError: false,
    });
    setBusy(false);
    if (r.error) setErr(r.error);
    else onCreated(r.data?.signing_secret ?? null);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-labelledby="sub-new-title">
      <div className="w-full max-w-2xl max-h-[90vh] flex flex-col rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800">
          <h2 id="sub-new-title" className="text-lg font-semibold text-white">New event subscription</h2>
          <button type="button" onClick={onClose} aria-label="Close"><X className="w-5 h-5 text-slate-400" /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          <div>
            <label className="block text-sm font-medium text-slate-200 mb-1.5" htmlFor="sub-name">Name</label>
            <input id="sub-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Reassess products when a rule is published" className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white" data-testid="sub-name" />
          </div>
          <div>
            <div className="text-sm font-medium text-slate-200 mb-1.5">When</div>
            <div className="space-y-2">
              {groups.map(([g, items]) => (
                <div key={g}>
                  <label className="flex items-center gap-2 text-xs text-slate-400 mb-1">
                    <input type="checkbox" checked={events.includes(`${g}.*`)} onChange={() => toggleGroup(g)} className="accent-cyan-500" /> every {g} event
                  </label>
                  <div className="grid gap-1 sm:grid-cols-2 pl-5">
                    {items.map((c) => (
                      <label key={c.type} className={`flex items-start gap-2 text-sm ${events.includes(`${g}.*`) ? 'opacity-50' : ''}`}>
                        <input type="checkbox" checked={events.includes(c.type) || events.includes(`${g}.*`)} disabled={events.includes(`${g}.*`)} onChange={() => toggle(c.type)} className="mt-1 accent-cyan-500" data-testid={`sub-event-${c.type}`} />
                        <span><span className="font-mono text-xs text-slate-200">{c.type}</span><span className="block text-xs text-slate-500">{c.description}</span></span>
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="text-sm font-medium text-slate-200 mb-1">Only when the event says <span className="font-normal text-slate-500">(optional)</span></div>
            {filters.map((f, i) => (
              <div key={i} className="flex items-center gap-2 mb-1">
                <input value={f.k} onChange={(e) => setFilters(filters.map((x, j) => (j === i ? { ...x, k: e.target.value } : x)))} placeholder="decision_key" className="w-48 bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-white font-mono" aria-label="Field" />
                <span className="text-xs text-slate-500">is</span>
                <input value={f.v} onChange={(e) => setFilters(filters.map((x, j) => (j === i ? { ...x, v: e.target.value } : x)))} placeholder="freight.remote.surcharge, or several with commas" className="flex-1 bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-white" aria-label="Value" />
                <button type="button" onClick={() => setFilters(filters.filter((_, j) => j !== i))} aria-label="Remove filter"><X className="w-4 h-4 text-slate-500" /></button>
              </div>
            ))}
            <button type="button" onClick={() => setFilters([...filters, { k: '', v: '' }])} className="inline-flex items-center gap-1 text-xs text-cyan-300"><Plus className="w-3.5 h-3.5" /> Add a condition</button>
            {events.length === 1 && catalog.find((c) => c.type === events[0]) && (
              <p className="text-[11px] text-slate-500 mt-1">Fields this event carries: {Object.keys(catalog.find((c) => c.type === events[0])!.sample).join(', ')}</p>
            )}
          </div>
          <div>
            <div className="text-sm font-medium text-slate-200 mb-1.5">Then</div>
            <div className="inline-flex rounded-lg border border-slate-700 p-0.5 bg-slate-950 mb-2" role="radiogroup">
              {(['webhook', 'agent', 'pipeline'] as const).map((t) => {
                const I = TARGET_ICON[t];
                return (
                  <button key={t} type="button" role="radio" aria-checked={targetType === t} onClick={() => { setTargetType(t); setAgentId(''); }} className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md ${targetType === t ? 'bg-slate-700 text-white' : 'text-slate-400'}`} data-testid={`sub-target-${t}`}>
                    <I className="w-3.5 h-3.5" /> {t === 'webhook' ? 'Call a URL' : t === 'agent' ? 'Run an agent' : 'Run a pipeline'}
                  </button>
                );
              })}
            </div>
            {targetType === 'webhook' ? (
              <>
                <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com/abenix-events" className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white" aria-invalid={!urlOk} data-testid="sub-url" />
                <p className={`text-[11px] mt-1 ${urlOk ? 'text-slate-500' : 'text-rose-300'}`}>{urlOk ? 'Each call is signed with HMAC-SHA256 in X-Abenix-Signature. Failed calls retry with growing gaps for about eight hours.' : 'Enter a full http or https URL.'}</p>
              </>
            ) : (
              <div className="space-y-2">
                <select value={agentId} onChange={(e) => setAgentId(e.target.value)} className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white" data-testid="sub-agent">
                  <option value="">Pick the {targetType} to run</option>
                  {choices.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
                <input value={message} onChange={(e) => setMessage(e.target.value)} className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white font-mono" aria-label="Message for the run" />
                <p className="text-[11px] text-slate-500">The run starts as you, with this message. Use {'{{data.decision_key}}'} and similar to fill in event fields. The whole event is also in the run&apos;s context.</p>
              </div>
            )}
          </div>
          {err && <p className="text-sm text-rose-300" role="alert">{err}</p>}
        </div>
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-slate-800">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-slate-300">Cancel</button>
          <button type="button" onClick={create} disabled={!ready || busy} className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white disabled:opacity-40" data-testid="sub-create">
            {busy && <Loader2 className="w-4 h-4 animate-spin" />} Create
          </button>
        </div>
      </div>
    </div>
  );
}

export default function EventsSettingsPage() {
  const { perms, loading: permsLoading } = useMyPermissions();
  const canManage = holds(perms?.capabilities, 'events.manage');
  const { data: subs, mutate, isLoading } = useApi<Sub[]>(canManage ? '/api/webhooks' : null);
  const { data: catalog } = useApi<CatalogItem[]>(canManage ? '/api/webhooks/catalog' : null);
  const [agents, setAgents] = useState<{ id: string; name: string; mode: string }[]>([]);
  const [creating, setCreating] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!canManage) return;
    fetchAllAgents<any>().then(({ agents }) => setAgents(agents.map((a) => ({ id: String(a.id), name: a.name, mode: (a.model_config?.mode || 'agent') === 'pipeline' ? 'pipeline' : 'agent' })))).catch(() => {});
  }, [canManage]);
  const names = useMemo(() => new Map(agents.map((a) => [a.id, a.name])), [agents]);

  if (permsLoading && !perms) {
    return (
      <div className="max-w-5xl mx-auto px-6 py-8" aria-busy="true">
        <div className="h-24 rounded-xl bg-slate-800/40 animate-pulse" />
      </div>
    );
  }

  if (!canManage) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-16 text-center" data-testid="events-no-access">
        <Bell className="w-10 h-10 text-slate-500 mx-auto mb-3" aria-hidden="true" />
        <h1 className="text-xl font-semibold text-white">Events</h1>
        <p className="text-slate-400 mt-2">Event subscriptions need the events.manage capability. An admin can grant it under Admin, Permissions.</p>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-2"><Bell className="w-6 h-6 text-cyan-400" /><h1 className="text-3xl font-semibold text-white">Events</h1></div>
          <p className="text-slate-400 max-w-3xl">
            React to what happens on the platform: call your system, or start an agent or pipeline, when a run finishes, a rule is published, an approval is decided or something is stopped. Events are recorded with the change itself, so none are lost, and failed deliveries retry on their own.
          </p>
        </div>
        {canManage && <button type="button" onClick={() => setCreating(true)} className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white" data-testid="sub-new"><Plus className="w-4 h-4" /> New subscription</button>}
      </header>

      {secret && (
        <div className="mb-4 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4" role="status" data-testid="sub-secret">
          <p className="text-sm text-amber-100">Your signing secret. It is shown only now. Use it to check X-Abenix-Signature on each call.</p>
          <div className="mt-2 flex items-center gap-2">
            <code className="flex-1 truncate rounded bg-slate-950 px-2 py-1 text-xs text-white">{secret}</code>
            <button type="button" onClick={() => { navigator.clipboard.writeText(secret); setCopied(true); }} className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs bg-slate-800 text-white">{copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />} {copied ? 'Copied' : 'Copy'}</button>
            <button type="button" onClick={() => setSecret(null)} aria-label="Dismiss"><X className="w-4 h-4 text-amber-200" /></button>
          </div>
        </div>
      )}

      {isLoading && !subs ? (
        <div className="space-y-3">{[0, 1].map((i) => <div key={i} className="h-24 rounded-xl bg-slate-800/40 animate-pulse" />)}</div>
      ) : !subs?.length ? (
        <div className="rounded-xl border border-dashed border-slate-700 p-8 text-center" data-testid="sub-empty">
          <Bell className="w-8 h-8 text-slate-600 mx-auto mb-2" />
          <p className="text-slate-300">No subscriptions yet.</p>
          <p className="text-sm text-slate-500 mt-1">For example, run an impact pipeline whenever a decision is published, or tell your ticketing system when a run fails.</p>
        </div>
      ) : (
        <div className="space-y-3">{subs.map((s) => <SubCard key={s.id} sub={s} catalog={catalog || []} agents={names} canManage={canManage} onChanged={mutate} />)}</div>
      )}

      {creating && (
        <CreateDialog catalog={catalog || []} agents={agents} onClose={() => setCreating(false)} onCreated={(s) => { setCreating(false); setSecret(s); setCopied(false); mutate(); }} />
      )}
    </div>
  );
}
