'use client';

import { useEffect, useRef, useState } from 'react';
import { Braces, CheckCircle2, CircleSlash, FlaskConical, ListChecks, Loader2, Save, TriangleAlert } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { getPath, orderedResult, setPath, type Evaluation, type Fact, type RuleDoc, type TryPreload } from '@/lib/decisions';
import { DraftInput, NumberInput } from './DraftInput';

const OUTCOME = {
  decided: { icon: CheckCircle2, cls: 'text-emerald-300 border-emerald-500/30 bg-emerald-500/5', text: 'Decided' },
  no_match: { icon: CircleSlash, cls: 'text-slate-300 border-slate-600 bg-slate-800/40', text: 'No rule applies' },
  missing_facts: { icon: TriangleAlert, cls: 'text-amber-300 border-amber-500/30 bg-amber-500/5', text: 'Missing facts' },
  invalid_facts: { icon: TriangleAlert, cls: 'text-rose-300 border-rose-500/30 bg-rose-500/5', text: 'Facts with the wrong type' },
  not_ready: { icon: TriangleAlert, cls: 'text-amber-300 border-amber-500/30 bg-amber-500/5', text: 'Fix the rules first' },
} as const;

const listParse = (t: string) => ({ value: t.trim() ? t.split(',').map((s) => s.trim()).filter(Boolean) : undefined });
const listFormat = (v: any) => (v === undefined || v === null ? '' : Array.isArray(v) ? v.join(', ') : String(v));

function FactField({ f, value, onChange, highlight }: { f: Fact; value: any; onChange: (v: any) => void; highlight?: boolean }) {
  const cls = `w-full bg-slate-950 border rounded-md px-2 py-1 text-sm text-white placeholder:text-slate-600 placeholder:italic ${highlight ? 'border-amber-500/70' : 'border-slate-700'}`;
  const a11y = { 'aria-label': f.label || f.path, 'data-testid': `try-fact-${f.path}` };
  if (f.type === 'boolean') {
    return (
      <select {...a11y} value={value === undefined ? '' : String(value)} onChange={(e) => onChange(e.target.value === '' ? undefined : e.target.value === 'true')} className={cls}>
        <option value="">not given</option><option value="true">yes</option><option value="false">no</option>
      </select>
    );
  }
  if (f.type === 'date') return <input {...a11y} type="date" value={value ?? ''} onChange={(e) => onChange(e.target.value || undefined)} className={`${cls} [color-scheme:dark]`} />;
  if (f.type === 'number') return <NumberInput {...a11y} value={value} emptyAs={undefined} onValue={onChange} placeholder="type a number" className={cls} />;
  if (f.type === 'list') return <DraftInput {...a11y} value={value} format={listFormat} parse={listParse} onValue={onChange} placeholder="items, separated by commas" className={cls} />;
  return <input {...a11y} value={value === undefined ? '' : String(value)} onChange={(e) => onChange(e.target.value === '' ? undefined : e.target.value)} placeholder="type text" className={cls} />;
}

// facts and outcomes by the names people gave them, values as a person would write them
function labelOf(doc: RuleDoc | null, key: string): string {
  return doc?.facts.find((f) => f.path === key)?.label || doc?.outputs.find((o) => o.field === key)?.label || key;
}

function plainValue(v: unknown): string {
  if (v === '' || v === null || v === undefined) return '(empty)';
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (typeof v === 'string' || typeof v === 'number') return String(v);
  return JSON.stringify(v);
}

export function resultRows(doc: RuleDoc | null, result: unknown): [string, string][] {
  if (!result || typeof result !== 'object' || Array.isArray(result)) return [['Answer', plainValue(result)]];
  return Object.entries(orderedResult(doc, result) as Record<string, unknown>).map(([k, v]) => [labelOf(doc, k), plainValue(v)]);
}

