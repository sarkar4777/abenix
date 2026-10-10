'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { scrollInMain } from '@/lib/scrollInMain';
import { DndContext, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core';
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { ClipboardPaste, Columns3, Download, GripVertical, Info, Plus } from 'lucide-react';
import {
  TYPE_LABEL,
  cellsByFact,
  formatCell,
  groupItems,
  isGroup,
  newRuleId,
  parseCell,
  problemsAt,
  tableable,
  type Condition,
  type OutcomeType,
  type Problem,
  type Rule,
  type RuleDoc,
} from '@/lib/decisions';
import { OUTCOME_TYPE_LABEL, effectiveOutcomeType, outcomeType, parseThen, setOutcomeCell, thenCellText } from '@/lib/decisionValues';
import { EXTRA_COLUMNS, newColumns, planPaste, applyPaste, type PasteColumn } from '@/lib/decisionPaste';
import PasteRulesDialog, { PASTE_EXAMPLE, PastePreview, pasteProblem, pasteSummary, usePastePlan } from './PasteRules';

type Extra = (typeof EXTRA_COLUMNS)[number]['role'];
const COLS_KEY = 'abenix.decisionTable.columns';
const BEFORE: Extra[] = ['description'];
const AFTER: Extra[] = ['requires', 'sources', 'valid_from', 'valid_to'];

function setFactConditions(rule: Rule, fact: string, conds: Condition[]): Rule {
  const items = groupItems(rule.when).filter((n) => isGroup(n) || (n as Condition).fact !== fact);
  return { ...rule, when: { all: [...items, ...conds.map((c) => ({ ...c, fact }))] } };
}

function extraText(rule: Rule, role: Extra): string {
  switch (role) {
    case 'description': return rule.description || '';
    case 'requires': return (rule.requires || []).join(', ');
    case 'sources': return (rule.provenance?.citations || []).join('; ');
    case 'valid_from': return rule.valid_from || '';
    case 'valid_to': return rule.valid_to || '';
    default: return '';
  }
}

function withExtra(rule: Rule, role: Extra, v: string): Rule {
  const t = v.trim();
  switch (role) {
    case 'description': return { ...rule, description: t };
    case 'requires': return { ...rule, requires: t.split(/[\s,;]+/).filter(Boolean) };
    case 'sources': return { ...rule, provenance: { ...(rule.provenance || {}), citations: t.split(/\s*[;\n|]\s*/).filter(Boolean) } };
    case 'valid_from': return { ...rule, valid_from: t || null };
    case 'valid_to': return { ...rule, valid_to: t || null };
    default: return rule;
  }
}

const EXTRA_HINT: Record<Extra, string> = {
  description: 'a sentence',
  requires: 'fact names, comma separated',
  sources: 'separate several with ;',
  valid_from: 'YYYY-MM-DD',
  valid_to: 'YYYY-MM-DD',
};

// commits on blur or Enter whenever the person typed, even the same text again
function Cell({ text, onCommit, invalid, testId, placeholder, readOnly, label }: { text: string; onCommit: (v: string) => void; invalid?: boolean; testId?: string; placeholder?: string; readOnly?: boolean; label?: string }) {
  const [draft, setDraft] = useState<string | null>(null);
  const dirty = useRef(false);
  const done = (el: HTMLInputElement) => el.blur();
  return (
    <input
      value={draft ?? text}
      disabled={readOnly}
      onChange={(e) => { dirty.current = true; setDraft(e.target.value); }}
      onFocus={() => { dirty.current = false; setDraft(text); }}
      onBlur={() => { if (draft !== null && dirty.current) onCommit(draft); dirty.current = false; setDraft(null); }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') done(e.target as HTMLInputElement);
        if (e.key === 'Escape') { dirty.current = false; setDraft(null); done(e.target as HTMLInputElement); }
      }}
      placeholder={placeholder ?? 'any'}
      aria-label={label}
      className={`w-full min-w-[110px] bg-transparent px-2 py-1.5 text-sm text-white outline-none focus:bg-slate-950 focus:ring-1 focus:ring-cyan-500 rounded disabled:text-slate-200 ${invalid ? 'ring-1 ring-rose-500/60' : ''} placeholder:text-slate-600 placeholder:italic`}
      data-testid={testId}
    />
  );
}

