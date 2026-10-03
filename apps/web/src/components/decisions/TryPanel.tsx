'use client';

import { useEffect, useRef, useState } from 'react';
import { Braces, CheckCircle2, CircleSlash, FlaskConical, ListChecks, Loader2, Save, TriangleAlert } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { getPath, setPath, type Evaluation, type Fact, type RuleDoc, type TryPreload } from '@/lib/decisions';

const OUTCOME = {
  decided: { icon: CheckCircle2, cls: 'text-emerald-300 border-emerald-500/30 bg-emerald-500/5', text: 'Decided' },
  no_match: { icon: CircleSlash, cls: 'text-slate-300 border-slate-600 bg-slate-800/40', text: 'No rule applies' },
  missing_facts: { icon: TriangleAlert, cls: 'text-amber-300 border-amber-500/30 bg-amber-500/5', text: 'Missing facts' },
  invalid_facts: { icon: TriangleAlert, cls: 'text-rose-300 border-rose-500/30 bg-rose-500/5', text: 'Facts with the wrong type' },
  not_ready: { icon: TriangleAlert, cls: 'text-amber-300 border-amber-500/30 bg-amber-500/5', text: 'Fix the rules first' },
} as const;

function FactField({ f, value, onChange, highlight }: { f: Fact; value: any; onChange: (v: any) => void; highlight?: boolean }) {
  const cls = `w-full bg-slate-950 border rounded-md px-2 py-1 text-sm text-white ${highlight ? 'border-amber-500/70' : 'border-slate-700'}`;
  const a11y = { 'aria-label': f.label || f.path, 'data-testid': `try-fact-${f.path}` };
  if (f.type === 'boolean') {
    return (
      <select {...a11y} value={value === undefined ? '' : String(value)} onChange={(e) => onChange(e.target.value === '' ? undefined : e.target.value === 'true')} className={cls}>
        <option value="">not given</option><option value="true">true</option><option value="false">false</option>
      </select>
    );
  }
  if (f.type === 'date') return <input {...a11y} type="date" value={value ?? ''} onChange={(e) => onChange(e.target.value || undefined)} className={`${cls} [color-scheme:dark]`} />;
  return (
    <input
      {...a11y}
      value={value === undefined ? '' : Array.isArray(value) ? value.join(', ') : String(value)}
      inputMode={f.type === 'number' ? 'decimal' : undefined}
      onChange={(e) => {
        const raw = e.target.value;
        if (raw === '') return onChange(undefined);
        if (f.type === 'number') return onChange(Number.isFinite(Number(raw)) && raw.trim() !== '' ? Number(raw) : raw);
        if (f.type === 'list') return onChange(raw.split(',').map((s) => s.trim()).filter(Boolean));
        onChange(raw);
      }}
      placeholder={f.type === 'number' ? '0' : f.type === 'list' ? 'a, b' : ''}
      className={cls}
    />
  );
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
}: {
  decisionKey: string;
  version: number;
  doc: RuleDoc | null;
  live: boolean;
  onSelectRule: (ruleKeyOrId: string) => void;
  onSavedTest: () => void;
  canSaveTest: boolean;
  preload?: TryPreload | null;
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
  const [saved, setSaved] = useState<string | null>(null);
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
  }

  async function saveTest() {
    if (!res) return;
    const r = await apiFetch(`/api/decisions/${encodeURIComponent(decisionKey)}/tests`, {
      method: 'POST',
      body: JSON.stringify({
        name: testName.trim() || `Case ${new Date().toLocaleString()}`,
        facts,
        as_of: asOf || null,
        expected_outcome: res.outcome === 'not_ready' ? 'decided' : res.outcome,
        expected: res.outcome === 'decided' ? res.result : null,
      }),
      throwOnError: false,
    });
    if (r.error) setSaved(`Not saved: ${r.error}`);
    else { setSaved('Saved as a golden test. Every new version must still give this result, or say why it changed.'); setTestName(''); onSavedTest(); }
  }

  const o = res ? OUTCOME[res.outcome] : null;
  const missing = new Set(res?.missing_facts ?? []);
  const invalid = new Set((res?.invalid_facts ?? []).map((x) => x.fact));

  return (
    <aside className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 space-y-4" aria-label="Try it" data-testid="try-panel">
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
              <label className="flex items-center justify-between text-xs text-slate-400 mb-0.5">
                <span>{f.label || f.path}{f.required ? '' : ' (optional)'}</span>
                {(missing.has(f.path) || invalid.has(f.path)) && <span className={missing.has(f.path) ? 'text-amber-300' : 'text-rose-300'}>{missing.has(f.path) ? 'needed' : 'wrong type'}</span>}
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
        {res && o && (
          <div className={`rounded-lg border p-3 ${o.cls}`} data-testid="try-result">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-sm font-medium"><o.icon className="w-4 h-4" /> {o.text}</span>
              {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin text-slate-400" /> : res.duration_us ? <span className="text-[10px] text-slate-500">{res.duration_us < 1000 ? `${res.duration_us} µs` : `${(res.duration_us / 1000).toFixed(1)} ms`}</span> : null}
            </div>
            {res.outcome === 'decided' && <pre className="mt-2 text-xs text-white whitespace-pre-wrap break-all" data-testid="try-result-value">{JSON.stringify(res.result, null, 2)}</pre>}
            {res.outcome === 'missing_facts' && <p className="mt-1 text-xs">Give these before it can decide: {res.missing_facts.join(', ')}.</p>}
            {res.outcome === 'invalid_facts' && (
              <ul className="mt-1 text-xs space-y-0.5">{res.invalid_facts.map((x) => <li key={x.fact}>{x.fact} should be {x.expected}, got “{x.value}”.</li>)}</ul>
            )}
            {res.outcome === 'not_ready' && <p className="mt-1 text-xs">{(res.problems ?? []).length} problem{(res.problems ?? []).length === 1 ? '' : 's'} in the rules. They are marked where they are.</p>}
            {res.applied_rules.length > 0 && (
              <div className="mt-2 text-xs">
                Applied:{' '}
                {res.applied_rules.map((r) => (
                  <button key={r} type="button" onClick={() => onSelectRule(r)} className="mr-1 underline decoration-dotted hover:text-white">{r}</button>
                ))}
              </div>
            )}
            {res.trace.map((s, i) => Object.keys(s.values_seen).length > 0 && (
              <div key={i} className="mt-1 text-[11px] text-slate-400">Looked at {Object.entries(s.values_seen).map(([k, v]) => `${k} = ${JSON.stringify(v)}`).join(', ')}</div>
            ))}
            {res.normalised.map((n) => <div key={n.fact} className="mt-1 text-[11px] text-slate-400">{n.fact} was read as {JSON.stringify(n.to)}.</div>)}
          </div>
        )}
      </div>

      {canSaveTest && res && res.outcome !== 'not_ready' && (
        <div className="border-t border-slate-800 pt-3">
          <div className="flex items-center gap-2">
            <input value={testName} onChange={(e) => setTestName(e.target.value)} placeholder="Name this case" className="flex-1 bg-slate-950 border border-slate-700 rounded-md px-2 py-1 text-xs text-white" aria-label="Golden test name" data-testid="try-test-name" />
            <button type="button" onClick={saveTest} className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs bg-slate-800 text-white hover:bg-slate-700" data-testid="try-save-test"><Save className="w-3.5 h-3.5" /> Keep as test</button>
          </div>
          {saved && <p className="mt-1 text-[11px] text-cyan-200" role="status">{saved}</p>}
        </div>
      )}
    </aside>
  );
}
