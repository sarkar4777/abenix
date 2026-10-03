'use client';

import { useMemo, useRef, useState } from 'react';
import { Calculator, Plus, Type } from 'lucide-react';
import { problemAt, type Outcome, type Problem, type Rule, type RuleDoc, type ThenCell } from '@/lib/decisions';

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
        placeholder="import.netMassTonnes * 2.1"
        spellCheck={false}
        className={`w-72 bg-slate-950 border rounded-md px-2 py-1.5 text-sm text-white font-mono ${invalid ? 'border-rose-500/60' : 'border-slate-700'}`}
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

export default function ThenEditor({
  doc,
  rule,
  index,
  onChange,
  onAddOutcome,
  problems,
  testPrefix,
}: {
  doc: RuleDoc;
  rule: Rule;
  index: number;
  onChange: (then: Record<string, ThenCell>) => void;
  onAddOutcome: (o: Outcome) => void;
  problems: Problem[];
  testPrefix: string;
}) {
  const [newField, setNewField] = useState('');
  const facts = doc.facts.map((f) => f.path);
  const at = `/rules/${index}/then`;
  const none = problemAt(problems, at);

  function setCell(field: string, cell: ThenCell | null) {
    const next = { ...(rule.then || {}) };
    if (cell === null) delete next[field];
    else next[field] = cell;
    onChange(next);
  }

  const fieldOk = /^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$/.test(newField.trim()) && !doc.outputs.some((o) => o.field === newField.trim());

  return (
    <div>
      <div className="text-xs text-slate-400 mb-2">Then</div>
      {doc.outputs.length === 0 && <p className="text-xs text-slate-500 mb-2">Name what this decision returns, for example obligation or duty_rate.</p>}
      <div className="space-y-2">
        {doc.outputs.map((o) => {
          const cell = rule.then?.[o.field];
          const isFormula = !!cell && typeof cell === 'object' && 'formula' in cell;
          const p = problemAt(problems, `${at}/${o.field}`) || problemAt(problems, `${at}/${o.field}/formula`);
          return (
            <div key={o.field}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="w-40 truncate text-sm text-slate-200" title={o.field}>{o.label || o.field}</span>
                {cell === undefined ? (
                  <button type="button" onClick={() => setCell(o.field, { value: '' })} className="text-xs text-cyan-300 hover:text-cyan-200" data-testid={`${testPrefix}-then-${o.field}-set`}>
                    Set a value
                  </button>
                ) : (
                  <>
                    <div className="inline-flex rounded-md border border-slate-700 p-0.5 bg-slate-950">
                      <button type="button" onClick={() => setCell(o.field, { value: isFormula ? '' : cell?.value })} className={`inline-flex items-center gap-1 px-2 py-1 text-xs rounded ${!isFormula ? 'bg-slate-700 text-white' : 'text-slate-400'}`} aria-pressed={!isFormula}>
                        <Type className="w-3 h-3" /> Value
                      </button>
                      <button type="button" onClick={() => setCell(o.field, { formula: isFormula ? cell!.formula : '' })} className={`inline-flex items-center gap-1 px-2 py-1 text-xs rounded ${isFormula ? 'bg-slate-700 text-white' : 'text-slate-400'}`} aria-pressed={isFormula} data-testid={`${testPrefix}-then-${o.field}-formula-toggle`}>
                        <Calculator className="w-3 h-3" /> Calculate
                      </button>
                    </div>
                    {isFormula ? (
                      <FormulaInput value={cell!.formula || ''} onChange={(v) => setCell(o.field, { ...cell, formula: v })} facts={facts} invalid={!!p} testId={`${testPrefix}-then-${o.field}-formula`} />
                    ) : (
                      <input
                        value={cell?.value === undefined || cell?.value === null ? '' : String(cell.value)}
                        onChange={(e) => {
                          const raw = e.target.value;
                          const v = raw === 'true' ? true : raw === 'false' ? false : raw !== '' && !Number.isNaN(Number(raw)) && o.type === 'number' ? Number(raw) : raw;
                          setCell(o.field, { value: v });
                        }}
                        placeholder="CBAM_DECLARATION_AND_CERTIFICATE_SURRENDER"
                        className={`w-80 bg-slate-950 border rounded-md px-2 py-1.5 text-sm text-white ${p ? 'border-rose-500/60' : 'border-slate-700'}`}
                        data-testid={`${testPrefix}-then-${o.field}-value`}
                      />
                    )}
                    <button type="button" onClick={() => setCell(o.field, null)} className="text-xs text-slate-500 hover:text-rose-300">Clear</button>
                  </>
                )}
              </div>
              {p && <p className="mt-0.5 ml-[10.5rem] text-xs text-rose-300" role="alert">{p.message}</p>}
            </div>
          );
        })}
      </div>
      <div className="flex items-center gap-2 mt-3">
        <input
          value={newField}
          onChange={(e) => setNewField(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && fieldOk) { onAddOutcome({ field: newField.trim(), label: newField.trim(), type: 'string' }); setCell(newField.trim(), { value: '' }); setNewField(''); } }}
          placeholder="New outcome, e.g. obligation"
          className="w-56 bg-slate-950 border border-slate-700 rounded-md px-2 py-1 text-xs text-white"
          aria-label="New outcome name"
          data-testid={`${testPrefix}-new-outcome`}
        />
        <button
          type="button"
          disabled={!fieldOk}
          onClick={() => { onAddOutcome({ field: newField.trim(), label: newField.trim(), type: 'string' }); setCell(newField.trim(), { value: '' }); setNewField(''); }}
          className="inline-flex items-center gap-1 text-xs text-cyan-300 disabled:text-slate-600"
          data-testid={`${testPrefix}-add-outcome`}
        >
          <Plus className="w-3.5 h-3.5" /> Add outcome
        </button>
      </div>
      {none && <p className="mt-1 text-xs text-rose-300" role="alert">{none.message}</p>}
    </div>
  );
}
