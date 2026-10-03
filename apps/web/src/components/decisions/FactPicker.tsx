'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Calendar, ChevronDown, Hash, List, Plus, ToggleLeft, Type } from 'lucide-react';
import { PATH_RE, TYPE_LABEL, type Fact, type FactType } from '@/lib/decisions';

export const TYPE_ICON: Record<FactType, typeof Type> = { string: Type, number: Hash, boolean: ToggleLeft, date: Calendar, list: List };

function guessType(path: string): FactType {
  const leaf = (path.split('.').pop() || '').toLowerCase();
  if (/(date|day|_at|since|until)$/.test(leaf) || /^date/.test(leaf)) return 'date';
  if (/(tonnes|tons|mass|weight|amount|price|cost|rate|count|qty|quantity|value|volume|percent|share|emissions)/.test(leaf)) return 'number';
  if (/^(is|has|can)[A-Z_]/.test(path.split('.').pop() || '')) return 'boolean';
  return 'string';
}

export default function FactPicker({
  facts,
  value,
  onChange,
  onAddFact,
  invalid,
  testId,
}: {
  facts: Fact[];
  value: string;
  onChange: (path: string, type?: FactType) => void;
  onAddFact: (f: Fact) => void;
  invalid?: boolean;
  testId?: string;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [newType, setNewType] = useState<FactType>('string');
  const box = useRef<HTMLDivElement>(null);
  const current = facts.find((f) => f.path === value);
  const Icon = current ? TYPE_ICON[current.type] : Type;

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  useEffect(() => setNewType(guessType(q.trim())), [q]);

  const matches = useMemo(() => {
    const n = q.trim().toLowerCase();
    return facts.filter((f) => !n || f.path.toLowerCase().includes(n) || (f.label || '').toLowerCase().includes(n));
  }, [facts, q]);
  const canAdd = q.trim() && PATH_RE.test(q.trim()) && !facts.some((f) => f.path === q.trim());
  const badPath = q.trim() && !PATH_RE.test(q.trim());

  function add() {
    const path = q.trim();
    onAddFact({ path, type: newType, label: path, required: true });
    onChange(path, newType);
    setQ('');
    setOpen(false);
  }

  return (
    <div className="relative" ref={box}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        data-invalid={invalid || undefined}
        className={`w-full min-w-[170px] flex items-center gap-1.5 px-2 py-1.5 rounded-md border text-sm text-left ${
          invalid ? 'border-rose-500/60 bg-rose-500/5' : 'border-slate-700 bg-slate-950 hover:border-slate-500'
        }`}
        data-testid={testId}
      >
        <Icon className="w-3.5 h-3.5 text-slate-400 shrink-0" />
        <span className={`truncate flex-1 ${value ? 'text-white' : 'text-slate-500'}`}>{current?.label || value || 'Pick a fact'}</span>
        <ChevronDown className="w-3.5 h-3.5 text-slate-500 shrink-0" />
      </button>
      {open && (
        <div className="absolute z-30 mt-1 w-72 rounded-lg border border-slate-700 bg-slate-900 shadow-2xl">
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                if (matches.length === 1 && !canAdd) {
                  onChange(matches[0].path);
                  setOpen(false);
                } else if (canAdd) add();
              }
              if (e.key === 'Escape') setOpen(false);
            }}
            placeholder="Search or type a new path, e.g. import.cnCode"
            className="w-full bg-transparent border-b border-slate-800 px-3 py-2 text-sm text-white outline-none"
            aria-label="Search facts"
          />
          <ul className="max-h-60 overflow-y-auto py-1" role="listbox">
            {matches.map((f) => {
              const I = TYPE_ICON[f.type];
              return (
                <li key={f.path}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={f.path === value}
                    onClick={() => { onChange(f.path); setOpen(false); setQ(''); }}
                    className={`w-full flex items-center gap-2 px-3 py-1.5 text-sm text-left ${f.path === value ? 'bg-cyan-500/10 text-white' : 'text-slate-300 hover:bg-slate-800'}`}
                  >
                    <I className="w-3.5 h-3.5 text-slate-500" />
                    <span className="truncate flex-1">{f.label || f.path}</span>
                    {f.label && f.label !== f.path && <span className="text-[10px] font-mono text-slate-500 truncate max-w-[110px]">{f.path}</span>}
                  </button>
                </li>
              );
            })}
            {!matches.length && !canAdd && <li className="px-3 py-2 text-xs text-slate-500">{facts.length ? 'No fact matches.' : 'No facts yet. Type a path to add one.'}</li>}
          </ul>
          {badPath && <p className="px-3 pb-2 text-xs text-rose-300">Paths use letters, digits and _ separated by dots.</p>}
          {canAdd && (
            <div className="border-t border-slate-800 p-2 flex items-center gap-2">
              <select value={newType} onChange={(e) => setNewType(e.target.value as FactType)} className="bg-slate-950 border border-slate-700 rounded px-1.5 py-1 text-xs text-white" aria-label="Type of the new fact">
                {(Object.keys(TYPE_LABEL) as FactType[]).map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
              </select>
              <button type="button" onClick={add} className="flex-1 inline-flex items-center gap-1.5 px-2 py-1 rounded bg-cyan-500/15 text-cyan-200 text-xs hover:bg-cyan-500/25" data-testid="fact-add-new">
                <Plus className="w-3.5 h-3.5" /> Add <span className="font-mono">{q.trim()}</span>
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
