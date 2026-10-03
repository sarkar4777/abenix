'use client';

import { useMemo, useState } from 'react';
import { DndContext, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core';
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { ClipboardPaste, Download, GripVertical, Info, Plus } from 'lucide-react';
import {
  cellsByFact,
  factsUsed,
  formatCell,
  groupItems,
  isGroup,
  newRuleId,
  parseCell,
  problemsAt,
  tableable,
  type Condition,
  type Problem,
  type Rule,
  type RuleDoc,
} from '@/lib/decisions';

function setFactConditions(rule: Rule, fact: string, conds: Condition[]): Rule {
  const items = groupItems(rule.when).filter((n) => isGroup(n) || (n as Condition).fact !== fact);
  return { ...rule, when: { all: [...items, ...conds.map((c) => ({ ...c, fact }))] } };
}

function cellValueText(rule: Rule, field: string): string {
  const cell = rule.then?.[field];
  if (!cell) return '';
  if ('formula' in cell && cell.formula !== undefined) return `=${cell.formula}`;
  return cell.value === undefined || cell.value === null ? '' : String(cell.value);
}

function parseThen(text: string): Rule['then'][string] | null {
  const t = text.trim();
  if (!t) return null;
  if (t.startsWith('=')) return { formula: t.slice(1).trim() };
  if (/^-?\d+(\.\d+)?$/.test(t)) return { value: Number(t) };
  if (/^(true|false)$/i.test(t)) return { value: /^true$/i.test(t) };
  return { value: t };
}

function Cell({ text, onCommit, invalid, testId, placeholder }: { text: string; onCommit: (v: string) => void; invalid?: boolean; testId?: string; placeholder?: string }) {
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <input
      value={draft ?? text}
      onChange={(e) => setDraft(e.target.value)}
      onFocus={() => setDraft(text)}
      onBlur={() => { if (draft !== null && draft !== text) onCommit(draft); setDraft(null); }}
      onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); if (e.key === 'Escape') { setDraft(null); (e.target as HTMLInputElement).blur(); } }}
      placeholder={placeholder ?? 'any'}
      className={`w-full min-w-[110px] bg-transparent px-2 py-1.5 text-sm text-white outline-none focus:bg-slate-950 focus:ring-1 focus:ring-cyan-500 rounded ${invalid ? 'ring-1 ring-rose-500/60' : ''} placeholder:text-slate-600`}
      data-testid={testId}
    />
  );
}

function Row({ rule, index, doc, facts, problems, onRule, readOnly, onOpen }: {
  rule: Rule; index: number; doc: RuleDoc; facts: string[]; problems: Problem[]; onRule: (r: Rule) => void; readOnly: boolean; onOpen: (id: string) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: rule.id });
  const flat = tableable(rule);
  const byFact = cellsByFact(rule);
  const errs = problemsAt(problems, `/rules/${index}`);
  return (
    <tr ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.5 : 1 }} className={`border-b border-slate-800 ${rule.enabled === false ? 'opacity-50' : ''}`} data-testid={`table-row-${index}`}>
      <td className="px-1 align-middle">
        {!readOnly && <button type="button" {...attributes} {...listeners} className="p-1 text-slate-600 hover:text-slate-300 cursor-grab" aria-label={`Drag row ${index + 1}`}><GripVertical className="w-4 h-4" /></button>}
      </td>
      <td className="px-1 text-[11px] text-slate-500 tabular-nums">{index + 1}</td>
      <td className="px-1 border-r border-slate-800">
        <Cell text={rule.key || ''} onCommit={(v) => onRule({ ...rule, key: v.trim() })} placeholder="rule key" testId={`table-${index}-key`} invalid={errs.some((p) => p.path.endsWith('/key'))} />
      </td>
      {flat ? (
        facts.map((f) => {
          const type = doc.facts.find((x) => x.path === f)?.type ?? 'string';
          const bad = errs.some((p) => p.path.includes('/when/'));
          return (
            <td key={f} className="px-1">
              <Cell
                text={formatCell(byFact[f] || [])}
                onCommit={(v) => { const parsed = parseCell(v, type); if (parsed) onRule(setFactConditions(rule, f, parsed)); }}
                invalid={bad && (byFact[f] || []).length > 0}
                testId={`table-${index}-${f}`}
              />
            </td>
          );
        })
      ) : (
        <td colSpan={facts.length} className="px-2 text-xs text-slate-400">
          <button type="button" onClick={() => onOpen(rule.id)} className="inline-flex items-center gap-1 text-cyan-300 hover:underline">
            <Info className="w-3.5 h-3.5" /> Uses grouped conditions, edit it in the rule builder
          </button>
        </td>
      )}
      {doc.outputs.map((o, oi) => (
        <td key={o.field} className={`px-1 ${oi === 0 ? 'border-l border-slate-800' : ''}`}>
          <Cell
            text={cellValueText(rule, o.field)}
            onCommit={(v) => { const cell = parseThen(v); const then = { ...(rule.then || {}) }; if (cell) then[o.field] = cell; else delete then[o.field]; onRule({ ...rule, then }); }}
            placeholder="—"
            invalid={errs.some((p) => p.path.startsWith(`/rules/${index}/then/${o.field}`))}
            testId={`table-${index}-out-${o.field}`}
          />
        </td>
      ))}
    </tr>
  );
}

