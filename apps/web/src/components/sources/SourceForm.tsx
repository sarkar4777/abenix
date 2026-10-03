'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, ChevronDown, FileSearch, KeyRound, Loader2, Plus, Trash2, X } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useApi } from '@/hooks/useApi';
import { TIER_STYLE } from '@/components/governance/TierPolicies';
import {
  CADENCES, KIND_LABEL, SELECTOR_HELP, bytes, isHttpUrl,
  type Preview, type Source, type SourceKind, type SourceSettings, type Tier,
} from '@/lib/sources';

type UrlCheck = { state: 'idle' | 'checking' | 'ok' | 'bad'; message?: string; suggested?: SourceKind };

const KINDS: SourceKind[] = ['html', 'pdf', 'xlsx', 'csv', 'json', 'rss'];
const INPUT = 'w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white placeholder:text-slate-600 focus:border-cyan-500 focus:outline-none';

export default function SourceForm({
  initial,
  onClose,
  onSaved,
}: {
  initial?: Source | null;
  onClose: () => void;
  onSaved: (s: Source) => void;
}) {
  const editing = !!initial;
  const { data: settings } = useApi<SourceSettings>('/api/sources/settings');
  const { data: kbs } = useApi<{ id: string; name: string }[]>('/api/knowledge-bases?limit=100&sort=name');
  const [name, setName] = useState(initial?.name || '');
  const [url, setUrl] = useState(initial?.url || '');
  const [kind, setKind] = useState<SourceKind>(initial?.kind || 'html');
  const [kindTouched, setKindTouched] = useState(editing);
  const [selector, setSelector] = useState(initial?.selector || '');
  const [cadence, setCadence] = useState<number>(initial?.cadence_minutes || 1440);
  const [customCadence, setCustomCadence] = useState(!CADENCES.some((c) => c.minutes === (initial?.cadence_minutes || 1440)));
  const [description, setDescription] = useState(initial?.description || '');
  const [jurisdiction, setJurisdiction] = useState(initial?.jurisdiction || '');
  const [tags, setTags] = useState((initial?.tags || []).join(', '));
  const [tier, setTier] = useState<Tier>(initial?.risk_tier || 'low');
  const [cred, setCred] = useState(initial?.credentials_key || '');
  const [kb, setKb] = useState(initial?.ingest_to_kb || '');
  const [headers, setHeaders] = useState<{ k: string; v: string }[]>(
    Object.entries(initial?.headers || {}).map(([k, v]) => ({ k, v })),
  );
  const [advanced, setAdvanced] = useState(editing && !!(initial?.credentials_key || initial?.ingest_to_kb || Object.keys(initial?.headers || {}).length));
  const [check, setCheck] = useState<UrlCheck>({ state: 'idle' });
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const seq = useRef(0);

  const urlShapeOk = isHttpUrl(url);
  const headerMap = useMemo(() => {
    const out: Record<string, string> = {};
    for (const h of headers) if (h.k.trim()) out[h.k.trim()] = h.v;
    return out;
  }, [headers]);
  const headerProblem = headers.some((h) => h.k.trim() && !/^[A-Za-z0-9][A-Za-z0-9-]{0,63}$/.test(h.k.trim()))
    ? 'Header names use letters, digits and dashes.'
    : headers.some((h) => ['authorization', 'cookie', 'x-api-key', 'proxy-authorization'].includes(h.k.trim().toLowerCase()))
      ? 'Put sign-in headers in a source credential below, so they are stored encrypted.'
      : null;
  const selectorHelp = SELECTOR_HELP[kind];

  useEffect(() => {
    const id = ++seq.current;
    if (!url.trim()) {
      setCheck({ state: 'idle' });
      return;
    }
    if (!urlShapeOk) {
      setCheck({ state: 'bad', message: 'Enter a full address that starts with https:// or http://.' });
      return;
    }
    setCheck({ state: 'checking' });
    const t = setTimeout(async () => {
      const r = await apiFetch<{ ok: boolean; reason: string | null; host: string; suggested_kind: SourceKind }>(
        '/api/sources/validate-url',
        { method: 'POST', body: JSON.stringify({ url: url.trim() }), throwOnError: false, silent: true },
      );
      if (id !== seq.current) return;
      if (r.error || !r.data) setCheck({ state: 'bad', message: r.error || 'Could not check the address.' });
      else if (!r.data.ok) setCheck({ state: 'bad', message: r.data.reason || 'This address cannot be watched.' });
      else {
        setCheck({ state: 'ok', message: `${r.data.host} can be watched.`, suggested: r.data.suggested_kind });
        if (!kindTouched && r.data.suggested_kind) setKind(r.data.suggested_kind);
      }
    }, 450);
    return () => clearTimeout(t);
  }, [url, urlShapeOk, kindTouched]);

  useEffect(() => {
    setPreview(null);
  }, [url, kind, selector, cred]);

  async function runPreview() {
    setPreviewing(true);
    setPreview(null);
    const r = await apiFetch<Preview>('/api/sources/preview', {
      method: 'POST',
      body: JSON.stringify({ url: url.trim(), kind, selector: selectorHelp ? selector.trim() || null : null, headers: headerMap, credentials_key: cred || null }),
      throwOnError: false,
    });
    setPreviewing(false);
    setPreview(r.data || { ok: false, error: r.error || 'The test fetch failed.' });
  }

  const ready = name.trim() && urlShapeOk && check.state !== 'bad' && !headerProblem && cadence >= 5;

  async function save() {
    setSaving(true);
    setErr(null);
    const body = {
      name: name.trim(),
      url: url.trim(),
      kind,
      selector: selectorHelp ? selector.trim() || null : null,
      cadence_minutes: cadence,
      description: description.trim(),
      jurisdiction: jurisdiction.trim() || null,
      tags: tags.split(',').map((t) => t.trim()).filter(Boolean),
      risk_tier: tier,
      credentials_key: cred || null,
      ingest_to_kb: kb || null,
      headers: headerMap,
    };
    const r = await apiFetch<Source>(editing ? `/api/sources/${initial!.id}` : '/api/sources', {
      method: editing ? 'PATCH' : 'POST',
      body: JSON.stringify(body),
      throwOnError: false,
    });
    setSaving(false);
    if (r.error || !r.data) setErr(r.error || 'Could not save the source.');
    else onSaved(r.data);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start md:items-center justify-center bg-black/60 p-4 overflow-y-auto" role="dialog" aria-modal="true" aria-labelledby="source-form-title">
      <div className="w-full max-w-5xl max-h-[94vh] flex flex-col rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800">
          <h2 id="source-form-title" className="text-lg font-semibold text-white">{editing ? `Edit ${initial!.name}` : 'Watch a new source'}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1 rounded text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
        </div>
        <div className="flex-1 overflow-y-auto grid lg:grid-cols-[1fr_1fr] gap-0">
          <div className="px-6 py-5 space-y-4 lg:border-r border-slate-800">
            <div>
              <label htmlFor="sf-url" className="block text-sm font-medium text-slate-200 mb-1.5">Address</label>
              <input id="sf-url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://eur-lex.europa.eu/…" className={INPUT} aria-invalid={check.state === 'bad'} aria-describedby="sf-url-msg" data-testid="source-url" autoFocus={!editing} />
              <p id="sf-url-msg" className={`mt-1 text-xs flex items-center gap-1.5 ${check.state === 'bad' ? 'text-rose-300' : check.state === 'ok' ? 'text-emerald-300' : 'text-slate-500'}`} aria-live="polite" data-testid="source-url-check">
                {check.state === 'checking' && <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Checking the address…</>}
                {check.state === 'ok' && <><CheckCircle2 className="w-3.5 h-3.5" /> {check.message}</>}
                {check.state === 'bad' && <><AlertTriangle className="w-3.5 h-3.5" /> {check.message}</>}
                {check.state === 'idle' && 'A web page, PDF, spreadsheet, CSV, JSON document or feed.'}
              </p>
            </div>
            <div>
              <label htmlFor="sf-name" className="block text-sm font-medium text-slate-200 mb-1.5">Name</label>
              <input id="sf-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="EU CBAM implementing regulation" className={INPUT} data-testid="source-name" />
            </div>
            <div>
              <div className="text-sm font-medium text-slate-200 mb-1.5">What it is</div>
              <div className="grid grid-cols-3 sm:grid-cols-6 gap-1 p-0.5 rounded-lg border border-slate-700 bg-slate-950" role="radiogroup" aria-label="Source kind">
                {KINDS.map((k) => (
                  <button key={k} type="button" role="radio" aria-checked={kind === k} onClick={() => { setKind(k); setKindTouched(true); }} className={`py-1.5 rounded-md text-xs ${kind === k ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`} data-testid={`source-kind-${k}`}>
                    {KIND_LABEL[k]}
                  </button>
                ))}
              </div>
              {check.suggested && check.suggested !== kind && (
                <p className="mt-1 text-xs text-amber-300">
                  The address looks like {KIND_LABEL[check.suggested]}.{' '}
                  <button type="button" className="underline" onClick={() => setKind(check.suggested!)}>Use that</button>
                </p>
              )}
            </div>
            {selectorHelp && (
              <div>
                <label htmlFor="sf-sel" className="block text-sm font-medium text-slate-200 mb-1.5">{selectorHelp.label} <span className="text-slate-500 font-normal">(optional)</span></label>
                <input id="sf-sel" value={selector} onChange={(e) => setSelector(e.target.value)} placeholder={selectorHelp.placeholder} className={`${INPUT} font-mono`} data-testid="source-selector" />
                <p className="mt-1 text-xs text-slate-500">{selectorHelp.help} Narrowing the watch keeps menus, banners and dates elsewhere on the page from showing up as changes.</p>
              </div>
            )}
            <div>
              <label htmlFor="sf-cad" className="block text-sm font-medium text-slate-200 mb-1.5">How often to check</label>
              <div className="flex gap-2">
                <select id="sf-cad" value={customCadence ? 'custom' : String(cadence)} onChange={(e) => { if (e.target.value === 'custom') setCustomCadence(true); else { setCustomCadence(false); setCadence(Number(e.target.value)); } }} className={INPUT} data-testid="source-cadence">
                  {CADENCES.map((c) => <option key={c.minutes} value={c.minutes}>{c.label}</option>)}
                  <option value="custom">Custom…</option>
                </select>
                {customCadence && (
                  <div className="flex items-center gap-2 shrink-0">
                    <input type="number" min={5} value={cadence} onChange={(e) => setCadence(Math.max(0, Number(e.target.value) || 0))} className={`${INPUT} w-28`} aria-label="Minutes between checks" />
                    <span className="text-xs text-slate-400">minutes</span>
                  </div>
                )}
              </div>
              {cadence < 5 && <p className="mt-1 text-xs text-rose-300">Check at most every 5 minutes.</p>}
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="sf-jur" className="block text-sm font-medium text-slate-200 mb-1.5">Jurisdiction <span className="text-slate-500 font-normal">(optional)</span></label>
                <input id="sf-jur" value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value)} placeholder="EU" className={INPUT} maxLength={64} />
              </div>
              <div>
                <label htmlFor="sf-tags" className="block text-sm font-medium text-slate-200 mb-1.5">Tags <span className="text-slate-500 font-normal">(comma separated)</span></label>
                <input id="sf-tags" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="cbam, carbon" className={INPUT} />
              </div>
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
              <p className="mt-1 text-xs text-slate-500">Carried on every change event, so subscribers can route high tier changes for review.</p>
            </div>
            <div>
              <label htmlFor="sf-desc" className="block text-sm font-medium text-slate-200 mb-1.5">Notes <span className="text-slate-500 font-normal">(optional)</span></label>
              <textarea id="sf-desc" value={description} onChange={(e) => setDescription(e.target.value)} rows={2} className={INPUT} placeholder="Why this source matters and who reviews its changes" />
            </div>

            <button type="button" onClick={() => setAdvanced((a) => !a)} className="inline-flex items-center gap-1.5 text-sm text-slate-300 hover:text-white" aria-expanded={advanced}>
              <ChevronDown className={`w-4 h-4 transition ${advanced ? 'rotate-180' : ''}`} /> Sign-in, headers and knowledge base
            </button>
            {advanced && (
              <div className="space-y-4 rounded-xl border border-slate-800 bg-slate-950/40 p-4">
                <div>
                  <label htmlFor="sf-cred" className="block text-sm font-medium text-slate-200 mb-1.5">Sign-in credential</label>
                  <select id="sf-cred" value={cred} onChange={(e) => setCred(e.target.value)} className={INPUT}>
                    <option value="">None, the source is public</option>
                    {(settings?.credential_keys || []).map((c) => (
                      <option key={c.key} value={c.key}>{c.key}{c.set ? '' : ' (not set yet)'}</option>
                    ))}
                  </select>
                  <p className="mt-1 text-xs text-slate-500 flex items-start gap-1.5">
                    <KeyRound className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                    Admins store these under Admin, Tool Configuration, Source Watch. A token is sent as a Bearer header, or store a full header such as “X-Api-Key: abc”. It is only sent to this source’s own host.
                  </p>
                </div>
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-sm font-medium text-slate-200">Request headers</span>
                    <button type="button" onClick={() => setHeaders((h) => [...h, { k: '', v: '' }])} className="inline-flex items-center gap-1 text-xs text-cyan-300 hover:underline" disabled={headers.length >= 20}>
                      <Plus className="w-3.5 h-3.5" /> Add header
                    </button>
                  </div>
                  {headers.length === 0 ? (
                    <p className="text-xs text-slate-500">None. Add one if the site needs, for example, an Accept-Language header.</p>
                  ) : (
                    <div className="space-y-2">
                      {headers.map((h, i) => (
                        <div key={i} className="flex gap-2">
                          <input value={h.k} onChange={(e) => setHeaders((hs) => hs.map((x, j) => (j === i ? { ...x, k: e.target.value } : x)))} placeholder="Accept-Language" className={`${INPUT} font-mono`} aria-label={`Header ${i + 1} name`} />
                          <input value={h.v} onChange={(e) => setHeaders((hs) => hs.map((x, j) => (j === i ? { ...x, v: e.target.value } : x)))} placeholder="en" className={`${INPUT} font-mono`} aria-label={`Header ${i + 1} value`} />
                          <button type="button" onClick={() => setHeaders((hs) => hs.filter((_, j) => j !== i))} aria-label={`Remove header ${i + 1}`} className="p-2 text-slate-500 hover:text-rose-300"><Trash2 className="w-4 h-4" /></button>
                        </div>
                      ))}
                    </div>
                  )}
                  {headerProblem && <p className="mt-1 text-xs text-rose-300">{headerProblem}</p>}
                </div>
                <div>
                  <label htmlFor="sf-kb" className="block text-sm font-medium text-slate-200 mb-1.5">Add each new snapshot to a knowledge base</label>
                  <select id="sf-kb" value={kb} onChange={(e) => setKb(e.target.value)} className={INPUT}>
                    <option value="">No, keep snapshots here only</option>
                    {(kbs || []).map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}
                  </select>
                  <p className="mt-1 text-xs text-slate-500">Each version becomes a new document version, so answers cite the exact snapshot they came from.</p>
                </div>
              </div>
            )}
          </div>

          <div className="px-6 py-5 bg-slate-950/30 flex flex-col min-h-[320px]">
            <div className="flex items-center justify-between gap-2 mb-3">
              <div>
                <div className="text-sm font-medium text-white">Test fetch</div>
                <p className="text-xs text-slate-500">See exactly the text that will be watched, before you save.</p>
              </div>
              <button type="button" onClick={runPreview} disabled={!urlShapeOk || check.state === 'bad' || previewing || !!headerProblem} className="inline-flex items-center gap-1.5 px-3 py-2 rounded-md text-sm border border-cyan-500/40 text-cyan-200 hover:bg-cyan-500/10 disabled:opacity-40" data-testid="source-test-fetch">
                {previewing ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileSearch className="w-4 h-4" />} Test fetch now
              </button>
            </div>
            <PreviewPanel preview={preview} loading={previewing} kind={kind} onUseKind={(k) => { setKind(k); setKindTouched(true); }} />
          </div>
        </div>
        {err && <p className="px-6 pt-3 text-sm text-rose-300" role="alert" data-testid="source-form-error">{err}</p>}
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-slate-800">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-md text-sm text-slate-300 hover:bg-slate-800">Cancel</button>
          <button type="button" onClick={save} disabled={!ready || saving} className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400 disabled:opacity-40" data-testid="source-save">
            {saving && <Loader2 className="w-4 h-4 animate-spin" />} {editing ? 'Save changes' : 'Start watching'}
          </button>
        </div>
      </div>
    </div>
  );
}

