'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { FileJson, Layers, Loader2, Plus, Scale, Search, Sparkles, Upload, X } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useApi } from '@/hooks/useApi';
import { holds, useMyPermissions } from '@/lib/capabilities';
import { CLIENT_SAMPLE, KEY_RE, STATE_STYLE, type Tier, type VersionSummary } from '@/lib/decisions';
import { TIER_STYLE } from '@/components/governance/TierPolicies';

interface ModelRow {
  id: string;
  key: string;
  name: string;
  description: string;
  risk_tier: Tier;
  tags: string[];
  updated_at: string | null;
  published: VersionSummary[];
  drafts: VersionSummary[];
  proposed: VersionSummary[];
  latest_version: number;
}

function when(iso: string | null) {
  return iso ? new Date(iso).toLocaleDateString(undefined, { dateStyle: 'medium' }) : '';
}

export default function DecisionsPage() {
  const { perms } = useMyPermissions();
  const canAuthor = holds(perms?.capabilities, 'decisions.author');
  const canView = holds(perms?.capabilities, 'decisions.view');
  const [q, setQ] = useState('');
  const { data, isLoading, error } = useApi<ModelRow[]>(canView ? '/api/decisions' : null);
  const [creating, setCreating] = useState<null | 'blank' | 'import' | 'example'>(null);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (data || []).filter(
      (m) => !needle || m.name.toLowerCase().includes(needle) || m.key.includes(needle) || m.tags.some((t) => t.toLowerCase().includes(needle)),
    );
  }, [data, q]);

  if (perms && !canView) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-16 text-center">
        <Scale className="w-10 h-10 text-slate-500 mx-auto mb-3" />
        <h1 className="text-xl font-semibold text-white">Decisions</h1>
        <p className="text-slate-400 mt-2">Viewing decisions needs the decisions.view capability. An admin can grant it under Admin, Permissions.</p>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <Scale className="w-6 h-6 text-cyan-400" />
            <h1 className="text-3xl font-semibold text-white">Decisions</h1>
          </div>
          <p className="text-slate-400 max-w-3xl">
            Business rules that give the same answer every time, with a trace of why. Write them in plain terms, test
            them, get them signed off, and agents, pipelines and apps evaluate them through the API.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/decisions/reference-sets" className="inline-flex items-center gap-1.5 px-3 py-2 rounded-md text-sm text-slate-300 border border-slate-700 hover:bg-slate-800">
            <Layers className="w-4 h-4" /> Reference sets
          </Link>
          {canAuthor && (
            <button type="button" onClick={() => setCreating('blank')} className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400" data-testid="decision-new">
              <Plus className="w-4 h-4" /> New decision
            </button>
          )}
        </div>
      </header>

      {(data || []).length > 0 && (
        <div className="flex items-center gap-2 rounded-md border border-slate-700 bg-slate-950 px-3 mb-4 max-w-md">
          <Search className="w-4 h-4 text-slate-500" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by name, key or tag…" className="flex-1 bg-transparent py-2 text-sm text-white outline-none" aria-label="Search decisions" />
        </div>
      )}

      {error ? (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-200">{error}</div>
      ) : isLoading && !data ? (
        <div className="space-y-3">{[0, 1, 2].map((i) => <div key={i} className="h-24 rounded-xl bg-slate-800/40 animate-pulse" />)}</div>
      ) : (data || []).length === 0 ? (
        <EmptyState canAuthor={canAuthor} onStart={setCreating} />
      ) : rows.length === 0 ? (
        <p className="text-sm text-slate-500">No decision matches “{q}”.</p>
      ) : (
        <div className="grid gap-3" data-testid="decision-list">
          {rows.map((m) => {
            const live = m.published[m.published.length - 1];
            return (
              <Link key={m.id} href={`/decisions/${encodeURIComponent(m.key)}`} className="block rounded-xl border border-slate-800 bg-slate-900/50 p-4 hover:border-slate-600 transition" data-testid={`decision-row-${m.key}`}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-base font-semibold text-white">{m.name}</span>
                      <span className={`text-[11px] px-1.5 py-0.5 rounded border ${TIER_STYLE[m.risk_tier]?.chip}`}>{TIER_STYLE[m.risk_tier]?.label} risk</span>
                    </div>
                    <div className="text-xs font-mono text-slate-500 mt-0.5">{m.key}</div>
                    {m.description && <p className="text-sm text-slate-400 mt-1 line-clamp-2">{m.description}</p>}
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5 text-xs">
                    {live ? (
                      <span className={`px-2 py-0.5 rounded border ${STATE_STYLE.published}`}>
                        v{live.version} in force{live.valid_from ? ` from ${when(live.valid_from)}` : ''}
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded border border-slate-700 text-slate-400">Not published yet</span>
                    )}
                    {m.proposed.length > 0 && <span className={`px-2 py-0.5 rounded border ${STATE_STYLE.proposed}`}>{m.proposed.length} awaiting sign-off</span>}
                    {m.drafts.length > 0 && <span className={`px-2 py-0.5 rounded border ${STATE_STYLE.draft}`}>{m.drafts.length} draft{m.drafts.length > 1 ? 's' : ''}</span>}
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      )}

      {creating && <CreateDialog start={creating} onClose={() => setCreating(null)} />}
    </div>
  );
}

function EmptyState({ canAuthor, onStart }: { canAuthor: boolean; onStart: (s: 'blank' | 'import' | 'example') => void }) {
  const cards = [
    { id: 'example' as const, icon: Sparkles, title: 'Start from an example', text: 'The remote area surcharge rule, ready to test and change.' },
    { id: 'blank' as const, icon: Plus, title: 'Start blank', text: 'Name it, add facts and outcomes, then build rules row by row.' },
    { id: 'import' as const, icon: FileJson, title: 'Import JSON rules', text: 'Paste or upload rules with ruleKey, when, then and provenance.' },
  ];
  return (
    <div className="rounded-2xl border border-dashed border-slate-700 p-8" data-testid="decision-empty">
      <h2 className="text-lg font-semibold text-white">No decisions yet</h2>
      <p className="text-sm text-slate-400 mt-1 max-w-2xl">
        A decision takes facts, such as a shipment date, a postcode and a weight, and returns an outcome, such as a
        surcharge, using rules you can read. Every answer can be replayed later with the rules that applied then.
      </p>
      {canAuthor ? (
        <div className="grid gap-3 md:grid-cols-3 mt-5">
          {cards.map((c) => (
            <button key={c.id} type="button" onClick={() => onStart(c.id)} className="text-left rounded-xl border border-slate-700 bg-slate-900/50 p-4 hover:border-cyan-500/50 transition" data-testid={`decision-start-${c.id}`}>
              <c.icon className="w-5 h-5 text-cyan-400 mb-2" />
              <div className="text-sm font-medium text-white">{c.title}</div>
              <div className="text-xs text-slate-400 mt-1">{c.text}</div>
            </button>
          ))}
        </div>
      ) : (
        <p className="text-xs text-slate-500 mt-4">Creating decisions needs the decisions.author capability.</p>
      )}
    </div>
  );
}

function slugify(s: string) {
  return s.toLowerCase().trim().replace(/[^a-z0-9._-]+/g, '-').replace(/^[-.]+|[-.]+$/g, '').slice(0, 120);
}

function CreateDialog({ start, onClose }: { start: 'blank' | 'import' | 'example'; onClose: () => void }) {
  const router = useRouter();
  const [mode, setMode] = useState(start);
  const [name, setName] = useState(start === 'example' ? 'Remote area surcharge' : '');
  const [key, setKey] = useState(start === 'example' ? 'freight.remote.surcharge' : '');
  const [keyTouched, setKeyTouched] = useState(start === 'example');
  const [tier, setTier] = useState<Tier>(start === 'example' ? 'high' : 'low');
  const [description, setDescription] = useState(start === 'example' ? 'Whether a shipment to a remote postcode carries a surcharge.' : '');
  const [json, setJson] = useState(start === 'example' ? JSON.stringify(CLIENT_SAMPLE, null, 2) : '');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const effectiveKey = keyTouched ? key : slugify(name);
  const keyOk = KEY_RE.test(effectiveKey);
  let parsed: any = null;
  let parseErr: string | null = null;
  if (mode !== 'blank' && json.trim()) {
    try {
      parsed = JSON.parse(json);
    } catch (e: any) {
      parseErr = `This is not valid JSON: ${e.message}`;
    }
  }
  const ruleCount = parsed ? (Array.isArray(parsed) ? parsed.length : Array.isArray(parsed?.rules) ? parsed.rules.length : parsed?.ruleKey ? 1 : 0) : 0;
  const ready = name.trim() && keyOk && (mode === 'blank' || (parsed && !parseErr && ruleCount > 0));

  async function onFile(f: File) {
    setJson(await f.text());
  }

  async function create() {
    setBusy(true);
    setErr(null);
    const r = await apiFetch<{ key: string }>('/api/decisions', {
      method: 'POST',
      body: JSON.stringify({ name: name.trim(), key: effectiveKey, description, risk_tier: tier, rules: mode === 'blank' ? null : parsed }),
      throwOnError: false,
    });
    setBusy(false);
    if (r.error) setErr(r.error);
    else router.push(`/decisions/${encodeURIComponent(r.data!.key)}`);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-labelledby="new-decision-title">
      <div className="w-full max-w-2xl max-h-[90vh] flex flex-col rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800">
          <h2 id="new-decision-title" className="text-lg font-semibold text-white">New decision</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1 rounded text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          <div className="inline-flex rounded-lg border border-slate-700 p-0.5 bg-slate-950" role="radiogroup" aria-label="How to start">
            {([['blank', 'Blank'], ['import', 'Import JSON'], ['example', 'Surcharge example']] as const).map(([id, label]) => (
              <button key={id} type="button" role="radio" aria-checked={mode === id} onClick={() => { setMode(id); if (id === 'example') { setJson(JSON.stringify(CLIENT_SAMPLE, null, 2)); if (!name) setName('Remote area surcharge'); } }} className={`px-3 py-1.5 text-xs rounded-md ${mode === id ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`}>
                {label}
              </button>
            ))}
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label htmlFor="dn-name" className="block text-sm font-medium text-slate-200 mb-1.5">Name</label>
              <input id="dn-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Remote area surcharge" className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white" data-testid="decision-name" autoFocus />
            </div>
            <div>
              <label htmlFor="dn-key" className="block text-sm font-medium text-slate-200 mb-1.5">Key</label>
              <input id="dn-key" value={effectiveKey} onChange={(e) => { setKeyTouched(true); setKey(e.target.value); }} className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white font-mono" aria-invalid={!keyOk && !!effectiveKey} data-testid="decision-key" />
              <p className={`mt-1 text-xs ${!keyOk && effectiveKey ? 'text-rose-300' : 'text-slate-500'}`}>
                {!keyOk && effectiveKey ? 'Use lowercase letters, digits, dots, dashes or underscores.' : 'Agents and apps call the decision by this key.'}
              </p>
            </div>
          </div>
          <div>
            <label htmlFor="dn-desc" className="block text-sm font-medium text-slate-200 mb-1.5">What it decides</label>
            <input id="dn-desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Whether a shipment carries a remote area surcharge" className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white" />
          </div>
          <div>
            <div className="text-sm font-medium text-slate-200 mb-1.5">Risk tier</div>
            <div className="grid grid-cols-4 gap-1 p-0.5 rounded-lg border border-slate-700 bg-slate-950" role="radiogroup" aria-label="Risk tier">
              {(['low', 'medium', 'high', 'critical'] as Tier[]).map((t) => (
                <button key={t} type="button" role="radio" aria-checked={tier === t} onClick={() => setTier(t)} className={`py-1.5 rounded-md text-xs flex items-center justify-center gap-1.5 ${tier === t ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${TIER_STYLE[t].dot}`} /> {TIER_STYLE[t].label}
                </button>
              ))}
            </div>
            <p className="mt-1 text-xs text-slate-500">Higher tiers need more sign-off before a new version goes live. You can change this later.</p>
          </div>
          {mode !== 'blank' && (
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label htmlFor="dn-json" className="text-sm font-medium text-slate-200">Rules as JSON</label>
                <label className="inline-flex items-center gap-1.5 text-xs text-cyan-300 cursor-pointer hover:underline">
                  <Upload className="w-3.5 h-3.5" /> Upload a file
                  <input type="file" accept=".json,application/json" className="hidden" onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} />
                </label>
              </div>
              <textarea id="dn-json" value={json} onChange={(e) => setJson(e.target.value)} rows={12} spellCheck={false} placeholder='{"ruleKey": "...", "when": {"all": [...]}, "then": {...}}' className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-xs text-slate-200 font-mono" data-testid="decision-json" />
              <p className={`mt-1 text-xs ${parseErr ? 'text-rose-300' : 'text-slate-500'}`}>
                {parseErr || (parsed ? `${ruleCount} rule${ruleCount === 1 ? '' : 's'} found. Facts and outcomes are added for you, and anything else the rules carry is kept.` : 'One rule, a list of rules, or an object with a rules list.')}
              </p>
            </div>
          )}
          {err && <p className="text-sm text-rose-300" role="alert">{err}</p>}
        </div>
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-slate-800">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-md text-sm text-slate-300 hover:bg-slate-800">Cancel</button>
          <button type="button" onClick={create} disabled={!ready || busy} className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400 disabled:opacity-40" data-testid="decision-create">
            {busy && <Loader2 className="w-4 h-4 animate-spin" />} Create and open
          </button>
        </div>
      </div>
    </div>
  );
}
