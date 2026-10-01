'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { KeyRound, Lock, Unlock, Search, ExternalLink, RotateCcw, FlaskConical, Save, Building2, Globe } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import type { ToolCredentialSource } from '@/components/CredentialBadge';

// Everything on this page comes from GET /api/admin/tool-config, which is
// generated from the tools' own config_fields. Nothing here names a tool.

type Kind = 'secret' | 'string' | 'url' | 'int' | 'bool' | 'select';
type Source = ToolCredentialSource;
type Scope = 'tenant' | 'platform';

interface KeyRow {
  key: string;
  label: string;
  kind: Kind;
  required: boolean;
  group: string;
  description: string;
  signup_url: string;
  default: string | null;
  options: string[];
  tools: string[];
  source: Source;
  is_set: boolean;
  scope: Scope;
  effective_source: Source;
  tenant_source: 'tenant' | 'unset';
  platform_source: Source;
  can_test: boolean;
  value?: string;
  tenant_value?: string;
  platform_value?: string;
}

interface Catalogue {
  groups: { group: string; keys: KeyRow[] }[];
  key_count: number;
  tool_count: number;
  missing_required: number;
  encrypted_at_rest: boolean;
  propagation_seconds: number;
  out_of_scope: string[];
  scope: Scope;
  tenant_id: string | null;
}

const SOURCE_LABEL: Record<Source, string> = {
  override: 'test override',
  tenant: 'saved for this tenant',
  stored: 'saved for the platform',
  env: 'from environment',
  file: 'from tool_defaults.yaml',
  default: 'tool default',
  unset: 'not set',
};

const SOURCE_CLS: Record<Source, string> = {
  override: 'text-violet-300 border-violet-500/30 bg-violet-500/10',
  tenant: 'text-emerald-300 border-emerald-500/30 bg-emerald-500/10',
  stored: 'text-teal-300 border-teal-500/30 bg-teal-500/10',
  env: 'text-cyan-300 border-cyan-500/30 bg-cyan-500/10',
  file: 'text-sky-300 border-sky-500/30 bg-sky-500/10',
  default: 'text-slate-300 border-slate-600 bg-slate-700/30',
  unset: 'text-slate-500 border-slate-700 bg-slate-800/40',
};

const SCOPE_HELP: Record<Scope, string> = {
  tenant: 'Values saved here apply to this tenant only and win over the platform value. This is what your agents run with.',
  platform: 'Values saved here are the fallback for every tenant. A tenant that saved its own value keeps it.',
};

function placeholderFor(row: KeyRow): string {
  if (row.is_set && row.kind === 'secret') return row.value || '********';
  if (row.is_set) return row.value || '';
  if (row.default) return `default: ${row.default}`;
  return row.kind === 'url' ? 'https://…' : 'not set';
}

function hasRowInScope(row: KeyRow, scope: Scope): boolean {
  return scope === 'tenant' ? row.tenant_source === 'tenant' : row.platform_source === 'stored';
}