function Row({ rule, index, doc, facts, before, after, problems, onRule, onDoc, readOnly, onOpen }: {
  rule: Rule; index: number; doc: RuleDoc; facts: string[]; before: Extra[]; after: Extra[]; problems: Problem[];
  onRule: (r: Rule) => void; onDoc: (d: RuleDoc) => void; readOnly: boolean; onOpen: (id: string) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: rule.id, disabled: readOnly });
  const flat = tableable(rule);
  const byFact = cellsByFact(rule);
  const errs = problemsAt(problems, `/rules/${index}`);
  const extraCell = (role: Extra) => (
    <td key={role} className="px-1 align-middle">
      <Cell text={extraText(rule, role)} onCommit={(v) => onRule(withExtra(rule, role, v))} placeholder={EXTRA_HINT[role]} readOnly={readOnly} testId={`table-${index}-${role}`} label={`${EXTRA_COLUMNS.find((c) => c.role === role)?.label} of row ${index + 1}`} invalid={errs.some((p) => p.path.includes(`/${role}`))} />
    </td>
  );
  return (
    <tr ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.5 : 1 }} className={`border-b border-slate-800 ${rule.enabled === false ? 'opacity-50' : ''}`} data-testid={`table-row-${index}`}>
      <td className="px-1 align-middle">
        {!readOnly && <button type="button" {...attributes} {...listeners} className="p-1 text-slate-600 hover:text-slate-300 cursor-grab" aria-label={`Drag row ${index + 1}`}><GripVertical className="w-4 h-4" /></button>}
      </td>
      <td className="px-1 text-[11px] text-slate-500 tabular-nums">{index + 1}</td>
      <td className="px-1 border-r border-slate-800">
        <Cell text={rule.key || ''} onCommit={(v) => onRule({ ...rule, key: v.trim() })} placeholder="rule key" testId={`table-${index}-key`} readOnly={readOnly} label={`Rule key of row ${index + 1}`} invalid={errs.some((p) => p.path.endsWith('/key'))} />
      </td>
      {before.map(extraCell)}
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
                readOnly={readOnly}
                label={`${f} in row ${index + 1}`}
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
      {doc.outputs.map((o, oi) => {
        const type = effectiveOutcomeType(doc, o);
        return (
          <td key={o.field} className={`px-1 ${oi === 0 ? 'border-l border-slate-800' : ''}`}>
            <Cell
              text={thenCellText(rule.then?.[o.field])}
              onCommit={(v) => onDoc(setOutcomeCell(doc, rule.id, o.field, parseThen(v, type)))}
              placeholder="not set"
              readOnly={readOnly}
              label={`${o.field} in row ${index + 1}`}
              invalid={errs.some((p) => p.path.startsWith(`/rules/${index}/then/${o.field}`))}
              testId={`table-${index}-out-${o.field}`}
            />
          </td>
        );
      })}
      {after.map(extraCell)}
    </tr>
  );
}

function readCols(): Extra[] {
  try {
    const v = JSON.parse(localStorage.getItem(COLS_KEY) || '[]');
    return Array.isArray(v) ? v.filter((x) => EXTRA_COLUMNS.some((c) => c.role === x)) : [];
  } catch { return []; }
}

// an empty decision starts from a paste: the header row names the facts and outcomes
function PasteFirst({ doc, defaults, onApply, focus }: { doc: RuleDoc; defaults: PasteColumn[]; onApply: (d: RuleDoc, msg: string) => void; focus: number }) {
  const { text, setText, plan, setPlan } = usePastePlan(doc, defaults);
  const box = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (!focus) return;
    const t = setTimeout(() => { scrollInMain(box.current, 'center'); box.current?.focus({ preventScroll: true }); }, 60);
    return () => clearTimeout(t);
  }, [focus]);
  const problem = pasteProblem(plan, doc);
  return (
    <div className="rounded-xl border border-dashed border-cyan-500/40 bg-cyan-500/5 p-4 space-y-3" data-testid="paste-first">
      <div className="flex items-center gap-2 text-sm font-medium text-white"><ClipboardPaste className="w-4 h-4 text-cyan-400" /> Paste your rules from Excel</div>
      <p className="text-xs text-slate-400 max-w-3xl">
        Copy the rows with their header row and paste them below. The header names each column: <code className="text-cyan-300">rule</code> for the rule key, a fact name for a condition, and an outcome name for the answer.
        Conditions are written like <code className="text-cyan-300">&gt;= 2</code>, <code className="text-cyan-300">&lt; 4</code> or <code className="text-cyan-300">between 1 and 5</code>.
        Optional columns: description, sources, facts needed, valid from, valid to.
      </p>
      <textarea
        ref={box}
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={5}
        spellCheck={false}
        placeholder={'Paste here. For example:\n' + PASTE_EXAMPLE.replace(/\t/g, '    ')}
        className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-xs text-slate-200 font-mono placeholder:text-slate-600"
        aria-label="Rows to paste"
        data-testid="paste-first-text"
      />
      {plan && <PastePreview plan={plan} onPlan={setPlan} />}
      {problem && <p className="text-xs text-rose-300" role="alert">{problem}</p>}
      {plan && !problem && (
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" onClick={() => { const r = applyPaste(doc, plan); onApply(r.doc, `Added ${r.added} rule${r.added === 1 ? '' : 's'} from the paste.`); setText(''); }} className="px-3 py-1.5 rounded-md text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400" data-testid="paste-first-apply">
            Add {pasteSummary(plan)}
          </button>
          <span className="text-[11px] text-slate-500">Nothing is saved until you press it.</span>
        </div>
      )}
    </div>
  );
}