export default function DecisionTable({ doc, onChange, problems, readOnly, onOpenRule }: {
  doc: RuleDoc; onChange: (d: RuleDoc) => void; problems: Problem[]; readOnly: boolean; onOpenRule: (id: string) => void;
}) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));
  const [pasteMsg, setPasteMsg] = useState<string | null>(null);
  const facts = useMemo(() => {
    const used = new Set<string>();
    doc.rules.forEach((r) => factsUsed(r.when, used));
    const ordered = doc.facts.map((f) => f.path).filter((p) => used.has(p));
    return ordered.length ? ordered : doc.facts.map((f) => f.path).slice(0, 3);
  }, [doc]);

  const setRule = (i: number, r: Rule) => onChange({ ...doc, rules: doc.rules.map((x, j) => (j === i ? r : x)) });

  function addRow() {
    onChange({ ...doc, rules: [...doc.rules, { id: newRuleId(doc), key: '', enabled: true, when: { all: [] }, then: {} }] });
  }

  function onDragEnd(e: DragEndEvent) {
    if (!e.over || e.active.id === e.over.id) return;
    const from = doc.rules.findIndex((r) => r.id === e.active.id);
    const to = doc.rules.findIndex((r) => r.id === e.over!.id);
    onChange({ ...doc, rules: arrayMove(doc.rules, from, to) });
  }

  function exportCsv() {
    const esc = (s: string) => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
    const header = ['rule', ...facts, ...doc.outputs.map((o) => o.field)];
    const lines = [header.join(',')];
    for (const r of doc.rules) {
      const by = cellsByFact(r);
      lines.push([r.key || r.id, ...facts.map((f) => formatCell(by[f] || [])), ...doc.outputs.map((o) => cellValueText(r, o.field))].map((x) => esc(String(x))).join(','));
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'rules.csv';
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // a block pasted from a spreadsheet: an optional header row names the columns
  function onPaste(e: React.ClipboardEvent) {
    if (readOnly) return;
    const text = e.clipboardData.getData('text');
    if (!text.includes('\t') && !text.includes('\n')) return;
    e.preventDefault();
    const rows = text.replace(/\r/g, '').split('\n').filter((l) => l.trim()).map((l) => l.split('\t'));
    if (!rows.length) return;
    const names = rows[0].map((h) => h.trim());
    const known = (h: string) =>
      h.toLowerCase() === 'rule' ||
      doc.facts.some((f) => f.path === h || (f.label || '').toLowerCase() === h.toLowerCase()) ||
      doc.outputs.some((o) => o.field === h || (o.label || '').toLowerCase() === h.toLowerCase());
    const hasHeader = names.some(known);
    const cols = hasHeader ? names : ['rule', ...facts, ...doc.outputs.map((o) => o.field)];
    const body = hasHeader ? rows.slice(1) : rows;
    let next = { ...doc, rules: [...doc.rules] };
    let added = 0;
    let unknown = new Set<string>();
    body.forEach((cells) => {
      let rule: Rule = { id: newRuleId(next), key: '', enabled: true, when: { all: [] }, then: {} };
      cols.forEach((col, ci) => {
        const v = (cells[ci] ?? '').trim();
        if (col.toLowerCase() === 'rule') { rule.key = v; return; }
        const fact = doc.facts.find((f) => f.path === col || (f.label || '').toLowerCase() === col.toLowerCase());
        if (fact) { const parsed = parseCell(v, fact.type); if (parsed?.length) rule = setFactConditions(rule, fact.path, parsed); return; }
        const out = doc.outputs.find((o) => o.field === col || (o.label || '').toLowerCase() === col.toLowerCase());
        if (out) { const cell = parseThen(v); if (cell) rule.then = { ...rule.then, [out.field]: cell }; return; }
        if (col) unknown.add(col);
      });
      const existing = rule.key ? next.rules.findIndex((r) => r.key === rule.key) : -1;
      if (existing >= 0) next.rules[existing] = { ...rule, id: next.rules[existing].id };
      else { next.rules.push(rule); added++; }
      next = { ...next, rules: [...next.rules] };
    });
    onChange(next);
    setPasteMsg(
      `Pasted ${body.length} row${body.length === 1 ? '' : 's'}, ${added} new.` +
        (unknown.size ? ` These columns are not facts or outcomes and were skipped: ${[...unknown].join(', ')}. Add them under Facts and outcomes first.` : ''),
    );
  }

  return (
    <div onPaste={onPaste} data-testid="decision-table">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
        <p className="text-xs text-slate-400 max-w-3xl">
          One row per rule. Type in a cell: <code className="text-cyan-300">&gt; 50</code>, <code className="text-cyan-300">&gt;= 2026-01-01</code>, <code className="text-cyan-300">a, b, c</code>, <code className="text-cyan-300">in EU_CBAM_CN_CODES</code>, <code className="text-cyan-300">between 1 and 5</code>. Empty means any. Outcomes starting with <code className="text-cyan-300">=</code> are calculated.
        </p>
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1 text-[11px] text-slate-500"><ClipboardPaste className="w-3.5 h-3.5" /> Paste rows from Excel</span>
          <button type="button" onClick={exportCsv} className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs text-slate-300 border border-slate-700 hover:bg-slate-800"><Download className="w-3.5 h-3.5" /> CSV</button>
        </div>
      </div>
      {pasteMsg && <p className="text-xs text-cyan-200 mb-2" role="status">{pasteMsg}</p>}
      <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/40">
        <table className="min-w-full text-left">
          <thead>
            <tr className="border-b border-slate-700 text-[11px] uppercase tracking-wide text-slate-400">
              <th className="w-8" />
              <th className="w-6 px-1">#</th>
              <th className="px-2 py-2 border-r border-slate-800">Rule</th>
              {facts.map((f) => <th key={f} className="px-2 py-2 normal-case text-xs">{doc.facts.find((x) => x.path === f)?.label || f}</th>)}
              {doc.outputs.map((o, i) => <th key={o.field} className={`px-2 py-2 normal-case text-xs text-cyan-300 ${i === 0 ? 'border-l border-slate-800' : ''}`}>{o.label || o.field}</th>)}
            </tr>
          </thead>
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={readOnly ? undefined : onDragEnd}>
            <SortableContext items={doc.rules.map((r) => r.id)} strategy={verticalListSortingStrategy}>
              <tbody className={readOnly ? 'pointer-events-none' : ''}>
                {doc.rules.map((r, i) => <Row key={r.id} rule={r} index={i} doc={doc} facts={facts} problems={problems} onRule={(x) => setRule(i, x)} readOnly={readOnly} onOpen={onOpenRule} />)}
              </tbody>
            </SortableContext>
          </DndContext>
        </table>
        {!doc.facts.length && <p className="p-4 text-sm text-slate-400">Add facts and outcomes first, then rules fill this grid.</p>}
      </div>
      {!readOnly && (
        <button type="button" onClick={addRow} className="mt-2 inline-flex items-center gap-1 text-xs text-cyan-300 hover:text-cyan-200" data-testid="table-add-row">
          <Plus className="w-3.5 h-3.5" /> Row
        </button>
      )}
    </div>
  );
}
