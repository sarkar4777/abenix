'use client';

import { useMemo, useState } from 'react';
import { Columns2, Rows3 } from 'lucide-react';
import type { Diff, DiffLine, Hunk, SheetDiff } from '@/lib/sources';

type Mode = 'unified' | 'split';

// Highlight only the part of a changed line that differs, by trimming the shared prefix and suffix.
function splitChange(a: string, b: string): { pre: string; a: string; b: string; post: string } {
  let i = 0;
  while (i < a.length && i < b.length && a[i] === b[i]) i++;
  let j = 0;
  while (j < a.length - i && j < b.length - i && a[a.length - 1 - j] === b[b.length - 1 - j]) j++;
  return { pre: a.slice(0, i), a: a.slice(i, a.length - j), b: b.slice(i, b.length - j), post: a.slice(a.length - j) };
}

function Inline({ text, other, side }: { text: string; other?: string; side: '-' | '+' }) {
  if (other === undefined) return <>{text || ' '}</>;
  const s = side === '-' ? splitChange(text, other) : splitChange(other, text);
  const mid = side === '-' ? s.a : s.b;
  const mark = side === '-' ? 'bg-rose-500/40 text-rose-50' : 'bg-emerald-500/40 text-emerald-50';
  return (
    <>
      {s.pre}
      {mid && <mark className={`${mark} rounded-sm px-0.5`}>{mid}</mark>}
      {s.post}
      {!text && ' '}
    </>
  );
}

interface Row { left?: DiffLine; right?: DiffLine; pairL?: string; pairR?: string }

function pairHunk(h: Hunk): Row[] {
  const rows: Row[] = [];
  let i = 0;
  const ls = h.lines;
  while (i < ls.length) {
    if (ls[i].op === ' ') {
      rows.push({ left: ls[i], right: ls[i] });
      i++;
      continue;
    }
    const del: DiffLine[] = [];
    const add: DiffLine[] = [];
    while (i < ls.length && ls[i].op === '-') del.push(ls[i++]);
    while (i < ls.length && ls[i].op === '+') add.push(ls[i++]);
    const n = Math.max(del.length, add.length);
    for (let k = 0; k < n; k++) {
      const paired = del[k] && add[k];
      rows.push({ left: del[k], right: add[k], pairL: paired ? add[k].text : undefined, pairR: paired ? del[k].text : undefined });
    }
  }
  return rows;
}

function unifiedPairs(h: Hunk): Map<number, string> {
  const out = new Map<number, string>();
  const ls = h.lines;
  let i = 0;
  while (i < ls.length) {
    if (ls[i].op === ' ') {
      i++;
      continue;
    }
    const ds: number[] = [];
    const as: number[] = [];
    while (i < ls.length && ls[i].op === '-') ds.push(i++);
    while (i < ls.length && ls[i].op === '+') as.push(i++);
    for (let k = 0; k < Math.min(ds.length, as.length); k++) {
      out.set(ds[k], ls[as[k]].text);
      out.set(as[k], ls[ds[k]].text);
    }
  }
  return out;
}

const NUM = 'w-12 shrink-0 select-none text-right pr-2 text-slate-600 tabular-nums';
const ROW_BG: Record<string, string> = { '-': 'bg-rose-500/10', '+': 'bg-emerald-500/10', ' ': '' };
const SIGN: Record<string, string> = { '-': 'text-rose-300', '+': 'text-emerald-300', ' ': 'text-slate-600' };

function HunkHeader({ h }: { h: Hunk }) {
  return (
    <div className="px-3 py-1 text-[11px] font-mono text-cyan-300/80 bg-cyan-500/5 border-y border-slate-800">
      Lines {h.old_start}–{h.old_start + Math.max(0, h.old_len - 1)} before, {h.new_start}–{h.new_start + Math.max(0, h.new_len - 1)} after
    </div>
  );
}