export default function DecisionTable({ doc, onChange, problems, readOnly, onOpenRule, focusPaste = 0 }: {
  doc: RuleDoc; onChange: (d: RuleDoc) => void; problems: Problem[]; readOnly: boolean; onOpenRule: (id: string) => void; focusPaste?: number;
}) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));
  const [pasteMsg, setPasteMsg] = useState<string | null>(null);
  const [extras, setExtras] = useState<Extra[]>([]);
  const [colsOpen, setColsOpen] = useState(false);
  const [pasteOpen, setPasteOpen] = useState<null | { text: string }>(null);
  useEffect(() => setExtras(readCols()), []);
  const emptyNow = !doc.facts.length && !doc.outputs.length && !doc.rules.length;
  // asked to paste with rules already there: open the paste dialog instead
  useEffect(() => {
    if (focusPaste && !readOnly && !emptyNow) setPasteOpen({ text: '' });
    // only a new request opens it, not every render
  }, [focusPaste]);
  const facts = useMemo(() => doc.facts.map((f) => f.path), [doc.facts]);
  const before = BEFORE.filter((r) => extras.includes(r));
  const after = AFTER.filter((r) => extras.includes(r));
  const defaults: PasteColumn[] = useMemo(() => [
    { header: 'rule', role: 'rule', target: '', type: 'string', exists: true },
    ...before.map((r): PasteColumn => ({ header: r, role: r, target: '', type: 'string', exists: true })),
    ...doc.facts.map((f): PasteColumn => ({ header: f.path, role: 'fact', target: f.path, type: f.type, exists: true })),
    ...doc.outputs.map((o): PasteColumn => ({ header: o.field, role: 'outcome', target: o.field, type: outcomeType(o), exists: true })),
    ...after.map((r): PasteColumn => ({ header: r, role: r, target: '', type: 'string', exists: true })),
  ], [doc.facts, doc.outputs, before.join(','), after.join(',')]);

  function toggleCol(r: Extra) {
    const next = extras.includes(r) ? extras.filter((x) => x !== r) : [...extras, r];
    setExtras(next);
    try { localStorage.setItem(COLS_KEY, JSON.stringify(next)); } catch { /* storage off */ }
  }

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
    const header = ['rule', ...before, ...facts, ...doc.outputs.map((o) => o.field), ...after];
    const lines = [header.join(',')];
    for (const r of doc.rules) {
      const by = cellsByFact(r);
      lines.push([r.key || r.id, ...before.map((x) => extraText(r, x)), ...facts.map((f) => formatCell(by[f] || [])), ...doc.outputs.map((o) => thenCellText(r.then?.[o.field])), ...after.map((x) => extraText(r, x))].map((x) => esc(String(x))).join(','));
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'rules.csv';
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function applied(d: RuleDoc, msg: string) {
    onChange(d);
    setPasteMsg(msg);
    setPasteOpen(null);
  }

  // a block pasted straight onto the table is always shown for a check before anything changes
  function onPaste(e: React.ClipboardEvent) {
    if (readOnly) return;
    const text = e.clipboardData.getData('text');
    if (!text.includes('\t') && !text.includes('\n')) return;
    e.preventDefault();
    setPasteOpen({ text });
  }

  const empty = !doc.facts.length && !doc.outputs.length && !doc.rules.length;
  const colCount = 3 + before.length + facts.length + doc.outputs.length + after.length;

  return (
    <div onPaste={empty ? undefined : onPaste} data-testid="decision-table">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
        <p className="text-xs text-slate-400 max-w-3xl">
          One row per rule. In a fact column type a condition: <code className="text-cyan-300">&gt; 50</code>, <code className="text-cyan-300">&gt;= 2026-01-01</code>, <code className="text-cyan-300">a, b, c</code>, <code className="text-cyan-300">between 1 and 5</code>, <code className="text-cyan-300">in SET_NAME</code>. Empty means any.
          In an outcome column type the answer, <code className="text-cyan-300">=</code> to calculate it, or <code className="text-cyan-300">&quot;&quot;</code> for empty text. A blank outcome is not set.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {!readOnly && !empty && (
            <button type="button" onClick={() => setPasteOpen({ text: '' })} className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs text-cyan-300 border border-slate-700 hover:bg-slate-800" data-testid="table-paste-open">
              <ClipboardPaste className="w-3.5 h-3.5" /> Paste from Excel
            </button>
          )}
          <div className="relative">
            <button type="button" onClick={() => setColsOpen((o) => !o)} aria-expanded={colsOpen} className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs text-slate-300 border border-slate-700 hover:bg-slate-800" data-testid="table-columns">
              <Columns3 className="w-3.5 h-3.5" /> Columns{extras.length ? ` (+${extras.length})` : ''}
            </button>
            {colsOpen && (
              <div className="absolute right-0 z-30 mt-1 w-56 rounded-lg border border-slate-700 bg-slate-900 shadow-xl p-2 space-y-1" data-testid="table-columns-menu">
                <p className="px-1 text-[11px] text-slate-500">Show more of each rule in the table.</p>
                {EXTRA_COLUMNS.map((c) => (
                  <label key={c.role} className="flex items-center gap-2 px-1 py-0.5 text-xs text-slate-200 cursor-pointer">
                    <input type="checkbox" checked={extras.includes(c.role)} onChange={() => toggleCol(c.role)} className="accent-cyan-500" data-testid={`table-col-${c.role}`} /> {c.label}
                  </label>
                ))}
              </div>
            )}
          </div>
          <button type="button" onClick={exportCsv} disabled={!doc.rules.length} className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs text-slate-300 border border-slate-700 hover:bg-slate-800 disabled:opacity-40"><Download className="w-3.5 h-3.5" /> CSV</button>
        </div>
      </div>
      {pasteMsg && <p className="text-xs text-cyan-200 mb-2" role="status" data-testid="table-paste-msg">{pasteMsg}</p>}
      {empty && !readOnly ? (
        <PasteFirst doc={doc} defaults={defaults} onApply={(d, msg) => applied(d, msg)} focus={focusPaste} />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/40">
          <table className="min-w-full text-left">
            <thead>
              <tr className="border-b border-slate-700 text-[11px] uppercase tracking-wide text-slate-400">
                <th className="w-8" />
                <th className="w-6 px-1">#</th>
                <th className="px-2 py-2 border-r border-slate-800">Rule</th>
                {before.map((r) => <th key={r} className="px-2 py-2 normal-case text-xs">{EXTRA_COLUMNS.find((c) => c.role === r)?.label}</th>)}
                {facts.map((f) => {
                  const fact = doc.facts.find((x) => x.path === f)!;
                  return <th key={f} className="px-2 py-2 normal-case text-xs" title={`${f}, ${TYPE_LABEL[fact.type]}`}>{fact.label || f}<span className="block text-[10px] font-normal text-slate-500">{TYPE_LABEL[fact.type]}</span></th>;
                })}
                {doc.outputs.map((o, i) => (
                  <th key={o.field} className={`px-2 py-2 normal-case text-xs text-cyan-300 ${i === 0 ? 'border-l border-slate-800' : ''}`} title={o.field}>
                    {o.label || o.field}<span className="block text-[10px] font-normal text-cyan-300/60">{OUTCOME_TYPE_LABEL[effectiveOutcomeType(doc, o) as OutcomeType]}</span>
                  </th>
                ))}
                {after.map((r) => <th key={r} className="px-2 py-2 normal-case text-xs">{EXTRA_COLUMNS.find((c) => c.role === r)?.label}</th>)}
              </tr>
            </thead>
            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={readOnly ? undefined : onDragEnd}>
              <SortableContext items={doc.rules.map((r) => r.id)} strategy={verticalListSortingStrategy}>
                <tbody>
                  {doc.rules.map((r, i) => <Row key={r.id} rule={r} index={i} doc={doc} facts={facts} before={before} after={after} problems={problems} onRule={(x) => setRule(i, x)} onDoc={onChange} readOnly={readOnly} onOpen={onOpenRule} />)}
                  {!doc.rules.length && (
                    <tr><td colSpan={colCount} className="px-4 py-3 text-sm text-slate-400">{readOnly ? 'This version has no rules.' : 'No rules yet. Add a row, or paste rows from Excel.'}</td></tr>
                  )}
                </tbody>
              </SortableContext>
            </DndContext>
          </table>
        </div>
      )}
      {!readOnly && !empty && (
        <button type="button" onClick={addRow} className="mt-2 inline-flex items-center gap-1 text-xs text-cyan-300 hover:text-cyan-200" data-testid="table-add-row">
          <Plus className="w-3.5 h-3.5" /> Row
        </button>
      )}
      {pasteOpen && <PasteRulesDialog doc={doc} defaults={defaults} initialText={pasteOpen.text} onApply={applied} onClose={() => setPasteOpen(null)} />}
    </div>
  );
}
