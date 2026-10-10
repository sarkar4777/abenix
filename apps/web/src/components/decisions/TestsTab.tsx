'use client';

import { useState } from 'react';
import { CheckCircle2, Loader2, Pencil, Play, Trash2, XCircle } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useApi } from '@/hooks/useApi';
import type { RuleDoc, TestResult, Validation } from '@/lib/decisions';

interface GoldenTest { id: string; name: string; facts: any; expected_outcome: string; expected: any; match?: 'exact' | 'subset'; as_of: string | null }

const OUTCOMES = ['decided', 'no_match', 'missing_facts', 'invalid_facts'];
const OUTCOME_WORDS: Record<string, string> = { no_match: 'no rule applies', missing_facts: 'missing facts', invalid_facts: 'facts with the wrong type', decided: 'a decision' };

// facts and answers as short a = b pairs, nested objects by their dotted path
// a fact or outcome by the name people gave it, the key when it has none
export function pairs(v: any, labels: Record<string, string> = {}, prefix = ''): string {
  if (v === null || v === undefined) return '';
  const name = (k: string) => labels[k] || k;
  if (typeof v !== 'object' || Array.isArray(v)) return `${name(prefix) || 'value'} = ${JSON.stringify(v)}`;
  return Object.entries(v).map(([k, x]) => {
    const path = prefix ? `${prefix}.${k}` : k;
    if (x && typeof x === 'object' && !Array.isArray(x) && !labels[path]) return pairs(x, labels, path);
    return `${name(path)} = ${typeof x === 'string' ? `“${x}”` : JSON.stringify(x)}`;
  }).filter(Boolean).join(', ');
}
const MATCH_HELP: Record<string, string> = {
  exact: 'The result must equal the expected JSON, nothing more and nothing less.',
  subset: 'Every key in the expected JSON must be in the result with the same value. Extra keys are ignored.',
};

function Editor({ t, decisionKey, onDone }: { t: GoldenTest; decisionKey: string; onDone: () => void }) {
  const [name, setName] = useState(t.name);
  const [outcome, setOutcome] = useState(t.expected_outcome);
  const [match, setMatch] = useState<string>(t.match ?? 'exact');
  const [expected, setExpected] = useState(JSON.stringify(t.expected ?? null, null, 2));
  const [facts, setFacts] = useState(JSON.stringify(t.facts ?? {}, null, 2));
  const [asOf, setAsOf] = useState(t.as_of ?? '');
  const [err, setErr] = useState<string | null>(null);
  async function save() {
    let e: any, f: any;
    try { e = JSON.parse(expected || 'null'); } catch { return setErr('Expected result is not valid JSON.'); }
    try { f = JSON.parse(facts || '{}'); } catch { return setErr('Facts are not valid JSON.'); }
    if (outcome === 'decided' && match === 'subset' && e !== null && (typeof e !== 'object' || Array.isArray(e))) {
      return setErr('A subset match needs the expected result as a JSON object.');
    }
    const r = await apiFetch(`/api/decisions/${encodeURIComponent(decisionKey)}/tests/${t.id}`, {
      method: 'PUT',
      body: JSON.stringify({ name, facts: f, expected_outcome: outcome, expected: outcome === 'decided' ? e : null, match, as_of: asOf || null }),
      throwOnError: false,
    });
    if (r.error) setErr(r.error);
    else onDone();
  }
  return (
    <div className="mt-3 grid gap-3 md:grid-cols-2">
      <div className="space-y-2">
        <input value={name} onChange={(e) => setName(e.target.value)} className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1 text-sm text-white" aria-label="Test name" />
        <div className="flex items-center gap-2">
          <select value={outcome} onChange={(e) => setOutcome(e.target.value)} className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-white" aria-label="Expected outcome">
            {OUTCOMES.map((o) => <option key={o} value={o}>{o.replace('_', ' ')}</option>)}
          </select>
          <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-white [color-scheme:dark]" aria-label="Pinned to date" title="Leave empty to check it as of the day the tests run" />
          {asOf && <button type="button" onClick={() => setAsOf('')} className="text-[11px] text-slate-400 hover:text-white">Unpin</button>}
        </div>
        <p className="text-[11px] text-slate-500">{asOf ? `Always checked as of ${asOf}.` : 'Checked as of the day the tests run. Pick a date to pin it.'}</p>
        <textarea value={facts} onChange={(e) => setFacts(e.target.value)} rows={7} spellCheck={false} className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 font-mono" aria-label="Facts" />
      </div>
      <div className="space-y-2">
        <div className="text-xs text-slate-400">Expected result {outcome !== 'decided' && '(only for decided)'}</div>
        <div className="flex items-center gap-2">
          <label htmlFor={`match-${t.id}`} className="text-xs text-slate-400">Match</label>
          <select id={`match-${t.id}`} value={match} onChange={(e) => setMatch(e.target.value)} disabled={outcome !== 'decided'} className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-white disabled:opacity-40" data-testid="test-match">
            <option value="exact">Exact</option>
            <option value="subset">Subset</option>
          </select>
        </div>
        <p className="text-xs text-slate-500">{MATCH_HELP[match] ?? MATCH_HELP.exact}</p>
        <textarea value={expected} onChange={(e) => setExpected(e.target.value)} rows={9} disabled={outcome !== 'decided'} spellCheck={false} className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 font-mono disabled:opacity-40" aria-label="Expected result" />
        {err && <p className="text-xs text-rose-300">{err}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onDone} className="px-3 py-1 text-xs text-slate-300">Cancel</button>
          <button type="button" onClick={save} className="px-3 py-1 rounded text-xs bg-cyan-500 text-white">Save test</button>
        </div>
      </div>
    </div>
  );
}

