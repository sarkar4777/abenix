'use client';

import { useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { AlertTriangle, CheckCircle2, CircuitBoard, Copy, Download, FileUp, KeyRound, Loader2, Plus, Search, Trash2 } from 'lucide-react';
import ConfirmModal from '@/components/ui/ConfirmModal';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { explainTelemetryError } from '@/lib/telemetry/errors';
import { ago } from '@/lib/telemetry/format';
import { BULK_MAX, deviceIdProblem, deviceSnippets, keysToCsv, parseKeysCsv, rowsToCsv, type DeviceKey } from '@/lib/telemetry/keys';
import { toastSuccess } from '@/stores/toastStore';
import { useKept } from '@/lib/telemetry/kept';
import { ingestEndpoint } from './PushPanel';

const PAGE = 50;
type Mode = 'list' | 'one' | 'bulk';

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function Copy1({ text, label = 'Copy', testId }: { text: string; label?: string; testId?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" onClick={() => { navigator.clipboard?.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500); }).catch(() => {}); }} className="inline-flex shrink-0 items-center gap-1 rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800" data-testid={testId}>
      {done ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-300" /> : <Copy className="h-3.5 w-3.5" />} {done ? 'Copied' : label}
    </button>
  );
}

// keys that let each device post as itself, made one at a time or thousands from a CSV
export default function KeysPanel({ sourceId, sourceName, ingestUrl }: { sourceId: string; sourceName: string; ingestUrl?: string | null }) {
  const { data, error, isLoading, mutate } = useApi<DeviceKey[]>(`/api/telemetry/connections/${sourceId}/keys`);
  const [mode, setMode] = useKept<Mode>(`keys:${sourceId}:mode`, 'list');
  const [q, setQ] = useState('');
  const [kind, setKind] = useState<'' | 'device' | 'gateway'>('');
  const [showRevoked, setShowRevoked] = useState(false);
  const [page, setPage] = useState(0);
  const [revoke, setRevoke] = useState<DeviceKey | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [one, setOne] = useState({ device_id: '', label: '', group: '' });
  const [touched, setTouched] = useState(false);
  const [made, setMade] = useKept<DeviceKey | null>(`keys:${sourceId}:made`, null);
  const [csv, setCsv] = useState('');
  const [bulkMade, setBulkMade] = useKept<{ keys: DeviceKey[]; csv: string } | null>(`keys:${sourceId}:bulk`, null);
  const [lang, setLang] = useState<'curl' | 'python' | 'js'>('curl');
  const fileRef = useRef<HTMLInputElement>(null);
  const endpoint = ingestEndpoint(sourceId, ingestUrl);

  const keys = useMemo(() => {
    const s = q.trim().toLowerCase();
    return (data || []).filter((k) => (showRevoked || !k.revoked_at) && (!kind || k.kind === kind) && (!s || `${k.device_id ?? ''} ${k.label ?? ''} ${k.group ?? ''} ${k.key_prefix ?? ''}`.toLowerCase().includes(s)));
  }, [data, q, kind, showRevoked]);
  const pages = Math.max(1, Math.ceil(keys.length / PAGE));
  const shown = keys.slice(page * PAGE, page * PAGE + PAGE);
  const parsed = useMemo(() => parseKeysCsv(csv), [csv]);
  const bad = parsed.rows.filter((r) => r.problem);
  const idErr = deviceIdProblem(one.device_id);

  async function createOne() {
    setTouched(true);
    if (idErr) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await apiFetch<DeviceKey>(`/api/telemetry/connections/${sourceId}/keys`, { method: 'POST', body: JSON.stringify({ device_id: one.device_id.trim(), label: one.label.trim() || undefined, group: one.group.trim() || undefined, kind: 'device' }) });
      setMade(res.data);
      setOne({ device_id: '', label: '', group: '' });
      setTouched(false);
      mutate();
    } catch (e) {
      setErr(explainTelemetryError(e, 'save'));
    } finally {
      setBusy(false);
    }
  }

  async function createBulk() {
    if (!parsed.rows.length || bad.length || parsed.problem) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await apiFetch<DeviceKey[] | { keys: DeviceKey[] }>(`/api/telemetry/connections/${sourceId}/keys/bulk`, { method: 'POST', body: JSON.stringify({ csv: rowsToCsv(parsed.rows) }) });
      const list = Array.isArray(res.data) ? res.data : res.data?.keys ?? [];
      const metaCsv = typeof res.meta?.csv === 'string' ? (res.meta.csv as string) : keysToCsv(list);
      setBulkMade({ keys: list, csv: metaCsv });
      setCsv('');
      mutate();
    } catch (e) {
      setErr(explainTelemetryError(e, 'save'));
    } finally {
      setBusy(false);
    }
  }

  async function doRevoke() {
    if (!revoke) return;
    setBusy(true);
    setErr(null);
    try {
      await apiFetch(`/api/telemetry/connections/${sourceId}/keys/${revoke.id}`, { method: 'DELETE' });
      toastSuccess(`Key for ${revoke.device_id || revoke.label || 'the device'} revoked`, 'It is refused from now on.');
      setRevoke(null);
      mutate();
    } catch (e) {
      setErr(explainTelemetryError(e, 'delete'));
    } finally {
      setBusy(false);
    }
  }

  const tab = (m: Mode, label: string) => (
    <button type="button" role="tab" aria-selected={mode === m} onClick={() => { setMode(m); setErr(null); }} className={`rounded-md px-2.5 py-1 text-xs ${mode === m ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`} data-testid={`tel-keys-${m}`}>{label}</button>
  );
  const input = 'w-full rounded-md border bg-slate-950 px-2.5 py-2 text-sm text-white placeholder:text-slate-600';
  const snip = made ? deviceSnippets(endpoint, made.key ?? '', made.device_id ?? 'device') : null;

  return (
    <div className="space-y-3" data-testid="tel-keys">
      <p className="text-sm text-slate-300">
        Give each tracker or device its own key. A device key can only write as its own device, so one lost key cannot pretend to be another device. Gateway keys come from Abenix Edge and write for many assets, only the ones they are allowed.
      </p>
      <div className="inline-flex rounded-lg border border-slate-700 p-0.5" role="tablist" aria-label="Keys">
        {tab('list', `Keys${data ? ` (${data.filter((k) => !k.revoked_at).length})` : ''}`)}
        {tab('one', 'Add one')}
        {tab('bulk', 'Add many from CSV')}
      </div>
      {err && <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-100" role="alert">{err}</p>}

      {mode === 'list' && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <label className="relative min-w-[12rem] flex-1">
              <span className="sr-only">Search keys</span>
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
              <input value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} placeholder="Device id, label or group" className="w-full rounded-lg border border-slate-700 bg-slate-900 py-1.5 pl-8 pr-2 text-sm text-white placeholder:text-slate-500" data-testid="tel-keys-search" />
            </label>
            <select value={kind} onChange={(e) => { setKind(e.target.value as typeof kind); setPage(0); }} aria-label="Kind of key" className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-200">
              <option value="">Devices and gateways</option>
              <option value="device">Device keys</option>
              <option value="gateway">Edge gateways</option>
            </select>
            <label className="flex items-center gap-1.5 text-xs text-slate-300"><input type="checkbox" checked={showRevoked} onChange={(e) => setShowRevoked(e.target.checked)} className="accent-cyan-500" /> Show revoked</label>
          </div>
          {error ? (
            <p className="text-sm text-rose-200" role="alert">{error}</p>
          ) : isLoading && !data ? (
            <p className="flex items-center gap-2 text-xs text-slate-400"><Loader2 className="h-4 w-4 animate-spin" /> Loading the keys</p>
          ) : !keys.length ? (
            <p className="rounded-lg border border-slate-700/60 p-3 text-sm text-slate-300" data-testid="tel-keys-empty">
              {data?.length ? 'No key matches.' : `No device keys on ${sourceName} yet. Everything uses the source token so far.`}{' '}
              {!data?.length && <button type="button" className="text-cyan-300 hover:underline" onClick={() => setMode('one')}>Add the first device</button>}
            </p>
          ) : (
            <>
              <ul className="divide-y divide-slate-800 rounded-lg border border-slate-700/60" data-testid="tel-keys-list">
                {shown.map((k) => (
                  <li key={k.id} className={`flex flex-wrap items-center gap-2 px-3 py-2 text-sm ${k.revoked_at ? 'opacity-60' : ''}`} data-testid="tel-key-row">
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-1.5">
                        <span className="font-mono text-slate-100">{k.kind === 'gateway' ? k.label || 'Gateway' : k.device_id}</span>
                        {k.kind === 'gateway' ? (
                          <Link href="/edge" className="inline-flex items-center gap-1 rounded border border-cyan-500/40 px-1 text-[10px] text-cyan-200 hover:underline"><CircuitBoard className="h-3 w-3" /> Edge gateway</Link>
                        ) : null}
                        {k.revoked_at && <span className="rounded bg-slate-700 px-1 text-[10px] text-slate-300">revoked {ago(k.revoked_at)}</span>}
                      </span>
                      <span className="block truncate text-xs text-slate-500">
                        {[k.label && k.kind !== 'gateway' ? k.label : null, k.group ? `group ${k.group}` : null, k.kind === 'gateway' && k.allowed_nodes?.length ? `writes for ${k.allowed_nodes.slice(0, 3).join(', ')}${k.allowed_nodes.length > 3 ? ` and ${k.allowed_nodes.length - 3} more` : ''}` : null, k.key_prefix ? `${k.key_prefix}…` : null].filter(Boolean).join(' · ')}
                      </span>
                    </span>
                    <span className="text-xs text-slate-400">{k.last_used_at ? `used ${ago(k.last_used_at)}` : 'never used'}</span>
                    {!k.revoked_at && (
                      <button type="button" onClick={() => { setRevoke(k); setErr(null); }} className="inline-flex items-center gap-1 rounded-md border border-rose-600/40 px-2 py-0.5 text-xs text-rose-200 hover:bg-rose-500/10" data-testid="tel-key-revoke"><Trash2 className="h-3.5 w-3.5" /> Revoke</button>
                    )}
                  </li>
                ))}
              </ul>
              {pages > 1 && (
                <div className="flex items-center justify-between text-xs text-slate-400">
                  <span>{page * PAGE + 1} to {Math.min(keys.length, (page + 1) * PAGE)} of {keys.length}</span>
                  <span className="flex gap-1">
                    <button type="button" disabled={page === 0} onClick={() => setPage((p) => p - 1)} title={page === 0 ? 'This is the first page' : undefined} className="rounded border border-slate-700 px-2 py-0.5 disabled:opacity-40">Previous</button>
                    <button type="button" disabled={page >= pages - 1} onClick={() => setPage((p) => p + 1)} title={page >= pages - 1 ? 'This is the last page' : undefined} className="rounded border border-slate-700 px-2 py-0.5 disabled:opacity-40">Next</button>
                  </span>
                </div>
              )}
            </>
          )}
        </>
      )}

      {mode === 'one' && (
        made ? (
          <div className="space-y-3" data-testid="tel-key-made">
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3">
              <p className="flex items-center gap-1.5 text-sm font-medium text-amber-100"><AlertTriangle className="h-4 w-4" /> Copy this key now. You will not see it again.</p>
              <div className="mt-2 flex items-center gap-2">
                <code className="min-w-0 flex-1 break-all rounded-md border border-slate-700 bg-slate-950 px-2.5 py-2 text-xs text-amber-100" data-testid="tel-key-value">{made.key}</code>
                <Copy1 text={made.key ?? ''} testId="tel-key-copy" />
              </div>
              <p className="mt-1 text-xs text-slate-400">It writes as {made.device_id} only. It is stored as a hash, so if it is lost, revoke it and make a new one.</p>
            </div>
            {snip && (
              <div>
                <div className="mb-1 flex items-center gap-1" role="tablist" aria-label="Code">
                  {(['curl', 'python', 'js'] as const).map((l) => (
                    <button key={l} type="button" role="tab" aria-selected={lang === l} onClick={() => setLang(l)} className={`rounded-md px-2 py-1 text-xs ${lang === l ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`}>{l === 'js' ? 'JavaScript' : l === 'python' ? 'Python' : 'curl'}</button>
                  ))}
                  <span className="flex-1" />
                  <Copy1 text={snip[lang]} label="Copy code" />
                </div>
                <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-md border border-slate-700 bg-slate-950 p-2.5 font-mono text-[11px] text-slate-200" data-testid="tel-key-snippet">{snip[lang]}</pre>
                <p className="mt-1 text-xs text-slate-500">Idempotency-Key makes a retry safe: the same key sent twice is stored once.</p>
              </div>
            )}
            <div className="flex gap-2">
              <button type="button" onClick={() => setMade(null)} className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800" data-testid="tel-key-another">Add another</button>
              <button type="button" onClick={() => { setMade(null); setMode('list'); }} className="rounded-lg bg-cyan-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-cyan-400">I have copied it</button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <div>
              <label htmlFor="tel-key-device" className="mb-1 block text-xs font-medium text-slate-300">Device id</label>
              <input id="tel-key-device" value={one.device_id} onChange={(e) => setOne({ ...one, device_id: e.target.value })} onBlur={() => setTouched(true)} placeholder="van-042" className={`${input} font-mono ${touched && idErr ? 'border-rose-500/60' : 'border-slate-700'}`} data-testid="tel-key-device" />
              {touched && idErr ? <p className="mt-1 text-xs text-rose-300" role="alert">{idErr}</p> : <p className="mt-1 text-xs text-slate-400">The asset name it shows up as. Example: van-042, or a serial number.</p>}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label htmlFor="tel-key-label" className="mb-1 block text-xs font-medium text-slate-300">Label <span className="font-normal text-slate-500">(optional)</span></label>
                <input id="tel-key-label" value={one.label} onChange={(e) => setOne({ ...one, label: e.target.value })} placeholder="Ford Transit, depot B" className={`${input} border-slate-700`} />
              </div>
              <div>
                <label htmlFor="tel-key-group" className="mb-1 block text-xs font-medium text-slate-300">Group <span className="font-normal text-slate-500">(optional)</span></label>
                <input id="tel-key-group" value={one.group} onChange={(e) => setOne({ ...one, group: e.target.value })} placeholder="fleet-north" className={`${input} border-slate-700`} />
              </div>
            </div>
            <button type="button" onClick={createOne} disabled={busy} className="inline-flex min-h-[38px] items-center gap-1.5 rounded-lg bg-cyan-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-cyan-400 disabled:opacity-60" data-testid="tel-key-create">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />} Make the key
            </button>
          </div>
        )
      )}

      {mode === 'bulk' && (
        bulkMade ? (
          <div className="space-y-3 rounded-lg border border-amber-500/40 bg-amber-500/5 p-3" data-testid="tel-keys-bulk-made">
            <p className="flex items-center gap-1.5 text-sm font-medium text-amber-100"><AlertTriangle className="h-4 w-4" /> {bulkMade.keys.length} keys made. Download them now, you will not see them again.</p>
            <button type="button" onClick={() => download(`${sourceName.replace(/\W+/g, '-').toLowerCase()}-device-keys.csv`, bulkMade.csv)} className="inline-flex items-center gap-1.5 rounded-lg bg-cyan-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-cyan-400" data-testid="tel-keys-download">
              <Download className="h-4 w-4" /> Download the keys as CSV
            </button>
            <p className="text-xs text-slate-400">Keep the file somewhere safe. Each line has a device id and its key, ready for your provisioning tool.</p>
            <button type="button" onClick={() => { setBulkMade(null); setMode('list'); }} className="text-xs text-cyan-300 hover:underline">I have downloaded them</button>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-slate-400">One device per line: device_id, then an optional label and group. A header row is fine. Up to {BULK_MAX.toLocaleString()} in one go.</p>
            <div className="flex flex-wrap items-center gap-2">
              <input ref={fileRef} type="file" accept=".csv,text/csv" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) f.text().then(setCsv).catch(() => setErr('Could not read that file. Try again or paste it below.')); e.target.value = ''; }} />
              <button type="button" onClick={() => fileRef.current?.click()} className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800" data-testid="tel-keys-upload"><FileUp className="h-3.5 w-3.5" /> Upload a CSV</button>
              <span className="text-xs text-slate-500">or paste it</span>
            </div>
            <textarea value={csv} onChange={(e) => setCsv(e.target.value)} rows={5} spellCheck={false} placeholder={'device_id,label,group\nvan-042,Ford Transit,fleet-north\nvan-043,,fleet-north'} className={`${input} border-slate-700 font-mono text-xs`} data-testid="tel-keys-csv" />
            {parsed.rows.length > 0 && (
              <div className="rounded-lg border border-slate-700/60 p-2 text-xs" data-testid="tel-keys-preview">
                <p className={bad.length || parsed.problem ? 'text-rose-200' : 'text-emerald-200'}>
                  {parsed.problem ?? (bad.length ? `${bad.length} of ${parsed.rows.length} lines need fixing before anything is made.` : `${parsed.rows.length} device${parsed.rows.length === 1 ? '' : 's'} ready.`)}
                </p>
                <ul className="mt-1 max-h-40 overflow-y-auto">
                  {(bad.length ? bad : parsed.rows).slice(0, 50).map((r) => (
                    <li key={r.line} className="flex gap-2 py-0.5">
                      <span className="w-12 shrink-0 text-slate-500">line {r.line}</span>
                      <span className="font-mono text-slate-200">{r.device_id || '(empty)'}</span>
                      {r.problem ? <span className="text-rose-300">{r.problem}</span> : <span className="text-slate-500">{[r.label, r.group].filter(Boolean).join(' · ')}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <button type="button" onClick={createBulk} disabled={busy || !parsed.rows.length || !!bad.length || !!parsed.problem} title={!parsed.rows.length ? 'Paste or upload a CSV first' : bad.length || parsed.problem ? 'Fix the lines marked above first' : undefined} className="inline-flex min-h-[38px] items-center gap-1.5 rounded-lg bg-cyan-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-cyan-400 disabled:opacity-50" data-testid="tel-keys-bulk-create">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Make {parsed.rows.length || ''} keys
            </button>
          </div>
        )
      )}

      {revoke && (
        <ConfirmModal
          open
          onClose={() => !busy && setRevoke(null)}
          onConfirm={doRevoke}
          loading={busy}
          icon={Trash2}
          title={`Revoke the key for ${revoke.kind === 'gateway' ? revoke.label || 'this gateway' : revoke.device_id}?`}
          description={`It stops working at once and anything sent with it is refused. ${revoke.kind === 'gateway' ? 'The gateway stops sending for every asset it covers until it is enrolled again on the Edge page.' : 'Make a new key for the device if it should keep sending.'} This is recorded in the audit log.`}
          confirmLabel="Revoke the key"
          confirmTestId="tel-key-revoke-confirm"
        />
      )}
    </div>
  );
}