function TextDiff({ diff, mode }: { diff: Diff; mode: Mode }) {
  const hunks = diff.hunks || [];
  if (!hunks.length) return <p className="text-sm text-slate-400 p-4">No line changes to show.</p>;
  return (
    <div className="font-mono text-xs leading-5" data-testid="diff-text">
      {hunks.map((h, hi) => (
        <div key={hi}>
          <HunkHeader h={h} />
          {mode === 'unified' ? (
            <UnifiedHunk h={h} />
          ) : (
            pairHunk(h).map((r, ri) => (
              <div key={ri} className="grid grid-cols-2 divide-x divide-slate-800">
                <div className={`flex ${r.left ? ROW_BG[r.left.op === ' ' ? ' ' : '-'] : 'bg-slate-900/60'}`}>
                  <span className={NUM}>{r.left?.old ?? ''}</span>
                  <span className="whitespace-pre-wrap break-words flex-1 pr-2 text-slate-200">
                    {r.left ? <Inline text={r.left.text} other={r.left.op === '-' ? r.pairL : undefined} side="-" /> : ''}
                  </span>
                </div>
                <div className={`flex ${r.right ? ROW_BG[r.right.op === ' ' ? ' ' : '+'] : 'bg-slate-900/60'}`}>
                  <span className={NUM}>{r.right?.new ?? ''}</span>
                  <span className="whitespace-pre-wrap break-words flex-1 pr-2 text-slate-200">
                    {r.right ? <Inline text={r.right.text} other={r.right.op === '+' ? r.pairR : undefined} side="+" /> : ''}
                  </span>
                </div>
              </div>
            ))
          )}
        </div>
      ))}
    </div>
  );
}

function UnifiedHunk({ h }: { h: Hunk }) {
  const pairs = useMemo(() => unifiedPairs(h), [h]);
  return (
    <>
      {h.lines.map((l, i) => (
        <div key={i} className={`flex ${ROW_BG[l.op]}`}>
          <span className={NUM}>{l.old ?? ''}</span>
          <span className={NUM}>{l.new ?? ''}</span>
          <span className={`w-4 shrink-0 select-none ${SIGN[l.op]}`} aria-hidden>{l.op === ' ' ? '' : l.op}</span>
          <span className="sr-only">{l.op === '+' ? 'Added: ' : l.op === '-' ? 'Removed: ' : ''}</span>
          <span className="whitespace-pre-wrap break-words flex-1 pr-2 text-slate-200">
            {l.op === ' ' ? l.text || ' ' : <Inline text={l.text} other={pairs.get(i)} side={l.op as '-' | '+'} />}
          </span>
        </div>
      ))}
    </>
  );
}

function Cells({ row, mark, tone }: { row: string[]; mark?: number[]; tone: string }) {
  return (
    <>
      {row.map((c, i) => (
        <td key={i} className={`px-2 py-1 align-top ${mark?.includes(i) ? tone : ''}`}>{c || <span className="text-slate-600">—</span>}</td>
      ))}
    </>
  );
}