export default function ToolConfigPage() {
  const [scope, setScope] = useState<Scope>('tenant');
  const [cat, setCat] = useState<Catalogue | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [rowMsg, setRowMsg] = useState<Record<string, { ok: boolean; text: string }>>({});
  const [query, setQuery] = useState('');
  const [onlyMissing, setOnlyMissing] = useState(false);

  async function load(s: Scope) {
    setLoading(true);
    setErr(null);
    const r = await apiFetch<Catalogue>(`/api/admin/tool-config?scope=${s}`);
    if (r.data) {
      setCat(r.data);
    } else {
      const e = (r.error || '').toLowerCase();
      setErr(e.includes('403') || e.includes('forbidden') || e.includes('admin') || e.includes('permission')
        ? 'Admin role required to view Tool Configuration.'
        : (r.error || 'Failed to load'));
    }
    setLoading(false);
  }

  useEffect(() => { load(scope); }, [scope]);

  // deep link: /admin/tool-config#TAVILY_API_KEY
  useEffect(() => {
    if (!cat || typeof window === 'undefined') return;
    const id = window.location.hash.replace('#', '');
    if (!id) return;
    const el = document.getElementById(`row-${id}`);
    if (el) {
      el.scrollIntoView({ block: 'center' });
      el.classList.add('ring-1', 'ring-cyan-400/60');
    }
  }, [cat]);

  function switchScope(s: Scope) {
    if (s === scope) return;
    setRowMsg({});
    setScope(s);
  }

  function applyRow(updated: KeyRow) {
    setCat((c) => c && {
      ...c,
      groups: c.groups.map((g) => ({ ...g, keys: g.keys.map((k) => (k.key === updated.key ? updated : k)) })),
      missing_required: c.groups
        .flatMap((g) => g.keys)
        .map((k) => (k.key === updated.key ? updated : k))
        .filter((k) => k.required && !k.is_set).length,
    });
  }

  async function save(row: KeyRow) {
    const value = (drafts[row.key] ?? '').trim();
    if (!value) return;
    setBusy((b) => ({ ...b, [row.key]: true }));
    const r = await apiFetch<KeyRow>(`/api/admin/tool-config/${encodeURIComponent(row.key)}`, {
      method: 'PATCH',
      body: JSON.stringify({ value, scope }),
    });
    setBusy((b) => ({ ...b, [row.key]: false }));
    if (r.data) {
      applyRow(r.data);
      setDrafts((d) => { const n = { ...d }; delete n[row.key]; return n; });
      const who = scope === 'tenant' ? 'this tenant' : 'the platform';
      setRowMsg((m) => ({ ...m, [row.key]: { ok: true, text: `Saved for ${who}. Agents pick it up within ${cat?.propagation_seconds ?? 30} seconds.` } }));
    } else {
      setRowMsg((m) => ({ ...m, [row.key]: { ok: false, text: r.error || 'Save failed' } }));
    }
  }

  async function clear(row: KeyRow) {
    setBusy((b) => ({ ...b, [row.key]: true }));
    const r = await apiFetch<KeyRow>(`/api/admin/tool-config/${encodeURIComponent(row.key)}?scope=${scope}`, { method: 'DELETE' });
    setBusy((b) => ({ ...b, [row.key]: false }));
    if (r.data) {
      applyRow(r.data);
      setRowMsg((m) => ({ ...m, [row.key]: { ok: true, text: `Cleared. Now ${SOURCE_LABEL[r.data!.source]}.` } }));
    } else {
      setRowMsg((m) => ({ ...m, [row.key]: { ok: false, text: r.error || 'Clear failed' } }));
    }
  }

  async function test(row: KeyRow) {
    setBusy((b) => ({ ...b, [row.key]: true }));
    const r = await apiFetch<{ ok: boolean; message: string; tool: string }>(
      `/api/admin/tool-config/${encodeURIComponent(row.key)}/test`,
      { method: 'POST', body: JSON.stringify({ value: (drafts[row.key] ?? '').trim(), scope }) },
    );
    setBusy((b) => ({ ...b, [row.key]: false }));
    if (r.data) {
      setRowMsg((m) => ({ ...m, [row.key]: { ok: r.data!.ok, text: `${r.data!.tool}: ${r.data!.message}` } }));
    } else {
      setRowMsg((m) => ({ ...m, [row.key]: { ok: false, text: r.error || 'Test failed' } }));
    }
  }

  const visible = useMemo(() => {
    if (!cat) return [];
    const q = query.trim().toLowerCase();
    return cat.groups
      .map((g) => ({
        ...g,
        keys: g.keys.filter((k) => {
          if (onlyMissing && k.is_set) return false;
          if (!q) return true;
          return (
            k.key.toLowerCase().includes(q) ||
            k.label.toLowerCase().includes(q) ||
            g.group.toLowerCase().includes(q) ||
            k.description.toLowerCase().includes(q) ||
            k.tools.some((t) => t.toLowerCase().includes(q))
          );
        }),
      }))
      .filter((g) => g.keys.length > 0);
  }, [cat, query, onlyMissing]);

  if (loading && !cat) {
    return <div className="p-8 text-slate-400 text-sm">Loading tool configuration…</div>;
  }
  if (err || !cat) {
    return (
      <div className="p-8">
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-200" data-testid="tool-config-error">
          {err || 'Nothing to show'}
        </div>
      </div>
    );
  }

  const scopeBtn = (s: Scope, label: string, Icon: typeof Building2) => (
    <button
      type="button"
      onClick={() => switchScope(s)}
      aria-pressed={scope === s}
      data-testid={`tool-config-scope-${s}`}
      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition ${
        scope === s ? 'bg-cyan-500 text-white' : 'text-slate-300 hover:text-white hover:bg-slate-800/70'
      }`}
    >
      <Icon className="w-3.5 h-3.5" /> {label}
    </button>
  );

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <header className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <KeyRound className="w-6 h-6 text-cyan-400" />
          <h1 className="text-3xl font-semibold text-white">Tool Configuration</h1>
        </div>
        <p className="text-slate-400 max-w-3xl">
          Every value a built-in tool needs to run, declared by the tool itself. Save a value here and
          agents use it within {cat.propagation_seconds} seconds, with no redeploy. A value saved for this
          tenant wins over the platform value, which wins over the environment and over{' '}
          <code className="text-cyan-300">tool_defaults.yaml</code>. Clear it and the next source applies again.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <div className="inline-flex items-center gap-1 p-1 rounded-lg border border-slate-700 bg-slate-900/60" role="group" aria-label="Scope" data-testid="tool-config-scope">
            {scopeBtn('tenant', 'This tenant', Building2)}
            {scopeBtn('platform', 'Platform', Globe)}
          </div>
          <p className="text-xs text-slate-400" data-testid="tool-config-scope-help">{SCOPE_HELP[scope]}</p>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <span className="px-2 py-1 rounded border border-slate-700 bg-slate-800/50 text-slate-300" data-testid="tool-config-counts">
            {cat.key_count} values across {cat.tool_count} tools
          </span>
          <span
            className={`px-2 py-1 rounded border ${cat.missing_required ? 'border-rose-500/30 bg-rose-500/10 text-rose-300' : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'}`}
            data-testid="tool-config-missing-required"
          >
            {cat.missing_required} required value{cat.missing_required === 1 ? '' : 's'} missing
          </span>
          <span
            className={`inline-flex items-center gap-1 px-2 py-1 rounded border ${cat.encrypted_at_rest ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/30 bg-amber-500/10 text-amber-300'}`}
            title={cat.encrypted_at_rest
              ? 'Values are AES-GCM encrypted with the cluster key before they reach the database.'
              : 'ABENIX_DATA_KEY_KEK_BASE64 is not set on this cluster, so saved values are stored as entered. See the encryption setup guide.'}
            data-testid="tool-config-encryption"
          >
            {cat.encrypted_at_rest ? <Lock className="w-3 h-3" /> : <Unlock className="w-3 h-3" />}
            {cat.encrypted_at_rest ? 'encrypted at rest' : 'stored unencrypted, set a cluster key'}
          </span>
        </div>
      </header>

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[240px]">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            type="search"
            placeholder="Search by key, provider or tool…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            data-testid="tool-config-search"
            className="w-full pl-10 pr-4 py-2.5 bg-slate-900 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/50"
          />
        </div>
        <label className="flex items-center gap-2 text-xs text-slate-300 select-none">
          <input type="checkbox" checked={onlyMissing} onChange={(e) => setOnlyMissing(e.target.checked)} />
          only values that are not set
        </label>
      </div>

      <div className={`space-y-4 ${loading ? 'opacity-60' : ''}`}>
        {visible.map((g) => (
          <motion.section
            key={g.group}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-xl border border-slate-700/60 bg-[#0B0F19] overflow-hidden"
            data-testid={`tool-config-group-${g.group}`}
          >
            <div className="px-4 py-3 border-b border-slate-800 flex items-baseline justify-between gap-3 flex-wrap">
              <h2 className="text-base font-semibold text-white">{g.group}</h2>
              <p className="text-[11px] text-slate-500">
                unlocks{' '}
                {Array.from(new Set(g.keys.flatMap((k) => k.tools))).sort().map((t, i, arr) => (
                  <span key={t}>
                    <Link href={`/tools#${t}`} className="font-mono text-cyan-300 hover:underline">{t}</Link>
                    {i < arr.length - 1 ? ', ' : ''}
                  </span>
                ))}
              </p>
            </div>
            <ul className="divide-y divide-slate-800/60">
              {g.keys.map((row) => {
                const draft = drafts[row.key] ?? '';
                const msg = rowMsg[row.key];
                const isBusy = !!busy[row.key];
                const canClear = hasRowInScope(row, scope);
                const tenantOverrides = scope === 'platform' && row.tenant_source === 'tenant';
                return (
                  <li key={row.key} id={`row-${row.key}`} className="px-4 py-3 rounded" data-testid={`tool-config-row-${row.key}`}>
                    <div className="flex items-start justify-between gap-3 flex-wrap">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-mono text-sm text-white">{row.key}</span>
                          {row.label && row.label !== row.key && (
                            <span className="text-xs text-slate-400">{row.label}</span>
                          )}
                          {row.required ? (
                            <span className="text-[9px] uppercase tracking-wider text-rose-300 border border-rose-500/30 bg-rose-500/10 rounded px-1.5 py-0.5">required</span>
                          ) : (
                            <span className="text-[9px] uppercase tracking-wider text-slate-400 border border-slate-700 rounded px-1.5 py-0.5">optional</span>
                          )}
                          <span
                            className={`text-[9px] uppercase tracking-wider border rounded px-1.5 py-0.5 ${SOURCE_CLS[row.source]}`}
                            data-testid={`tool-config-source-${row.key}`}
                            data-source={row.source}
                            data-scope={scope}
                            title={scope === 'tenant' ? 'What this tenant’s agents run with' : 'The platform fallback, tenant rows ignored'}
                          >
                            {SOURCE_LABEL[row.source]}
                          </span>
                          {tenantOverrides && (
                            <span
                              className="text-[9px] uppercase tracking-wider border rounded px-1.5 py-0.5 text-emerald-300 border-emerald-500/30 bg-emerald-500/10"
                              data-testid={`tool-config-effective-${row.key}`}
                              title="Your tenant saved its own value, so this platform value is not what your agents use"
                            >
                              this tenant overrides
                            </span>
                          )}
                        </div>
                        {row.description && <p className="text-[11px] text-slate-500 mt-1 max-w-2xl">{row.description}</p>}
                        <p className="text-[11px] text-slate-500 mt-1">
                          used by{' '}
                          {row.tools.map((t, i) => (
                            <span key={t}>
                              <Link href={`/tools#${t}`} className="font-mono text-slate-300 hover:text-cyan-300">{t}</Link>
                              {i < row.tools.length - 1 ? ', ' : ''}
                            </span>
                          ))}
                          {row.signup_url && (
                            <>
                              {' · '}
                              <a href={row.signup_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-cyan-300 hover:underline">
                                get a key <ExternalLink className="w-3 h-3" />
                              </a>
                            </>
                          )}
                        </p>
                      </div>
                    </div>

                    <div className="mt-2 flex items-center gap-2 flex-wrap">
                      {row.kind === 'select' && row.options.length > 0 ? (
                        <select
                          value={draft}
                          onChange={(e) => setDrafts((d) => ({ ...d, [row.key]: e.target.value }))}
                          data-testid={`tool-config-input-${row.key}`}
                          className="w-72 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white font-mono focus:outline-none focus:border-cyan-500"
                        >
                          <option value="">{placeholderFor(row)}</option>
                          {row.options.map((o) => <option key={o} value={o}>{o}</option>)}
                        </select>
                      ) : row.kind === 'bool' ? (
                        <select
                          value={draft}
                          onChange={(e) => setDrafts((d) => ({ ...d, [row.key]: e.target.value }))}
                          data-testid={`tool-config-input-${row.key}`}
                          className="w-72 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white font-mono focus:outline-none focus:border-cyan-500"
                        >
                          <option value="">{placeholderFor(row)}</option>
                          <option value="true">true</option>
                          <option value="false">false</option>
                        </select>
                      ) : (
                        <input
                          type={row.kind === 'secret' ? 'password' : row.kind === 'int' ? 'number' : 'text'}
                          value={draft}
                          onChange={(e) => setDrafts((d) => ({ ...d, [row.key]: e.target.value }))}
                          placeholder={placeholderFor(row)}
                          autoComplete="off"
                          data-testid={`tool-config-input-${row.key}`}
                          className="flex-1 min-w-[260px] max-w-xl px-3 py-2 bg-slate-900/60 border border-slate-700 rounded-lg text-xs text-white font-mono focus:outline-none focus:border-cyan-500"
                        />
                      )}
                      <button
                        onClick={() => save(row)}
                        disabled={isBusy || !draft.trim()}
                        data-testid={`tool-config-save-${row.key}`}
                        title={scope === 'tenant' ? 'Save for this tenant' : 'Save for the platform'}
                        className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-cyan-500 text-white text-xs font-semibold hover:bg-cyan-400 disabled:opacity-40"
                      >
                        <Save className="w-3 h-3" /> Save
                      </button>
                      {row.can_test && (
                        <button
                          onClick={() => test(row)}
                          disabled={isBusy || (!draft.trim() && !row.is_set)}
                          data-testid={`tool-config-test-${row.key}`}
                          className="inline-flex items-center gap-1 px-3 py-2 rounded-lg border border-slate-700/60 bg-slate-800/40 text-slate-200 text-xs hover:bg-slate-800/70 disabled:opacity-40"
                        >
                          <FlaskConical className="w-3 h-3" /> Test
                        </button>
                      )}
                      {canClear && (
                        <button
                          onClick={() => clear(row)}
                          disabled={isBusy}
                          data-testid={`tool-config-clear-${row.key}`}
                          className="inline-flex items-center gap-1 px-3 py-2 rounded-lg border border-slate-700/60 text-slate-400 text-xs hover:text-white hover:bg-slate-800/70 disabled:opacity-40"
                        >
                          <RotateCcw className="w-3 h-3" /> {scope === 'tenant' ? 'Clear tenant value' : 'Clear platform value'}
                        </button>
                      )}
                    </div>
                    {msg && (
                      <p className={`text-[11px] mt-1.5 ${msg.ok ? 'text-emerald-300' : 'text-rose-300'}`} data-testid={`tool-config-msg-${row.key}`}>
                        {msg.text}
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>
          </motion.section>
        ))}
        {visible.length === 0 && (
          <p className="text-sm text-slate-500">Nothing matches.</p>
        )}
      </div>

      <div className="mt-8 rounded-xl border border-slate-800 bg-slate-900/40 p-4 text-xs text-slate-400 space-y-1">
        <p className="text-slate-300 font-medium">Not on this page</p>
        {cat.out_of_scope.map((line) => <p key={line}>{line}</p>)}
        <p className="pt-1">
          Adding a tool? Declare its values as <code className="text-cyan-300">config_fields</code> on the tool class
          and it appears here. See the developer guide under Help -&gt; Add a tool.
        </p>
      </div>
    </div>
  );
}
