'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Loader2, Pause, Play, Plug, RefreshCw, Trash2 } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';

interface KindField {
  name: string;
  label: string;
  kind: string;
  required: boolean;
  help: string;
  default: unknown;
  secret: boolean;
}

interface Kind {
  kind: string;
  label: string;
  needs_admin: boolean;
  verified_live: boolean;
  fields: KindField[];
}

interface Connector {
  id: string;
  name: string;
  kind: string;
  label: string;
  verified_live: boolean;
  active: boolean;
  status: string;
  last_error: string | null;
  cadence_minutes: number;
  encrypted_at_rest: boolean;
  last_finished_at: string | null;
  next_sync_at: string | null;
  items: { seen: number; ingested: number; updated: number; deleted: number; failed: number; skipped: number };
}

interface Item {
  external_id: string;
  name: string;
  status: string;
  error: string | null;
}

const STATUS_TEXT: Record<string, string> = {
  idle: 'Up to date',
  queued: 'Waiting for a worker',
  running: 'Syncing',
  pausing: 'Pausing',
  paused: 'Paused',
  failed: 'Last sync failed',
  quota_exceeded: 'Stopped at a workspace limit',
  needs_confirmation: 'Waiting for you to confirm deletes',
};

const BUSY = new Set(['queued', 'running', 'pausing']);

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function ConnectorsPanel({ kbId }: { kbId: string }) {
  const [kinds, setKinds] = useState<Kind[]>([]);
  const [rows, setRows] = useState<Connector[] | null>(null);
  const [loadError, setLoadError] = useState('');
  const [adding, setAdding] = useState(false);
  const [kind, setKind] = useState('');
  const [name, setName] = useState('');
  const [cadence, setCadence] = useState('1440');
  const [values, setValues] = useState<Record<string, string | boolean>>({});
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  const [testResult, setTestResult] = useState('');
  const [problems, setProblems] = useState<{ id: string; items: Item[] } | null>(null);

  const base = `/api/knowledge-bases/${kbId}/connectors`;

  const load = useCallback(async () => {
    const r = await apiFetch<Connector[]>(base, { silent: true, throwOnError: false });
    if (r.data) {
      setRows(r.data);
      setLoadError('');
    } else {
      setLoadError(r.error || 'Connectors could not be loaded.');
    }
  }, [base]);

  useEffect(() => {
    load();
    apiFetch<Kind[]>('/api/knowledge-connector-kinds', { silent: true, throwOnError: false }).then((r) => {
      if (r.data) setKinds(r.data);
    });
  }, [load]);

  const anyBusy = (rows ?? []).some((c) => BUSY.has(c.status));
  useEffect(() => {
    if (!anyBusy) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [anyBusy, load]);

  const chosen = useMemo(() => kinds.find((k) => k.kind === kind), [kinds, kind]);

  const choose = (k: string) => {
    setKind(k);
    setTestResult('');
    setActionError('');
    const found = kinds.find((x) => x.kind === k);
    setValues(
      Object.fromEntries(
        (found?.fields ?? []).map((f) => [f.name, f.kind === 'bool' ? Boolean(f.default) : f.default ? String(f.default) : '']),
      ),
    );
  };

  const payload = () => ({
    kind,
    values: Object.fromEntries(Object.entries(values).filter(([, v]) => v !== '')),
  });

  const test = async () => {
    setBusy(true);
    setActionError('');
    setTestResult('');
    try {
      const r = await apiFetch<{ ok: boolean; error?: string; sample?: string[] }>(`${base}/test`, {
        method: 'POST',
        body: JSON.stringify(payload()),
      });
      if (r.data?.ok) {
        const sample = r.data.sample ?? [];
        setTestResult(sample.length ? `Connected. Found ${sample.join(', ')}` : 'Connected. Nothing found there yet.');
      } else {
        setActionError(r.data?.error || 'The test failed.');
      }
    } catch (e) {
      setActionError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const create = async () => {
    setBusy(true);
    setActionError('');
    try {
      await apiFetch(base, {
        method: 'POST',
        body: JSON.stringify({ ...payload(), name: name.trim(), cadence_minutes: Number(cadence) || 1440 }),
      });
      setAdding(false);
      setKind('');
      setName('');
      setValues({});
      setTestResult('');
      await load();
    } catch (e) {
      setActionError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const act = async (id: string, path: string, method = 'POST') => {
    setActionError('');
    try {
      await apiFetch(`${base}/${id}${path}`, { method });
      await load();
    } catch (e) {
      setActionError(errorText(e));
    }
  };

  const showProblems = async (id: string) => {
    if (problems?.id === id) {
      setProblems(null);
      return;
    }
    const [failed, skipped] = await Promise.all([
      apiFetch<Item[]>(`${base}/${id}/items?status=failed&limit=50`, { silent: true, throwOnError: false }),
      apiFetch<Item[]>(`${base}/${id}/items?status=skipped&limit=50`, { silent: true, throwOnError: false }),
    ]);
    setProblems({ id, items: [...(failed.data ?? []), ...(skipped.data ?? [])] });
  };

  const missing = chosen?.fields.some((f) => f.required && !values[f.name]) ?? true;

  return (
    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 space-y-3" data-testid="connectors-panel">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          <Plug className="w-4 h-4 text-cyan-400" />
          Connectors
        </h3>
        <button
          onClick={() => setAdding(!adding)}
          data-testid="connector-add"
          className="rounded-md bg-slate-700 hover:bg-slate-600 px-3 py-1 text-xs text-white"
        >
          {adding ? 'Close' : 'Add connector'}
        </button>
      </div>
      <p className="text-xs text-slate-400">
        Keeps this collection in step with a source. Each sync takes only what changed, and removes what was deleted there.
      </p>
      {loadError && <p role="alert" className="text-xs text-rose-300">{loadError}</p>}
      {actionError && <p role="alert" data-testid="connector-error" className="text-xs text-rose-300">{actionError}</p>}

      {adding && (
        <div className="rounded-lg bg-slate-900/50 p-3 space-y-2" data-testid="connector-form">
          <label className="block text-xs text-slate-400">
            Source
            <select
              value={kind}
              onChange={(e) => choose(e.target.value)}
              data-testid="connector-kind"
              className="mt-1 block w-full max-w-md rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-white text-sm"
            >
              <option value="">Choose a source…</option>
              {kinds.map((k) => (
                <option key={k.kind} value={k.kind}>{k.label}</option>
              ))}
            </select>
          </label>
          {chosen && !chosen.verified_live && (
            <p className="text-[11px] text-amber-300" data-testid="connector-unverified">
              This connector is tested against a simulated {chosen.label} only. It has not yet run against the real service, so check the first sync.
            </p>
          )}
          {chosen && (
            <>
              <label className="block text-xs text-slate-400">
                Name
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  data-testid="connector-name"
                  className="mt-1 block w-full max-w-md rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-white text-sm"
                />
              </label>
              {chosen.fields.map((f) => (
                <label key={f.name} className="block text-xs text-slate-400">
                  {f.kind === 'bool' ? (
                    <span className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={Boolean(values[f.name])}
                        onChange={(e) => setValues({ ...values, [f.name]: e.target.checked })}
                      />
                      {f.label}
                    </span>
                  ) : (
                    <>
                      {f.label}{f.required ? ' *' : ''}
                      {f.kind === 'textarea' ? (
                        <textarea
                          value={String(values[f.name] ?? '')}
                          onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
                          rows={3}
                          className="mt-1 block w-full max-w-2xl rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-white text-sm font-mono"
                        />
                      ) : (
                        <input
                          type={f.secret ? 'password' : 'text'}
                          autoComplete="off"
                          value={String(values[f.name] ?? '')}
                          onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
                          data-testid={`connector-field-${f.name}`}
                          className="mt-1 block w-full max-w-md rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-white text-sm"
                        />
                      )}
                    </>
                  )}
                  {f.help && <span className="block text-[10px] text-slate-500 mt-0.5">{f.help}</span>}
                </label>
              ))}
              <label className="block text-xs text-slate-400">
                Sync every
                <select
                  value={cadence}
                  onChange={(e) => setCadence(e.target.value)}
                  className="mt-1 block w-48 rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-white text-sm"
                >
                  <option value="15">15 minutes</option>
                  <option value="60">Hour</option>
                  <option value="360">6 hours</option>
                  <option value="1440">Day</option>
                  <option value="10080">Week</option>
                </select>
              </label>
              {testResult && <p className="text-xs text-emerald-300" data-testid="connector-test-result">{testResult}</p>}
              <div className="flex gap-2">
                <button
                  onClick={test}
                  disabled={busy || missing}
                  data-testid="connector-test"
                  className="rounded-md bg-slate-700 hover:bg-slate-600 px-3 py-1.5 text-xs text-white disabled:opacity-50"
                >
                  Test connection
                </button>
                <button
                  onClick={create}
                  disabled={busy || missing || !name.trim()}
                  data-testid="connector-create"
                  className="rounded-md bg-cyan-600 hover:bg-cyan-500 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
                >
                  {busy ? 'Saving…' : 'Save and sync'}
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {rows === null && !loadError && (
        <p className="text-xs text-slate-500 flex items-center gap-2">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading connectors…
        </p>
      )}
      {rows?.length === 0 && !adding && (
        <p className="text-xs text-slate-500" data-testid="connectors-empty">No connectors yet. Documents only arrive by upload.</p>
      )}
      {rows?.map((c) => (
        <div key={c.id} className="rounded-lg bg-slate-900/50 p-3 text-xs space-y-1.5" data-testid="connector-row" data-kind={c.kind}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-white font-medium">
              {c.name} <span className="text-slate-500 font-normal">{c.label}</span>
            </p>
            <div className="flex gap-1">
              <button
                onClick={() => act(c.id, '/sync')}
                disabled={BUSY.has(c.status)}
                aria-label={`Sync ${c.name} now`}
                data-testid="connector-sync"
                className="p-1 rounded bg-slate-700/50 text-slate-300 hover:text-cyan-400 disabled:opacity-40"
              >
                <RefreshCw className="w-3.5 h-3.5" />
              </button>
              {c.active ? (
                <button onClick={() => act(c.id, '/pause')} aria-label={`Pause ${c.name}`} className="p-1 rounded bg-slate-700/50 text-slate-300 hover:text-amber-400">
                  <Pause className="w-3.5 h-3.5" />
                </button>
              ) : (
                <button onClick={() => act(c.id, '/resume')} aria-label={`Resume ${c.name}`} className="p-1 rounded bg-slate-700/50 text-slate-300 hover:text-emerald-400">
                  <Play className="w-3.5 h-3.5" />
                </button>
              )}
              <button onClick={() => act(c.id, '', 'DELETE')} aria-label={`Remove ${c.name}`} className="p-1 rounded bg-slate-700/50 text-slate-300 hover:text-rose-400">
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
          <p className="text-slate-300 flex items-center gap-1.5" data-testid="connector-status">
            {BUSY.has(c.status) && <Loader2 className="w-3 h-3 animate-spin text-cyan-400" />}
            {STATUS_TEXT[c.status] ?? c.status}
            {c.last_finished_at && (
              <span className="text-slate-500">, last finished {new Date(c.last_finished_at).toLocaleString()}</span>
            )}
          </p>
          <p className="text-slate-500">
            Last pass saw {c.items.seen.toLocaleString()}, added {c.items.ingested.toLocaleString()}, updated {c.items.updated.toLocaleString()}, removed {c.items.deleted.toLocaleString()}
            {c.items.failed + c.items.skipped > 0 && (
              <>
                , <button onClick={() => showProblems(c.id)} className="text-amber-300 hover:underline" data-testid="connector-problems">
                  {c.items.failed} failed and {c.items.skipped} skipped
                </button>
              </>
            )}
          </p>
          {c.last_error && (
            <p className="text-rose-300 flex items-start gap-1.5" data-testid="connector-last-error">
              <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              <span>{c.last_error}</span>
            </p>
          )}
          {c.status === 'needs_confirmation' && (
            <button
              onClick={() => act(c.id, '/sync?confirm_deletes=true')}
              data-testid="connector-confirm-deletes"
              className="rounded-md bg-rose-600 hover:bg-rose-500 px-3 py-1 text-xs text-white"
            >
              They really are gone, sync and delete them here
            </button>
          )}
          {!c.encrypted_at_rest && (
            <p className="text-[11px] text-amber-300">Credentials are stored unencrypted, this server has no data key configured.</p>
          )}
          {!c.verified_live && (
            <p className="text-[11px] text-slate-500">Tested against a simulated service only, not yet the real one.</p>
          )}
          {problems?.id === c.id && (
            <ul className="mt-1 space-y-0.5 text-[11px] text-slate-400" data-testid="connector-problem-list">
              {problems.items.map((i) => (
                <li key={i.external_id}>
                  <span className="text-slate-200">{i.name || i.external_id}</span> {i.error || i.status}
                </li>
              ))}
              {problems.items.length === 0 && <li>Nothing failed or skipped now.</li>}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}

export default ConnectorsPanel;
