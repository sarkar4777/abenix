'use client';

import { useState } from 'react';
import { X } from 'lucide-react';
import { OPERATORS, type Condition, type FactType } from '@/lib/decisions';

const base = 'bg-slate-950 border rounded-md px-2 py-1.5 text-sm text-white outline-none focus:border-cyan-500';

function coerce(type: FactType, raw: string): any {
  if (type === 'number') {
    if (raw.trim() === '' || raw.trim() === '-') return raw;
    const n = Number(raw);
    return Number.isFinite(n) ? n : raw;
  }
  return raw;
}

function Scalar({ type, value, onChange, invalid, testId, placeholder }: { type: FactType; value: any; onChange: (v: any) => void; invalid?: boolean; testId?: string; placeholder?: string }) {
  const border = invalid ? 'border-rose-500/60' : 'border-slate-700';
  if (type === 'date') {
    return <input type="date" value={value ?? ''} onChange={(e) => onChange(e.target.value)} className={`${base} ${border} [color-scheme:dark]`} aria-invalid={invalid} data-testid={testId} />;
  }
  if (type === 'boolean') {
    return (
      <select value={String(value ?? 'true')} onChange={(e) => onChange(e.target.value === 'true')} className={`${base} ${border}`} data-testid={testId}>
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
    );
  }
  return (
    <input
      type="text"
      inputMode={type === 'number' ? 'decimal' : undefined}
      value={value ?? ''}
      onChange={(e) => onChange(coerce(type, e.target.value))}
      placeholder={placeholder || (type === 'number' ? '0' : 'value')}
      className={`${base} ${border} w-36`}
      aria-invalid={invalid}
      data-testid={testId}
    />
  );
}

function Chips({ type, values, onChange, invalid, testId }: { type: FactType; values: any[]; onChange: (v: any[]) => void; invalid?: boolean; testId?: string }) {
  const [draft, setDraft] = useState('');
  function commit(text: string) {
    const parts = text.split(/[,\n\t]/).map((s) => s.trim()).filter(Boolean);
    if (!parts.length) return;
    const next = [...values];
    for (const p of parts) {
      const v = coerce(type, p);
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
          <button type="button" aria-label={`Remove ${v}`} onClick={() => onChange(values.filter((_, j) => j !== i))} className="text-slate-400 hover:text-white"><X className="w-3 h-3" /></button>
        </span>
      ))}
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); commit(draft); }
          else if (e.key === 'Backspace' && !draft && values.length) onChange(values.slice(0, -1));
        }}
        onPaste={(e) => { const t = e.clipboardData.getData('text'); if (/[,\n\t]/.test(t)) { e.preventDefault(); commit(t); } }}
        onBlur={() => commit(draft)}
        placeholder={values.length ? '' : 'Type, then Enter. Paste a list to add many.'}
        className="flex-1 min-w-[90px] bg-transparent text-sm text-white outline-none py-0.5"
        data-testid={testId}
      />
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
}: {
  cond: Condition;
  type: FactType;
  onChange: (patch: Partial<Condition>) => void;
  invalid?: boolean;
  referenceSets: { key: string; name: string; count: number }[];
  testId?: string;
}) {
  const shape = OPERATORS[cond.op]?.shape ?? 'one';
  if (shape === 'none') return null;
  if (shape === 'two') {
    const vs = cond.values ?? [];
    return (
      <span className="inline-flex items-center gap-1.5">
        <Scalar type={type} value={vs[0]} onChange={(v) => onChange({ values: [v, vs[1]] })} invalid={invalid} testId={testId && `${testId}-lo`} placeholder="from" />
        <span className="text-xs text-slate-500">and</span>
        <Scalar type={type} value={vs[1]} onChange={(v) => onChange({ values: [vs[0], v] })} invalid={invalid} testId={testId && `${testId}-hi`} placeholder="to" />
      </span>
    );
  }
  if (shape === 'many') return <Chips type={type} values={cond.values ?? []} onChange={(values) => onChange({ values })} invalid={invalid} testId={testId} />;
  if (shape === 'set') {
    return (
      <select value={cond.set ?? ''} onChange={(e) => onChange({ set: e.target.value })} className={`${base} ${invalid ? 'border-rose-500/60' : 'border-slate-700'} max-w-xs`} data-testid={testId}>
        <option value="">Pick a reference set</option>
        {referenceSets.map((s) => <option key={s.key} value={s.key}>{s.name} ({s.count})</option>)}
        {cond.set && !referenceSets.some((s) => s.key === cond.set) && <option value={cond.set}>{cond.set} (not found)</option>}
      </select>
    );
  }
  return <Scalar type={type === 'list' ? 'string' : type} value={cond.value} onChange={(value) => onChange({ value })} invalid={invalid} testId={testId} />;
}