export default function TestsTab({ decisionKey, version, validation, onRun, canEdit, onOpenTry, doc }: {
  decisionKey: string; version: number; validation: Validation | null; onRun: () => Promise<void>; canEdit: boolean; onOpenTry?: () => void; doc?: RuleDoc | null;
}) {
  const factLabels = Object.fromEntries((doc?.facts || []).filter((f) => f.label).map((f) => [f.path, f.label!]));
  const outLabels = Object.fromEntries((doc?.outputs || []).filter((o) => o.label).map((o) => [o.field, o.label!]));
  const { data: tests, mutate, isLoading, error } = useApi<GoldenTest[]>(`/api/decisions/${encodeURIComponent(decisionKey)}/tests`);
  const [running, setRunning] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const results = new Map<string, TestResult>((validation?.tests ?? []).map((r) => [r.test_id, r]));
  const failed = (validation?.tests ?? []).filter((r) => !r.passed).length;

  async function run() {
    setRunning(true);
    await onRun();
    setRunning(false);
  }
  async function del(id: string) {
    await apiFetch(`/api/decisions/${encodeURIComponent(decisionKey)}/tests/${id}`, { method: 'DELETE', throwOnError: false });
    setConfirm(null);
    mutate();
  }

  return (
    <div data-testid="tests-tab">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <p className="text-sm text-slate-400 max-w-3xl">
          Golden tests are facts with the answer they must give. Every version is checked against them before it can be proposed. Add one from Try it with a single click.
        </p>
        <button type="button" onClick={run} disabled={running} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm bg-slate-800 text-white hover:bg-slate-700 disabled:opacity-50" data-testid="tests-run">
          {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />} Run against version {version}
        </button>
      </div>
      {validation && (
        <p className={`text-sm mb-3 ${failed ? 'text-rose-300' : 'text-emerald-300'}`} data-testid="tests-summary">
          {validation.tests.length ? (failed ? `${failed} of ${validation.tests.length} fail on version ${version}.` : `All ${validation.tests.length} pass on version ${version}.`) : 'No tests ran.'}
        </p>
      )}
      {error && !tests ? (
        <p role="alert" className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-200" data-testid="tests-load-error">The golden tests could not be loaded. Reload the page to try again.</p>
      ) : isLoading && !tests ? (
        <div className="h-20 rounded-xl bg-slate-800/40 animate-pulse" />
      ) : !tests?.length ? (
        <div className="rounded-xl border border-dashed border-slate-700 p-6 text-center text-sm text-slate-400" data-testid="tests-empty">
          <p className="text-slate-300">No golden tests yet.</p>
          <p className="mt-1">A golden test is a case with the answer it must always give, so a later change can&apos;t quietly break it. Enter facts in Try it, check the answer, then press Keep as test.</p>
          {onOpenTry && <button type="button" onClick={onOpenTry} className="mt-3 inline-flex items-center gap-1 px-3 py-1.5 rounded-md text-sm bg-cyan-500 text-white hover:bg-cyan-400" data-testid="tests-open-try">Open Try it</button>}
        </div>
      ) : (
        <ul className="space-y-2">
          {tests.map((t) => {
            const r = results.get(t.id);
            return (
              <li key={t.id} className={`rounded-xl border p-3 ${r ? (r.passed ? 'border-emerald-500/20' : 'border-rose-500/40 bg-rose-500/5') : 'border-slate-800'}`} data-testid={`test-${t.name}`}>
                <div className="flex flex-wrap items-center gap-2">
                  {r ? (r.passed ? <CheckCircle2 className="w-4 h-4 text-emerald-400" /> : <XCircle className="w-4 h-4 text-rose-400" />) : <span className="w-4 h-4 rounded-full border border-slate-600" />}
                  <span className="text-sm text-white font-medium">{t.name}</span>
                  <span className="text-xs text-slate-500">expects {t.expected_outcome.replace('_', ' ')}{t.expected_outcome === 'decided' && t.match === 'subset' ? ', subset match' : ''}{t.as_of ? `, pinned to ${t.as_of.slice(0, 10)}` : ', as of the day the tests run'}</span>
                  {canEdit && (
                    <span className="ml-auto flex items-center gap-1">
                      <button type="button" onClick={() => setEditing(editing === t.id ? null : t.id)} className="p-1 text-slate-400 hover:text-white" aria-label={`Edit ${t.name}`}><Pencil className="w-4 h-4" /></button>
                      {confirm === t.id ? (
                        <span className="text-xs"><button type="button" onClick={() => del(t.id)} className="px-2 py-0.5 rounded bg-rose-600 text-white">Delete</button><button type="button" onClick={() => setConfirm(null)} className="px-2 py-0.5 text-slate-300">Keep</button></span>
                      ) : (
                        <button type="button" onClick={() => setConfirm(t.id)} className="p-1 text-slate-400 hover:text-rose-300" aria-label={`Delete ${t.name}`}><Trash2 className="w-4 h-4" /></button>
                      )}
                    </span>
                  )}
                </div>
                <dl className="mt-1.5 grid gap-x-3 gap-y-0.5 text-[11px] sm:grid-cols-[auto_minmax(0,1fr)]" data-testid="test-detail">
                  <dt className="text-slate-500">Given</dt>
                  <dd className="text-slate-300 break-words">{pairs(t.facts, factLabels) || 'no facts'}</dd>
                  <dt className="text-slate-500">Expects</dt>
                  <dd className="text-slate-300 break-words">{t.expected_outcome === 'decided' ? pairs(t.expected, outLabels) || 'a decision' : OUTCOME_WORDS[t.expected_outcome] || t.expected_outcome}</dd>
                </dl>
                {r && !r.passed && (
                  <div className="mt-2 grid gap-2 md:grid-cols-2 text-xs">
                    <div><div className="text-slate-500 mb-0.5">Expected{t.match === 'subset' && t.expected_outcome === 'decided' ? ' (these keys at least)' : ''}</div><pre className="text-slate-200 whitespace-pre-wrap">{t.expected_outcome === 'decided' ? JSON.stringify(t.expected, null, 2) : t.expected_outcome}</pre></div>
                    <div><div className="text-slate-500 mb-0.5">Got</div><pre className="text-rose-200 whitespace-pre-wrap">{r.outcome === 'decided' ? JSON.stringify(r.result, null, 2) : `${r.outcome}${r.missing_facts.length ? `: ${r.missing_facts.join(', ')}` : ''}`}</pre></div>
                  </div>
                )}
                {editing === t.id && <Editor t={t} decisionKey={decisionKey} onDone={() => { setEditing(null); mutate(); }} />}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
