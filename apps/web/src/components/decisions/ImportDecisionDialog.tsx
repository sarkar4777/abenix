'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { AlertTriangle, CheckCircle2, FileJson, Loader2, Upload, X } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { KEY_RE, normProblemPath, type Problem } from '@/lib/decisions';
import { decisionErrorText } from '@/lib/decisionValues';

interface Preview {
  creates: boolean;
  key: string | null;
  name?: string;
  risk_tier?: string;
  rules: number;
  tests: number;
  problems: Problem[];
  normalized?: { path?: string; message?: string; from?: unknown; to?: unknown }[];
  tier_note?: string | null;
  target?: 'new' | 'existing';
  identical_to_latest?: boolean;
  suggested_key?: string | null;
  name_taken?: boolean;
}

const BLOCKING = new Set(['BAD_FILE', 'NO_KEY', 'BAD_KEY', 'KEY_TAKEN', 'ARCHIVED', 'BAD_TIER']);

function where(path: string): string {
  const p = normProblemPath(path || '');
  const m = p.match(/^\/rules\/(\d+)(?:\/(.*))?$/);
  if (m) return `Rule ${Number(m[1]) + 1}${m[2] ? `, ${m[2].replace(/\//g, ' ')}` : ''}`;
  if (p === '/key') return 'Key';
  if (!p || p === '/') return 'File';
  return p.slice(1).replace(/\//g, ' ');
}

// a draft into a decision that already exists is the risky way, so a new decision is the default
export default function ImportDecisionDialog({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const [text, setText] = useState('');
  const [fileName, setFileName] = useState<string | null>(null);
  const [mode, setMode] = useState<'new' | 'draft'>('new');
  const [asKey, setAsKey] = useState('');
  const [asName, setAsName] = useState('');
  const [keyTouched, setKeyTouched] = useState(false);
  const [base, setBase] = useState<Preview | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [checking, setChecking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [sure, setSure] = useState(false);
  const seq = useRef(0);

  let parsed: any = null;
  let parseErr: string | null = null;
  if (text.trim()) {
    try { parsed = JSON.parse(text); } catch (e: any) { parseErr = e.message; }
    if (parsed !== null && (typeof parsed !== 'object' || Array.isArray(parsed))) { parseErr = 'The file should hold one decision, an object with a key and its rules.'; parsed = null; }
  }
  const exists = !!base && (base.target === 'existing' || !base.creates);
  const altKey = exists && mode === 'new' ? asKey.trim() : '';
  const altBad = !!altKey && !KEY_RE.test(altKey);

  // first look at the file as it is, to learn whether its key is already used
  useEffect(() => {
    setBase(null);
    setPreview(null);
    setErr(null);
    setKeyTouched(false);
    setSure(false);
    if (!parsed) return;
    const n = ++seq.current;
    setChecking(true);
    const t = setTimeout(async () => {
      const r = await apiFetch<Preview>('/api/decisions/import?preview=1', { method: 'POST', body: text, throwOnError: false, silent: true });
      if (n !== seq.current) return;
      setChecking(false);
      if (!r.data) { setErr(r.error || 'The file could not be checked.'); return; }
      const p = { ...r.data, problems: (r.data.problems || []).map((x) => ({ ...x, path: (x as any).path ?? (x as any).field ?? '' })) };
      setBase(p);
      const taken = p.target === 'existing' || !p.creates;
      setMode('new');
      setAsKey(taken ? p.suggested_key || `${p.key || 'decision'}.copy` : '');
      setAsName(taken ? `${p.name || p.key} (copy)` : p.name || '');
      if (!taken) setPreview(p);
    }, 400);
    return () => clearTimeout(t);
    // parsed follows text
  }, [text]);

  // then check the choice: under a new key, or as a draft of the existing decision
  useEffect(() => {
    if (!base || !exists) return;
    if (mode === 'draft') { setPreview(base); return; }
    if (altBad || !altKey) { setPreview(null); return; }
    const n = ++seq.current;
    setChecking(true);
    const t = setTimeout(async () => {
      const r = await apiFetch<Preview>(`/api/decisions/import?preview=1&as_new_key=${encodeURIComponent(altKey)}`, { method: 'POST', body: text, throwOnError: false, silent: true });
      if (n !== seq.current) return;
      setChecking(false);
      if (r.data) setPreview({ ...r.data, problems: (r.data.problems || []).map((x) => ({ ...x, path: (x as any).path ?? (x as any).field ?? '' })) });
      else setErr(r.error || 'The file could not be checked.');
    }, 350);
    return () => clearTimeout(t);
  }, [base, exists, mode, altKey, altBad, text]);

  async function onFile(f: File) {
    setFileName(f.name);
    setText(await f.text());
  }

  async function go() {
    if (!parsed || !preview) return;
    setBusy(true);
    setErr(null);
    const q = new URLSearchParams();
    if (altKey) q.set('as_new_key', altKey);
    const name = asName.trim();
    if (name && (exists ? mode === 'new' : name !== (base?.name || ''))) q.set('as_new_name', name);
    const qs = q.toString();
    const r = await apiFetch<any>(`/api/decisions/import${qs ? `?${qs}` : ''}`, { method: 'POST', body: text, throwOnError: false });
    setBusy(false);
    if (r.error || !r.data) { setErr(decisionErrorText(r.errorDetail?.error_code, r.error || 'Not imported.')); return; }
    if (r.data.no_changes) { setErr(null); setPreview({ ...preview, identical_to_latest: true }); return; }
    // open the draft the import made, not the first version
    const d = r.data.draft;
    const n = typeof d === 'number' ? d : d?.version ?? r.data.version;
    router.push(`/decisions/${encodeURIComponent(r.data.key)}${n ? `?version=${n}` : ''}`);
  }

  const shown = preview;
  const blocking = (shown?.problems || []).filter((p) => BLOCKING.has(p.code));
  const ruleProblems = (shown?.problems || []).filter((p) => !BLOCKING.has(p.code));
  const identical = mode === 'draft' && !!base?.identical_to_latest;
  const needSure = exists && mode === 'draft';
  const ready = !!parsed && !!shown && !blocking.length && !checking && !altBad && !identical && (!needSure || sure) && (mode === 'draft' || !exists || !!altKey);
  const why = !text.trim() ? 'Choose a file or paste the JSON first.'
    : parseErr ? 'Fix the JSON first.'
    : altBad ? 'Fix the new key first.'
    : checking || (!shown && !err) ? 'Checking the file…'
    : blocking.length ? 'Sort out the problem above first.'
    : identical ? 'The file has no changes to import.'
    : needSure && !sure ? 'Tick the box to confirm a draft into the existing decision.'
    : '';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-labelledby="import-decision-title" data-testid="import-decision-dialog">
      <div className="w-full max-w-2xl max-h-[90vh] flex flex-col rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800">
          <h2 id="import-decision-title" className="flex items-center gap-2 text-lg font-semibold text-white"><FileJson className="w-5 h-5 text-cyan-400" /> Import a decision</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1 rounded text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          <p className="text-sm text-slate-400">
            Bring in a whole decision from a file: its rules, golden tests and risk tier. Use a file exported with Export, Full decision, or one with a key, a name, rules and tests.
            Nothing is published. You get a draft to check, then propose as usual. <a href="/docs?doc=08-howto%2F09-decisions#files-export-and-import" target="_blank" rel="noreferrer" className="text-cyan-300 hover:underline">More on files</a>
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <label className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-slate-700 text-sm text-cyan-300 cursor-pointer hover:bg-slate-800">
              <Upload className="w-4 h-4" /> Choose a file
              <input type="file" accept=".json,application/json" className="sr-only" onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} data-testid="import-decision-file" />
            </label>
            <span className="text-xs text-slate-500">{fileName ? `Read ${fileName}.` : 'or paste the JSON below'}</span>
          </div>
          <textarea
            value={text}
            onChange={(e) => { setText(e.target.value); setFileName(null); }}
            rows={6}
            spellCheck={false}
            placeholder="paste the decision file here"
            className={`w-full bg-slate-950 border rounded-md px-3 py-2 text-xs text-slate-200 font-mono placeholder:text-slate-600 placeholder:italic placeholder:font-sans ${parseErr ? 'border-rose-500/60' : 'border-slate-700'}`}
            aria-label="Decision file as JSON"
            data-testid="import-decision-json"
          />
          {parseErr && <p className="text-xs text-rose-300" role="alert">This is not valid JSON: {parseErr}</p>}

          {exists && base && (
            <fieldset className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 space-y-2" data-testid="import-target">
              <legend className="px-1 text-xs text-amber-200">{base.key} already exists in this workspace</legend>
              <label className="flex items-start gap-2 text-sm text-slate-200">
                <input type="radio" name="import-mode" checked={mode === 'new'} onChange={() => setMode('new')} className="mt-1 accent-cyan-500" data-testid="import-as-new" />
                <span>Import it as a new decision <span className="text-slate-500">(safest, nothing existing changes)</span></span>
              </label>
              {mode === 'new' && (
                <div className="ml-6 grid gap-2 sm:grid-cols-2">
                  <div>
                    <label htmlFor="import-as-key" className="block text-xs text-slate-400 mb-1">New key</label>
                    <input id="import-as-key" value={asKey} onChange={(e) => { setAsKey(e.target.value.trim()); setKeyTouched(true); }} className={`w-full bg-slate-950 border rounded-md px-2 py-1.5 text-sm text-white font-mono ${altBad ? 'border-rose-500/60' : 'border-slate-700'}`} data-testid="import-as-key" />
                    <p className={`mt-0.5 text-[11px] ${altBad ? 'text-rose-300' : 'text-slate-500'}`}>{altBad ? 'Use lowercase letters, digits, dots, dashes or underscores.' : keyTouched ? 'Agents and apps call it by this key.' : 'A free key, suggested for you.'}</p>
                  </div>
                  <div>
                    <label htmlFor="import-as-name" className="block text-xs text-slate-400 mb-1">Name</label>
                    <input id="import-as-name" value={asName} onChange={(e) => setAsName(e.target.value)} className="w-full bg-slate-950 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-white" data-testid="import-as-name" />
                    <p className="mt-0.5 text-[11px] text-slate-500">So the copy is not mistaken for the original.</p>
                  </div>
                </div>
              )}
              <label className="flex items-start gap-2 text-sm text-slate-200">
                <input type="radio" name="import-mode" checked={mode === 'draft'} onChange={() => setMode('draft')} disabled={!!base.identical_to_latest} className="mt-1 accent-cyan-500" data-testid="import-as-draft" />
                <span>Add it as a new draft of {base.key}{base.identical_to_latest ? <span className="text-slate-500"> (not offered, the file matches its latest version)</span> : null}</span>
              </label>
              {mode === 'draft' && (
                <label className="ml-6 flex items-start gap-2 text-xs text-amber-100">
                  <input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} className="mt-0.5 accent-amber-500" data-testid="import-draft-sure" />
                  I understand this makes a new draft of {base.key}. What it answers does not change until that draft is proposed, signed off and published.
                </label>
              )}
            </fieldset>
          )}

          {!exists && base && (
            <div>
              <label htmlFor="import-as-name" className="block text-xs text-slate-400 mb-1">Name</label>
              <input id="import-as-name" value={asName} onChange={(e) => setAsName(e.target.value)} className="w-full bg-slate-950 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-white" data-testid="import-as-name" />
              {base.name_taken && <p className="mt-0.5 text-[11px] text-amber-200">Another decision already has this name. Rename it so people can tell them apart.</p>}
            </div>
          )}

          {checking && <p className="text-xs text-slate-400 flex items-center gap-1.5"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Checking the file…</p>}
          {shown && (
            <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-3 space-y-2 text-sm" data-testid="import-decision-preview">
              <p className="text-slate-200">
                {mode === 'draft' && exists
                  ? <>Adds a new draft to <span className="font-mono text-cyan-300">{base?.key}</span>, which already exists</>
                  : <>Creates a new decision <span className="font-mono text-cyan-300">{shown.key}</span>{(asName || shown.name) ? ` called ${asName || shown.name}` : ''}</>}
                {' '}with {shown.rules} rule{shown.rules === 1 ? '' : 's'} and {shown.tests} golden test{shown.tests === 1 ? '' : 's'}{shown.risk_tier ? `, at ${shown.risk_tier} risk` : ''}.
              </p>
              {identical && <p className="text-xs text-amber-200" data-testid="import-identical">This file matches the latest version of {base?.key}, so a draft would change nothing.</p>}
              {shown.tier_note && <p className="text-xs text-amber-200">{shown.tier_note}</p>}
              {(shown.normalized || []).length > 0 && (
                <p className="text-xs text-slate-400">{shown.normalized!.length} value{shown.normalized!.length === 1 ? ' is' : 's are'} tidied on the way in, for example numbers written as text.</p>
              )}
              {blocking.map((p, i) => <p key={i} className="flex gap-1.5 text-xs text-rose-300" role="alert"><AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" /> {p.message}</p>)}
              {ruleProblems.length > 0 ? (
                <div>
                  <p className="text-xs text-amber-200">{ruleProblems.length} problem{ruleProblems.length === 1 ? '' : 's'} in the rules. You can still import and fix them in the draft.</p>
                  <ul className="mt-1 space-y-0.5 max-h-32 overflow-y-auto" data-testid="import-decision-problems">
                    {ruleProblems.map((p, i) => <li key={i} className="text-[11px] text-slate-300"><span className="text-slate-500">{where(p.path)}:</span> {p.message}</li>)}
                  </ul>
                </div>
              ) : !blocking.length && <p className="flex items-center gap-1.5 text-xs text-emerald-300"><CheckCircle2 className="w-3.5 h-3.5" /> No problems found.</p>}
            </div>
          )}
          {err && <p className="text-sm text-rose-300" role="alert">{err}</p>}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 px-6 py-4 border-t border-slate-800">
          {!ready && why && <span className="mr-auto text-xs text-slate-500" data-testid="import-decision-why">{why}</span>}
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-md text-sm text-slate-300 hover:bg-slate-800">Cancel</button>
          <button type="button" onClick={go} disabled={!ready || busy} className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400 disabled:opacity-40" data-testid="import-decision-go">
            {busy && <Loader2 className="w-4 h-4 animate-spin" />} {exists && mode === 'draft' ? 'Import as a new draft' : 'Import as a new decision'}
          </button>
        </div>
      </div>
    </div>
  );
}