function PreviewPanel({ preview, loading, kind, onUseKind }: { preview: Preview | null; loading: boolean; kind: SourceKind; onUseKind: (k: SourceKind) => void }) {
  if (loading) {
    return (
      <div className="flex-1 rounded-xl border border-slate-800 p-4 space-y-2" aria-busy="true">
        {[0, 1, 2, 3, 4].map((i) => <div key={i} className="h-3 rounded bg-slate-800/60 animate-pulse" style={{ width: `${90 - i * 12}%` }} />)}
      </div>
    );
  }
  if (!preview) {
    return (
      <div className="flex-1 rounded-xl border border-dashed border-slate-700 p-6 flex items-center justify-center text-center text-sm text-slate-500">
        Nothing fetched yet. Test fetch shows the cleaned text, with scripts, menus and footers taken out, that changes are detected on.
      </div>
    );
  }
  if (!preview.ok) {
    return (
      <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-200" role="alert" data-testid="source-preview-error">
        <div className="flex items-center gap-2 font-medium"><AlertTriangle className="w-4 h-4" /> The test fetch did not work</div>
        <p className="mt-1">{preview.error}</p>
        {preview.detected_kind && preview.detected_kind !== kind && (
          <p className="mt-2 text-amber-200">
            It looks like {KIND_LABEL[preview.detected_kind]}.{' '}
            <button type="button" className="underline" onClick={() => onUseKind(preview.detected_kind!)}>Read it as {KIND_LABEL[preview.detected_kind]}</button>
          </p>
        )}
      </div>
    );
  }
  return (
    <div className="flex-1 flex flex-col min-h-0" data-testid="source-preview">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400 mb-2">
        <span className="text-emerald-300 inline-flex items-center gap-1"><CheckCircle2 className="w-3.5 h-3.5" /> HTTP {preview.status}</span>
        <span>{preview.content_type || 'unknown type'}</span>
        <span>{bytes(preview.bytes)}</span>
        <span>{preview.elapsed_ms} ms</span>
        <span>{(preview.text_chars || 0).toLocaleString()} characters, {preview.lines} lines</span>
        {preview.etag && <span title="The site supports conditional requests, so unchanged checks are cheap">ETag</span>}
      </div>
      {preview.detected_kind && preview.detected_kind !== preview.kind && (
        <p className="text-xs text-amber-300 mb-2">
          The server says this is {KIND_LABEL[preview.detected_kind]}.{' '}
          <button type="button" className="underline" onClick={() => onUseKind(preview.detected_kind!)}>Read it that way</button>
        </p>
      )}
      {preview.title && <div className="text-sm font-medium text-white mb-1">{preview.title}</div>}
      {(preview.notes || []).map((n) => <p key={n} className="text-xs text-amber-300 mb-1">{n}</p>)}
      {preview.table ? (
        <div className="flex-1 overflow-auto rounded-lg border border-slate-800 max-h-[420px]">
          <table className="min-w-full text-xs font-mono text-slate-200">
            <tbody className="divide-y divide-slate-800">
              {preview.table.rows.map((r, i) => (
                <tr key={i} className={i === 0 ? 'bg-slate-900 text-slate-400' : ''}>
                  {r.map((c, j) => <td key={j} className="px-2 py-1 whitespace-nowrap">{c}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="px-2 py-1 text-[11px] text-slate-500">
            {preview.table.total_rows} rows{preview.table.sheets.length > 1 ? ` in ${preview.table.sheets.length} sheets` : ''}, first {preview.table.rows.length} shown.
          </p>
        </div>
      ) : (
        <pre className="flex-1 overflow-auto rounded-lg border border-slate-800 bg-slate-950 p-3 text-xs text-slate-200 whitespace-pre-wrap break-words max-h-[420px]" data-testid="source-preview-text">
          {preview.text || '(no readable text)'}
          {(preview.text_chars || 0) > (preview.text?.length || 0) && `\n\n… ${((preview.text_chars || 0) - (preview.text?.length || 0)).toLocaleString()} more characters`}
        </pre>
      )}
    </div>
  );
}
