'use client';

import { useMemo, useRef, useState } from 'react';
import { Calculator, Plus, Type } from 'lucide-react';
import { PATH_RE, problemAt, type Outcome, type OutcomeType, type Problem, type Rule, type RuleDoc, type ThenCell } from '@/lib/decisions';
import { OUTCOME_TYPE_LABEL, changeOutcomeType, guessFactType, numberDraft, effectiveOutcomeType, outcomeType, setOutcomeCell } from '@/lib/decisionValues';
import { DraftInput, numberParse, type Parsed } from './DraftInput';

const EDITABLE_TYPES: OutcomeType[] = ['string', 'number', 'boolean', 'date'];

function FormulaInput({ value, onChange, facts, invalid, testId }: { value: string; onChange: (v: string) => void; facts: string[]; invalid?: boolean; testId?: string }) {
  const ref = useRef<HTMLInputElement>(null);
  const [caret, setCaret] = useState(0);
  const [focus, setFocus] = useState(false);
  const before = value.slice(0, caret);
  const m = before.match(/([A-Za-z_][A-Za-z0-9_.]*)$/);
  const word = m ? m[1] : '';
  const suggestions = useMemo(
    () => (word.length >= 1 ? facts.filter((f) => f.toLowerCase().startsWith(word.toLowerCase()) && f !== word).slice(0, 6) : []),
    [word, facts],
  );
  function pick(f: string) {
    const start = caret - word.length;
    const next = value.slice(0, start) + f + value.slice(caret);
    onChange(next);
    requestAnimationFrame(() => {
      ref.current?.focus();
      const pos = start + f.length;
      ref.current?.setSelectionRange(pos, pos);
      setCaret(pos);
    });
  }
  return (
    <div className="relative">
      <input
        ref={ref}
        value={value}
        onChange={(e) => { onChange(e.target.value); setCaret(e.target.selectionStart ?? e.target.value.length); }}
        onKeyUp={(e) => setCaret((e.target as HTMLInputElement).selectionStart ?? 0)}
        onClick={(e) => setCaret((e.target as HTMLInputElement).selectionStart ?? 0)}
        onFocus={() => setFocus(true)}
        onBlur={() => setTimeout(() => setFocus(false), 150)}
        onKeyDown={(e) => { if (e.key === 'Tab' && suggestions.length && focus) { e.preventDefault(); pick(suggestions[0]); } }}
        placeholder="a formula using fact names"
        spellCheck={false}
        className={`w-72 max-w-full bg-slate-950 border rounded-md px-2 py-1.5 text-sm text-white font-mono placeholder:text-slate-600 placeholder:italic placeholder:font-sans ${invalid ? 'border-rose-500/60' : 'border-slate-700'}`}
        aria-invalid={invalid}
        data-testid={testId}
      />
      {focus && suggestions.length > 0 && (
        <ul className="absolute z-30 mt-1 w-72 rounded-md border border-slate-700 bg-slate-900 shadow-xl py-1">
          {suggestions.map((f) => (
            <li key={f}>
              <button type="button" onMouseDown={(e) => { e.preventDefault(); pick(f); }} className="w-full text-left px-3 py-1 text-xs font-mono text-slate-200 hover:bg-slate-800">{f}</button>
            </li>
          ))}
          <li className="px-3 pt-1 text-[10px] text-slate-500">Tab picks the first</li>
        </ul>
      )}
    </div>
  );
}

const textParse = (t: string): Parsed<any> => ({ value: t });
const jsonParse = (t: string): Parsed<any> => {
  try { return { value: JSON.parse(t) }; } catch { return { value: t }; }
};
const fmt = (v: any) => (v === undefined || v === null ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v));

// the same input element for text and number, so a type picked from the first value does not drop focus
function ValueEditor({ type, value, onValue, onCommit, invalid, testId, readOnly }: {
  type: OutcomeType; value: any; onValue: (v: any) => void; onCommit: () => void; invalid?: boolean; testId?: string; readOnly?: boolean;
}) {
  const border = invalid ? 'border-rose-500/60' : 'border-slate-700';
  if (type === 'boolean') {
    const v = value === true ? 'true' : value === false ? 'false' : '';
    return (
      <select value={v} disabled={readOnly} onChange={(e) => { onValue(e.target.value === '' ? '' : e.target.value === 'true'); onCommit(); }} className={`bg-slate-950 border rounded-md px-2 py-1.5 text-sm text-white ${border}`} data-testid={testId}>
        <option value="">pick yes or no</option>
        <option value="true">yes</option>
        <option value="false">no</option>
      </select>
    );
  }
  if (type === 'date') {
    return <input type="date" disabled={readOnly} value={typeof value === 'string' ? value : ''} onChange={(e) => onValue(e.target.value)} onBlur={onCommit} className={`bg-slate-950 border rounded-md px-2 py-1.5 text-sm text-white [color-scheme:dark] ${border}`} data-testid={testId} />;
  }
  return (
    <DraftInput
      value={value}
      format={fmt}
      parse={type === 'number' ? numberParse('') : type === 'object' ? jsonParse : textParse}
      onValue={onValue}
      onCommit={onCommit}
      disabled={readOnly}
      inputMode={type === 'number' ? 'decimal' : undefined}
      placeholder={type === 'number' ? 'number' : 'empty text'}
      className={`w-64 max-w-full bg-slate-950 border rounded-md px-2 py-1.5 text-sm text-white placeholder:text-slate-600 placeholder:italic disabled:opacity-80 ${border}`}
      aria-invalid={invalid}
      data-testid={testId}
    />
  );
}