function SheetView({ s }: { s: SheetDiff }) {
  const header = s.header.length ? s.header : null;
  const more = (k: 'added' | 'removed' | 'changed') => {
    const total = s[`${k}_total` as const];
    return total && total > s[k].length ? <p className="text-xs text-slate-500 px-3 py-1">Showing {s[k].length} of {total}.</p> : null;
  };
  return (
    <section className="border border-slate-800 rounded-lg overflow-hidden">
      <header className="flex flex-wrap items-center gap-2 px-3 py-2 bg-slate-900/70 border-b border-slate-800 text-sm">
        <span className="font-medium text-white">{s.name || 'Table'}</span>
        <span className="text-xs text-slate-500">{s.rows_old} rows before, {s.rows_new} after</span>
        {s.key_column && <span className="text-xs text-slate-400">Rows matched on “{s.key_column}”</span>}
        {s.header_changed && <span className="text-xs text-amber-300">The header row changed, so rows are compared whole.</span>}
      </header>
      <div className="overflow-x-auto">
        <table className="min-w-full text-xs font-mono text-slate-200">
          {header && (
            <thead className="bg-slate-900/40 text-slate-400">
              <tr>
                <th className="px-2 py-1 text-left w-20" />
                {header.map((h, i) => <th key={i} className="px-2 py-1 text-left font-medium">{h}</th>)}
              </tr>
            </thead>
          )}
          <tbody className="divide-y divide-slate-800/70">
            {s.changed.map((c) => (
              <tr key={`c-${c.key}`} className="bg-amber-500/5">
                <td className="px-2 py-1 align-top text-amber-300 whitespace-nowrap">Changed</td>
                {c.after.map((v, i) => (
                  <td key={i} className="px-2 py-1 align-top">
                    {c.indexes.includes(i) ? (
                      <span className="inline-flex flex-col">
                        <del className="bg-rose-500/20 text-rose-200 px-0.5 rounded-sm">{c.before[i] || '—'}</del>
                        <ins className="bg-emerald-500/20 text-emerald-200 px-0.5 rounded-sm no-underline">{v || '—'}</ins>
                      </span>
                    ) : (
                      v
                    )}
                  </td>
                ))}
              </tr>
            ))}
            {s.added.map((r, i) => (
              <tr key={`a-${i}`} className="bg-emerald-500/10">
                <td className="px-2 py-1 align-top text-emerald-300 whitespace-nowrap">Added</td>
                <Cells row={r} tone="" />
              </tr>
            ))}
            {s.removed.map((r, i) => (
              <tr key={`r-${i}`} className="bg-rose-500/10">
                <td className="px-2 py-1 align-top text-rose-300 whitespace-nowrap">Removed</td>
                <Cells row={r} tone="" />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {more('changed')}
      {more('added')}
      {more('removed')}
    </section>
  );
}

export default function DiffView({ diff }: { diff: Diff }) {
  const [mode, setMode] = useState<Mode>('split');
  if (diff.kind === 'table') {
    return (
      <div className="space-y-4" data-testid="diff-table">
        {(diff.sheets || []).map((s, i) => <SheetView key={i} s={s} />)}
        {diff.truncated && <p className="text-xs text-slate-500">Large change, only the first rows of each kind are kept.</p>}
      </div>
    );
  }
  return (
    <div>
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-3 text-xs">
          <span className="inline-flex items-center gap-1 text-emerald-300"><span className="w-2.5 h-2.5 rounded-sm bg-emerald-500/40" /> Added</span>
          <span className="inline-flex items-center gap-1 text-rose-300"><span className="w-2.5 h-2.5 rounded-sm bg-rose-500/40" /> Removed</span>
        </div>
        <div className="inline-flex rounded-lg border border-slate-700 p-0.5 bg-slate-950" role="radiogroup" aria-label="Diff layout">
          {([['split', 'Side by side', Columns2], ['unified', 'Unified', Rows3]] as const).map(([id, label, Icon]) => (
            <button
              key={id}
              type="button"
              role="radio"
              aria-checked={mode === id}
              onClick={() => setMode(id)}
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-md ${mode === id ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`}
              data-testid={`diff-mode-${id}`}
            >
              <Icon className="w-3.5 h-3.5" /> {label}
            </button>
          ))}
        </div>
      </div>
      {mode === 'split' && (
        <div className="grid grid-cols-2 text-[11px] uppercase tracking-wide text-slate-500 border border-b-0 border-slate-800 rounded-t-lg bg-slate-900/60">
          <div className="px-3 py-1.5">Before</div>
          <div className="px-3 py-1.5 border-l border-slate-800">After</div>
        </div>
      )}
      <div className={`border border-slate-800 ${mode === 'split' ? 'rounded-b-lg' : 'rounded-lg'} overflow-hidden bg-slate-950`}>
        <TextDiff diff={diff} mode={mode} />
      </div>
      {diff.truncated && <p className="mt-2 text-xs text-slate-500">This change is very large, so only the first part of the diff is kept.</p>}
    </div>
  );
}