export default function TryPanel({
  decisionKey,
  version,
  doc,
  live,
  onSelectRule,
  onSavedTest,
  canSaveTest,
  preload,
  problemCount,
}: {
  decisionKey: string;
  version: number;
  doc: RuleDoc | null;
  live: boolean;
  onSelectRule: (ruleKeyOrId: string) => void;
  onSavedTest: () => void;
  canSaveTest: boolean;
  preload?: TryPreload | null;
  // the same count the tabs and the problem list show
  problemCount: number;
}) {
  const [facts, setFacts] = useState<Record<string, any>>(() => preload?.facts ?? {});
  const [asOf, setAsOf] = useState((preload?.as_of || new Date().toISOString()).slice(0, 10));
  const [mode, setMode] = useState<'form' | 'json'>('form');
  const [jsonText, setJsonText] = useState(() => JSON.stringify(preload?.facts ?? {}, null, 2));
  const [jsonErr, setJsonErr] = useState<string | null>(null);
  const [res, setRes] = useState<Evaluation | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [testName, setTestName] = useState('');
  const [pin, setPin] = useState(false);
  const [pinDate, setPinDate] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<{ ok: boolean; text: string } | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    const n = ++seq.current;
    const t = setTimeout(async () => {
      setBusy(true);
      const r = await apiFetch<Evaluation>(`/api/decisions/${encodeURIComponent(decisionKey)}/versions/${version}/try`, {
        method: 'POST',
        body: JSON.stringify({ facts, as_of: asOf || null, authoring: live && doc ? doc : null }),
        throwOnError: false,
        silent: true,
      });
      if (n !== seq.current) return;
      setBusy(false);
      if (r.data) {
        // a not_ready answer carries only problems, so fill the rest in
        setRes({ result: null, applied_rules: [], missing_facts: [], invalid_facts: [], normalised: [], trace: [], trace_hash: '', duration_us: 0, ...(r.data as Partial<Evaluation>) } as Evaluation);
        setErr(null);
      } else setErr(r.error);
    }, 350);
    return () => clearTimeout(t);
  }, [facts, asOf, doc, live, decisionKey, version]);

  function setFact(path: string, v: any) {
    const next = setPath(facts, path, v);
    if (v === undefined) {
      const parts = path.split('.');
      let cur: any = next;
      for (const p of parts.slice(0, -1)) cur = cur?.[p];
      if (cur) delete cur[parts[parts.length - 1]];
    }
    setFacts(next);
    setJsonText(JSON.stringify(next, null, 2));
    setSaved(null);
  }

  async function saveTest() {
    if (!res) return;
    setSaving(true);
    const pinned = pin ? pinDate || asOf : null;
    const r = await apiFetch(`/api/decisions/${encodeURIComponent(decisionKey)}/tests`, {
      method: 'POST',
      body: JSON.stringify({
        name: testName.trim() || `Case ${new Date().toLocaleString()}`,
        facts,
        as_of: pinned,
        expected_outcome: res.outcome === 'not_ready' ? 'decided' : res.outcome,
        expected: res.outcome === 'decided' ? res.result : null,
      }),
      throwOnError: false,
    });
    setSaving(false);
    if (r.error) setSaved({ ok: false, text: `Not saved: ${r.error}` });
    else {
      setSaved({ ok: true, text: `Saved as a golden test${pinned ? `, always checked as of ${pinned}` : ', checked as of the day the tests run'}. Every new version must still give this result, or say why it changed.` });
      setTestName('');
      onSavedTest();
    }
  }

  const o = res ? OUTCOME[res.outcome] : null;
  const missing = new Set(res?.missing_facts ?? []);
  const invalid = new Set((res?.invalid_facts ?? []).map((x) => x.fact));
  const notReadyCount = problemCount || (res?.problems ?? []).filter((p) => p.severity !== 'warning').length;

  return (
    <aside className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 space-y-4 min-w-0" aria-label="Try it" data-testid="try-panel">
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-white"><FlaskConical className="w-4 h-4 text-cyan-400" /> Try it</h3>
        <div className="inline-flex rounded-md border border-slate-700 p-0.5 bg-slate-950">
          <button type="button" onClick={() => setMode('form')} className={`px-2 py-0.5 text-xs rounded ${mode === 'form' ? 'bg-slate-700 text-white' : 'text-slate-400'}`} aria-pressed={mode === 'form'}><ListChecks className="w-3.5 h-3.5 inline" /> Form</button>
          <button type="button" onClick={() => setMode('json')} className={`px-2 py-0.5 text-xs rounded ${mode === 'json' ? 'bg-slate-700 text-white' : 'text-slate-400'}`} aria-pressed={mode === 'json'}><Braces className="w-3.5 h-3.5 inline" /> JSON</button>
        </div>
      </div>
      <p className="text-[11px] text-slate-500">{live ? 'Runs your unsaved changes as you edit.' : 'Runs this version exactly as stored.'}</p>
      {preload && <p className="text-[11px] text-cyan-200 rounded-md bg-cyan-500/10 px-2 py-1" role="status" data-testid="try-preloaded">Filled in with the facts from a recorded evaluation. Change any of them to see what would happen.</p>}
      <div>
        <label className="block text-xs text-slate-400 mb-1" htmlFor="try-asof">Date of the activity</label>
        <input id="try-asof" type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} className="bg-slate-950 border border-slate-700 rounded-md px-2 py-1 text-sm text-white [color-scheme:dark]" data-testid="try-as-of" />
      </div>
      {mode === 'form' ? (
        <div className="space-y-2">
          {(doc?.facts ?? []).length === 0 && <p className="text-xs text-slate-500">No facts yet. Add them in Facts and outcomes, or switch to JSON.</p>}
          {(doc?.facts ?? []).map((f) => (
            <div key={f.path}>
              <label className="flex items-center justify-between gap-2 text-xs text-slate-400 mb-0.5">
                <span className="truncate">{f.label || f.path}{f.required || missing.has(f.path) ? '' : ' (optional)'}</span>
                {(missing.has(f.path) || invalid.has(f.path)) && (
                  <span className={`shrink-0 text-[10px] font-medium uppercase tracking-wide px-1.5 rounded ${missing.has(f.path) ? 'text-amber-200 bg-amber-500/20' : 'text-rose-200 bg-rose-500/20'}`} data-testid={`try-fact-${f.path}-flag`}>
                    {missing.has(f.path) ? 'needed' : 'wrong type'}
                  </span>
                )}
              </label>
              <FactField f={f} value={getPath(facts, f.path)} onChange={(v) => setFact(f.path, v)} highlight={missing.has(f.path) || invalid.has(f.path)} />
            </div>
          ))}
        </div>
      ) : (
        <div>
          <textarea
            value={jsonText}
            onChange={(e) => {
              setJsonText(e.target.value);
              try { const v = JSON.parse(e.target.value || '{}'); if (v && typeof v === 'object' && !Array.isArray(v)) { setFacts(v); setJsonErr(null); } else setJsonErr('Facts must be an object.'); }
              catch (ex: any) { setJsonErr(ex.message); }
            }}
            rows={10}
            spellCheck={false}
            className="w-full bg-slate-950 border border-slate-700 rounded-md px-2 py-1.5 text-xs text-slate-200 font-mono"
            aria-label="Facts as JSON"
            data-testid="try-json"
          />
          {jsonErr && <p className="text-xs text-rose-300">{jsonErr}</p>}
        </div>
      )}

      <div aria-live="polite">
        {err && <p className="text-sm text-rose-300">{err}</p>}
        {!res && !err && <p className="text-xs text-slate-500 flex items-center gap-1.5"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Working out the answer…</p>}
        {res && o && (
          <div className={`rounded-lg border p-3 ${o.cls}`} data-testid="try-result">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-sm font-medium"><o.icon className="w-4 h-4" /> {o.text}</span>
              {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin text-slate-400" /> : res.duration_us ? <span className="text-[10px] text-slate-500">{res.duration_us < 1000 ? `${res.duration_us} µs` : `${(res.duration_us / 1000).toFixed(1)} ms`}</span> : null}
            </div>
            {res.outcome === 'decided' && (
              <>
                <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-sm" data-testid="try-result-readable">
                  {resultRows(doc, res.result).map(([k, v]) => (
                    <div key={k} className="contents">
                      <dt className="text-slate-400">{k}</dt>
                      <dd className="text-white break-words">{v}</dd>
                    </div>
                  ))}
                </dl>
                <details className="mt-1 text-[11px] text-slate-500">
                  <summary className="cursor-pointer hover:text-slate-300">As JSON, the way agents and apps get it</summary>
                  <pre className="mt-1 text-xs text-slate-200 whitespace-pre-wrap break-all" data-testid="try-result-value">{JSON.stringify(orderedResult(doc, res.result), null, 2)}</pre>
                </details>
              </>
            )}
            {res.outcome === 'missing_facts' && <p className="mt-1 text-xs">Give these before it can decide: {res.missing_facts.map((m) => doc?.facts.find((f) => f.path === m)?.label || m).join(', ')}.</p>}
            {res.outcome === 'invalid_facts' && (
              <ul className="mt-1 text-xs space-y-0.5">{res.invalid_facts.map((x) => <li key={x.fact}>{x.fact} should be {x.expected}, got “{x.value}”.</li>)}</ul>
            )}
            {res.outcome === 'not_ready' && (
              <p className="mt-1 text-xs" data-testid="try-problem-count">
                {notReadyCount || 'Some'} problem{notReadyCount === 1 ? '' : 's'} to fix in the rules. The list above the tabs says where each one is.
              </p>
            )}
            {res.applied_rules.length > 0 && (
              <div className="mt-2 text-xs">
                Applied:{' '}
                {res.applied_rules.map((r) => (
                  <button key={r} type="button" onClick={() => onSelectRule(r)} className="mr-1 underline decoration-dotted hover:text-white">{r}</button>
                ))}
              </div>
            )}
            {res.trace.map((s, i) => Object.keys(s.values_seen).length > 0 && (
              <div key={i} className="mt-1 text-[11px] text-slate-400">Looked at {Object.entries(s.values_seen).map(([k, v]) => `${labelOf(doc, k)} = ${plainValue(v)}`).join(', ')}</div>
            ))}
            {res.normalised.map((n) => <div key={n.fact} className="mt-1 text-[11px] text-slate-400">{labelOf(doc, n.fact)} was read as {plainValue(n.to)}.</div>)}
          </div>
        )}
      </div>

      {canSaveTest && res && res.outcome !== 'not_ready' && (
        <div className="border-t border-slate-800 pt-3">
          <div className="flex items-center gap-2">
            <input value={testName} onChange={(e) => setTestName(e.target.value)} placeholder="name this case" className="flex-1 min-w-0 bg-slate-950 border border-slate-700 rounded-md px-2 py-1 text-xs text-white placeholder:text-slate-600 placeholder:italic" aria-label="Golden test name" data-testid="try-test-name" />
            <button type="button" onClick={saveTest} disabled={saving} className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs bg-slate-800 text-white hover:bg-slate-700 disabled:opacity-50" data-testid="try-save-test">
              {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />} Keep as test
            </button>
          </div>
          <label className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
            <input type="checkbox" checked={pin} onChange={(e) => { setPin(e.target.checked); if (e.target.checked && !pinDate) setPinDate(asOf); }} className="accent-cyan-500" data-testid="try-test-pin" />
            Pin it to a date
            {pin && <input type="date" value={pinDate} onChange={(e) => setPinDate(e.target.value)} className="bg-slate-950 border border-slate-700 rounded px-1.5 py-0.5 text-[11px] text-white [color-scheme:dark]" aria-label="Date the test is checked as of" data-testid="try-test-pin-date" />}
          </label>
          <p className="text-[11px] text-slate-500">{pin ? 'The test always runs as of this date, so rules dated later do not change it.' : 'The test runs as of the day the tests run, so it follows the rules in force then.'}</p>
          {saved && <p className={`mt-1 text-[11px] ${saved.ok ? 'text-cyan-200' : 'text-rose-300'}`} role="status" data-testid="try-test-saved">{saved.text}</p>}
        </div>
      )}
    </aside>
  );
}