function typeMismatch(type: OutcomeType, v: any): string | null {
  if (v === '' || v === undefined || v === null) return null;
  if (type === 'number' && typeof v !== 'number') return numberDraft(String(v)).kind === 'number' ? null : 'This outcome is a Number. Type a number, or change its type to Text.';
  if (type === 'boolean' && typeof v !== 'boolean') return 'This outcome is Yes / no. Pick yes or no, or change its type.';
  if (type === 'date' && (typeof v !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(v))) return 'This outcome is a Date. Pick a date, or change its type to Text.';
  return null;
}

export default function ThenEditor({
  doc,
  rule,
  index,
  onDoc,
  problems,
  testPrefix,
  readOnly = false,
}: {
  doc: RuleDoc;
  rule: Rule;
  index: number;
  // takes a function of the latest document, several changes can land in one event
  onDoc: (fn: (d: RuleDoc) => RuleDoc) => void;
  problems: Problem[];
  testPrefix: string;
  readOnly?: boolean;
}) {
  const [newField, setNewField] = useState('');
  const facts = doc.facts.map((f) => f.path);
  const at = `/rules/${index}/then`;
  const none = problemAt(problems, at);

  const setCell = (field: string, cell: ThenCell | null, infer = false) =>
    onDoc((d) => {
      if (infer) return setOutcomeCell(d, rule.id, field, cell);
      return {
        ...d,
        rules: d.rules.map((r) => {
          if (r.id !== rule.id) return r;
          const then = { ...(r.then || {}) };
          if (cell === null) delete then[field];
          else then[field] = cell;
          return { ...r, then };
        }),
      };
    });
  // the first value decides the type once the person has finished typing it, an empty number or date means not set
  const inferNow = (field: string) =>
    onDoc((d) => {
      const r = d.rules.find((x) => x.id === rule.id);
      const c = r?.then?.[field];
      const o = d.outputs.find((x) => x.field === field);
      if (c && !('formula' in c) && (c.value === '' || c.value === undefined) && outcomeType(o) !== 'string') {
        const then = { ...(r!.then || {}) };
        delete then[field];
        return { ...d, rules: d.rules.map((x) => (x.id === rule.id ? { ...x, then } : x)) };
      }
      return c ? setOutcomeCell(d, rule.id, field, c) : d;
    });

  const name = newField.trim();
  const nameProblem = !name ? null : !PATH_RE.test(name) || name.startsWith('_') ? 'Use letters, digits and _, starting with a letter.' : doc.outputs.some((o) => o.field === name) ? `${name} is already an outcome.` : null;
  const fieldOk = !!name && !nameProblem;

  function addOutcome() {
    if (!fieldOk) return;
    const guess = guessFactType(name);
    const type: OutcomeType = guess === 'number' || guess === 'boolean' || guess === 'date' ? guess : 'string';
    const o: Outcome = { field: name, label: name, type };
    onDoc((d) => ({
      ...d,
      outputs: d.outputs.some((x) => x.field === o.field) ? d.outputs : [...d.outputs, o],
      rules: d.rules.map((r) => (r.id === rule.id ? { ...r, then: { ...(r.then || {}), [o.field]: { value: '' } } } : r)),
    }));
    setNewField('');
  }

  return (
    <div>
      <div className="text-xs text-slate-400 mb-2">Then</div>
      {doc.outputs.length === 0 && <p className="text-xs text-slate-500 mb-2">Name what this decision gives back, then set its value for this rule.</p>}
      <div className="space-y-2">
        {doc.outputs.map((o) => {
          const cell = rule.then?.[o.field];
          const isFormula = !!cell && typeof cell === 'object' && 'formula' in cell;
          const type = effectiveOutcomeType(doc, o);
          const blank = !!cell && !isFormula && (cell.value === '' || cell.value === undefined);
          const found = problemAt(problems, `${at}/${o.field}`) || problemAt(problems, `${at}/${o.field}/formula`) || problemAt(problems, `${at}/${o.field}/value`);
          // an empty box is just not filled in yet, not a wrong type
          const p = blank && found?.code === 'OUTCOME_TYPE' ? null : found;
          const local = !p && cell && !isFormula ? typeMismatch(type, cell.value) : null;
          const canMakeText = !readOnly && !blank && !isFormula && type !== 'string' && type !== 'object' && (p?.code === 'OUTCOME_TYPE' || !!local);
          const tid = `${testPrefix}-then-${o.field}`;
          return (
            <div key={o.field} data-testid={`${tid}-row`}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="w-40 truncate text-sm text-slate-200" title={o.field}>{o.label || o.field}</span>
                {readOnly ? (
                  <span className="text-[11px] text-slate-500 w-20">{OUTCOME_TYPE_LABEL[type]}</span>
                ) : (
                  <select
                    value={type}
                    onChange={(e) => onDoc((d) => changeOutcomeType(d, o.field, e.target.value as OutcomeType))}
                    className="bg-slate-950 border border-slate-700 rounded-md px-1.5 py-1 text-xs text-slate-300"
                    aria-label={`Type of ${o.field}`}
                    title="What kind of value this outcome gives. It applies to every rule."
                    data-testid={`${tid}-type`}
                  >
                    {[...EDITABLE_TYPES, ...(type === 'object' ? ['object' as const] : [])].map((t) => <option key={t} value={t}>{OUTCOME_TYPE_LABEL[t]}</option>)}
                  </select>
                )}
                {cell === undefined ? (
                  readOnly ? <span className="text-xs text-slate-500 italic">not set by this rule</span> : (
                    <button type="button" onClick={() => setCell(o.field, { value: type === 'boolean' ? true : '' })} className="text-xs text-cyan-300 hover:text-cyan-200" data-testid={`${tid}-set`}>
                      Set a value
                    </button>
                  )
                ) : (
                  <>
                    {!readOnly && (
                      <div className="inline-flex rounded-md border border-slate-700 p-0.5 bg-slate-950">
                        <button type="button" onClick={() => setCell(o.field, { value: isFormula ? '' : cell?.value })} className={`inline-flex items-center gap-1 px-2 py-1 text-xs rounded ${!isFormula ? 'bg-slate-700 text-white' : 'text-slate-400'}`} aria-pressed={!isFormula}>
                          <Type className="w-3 h-3" /> Value
                        </button>
                        <button type="button" onClick={() => setCell(o.field, { formula: isFormula ? cell!.formula : '' })} className={`inline-flex items-center gap-1 px-2 py-1 text-xs rounded ${isFormula ? 'bg-slate-700 text-white' : 'text-slate-400'}`} aria-pressed={isFormula} data-testid={`${tid}-formula-toggle`}>
                          <Calculator className="w-3 h-3" /> Calculate
                        </button>
                      </div>
                    )}
                    {isFormula ? (
                      readOnly ? <code className="text-sm text-slate-200">= {cell!.formula}</code> : (
                        <FormulaInput value={cell!.formula || ''} onChange={(v) => setCell(o.field, { ...cell, formula: v })} facts={facts} invalid={!!p} testId={`${tid}-formula`} />
                      )
                    ) : (
                      <ValueEditor
                        type={type}
                        value={cell?.value}
                        onValue={(v) => setCell(o.field, { value: v })}
                        onCommit={() => inferNow(o.field)}
                        invalid={!!p || !!local}
                        testId={`${tid}-value`}
                        readOnly={readOnly}
                      />
                    )}
                    {!readOnly && <button type="button" onClick={() => setCell(o.field, null)} className="text-xs text-slate-500 hover:text-rose-300" title="This rule stops setting this outcome" data-testid={`${tid}-clear`}>Clear</button>}
                  </>
                )}
              </div>
              {(p || local) && (
                <p className="mt-0.5 sm:ml-[10.5rem] text-xs text-rose-300" role="alert" data-testid={`${tid}-problem`}>
                  {p?.message || local}{' '}
                  {canMakeText && (
                    <button type="button" onClick={() => onDoc((d) => changeOutcomeType(d, o.field, 'string'))} className="ml-1 rounded border border-cyan-500/40 px-1.5 py-0.5 text-cyan-200 hover:bg-cyan-500/10" data-testid={`${tid}-make-text`}>
                      Make {o.label || o.field} Text
                    </button>
                  )}
                </p>
              )}
            </div>
          );
        })}
      </div>
      {!readOnly && (
        <div className="mt-3">
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={newField}
              onChange={(e) => setNewField(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') addOutcome(); }}
              placeholder="name of a new outcome"
              className={`w-56 bg-slate-950 border rounded-md px-2 py-1 text-xs text-white placeholder:text-slate-600 placeholder:italic ${nameProblem ? 'border-rose-500/60' : 'border-slate-700'}`}
              aria-label="New outcome name"
              aria-invalid={!!nameProblem}
              data-testid={`${testPrefix}-new-outcome`}
            />
            <button
              type="button"
              disabled={!fieldOk}
              onClick={addOutcome}
              title={fieldOk ? '' : 'Type a name first'}
              className="inline-flex items-center gap-1 text-xs text-cyan-300 disabled:text-slate-600"
              data-testid={`${testPrefix}-add-outcome`}
            >
              <Plus className="w-3.5 h-3.5" /> Add outcome
            </button>
          </div>
          {nameProblem && <p className="mt-0.5 text-xs text-rose-300">{nameProblem}</p>}
          {!nameProblem && !name && doc.outputs.length === 0 && <p className="mt-0.5 text-[11px] text-slate-500">The type is guessed from the first value you give it. You can change it next to the name.</p>}
        </div>
      )}
      {none && <p className="mt-1 text-xs text-rose-300" role="alert">{none.message}</p>}
    </div>
  );
}
