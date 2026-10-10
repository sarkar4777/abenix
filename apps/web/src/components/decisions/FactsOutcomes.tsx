'use client';

import { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { PATH_RE, TYPE_LABEL, factsUsed, groupItems, isGroup, problemAt, type Fact, type FactType, type Group, type OutcomeType, type Problem, type Rule, type RuleDoc } from '@/lib/decisions';
import { OUTCOME_TYPE_LABEL, changeFactType, changeOutcomeType, guessFactType, effectiveOutcomeType, outcomeType } from '@/lib/decisionValues';

function renameInGroup(g: Group, from: string, to: string): Group {
  const kind = 'any' in g && g.any ? 'any' : 'all';
  const items = groupItems(g).map((n) => (isGroup(n) ? renameInGroup(n, from, to) : n.fact === from ? { ...n, fact: to } : n));
  const out: Group = { [kind]: items } as Group;
  if (g.negate) out.negate = true;
  return out;
}

function renameFact(doc: RuleDoc, from: string, to: string): RuleDoc {
  const re = new RegExp(`(^|[^A-Za-z0-9_.])${from.replace(/\./g, '\\.')}(?![A-Za-z0-9_])`, 'g');
  return {
    ...doc,
    facts: doc.facts.map((f) => (f.path === from ? { ...f, path: to } : f)),
    rules: doc.rules.map((r): Rule => ({
      ...r,
      requires: (r.requires || []).map((p) => (p === from ? to : p)),
      when: renameInGroup(r.when, from, to),
      then: Object.fromEntries(
        Object.entries(r.then || {}).map(([k, c]) => [k, c && 'formula' in c && c.formula ? { ...c, formula: c.formula.replace(re, `$1${to}`) } : c]),
      ),
    })),
  };
}

function usage(doc: RuleDoc, path: string): number {
  return doc.rules.filter((r) => factsUsed(r.when).has(path) || Object.values(r.then || {}).some((c) => c && 'formula' in c && (c.formula || '').includes(path))).length;
}

const OUT_TYPES: OutcomeType[] = ['number', 'string', 'boolean', 'date'];

function asOutcomeType(t: FactType): OutcomeType {
  return t === 'number' || t === 'boolean' || t === 'date' ? t : 'string';
}

export default function FactsOutcomes({ doc, onChange, problems, readOnly }: { doc: RuleDoc; onChange: (d: RuleDoc) => void; problems: Problem[]; readOnly: boolean }) {
  const [newPath, setNewPath] = useState('');
  const [newType, setNewType] = useState<FactType>('string');
  const [typeTouched, setTypeTouched] = useState(false);
  const [newOut, setNewOut] = useState('');
  const [newOutType, setNewOutType] = useState<OutcomeType>('string');
  const [outTypeTouched, setOutTypeTouched] = useState(false);
  const [renaming, setRenaming] = useState<Record<string, string>>({});

  const setFact = (i: number, patch: Partial<Fact>) => onChange({ ...doc, facts: doc.facts.map((f, j) => (j === i ? { ...f, ...patch } : f)) });
  const pathOk = PATH_RE.test(newPath.trim()) && !doc.facts.some((f) => f.path === newPath.trim());
  const outOk = PATH_RE.test(newOut.trim()) && !newOut.trim().startsWith('_') && !doc.outputs.some((o) => o.field === newOut.trim());
  const outProblem = newOut.trim() && !outOk ? (doc.outputs.some((o) => o.field === newOut.trim()) ? `${newOut.trim()} is already an outcome.` : 'Use letters, digits and _, starting with a letter.') : null;
  const factProblem = newPath.trim() && !pathOk ? (doc.facts.some((f) => f.path === newPath.trim()) ? `${newPath.trim()} is already a fact.` : 'Use letters, digits and _, with dots between parts, like worker.distance_m.') : null;

  function addFact() {
    if (!pathOk) return;
    onChange({ ...doc, facts: [...doc.facts, { path: newPath.trim(), type: newType, label: newPath.trim(), required: true }] });
    setNewPath('');
    setTypeTouched(false);
  }
  function addOutcome() {
    if (!outOk) return;
    onChange({ ...doc, outputs: [...doc.outputs, { field: newOut.trim(), label: newOut.trim(), type: newOutType }] });
    setNewOut('');
    setOutTypeTouched(false);
  }

  const cellIn = 'w-full bg-transparent px-1 py-1 text-sm text-white rounded focus:bg-slate-950 outline-none disabled:text-slate-200';

  return (
    <div className="grid gap-6 2xl:grid-cols-2" data-testid="facts-outcomes">
      <section className="min-w-0">
        <h3 className="text-sm font-semibold text-white">Facts</h3>
        <p className="text-xs text-slate-400 mb-3">What callers send in. Required facts must be present, otherwise the answer is “missing facts” rather than a guess. Types are checked before any rule runs.</p>
        <div className="rounded-xl border border-slate-800 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-900/60 text-[11px] uppercase tracking-wide text-slate-400">
              <tr><th className="px-3 py-2 text-left">Name</th><th className="px-3 py-2 text-left">Label</th><th className="px-3 py-2 text-left">Type</th><th className="px-3 py-2">Required</th><th className="px-3 py-2">Used in</th><th /></tr>
            </thead>
            <tbody>
              {doc.facts.length === 0 && <tr><td colSpan={6} className="px-3 py-3 text-xs text-slate-500">No facts yet. Add one below, pick one in a rule&apos;s condition, or paste rules in the Table tab.</td></tr>}
              {doc.facts.map((f, i) => {
                const used = usage(doc, f.path);
                const draft = renaming[f.path];
                const p = problemAt(problems, `/facts/${i}/path`) || problemAt(problems, `/facts/${i}/type`) || problemAt(problems, `/facts/${i}`);
                return (
                  <tr key={f.path} className="border-t border-slate-800" data-testid={`fact-row-${f.path}`}>
                    <td className="px-2 py-1">
                      <input
                        value={draft ?? f.path}
                        disabled={readOnly}
                        onChange={(e) => setRenaming({ ...renaming, [f.path]: e.target.value })}
                        onBlur={() => {
                          const to = (draft ?? f.path).trim();
                          if (to !== f.path && PATH_RE.test(to) && !doc.facts.some((x) => x.path === to)) onChange(renameFact(doc, f.path, to));
                          const r = { ...renaming };
                          delete r[f.path];
                          setRenaming(r);
                        }}
                        className={`${cellIn} font-mono text-xs ${draft !== undefined && !PATH_RE.test(draft.trim()) ? 'ring-1 ring-rose-500/60' : ''}`}
                        aria-label={`Name of ${f.path}`}
                      />
                      {p && <p className="text-[11px] text-rose-300 px-1">{p.message}</p>}
                    </td>
                    <td className="px-2 py-1"><input value={f.label || ''} disabled={readOnly} onChange={(e) => setFact(i, { label: e.target.value })} className={cellIn} aria-label={`Label of ${f.path}`} /></td>
                    <td className="px-2 py-1">
                      <select value={f.type} disabled={readOnly} onChange={(e) => onChange(changeFactType(doc, f.path, e.target.value as FactType))} className="bg-slate-950 border border-slate-700 rounded px-1.5 py-1 text-xs text-white disabled:opacity-80" aria-label={`Type of ${f.path}`} data-testid={`fact-type-${f.path}`}>
                        {(Object.keys(TYPE_LABEL) as FactType[]).map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
                      </select>
                    </td>
                    <td className="px-2 py-1 text-center"><input type="checkbox" checked={!!f.required} disabled={readOnly} onChange={(e) => setFact(i, { required: e.target.checked })} className="accent-cyan-500" aria-label={`${f.path} required`} /></td>
                    <td className="px-2 py-1 text-center text-xs text-slate-400">{used ? `${used} rule${used > 1 ? 's' : ''}` : '—'}</td>
                    <td className="px-2 py-1 text-right">
                      {!readOnly && (
                        <button type="button" disabled={used > 0} title={used ? 'Used by rules. Remove it from those rules first.' : 'Remove'} onClick={() => onChange({ ...doc, facts: doc.facts.filter((x) => x.path !== f.path) })} className="p-1 rounded text-slate-500 hover:text-rose-300 disabled:opacity-30 disabled:hover:text-slate-500" aria-label={`Remove ${f.path}`}>
                          <Trash2 className="w-4 h-4" />
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!readOnly && (
            <>
              <div className="flex flex-wrap items-center gap-2 border-t border-slate-800 p-2">
                <input
                  value={newPath}
                  onChange={(e) => { setNewPath(e.target.value); if (!typeTouched) setNewType(guessFactType(e.target.value.trim())); }}
                  onKeyDown={(e) => { if (e.key === 'Enter') addFact(); }}
                  placeholder="name of a new fact"
                  className={`flex-1 min-w-[160px] bg-slate-950 border rounded px-2 py-1 text-xs text-white font-mono placeholder:text-slate-600 placeholder:italic placeholder:font-sans ${factProblem ? 'border-rose-500/60' : 'border-slate-700'}`}
                  aria-label="New fact name"
                  aria-invalid={!!factProblem}
                  data-testid="fact-new-path"
                />
                <select value={newType} onChange={(e) => { setTypeTouched(true); setNewType(e.target.value as FactType); }} className="bg-slate-950 border border-slate-700 rounded px-1.5 py-1 text-xs text-white" aria-label="New fact type" data-testid="fact-new-path-type">
                  {(Object.keys(TYPE_LABEL) as FactType[]).map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
                </select>
                <button type="button" disabled={!pathOk} onClick={addFact} title={pathOk ? '' : 'Type a name first'} className="inline-flex items-center gap-1 text-xs text-cyan-300 disabled:text-slate-600" data-testid="fact-add">
                  <Plus className="w-3.5 h-3.5" /> Add fact
                </button>
              </div>
              {factProblem && <p className="px-3 pb-2 text-xs text-rose-300">{factProblem}</p>}
              {!factProblem && newPath.trim() && !typeTouched && <p className="px-3 pb-2 text-[11px] text-slate-500">Type guessed from the name. Change it if that is wrong.</p>}
            </>
          )}
        </div>
      </section>

      <section className="min-w-0">
        <h3 className="text-sm font-semibold text-white">Outcomes</h3>
        <p className="text-xs text-slate-400 mb-3">What the decision gives back. Each rule sets some or all of them. The type says what kind of value each one holds, and every rule&apos;s value is checked against it.</p>
        <div className="rounded-xl border border-slate-800 overflow-x-auto">
          <table className="w-full text-sm" data-testid="outcomes-table">
            <thead className="bg-slate-900/60 text-[11px] uppercase tracking-wide text-slate-400">
              <tr><th className="px-3 py-2 text-left">Name</th><th className="px-3 py-2 text-left">Label</th><th className="px-3 py-2 text-left">Type</th><th className="px-3 py-2">Set by</th><th /></tr>
            </thead>
            <tbody>
              {doc.outputs.length === 0 && <tr><td colSpan={5} className="px-3 py-3 text-xs text-slate-500">No outcomes yet. Add one below or from a rule&apos;s Then.</td></tr>}
              {doc.outputs.map((o, i) => {
                const by = doc.rules.filter((r) => r.then && o.field in r.then).length;
                const p = problemAt(problems, `/outputs/${i}/field`) || problemAt(problems, `/outputs/${i}/type`) || problemAt(problems, `/outputs/${i}`);
                const type = effectiveOutcomeType(doc, o);
                return (
                  <tr key={o.field} className="border-t border-slate-800" data-testid={`outcome-row-${o.field}`}>
                    <td className="px-3 py-1.5 font-mono text-xs text-white">{o.field}{p && <p className="font-sans text-[11px] text-rose-300">{p.message}</p>}</td>
                    <td className="px-2 py-1"><input value={o.label || ''} disabled={readOnly} onChange={(e) => onChange({ ...doc, outputs: doc.outputs.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)) })} className={cellIn} aria-label={`Label of ${o.field}`} /></td>
                    <td className="px-2 py-1">
                      <select value={type} disabled={readOnly} onChange={(e) => onChange(changeOutcomeType(doc, o.field, e.target.value as OutcomeType))} className="bg-slate-950 border border-slate-700 rounded px-1.5 py-1 text-xs text-white disabled:opacity-80" aria-label={`Type of ${o.field}`} data-testid={`outcome-type-${o.field}`}>
                        {[...OUT_TYPES, ...(type === 'object' ? ['object' as const] : [])].map((t) => <option key={t} value={t}>{OUTCOME_TYPE_LABEL[t]}</option>)}
                      </select>
                    </td>
                    <td className="px-2 py-1 text-center text-xs text-slate-400">{by ? `${by} rule${by > 1 ? 's' : ''}` : '—'}</td>
                    <td className="px-2 py-1 text-right">
                      {!readOnly && (
                        <button type="button" disabled={by > 0} title={by ? 'Set by rules. Clear it in those rules first.' : 'Remove'} onClick={() => onChange({ ...doc, outputs: doc.outputs.filter((x) => x.field !== o.field) })} className="p-1 rounded text-slate-500 hover:text-rose-300 disabled:opacity-30" aria-label={`Remove ${o.field}`}>
                          <Trash2 className="w-4 h-4" />
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!readOnly && (
            <>
              <div className="flex flex-wrap items-center gap-2 border-t border-slate-800 p-2">
                <input
                  value={newOut}
                  onChange={(e) => { setNewOut(e.target.value); if (!outTypeTouched) setNewOutType(asOutcomeType(guessFactType(e.target.value.trim()))); }}
                  onKeyDown={(e) => { if (e.key === 'Enter') addOutcome(); }}
                  placeholder="name of a new outcome"
                  className={`flex-1 min-w-[160px] bg-slate-950 border rounded px-2 py-1 text-xs text-white font-mono placeholder:text-slate-600 placeholder:italic placeholder:font-sans ${outProblem ? 'border-rose-500/60' : 'border-slate-700'}`}
                  aria-label="New outcome name"
                  aria-invalid={!!outProblem}
                  data-testid="outcome-new-name"
                />
                <select value={newOutType} onChange={(e) => { setOutTypeTouched(true); setNewOutType(e.target.value as OutcomeType); }} className="bg-slate-950 border border-slate-700 rounded px-1.5 py-1 text-xs text-white" aria-label="New outcome type" data-testid="outcome-new-type">
                  {OUT_TYPES.map((t) => <option key={t} value={t}>{OUTCOME_TYPE_LABEL[t]}</option>)}
                </select>
                <button type="button" disabled={!outOk} onClick={addOutcome} title={outOk ? '' : 'Type a name first'} className="inline-flex items-center gap-1 text-xs text-cyan-300 disabled:text-slate-600" data-testid="outcome-add">
                  <Plus className="w-3.5 h-3.5" /> Add outcome
                </button>
              </div>
              {outProblem && <p className="px-3 pb-2 text-xs text-rose-300">{outProblem}</p>}
            </>
          )}
          {problemAt(problems, '/outputs') && <p className="px-3 pb-2 text-xs text-rose-300">{problemAt(problems, '/outputs')!.message}</p>}
        </div>
      </section>
    </div>
  );
}
