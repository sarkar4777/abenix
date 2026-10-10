'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Calendar, ChevronDown, Hash, List, Plus, ToggleLeft, Type } from 'lucide-react';
import { TYPE_LABEL, type Fact, type FactType } from '@/lib/decisions';
import { guessFactType } from '@/lib/decisionValues';
import { toPath } from '@/lib/decisionPaste';

export const TYPE_ICON: Record<FactType, typeof Type> = { string: Type, number: Hash, boolean: ToggleLeft, date: Calendar, list: List };

// why the saved name differs from what was typed, in the words that fit
export function factNameNote(typed: string, path: string): string {
  const why = /\s/.test(typed) ? "Fact names can't have spaces" : /[A-Z]/.test(typed) ? 'Fact names are lowercase' : 'Fact names use only letters, digits, _ and dots';
  return `${why}, so it is saved as ${path} and shown as “${typed}”.`;
}

export default function FactPicker({
  facts,
  value,
  onChange,
  onAddFact,
  onFactType,
  invalid,
  testId,
  readOnly,
}: {
  facts: Fact[];
  value: string;
  onChange: (path: string, type?: FactType) => void;
  onAddFact: (f: Fact) => void;
  onFactType?: (path: string, type: FactType) => void;
  invalid?: boolean;
  testId?: string;
  readOnly?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [newType, setNewType] = useState<FactType>('string');
  const [typeTouched, setTypeTouched] = useState(false);
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


  const matches = useMemo(() => {
    const n = q.trim().toLowerCase();
    return facts.filter((f) => !n || f.path.toLowerCase().includes(n) || (f.label || '').toLowerCase().includes(n));
  }, [facts, q]);
  // "tip speed" becomes tip_speed, the label keeps what was typed
  const typed = q.trim();
  const path = toPath(typed);
  const canAdd = !!path && !facts.some((f) => f.path === path);
  const badPath = !!typed && !path;

  useEffect(() => {
    if (!typeTouched) setNewType(guessFactType(path || q.trim()));
  }, [q, path, typeTouched]);

  function add() {
    if (!path) return;
    onAddFact({ path, type: newType, label: typed && typed !== path ? typed : path, required: true });
    onChange(path, newType);
    setQ('');
    setTypeTouched(false);
    setOpen(false);
  }

  return (
    <div className="relative" ref={box}>
      <button
        type="button"
        onClick={() => !readOnly && setOpen((o) => !o)}
        disabled={readOnly}
        aria-haspopup="listbox"
        aria-expanded={open}
        data-invalid={invalid || undefined}
        title={current ? `${current.path}, ${TYPE_LABEL[current.type]}` : undefined}
        className={`w-full min-w-[170px] flex items-center gap-1.5 px-2 py-1.5 rounded-md border text-sm text-left disabled:cursor-default ${
          invalid ? 'border-rose-500/60 bg-rose-500/5' : 'border-slate-700 bg-slate-950 hover:border-slate-500'
        }`}
        data-testid={testId}
      >
        <Icon className="w-3.5 h-3.5 text-slate-400 shrink-0" />
        <span className={`truncate flex-1 ${value ? 'text-white' : 'text-slate-500'}`}>{current?.label || value || 'Pick a fact'}</span>
        {!readOnly && <ChevronDown className="w-3.5 h-3.5 text-slate-500 shrink-0" />}
      </button>
      {open && (
        <div className="absolute z-30 mt-1 w-72 max-w-[calc(100vw-2rem)] rounded-lg border border-slate-700 bg-slate-900 shadow-2xl">
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
            placeholder="Search, or type a new fact name"
            className="w-full bg-transparent border-b border-slate-800 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-500"
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
                    <span className="text-[10px] text-slate-500" aria-hidden="true">{TYPE_LABEL[f.type]}</span>
                  </button>
                </li>
              );
            })}
            {!matches.length && !canAdd && <li className="px-3 py-2 text-xs text-slate-500">{typed ? `No fact matches “${typed}”.` : facts.length ? 'No fact matches.' : 'No facts yet. Type a name to add one.'}</li>}
          </ul>
          {badPath && <p className="px-3 pb-2 text-xs text-rose-300">A fact name needs letters or digits, with dots between parts, like worker.distance_m.</p>}
          {canAdd && (
            <div className="border-t border-slate-800 p-2 space-y-1.5">
              <div className="flex items-center gap-2">
                <label className="text-[11px] text-slate-400" htmlFor="fact-new-type">Type</label>
                <select
                  id="fact-new-type"
                  value={newType}
                  onChange={(e) => { setTypeTouched(true); setNewType(e.target.value as FactType); }}
                  className="bg-slate-950 border border-slate-700 rounded px-1.5 py-1 text-xs text-white"
                  aria-label="Type of the new fact"
                  data-testid="fact-new-type"
                >
                  {(Object.keys(TYPE_LABEL) as FactType[]).map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
                </select>
                <button type="button" onClick={add} className="flex-1 inline-flex items-center gap-1.5 px-2 py-1 rounded bg-cyan-500/15 text-cyan-200 text-xs hover:bg-cyan-500/25 min-w-0" data-testid="fact-add-new">
                  <Plus className="w-3.5 h-3.5 shrink-0" /> <span className="truncate">Add <span className="font-mono">{path}</span></span>
                </button>
              </div>
              {path !== typed && <p className="text-[11px] text-slate-400" data-testid="fact-name-normalised">{factNameNote(typed, path)}</p>}
              <p className="text-[11px] text-slate-500">
                {typeTouched ? 'You can change the type later.' : `Guessed from the name. ${newType === 'string' ? 'Text matches words. Pick Number to compare amounts.' : 'Change it if that is wrong.'}`}
              </p>
            </div>
          )}
          {current && onFactType && !q.trim() && (
            <div className="border-t border-slate-800 p-2 flex items-center gap-2">
              <label className="text-[11px] text-slate-400" htmlFor="fact-current-type">{current.label || current.path} is</label>
              <select
                id="fact-current-type"
                value={current.type}
                onChange={(e) => onFactType(current.path, e.target.value as FactType)}
                className="bg-slate-950 border border-slate-700 rounded px-1.5 py-1 text-xs text-white"
                data-testid="fact-current-type"
              >
                {(Object.keys(TYPE_LABEL) as FactType[]).map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
              </select>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
