'use client';

import { useState } from 'react';
import { X } from 'lucide-react';
import { OPERATORS, type Condition, type FactType } from '@/lib/decisions';
import { coerceTo } from '@/lib/decisionValues';
import { NumberInput } from './DraftInput';

const base = 'bg-slate-950 border rounded-md px-2 py-1.5 text-sm text-white outline-none focus:border-cyan-500';

function Scalar({ type, value, onChange, invalid, testId, placeholder, readOnly }: { type: FactType; value: any; onChange: (v: any) => void; invalid?: boolean; testId?: string; placeholder?: string; readOnly?: boolean }) {
  const border = invalid ? 'border-rose-500/60' : 'border-slate-700';
  if (type === 'date') {
    return <input type="date" value={value ?? ''} disabled={readOnly} onChange={(e) => onChange(e.target.value)} className={`${base} ${border} [color-scheme:dark] disabled:opacity-70`} aria-invalid={invalid} data-testid={testId} />;
  }
  if (type === 'boolean') {
    return (
      <select value={String(value ?? 'true')} disabled={readOnly} onChange={(e) => onChange(e.target.value === 'true')} className={`${base} ${border}`} data-testid={testId}>
        <option value="true">yes</option>
        <option value="false">no</option>
      </select>
    );
  }
  if (type === 'number') {
    return (
      <NumberInput
        value={value}
        onValue={onChange}
        disabled={readOnly}
        placeholder={placeholder || 'number'}
        className={`${base} ${border} w-36 placeholder:text-slate-600 placeholder:italic disabled:opacity-70`}
        aria-invalid={invalid}
        data-testid={testId}
      />
    );
  }
  return (
    <input
      type="text"
      value={value ?? ''}
      disabled={readOnly}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder || 'text'}
      className={`${base} ${border} w-36 placeholder:text-slate-600 placeholder:italic disabled:opacity-70`}
      aria-invalid={invalid}
      data-testid={testId}
    />
  );
}

function Chips({ type, values, onChange, invalid, testId, readOnly }: { type: FactType; values: any[]; onChange: (v: any[]) => void; invalid?: boolean; testId?: string; readOnly?: boolean }) {
  const [draft, setDraft] = useState('');
  function commit(text: string) {
    const parts = text.split(/[,\n\t]/).map((s) => s.trim()).filter(Boolean);
    if (!parts.length) return;
    const next = [...values];
    for (const p of parts) {
      const v = coerceTo(type, p);
      if (!next.some((x) => String(x) === String(v))) next.push(v);
    }
    onChange(next);
    setDraft('');
  }
  return (
    <div className={`flex flex-wrap items-center gap-1 min-w-[200px] max-w-md rounded-md border ${invalid ? 'border-rose-500/60' : 'border-slate-700'} bg-slate-950 px-1.5 py-1`}>
      {values.map((v, i) => (
        <span key={`${v}-${i}`} className="inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded bg-slate-800 text-slate-200">
          {String(v)}
          {!readOnly && <button type="button" aria-label={`Remove ${v}`} onClick={() => onChange(values.filter((_, j) => j !== i))} className="text-slate-400 hover:text-white"><X className="w-3 h-3" /></button>}
        </span>
      ))}
      {!readOnly && <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); commit(draft); }
          else if (e.key === 'Backspace' && !draft && values.length) onChange(values.slice(0, -1));
        }}
        onPaste={(e) => { const t = e.clipboardData.getData('text'); if (/[,\n\t]/.test(t)) { e.preventDefault(); commit(t); } }}
        onBlur={() => commit(draft)}
        placeholder={values.length ? '' : 'Type, then Enter. Paste a list to add many.'}
        className="flex-1 min-w-[90px] bg-transparent text-sm text-white outline-none py-0.5 placeholder:text-slate-600"
        data-testid={testId}
      />}
    </div>
  );
}

export default function ValueInput({
  cond,
  type,
  onChange,
  invalid,
  referenceSets,
  testId,
  readOnly,
}: {
  cond: Condition;
  type: FactType;
  onChange: (patch: Partial<Condition>) => void;
  invalid?: boolean;
  referenceSets: { key: string; name: string; count: number }[];
  testId?: string;
  readOnly?: boolean;
}) {
  const shape = OPERATORS[cond.op]?.shape ?? 'one';
  if (shape === 'none') return null;
  if (shape === 'two') {
    const vs = cond.values ?? [];
    return (
      <span className="inline-flex items-center gap-1.5">
        <Scalar type={type} value={vs[0]} onChange={(v) => onChange({ values: [v, vs[1]] })} invalid={invalid} testId={testId && `${testId}-lo`} placeholder="from" readOnly={readOnly} />
        <span className="text-xs text-slate-500">and</span>
        <Scalar type={type} value={vs[1]} onChange={(v) => onChange({ values: [vs[0], v] })} invalid={invalid} testId={testId && `${testId}-hi`} placeholder="to" readOnly={readOnly} />
      </span>
    );
  }
  if (shape === 'many') return <Chips type={type} values={cond.values ?? []} onChange={(values) => onChange({ values })} invalid={invalid} testId={testId} readOnly={readOnly} />;
  if (shape === 'set') {
    return (
      <select title="A reference set is a named list of values, such as postcodes, kept under Decisions, Reference sets" value={cond.set ?? ''} disabled={readOnly} onChange={(e) => onChange({ set: e.target.value })} className={`${base} ${invalid ? 'border-rose-500/60' : 'border-slate-700'} max-w-xs`} data-testid={testId}>
        <option value="">{referenceSets.length ? 'Pick a reference set (a named list)' : 'No reference sets yet. Add one under Decisions, Reference sets'}</option>
        {referenceSets.map((s) => <option key={s.key} value={s.key}>{s.name} ({s.count})</option>)}
        {cond.set && !referenceSets.some((s) => s.key === cond.set) && <option value={cond.set}>{cond.set} (not found)</option>}
      </select>
    );
  }
  return <Scalar type={type === 'list' ? 'string' : type} value={cond.value} onChange={(value) => onChange({ value })} invalid={invalid} testId={testId} readOnly={readOnly} />;
}
