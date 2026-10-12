'use client';

import { useId, useState } from 'react';
import { X } from 'lucide-react';
import { addTags, LIMITS } from './lib';

export default function TagInput({
  id, tags, onChange, suggestions = [], problem, describedBy,
}: {
  id: string;
  tags: string[];
  onChange: (tags: string[]) => void;
  suggestions?: string[];
  problem?: string | null;
  describedBy?: string;
}) {
  const [text, setText] = useState('');
  const [local, setLocal] = useState<string | null>(null);
  const listId = useId();
  const shown = local || problem;

  const commit = (raw: string) => {
    if (!raw.trim()) return true;
    const r = addTags(tags, raw);
    setLocal(r.problem);
    if (r.tags.length !== tags.length) onChange(r.tags);
    if (!r.problem) setText('');
    return !r.problem;
  };

  const full = tags.length >= LIMITS.tags;
  return (
    <div>
      <div className={`flex min-h-[42px] flex-wrap items-center gap-1.5 rounded-md border bg-slate-950 px-2 py-1.5 focus-within:border-cyan-500 ${shown ? 'border-rose-500/60' : 'border-slate-700'}`}>
        {tags.map((t) => (
          <span key={t} className="inline-flex max-w-full items-center gap-1 rounded-full border border-cyan-500/30 bg-cyan-500/10 py-0.5 pl-2 pr-1 text-xs text-cyan-100" data-testid="asset-tag-chip" data-tag={t}>
            <span className="truncate">{t}</span>
            <button type="button" onClick={() => { onChange(tags.filter((x) => x !== t)); setLocal(null); }} aria-label={`Remove tag ${t}`} className="rounded-full p-0.5 text-cyan-200 hover:bg-cyan-500/20 hover:text-white">
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        <input
          id={id}
          value={text}
          list={suggestions.length ? listId : undefined}
          onChange={(e) => {
            const v = e.target.value;
            setLocal(null);
            if (v.includes(',')) {
              const cut = v.lastIndexOf(',');
              if (commit(v.slice(0, cut))) setText(v.slice(cut + 1));
              else setText(v);
            } else setText(v);
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { e.preventDefault(); commit(text); }
            else if (e.key === 'Backspace' && !text && tags.length) onChange(tags.slice(0, -1));
          }}
          onBlur={() => { if (text.trim()) commit(text); }}
          placeholder={full ? 'Tag limit reached' : tags.length ? 'Add another' : 'north depot, refrigerated'}
          disabled={full && !text}
          aria-invalid={!!shown}
          aria-describedby={describedBy}
          className="min-w-[8rem] flex-1 bg-transparent py-0.5 text-sm text-white placeholder:text-slate-600 focus:outline-none disabled:cursor-not-allowed"
          data-testid="asset-tags-input"
        />
        {suggestions.length > 0 && (
          <datalist id={listId}>
            {suggestions.filter((s) => !tags.includes(s)).slice(0, 100).map((s) => <option key={s} value={s} />)}
          </datalist>
        )}
      </div>
      {shown && <p className="mt-1 text-xs text-rose-300" role="alert" data-testid="asset-err-tags">{shown}</p>}
    </div>
  );
}
