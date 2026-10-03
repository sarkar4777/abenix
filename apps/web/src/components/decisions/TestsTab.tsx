'use client';

import { useState } from 'react';
import { CheckCircle2, Loader2, Pencil, Play, Trash2, XCircle } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useApi } from '@/hooks/useApi';
import type { TestResult, Validation } from '@/lib/decisions';

interface GoldenTest { id: string; name: string; facts: any; expected_outcome: string; expected: any; as_of: string | null }

const OUTCOMES = ['decided', 'no_match', 'missing_facts', 'invalid_facts'];

function Editor({ t, decisionKey, onDone }: { t: GoldenTest; decisionKey: string; onDone: () => void }) {
  const [name, setName] = useState(t.name);
  const [outcome, setOutcome] = useState(t.expected_outcome);
  const [expected, setExpected] = useState(JSON.stringify(t.expected ?? null, null, 2));
  const [facts, setFacts] = useState(JSON.stringify(t.facts ?? {}, null, 2));
  const [asOf, setAsOf] = useState(t.as_of ?? '');
  const [err, setErr] = useState<string | null>(null);
  async function save() {
    let e: any, f: any;
    try { e = JSON.parse(expected || 'null'); } catch { return setErr('Expected result is not valid JSON.'); }
    try { f = JSON.parse(facts || '{}'); } catch { return setErr('Facts are not valid JSON.'); }
    const r = await apiFetch(`/api/decisions/${encodeURIComponent(decisionKey)}/tests/${t.id}`, {
      method: 'PUT',
      body: JSON.stringify({ name, facts: f, expected_outcome: outcome, expected: outcome === 'decided' ? e : null, as_of: asOf || null }),
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
          <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-white [color-scheme:dark]" aria-label="As of" />
        </div>
        <textarea value={facts} onChange={(e) => setFacts(e.target.value)} rows={7} spellCheck={false} className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 font-mono" aria-label="Facts" />
      </div>
      <div className="space-y-2">
        <div className="text-xs text-slate-400">Expected result {outcome !== 'decided' && '(only for decided)'}</div>
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

export default function TestsTab({ decisionKey, version, validation, onRun, canEdit }: {
  decisionKey: string; version: number; validation: Validation | null; onRun: () => Promise<void>; canEdit: boolean;
}) {
  const { data: tests, mutate, isLoading } = useApi<GoldenTest[]>(`/api/decisions/${encodeURIComponent(decisionKey)}/tests`);
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
      {isLoading && !tests ? (
        <div className="h-20 rounded-xl bg-slate-800/40 animate-pulse" />
      ) : !tests?.length ? (
        <div className="rounded-xl border border-dashed border-slate-700 p-6 text-center text-sm text-slate-400">No golden tests yet. Open Try it, enter facts, check the answer, then Keep as test.</div>
      ) : (
        <ul className="space-y-2">
          {tests.map((t) => {
            const r = results.get(t.id);
            return (
              <li key={t.id} className={`rounded-xl border p-3 ${r ? (r.passed ? 'border-emerald-500/20' : 'border-rose-500/40 bg-rose-500/5') : 'border-slate-800'}`} data-testid={`test-${t.name}`}>
                <div className="flex flex-wrap items-center gap-2">
                  {r ? (r.passed ? <CheckCircle2 className="w-4 h-4 text-emerald-400" /> : <XCircle className="w-4 h-4 text-rose-400" />) : <span className="w-4 h-4 rounded-full border border-slate-600" />}
                  <span className="text-sm text-white font-medium">{t.name}</span>
                  <span className="text-xs text-slate-500">expects {t.expected_outcome.replace('_', ' ')}{t.as_of ? ` on ${t.as_of}` : ''}</span>
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
                {r && !r.passed && (
                  <div className="mt-2 grid gap-2 md:grid-cols-2 text-xs">
                    <div><div className="text-slate-500 mb-0.5">Expected</div><pre className="text-slate-200 whitespace-pre-wrap">{t.expected_outcome === 'decided' ? JSON.stringify(t.expected, null, 2) : t.expected_outcome}</pre></div>
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
