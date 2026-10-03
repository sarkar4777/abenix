'use client';

import { useEffect, useRef, useState } from 'react';
import { DndContext, PointerSensor, KeyboardSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core';
import { SortableContext, arrayMove, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { AlertTriangle, Copy, GripVertical, Plus, Quote, Trash2, X } from 'lucide-react';
import {
  KEY_RE,
  newRuleId,
  problemAt,
  problemsAt,
  ruleSentence,
  type Fact,
  type Outcome,
  type Problem,
  type Rule,
  type RuleDoc,
} from '@/lib/decisions';
import ConditionGroup from './ConditionGroup';
import ThenEditor from './ThenEditor';

interface Overlap { rule: string; other: string; kind: 'shadowed' | 'conflict'; message: string }

function RuleCard({ doc, rule, index, selected, onSelect, problems, overlaps, onToggle }: {
  doc: RuleDoc; rule: Rule; index: number; selected: boolean; onSelect: () => void; problems: Problem[]; overlaps: Overlap[]; onToggle: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: rule.id });
  const errs = problemsAt(problems, `/rules/${index}`).filter((p) => p.severity === 'error').length;
  const warn = overlaps.filter((o) => o.rule === (rule.key || rule.id)).length;
  return (
    <li ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.5 : 1 }}>
      <div
        role="button"
        tabIndex={0}
        onClick={onSelect}
        onKeyDown={(e) => { if (e.key === 'Enter') onSelect(); }}
        className={`group flex gap-2 rounded-lg border p-2.5 cursor-pointer transition ${selected ? 'border-cyan-500/60 bg-cyan-500/5' : 'border-slate-800 bg-slate-900/40 hover:border-slate-600'} ${rule.enabled === false ? 'opacity-60' : ''}`}
        data-testid={`rule-card-${index}`}
      >
        <button type="button" {...attributes} {...listeners} onClick={(e) => e.stopPropagation()} className="self-start p-0.5 rounded text-slate-600 hover:text-slate-300 cursor-grab" aria-label={`Drag rule ${index + 1} to reorder`}>
          <GripVertical className="w-4 h-4" />
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-slate-500 tabular-nums">{index + 1}</span>
            <span className="text-sm text-white truncate font-medium">{rule.key || rule.description || `Rule ${index + 1}`}</span>
            {errs > 0 && <span className="ml-auto text-[10px] px-1.5 rounded bg-rose-500/15 text-rose-300">{errs} to fix</span>}
            {!errs && warn > 0 && <span className="ml-auto text-[10px] px-1.5 rounded bg-amber-500/15 text-amber-300">overlap</span>}
          </div>
          <p className="text-xs text-slate-400 mt-0.5 line-clamp-3">{ruleSentence(doc, rule)}</p>
        </div>
        <label className="self-start" onClick={(e) => e.stopPropagation()} title={rule.enabled === false ? 'Off, the rule is skipped' : 'On'}>
          <input type="checkbox" checked={rule.enabled !== false} onChange={onToggle} className="accent-cyan-500" aria-label={`Rule ${index + 1} on`} />
        </label>
      </div>
    </li>
  );
}

export default function RuleBuilder({
  doc,
  onChange,
  problems,
  overlaps,
  referenceSets,
  readOnly,
  selectedId,
  onSelect,
}: {
  doc: RuleDoc;
  onChange: (d: RuleDoc) => void;
  problems: Problem[];
  overlaps: Overlap[];
  referenceSets: { key: string; name: string; count: number }[];
  readOnly: boolean;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const idx = doc.rules.findIndex((r) => r.id === selectedId);
  const rule = idx >= 0 ? doc.rules[idx] : null;
  // several updates in one event (add a fact, then use it) must build on each other, not on the stale prop
  const latest = useRef(doc);
  latest.current = doc;
  const commit = (d: RuleDoc) => {
    latest.current = d;
    onChange(d);
  };

  useEffect(() => {
    if (!rule && doc.rules.length) onSelect(doc.rules[0].id);
  }, [rule, doc.rules, onSelect]);

  const setRule = (patch: Partial<Rule>) => {
    const d = latest.current;
    commit({ ...d, rules: d.rules.map((r) => (r.id === selectedId ? { ...r, ...patch } : r)) });
  };
  const addFact = (f: Fact) => {
    const d = latest.current;
    commit({ ...d, facts: d.facts.some((x) => x.path === f.path) ? d.facts : [...d.facts, f] });
  };
  const addOutcome = (o: Outcome) => {
    const d = latest.current;
    commit({ ...d, outputs: d.outputs.some((x) => x.field === o.field) ? d.outputs : [...d.outputs, o] });
  };

  function addRule() {
    const id = newRuleId(doc);
    const r: Rule = { id, key: '', description: '', enabled: true, when: { all: [] }, then: {} };
    onChange({ ...doc, rules: [...doc.rules, r] });
    onSelect(id);
  }
  function duplicate() {
    if (!rule) return;
    const id = newRuleId(doc);
    const copy: Rule = { ...structuredClone(rule), id, key: rule.key ? `${rule.key}.copy` : '' };
    const rules = [...doc.rules];
    rules.splice(idx + 1, 0, copy);
    onChange({ ...doc, rules });
    onSelect(id);
  }
  function remove(id: string) {
    const rules = doc.rules.filter((r) => r.id !== id);
    onChange({ ...doc, rules });
    onSelect(rules[Math.max(0, idx - 1)]?.id ?? null);
    setConfirmDelete(null);
  }
  function onDragEnd(e: DragEndEvent) {
    if (!e.over || e.active.id === e.over.id) return;
    const from = doc.rules.findIndex((r) => r.id === e.active.id);
    const to = doc.rules.findIndex((r) => r.id === e.over!.id);
    onChange({ ...doc, rules: arrayMove(doc.rules, from, to) });
  }

  const at = `/rules/${idx}`;
  const keyProblem = problemAt(problems, `${at}/key`);
  const fromP = problemAt(problems, `${at}/valid_from`);
  const toP = problemAt(problems, `${at}/valid_to`);
  const myOverlaps = rule ? overlaps.filter((o) => o.rule === (rule.key || rule.id)) : [];
  const citations = rule?.provenance?.citations ?? [];

  return (
    <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
      <aside>
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs text-slate-400">
            {doc.rules.length} rule{doc.rules.length === 1 ? '' : 's'} ·{' '}
            <select
              value={doc.hit_policy}
              onChange={(e) => onChange({ ...doc, hit_policy: e.target.value as RuleDoc['hit_policy'] })}
              disabled={readOnly}
              className="bg-transparent text-cyan-300 text-xs outline-none cursor-pointer"
              aria-label="Which rules apply"
              data-testid="hit-policy"
            >
              <option value="first">first match wins</option>
              <option value="collect">every match applies</option>
            </select>
          </div>
          {!readOnly && (
            <button type="button" onClick={addRule} className="inline-flex items-center gap-1 text-xs text-cyan-300 hover:text-cyan-200" data-testid="rule-add">
              <Plus className="w-3.5 h-3.5" /> Rule
            </button>
          )}
        </div>
        <p className="text-[11px] text-slate-500 mb-2">
          {doc.hit_policy === 'first'
            ? 'Rules are checked top to bottom and the first one that matches decides. Drag to change the order.'
            : 'Every rule that matches contributes its outcome, so the result is a list.'}
        </p>
        {doc.rules.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-700 p-4 text-center">
            <p className="text-sm text-slate-300">No rules yet.</p>
            {!readOnly && <button type="button" onClick={addRule} className="mt-2 inline-flex items-center gap-1 text-sm text-cyan-300" data-testid="rule-add-first"><Plus className="w-4 h-4" /> Add the first rule</button>}
          </div>
        ) : (
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={readOnly ? undefined : onDragEnd}>
            <SortableContext items={doc.rules.map((r) => r.id)} strategy={verticalListSortingStrategy}>
              <ul className="space-y-1.5" data-testid="rule-list">
                {doc.rules.map((r, i) => (
                  <RuleCard key={r.id} doc={doc} rule={r} index={i} selected={r.id === selectedId} onSelect={() => onSelect(r.id)} problems={problems} overlaps={overlaps}
                    onToggle={() => !readOnly && onChange({ ...doc, rules: doc.rules.map((x) => (x.id === r.id ? { ...x, enabled: x.enabled === false } : x)) })} />
                ))}
              </ul>
            </SortableContext>
          </DndContext>
        )}
      </aside>

      {rule ? (
        <section className={`rounded-xl border border-slate-800 bg-slate-900/50 p-5 space-y-5 ${readOnly ? 'pointer-events-none opacity-90' : ''}`} aria-label={`Rule ${idx + 1}`} data-testid="rule-editor">
          <div className="flex flex-wrap items-start gap-3">
            <div className="flex-1 min-w-[220px]">
              <label className="block text-xs text-slate-400 mb-1" htmlFor="rule-key">Rule key</label>
              <input id="rule-key" value={rule.key || ''} onChange={(e) => setRule({ key: e.target.value })} placeholder="freight.remote.surcharge" className={`w-full bg-slate-950 border rounded-md px-2 py-1.5 text-sm text-white font-mono ${keyProblem ? 'border-rose-500/60' : 'border-slate-700'}`} data-testid="rule-key" />
              {keyProblem ? <p className="mt-0.5 text-xs text-rose-300">{keyProblem.message}</p> : rule.key && !KEY_RE.test(rule.key) ? null : <p className="mt-0.5 text-[11px] text-slate-500">Shown in results as the rule that applied.</p>}
            </div>
            <div className="flex-[2] min-w-[260px]">
              <label className="block text-xs text-slate-400 mb-1" htmlFor="rule-desc">What it means</label>
              <input id="rule-desc" value={rule.description || ''} onChange={(e) => setRule({ description: e.target.value })} placeholder="Shipments to remote postcodes above 50 kg carry a remote area surcharge" className="w-full bg-slate-950 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-white" data-testid="rule-description" />
            </div>
            {!readOnly && (
              <div className="flex items-center gap-1 pt-5">
                <button type="button" onClick={duplicate} className="p-1.5 rounded text-slate-400 hover:text-white hover:bg-slate-800" aria-label="Duplicate rule"><Copy className="w-4 h-4" /></button>
                {confirmDelete === rule.id ? (
                  <span className="inline-flex items-center gap-1 text-xs">
                    <button type="button" onClick={() => remove(rule.id)} className="px-2 py-1 rounded bg-rose-600 text-white" data-testid="rule-delete-confirm">Delete</button>
                    <button type="button" onClick={() => setConfirmDelete(null)} className="px-2 py-1 rounded text-slate-300">Keep</button>
                  </span>
                ) : (
                  <button type="button" onClick={() => setConfirmDelete(rule.id)} className="p-1.5 rounded text-slate-400 hover:text-rose-300 hover:bg-slate-800" aria-label="Delete rule" data-testid="rule-delete"><Trash2 className="w-4 h-4" /></button>
                )}
              </div>
            )}
          </div>

          <p className="text-sm text-slate-300 rounded-lg bg-slate-950/60 border border-slate-800 px-3 py-2" data-testid="rule-sentence">{ruleSentence(doc, rule)}</p>

          {myOverlaps.map((o, i) => (
            <p key={i} className={`flex gap-2 text-xs rounded-md px-3 py-2 ${o.kind === 'conflict' ? 'text-rose-200 bg-rose-500/10' : 'text-amber-200 bg-amber-500/10'}`}>
              <AlertTriangle className="w-4 h-4 shrink-0" /> {o.message}
            </p>
          ))}

          <ConditionGroup
            doc={doc}
            when={rule.when}
            onChange={(when) => setRule({ when })}
            problems={problems}
            base={`${at}/when`}
            referenceSets={referenceSets}
            onAddFact={addFact}
            testPrefix={`rule${idx}`}
          />

          <ThenEditor doc={doc} rule={rule} index={idx} onChange={(then) => setRule({ then })} onAddOutcome={addOutcome} problems={problems} testPrefix={`rule${idx}`} />

          <div className="grid gap-4 md:grid-cols-2 border-t border-slate-800 pt-4">
            <div>
              <div className="text-xs text-slate-400 mb-1">In force for this rule</div>
              <div className="flex items-center gap-2">
                <input type="date" value={rule.valid_from || ''} onChange={(e) => setRule({ valid_from: e.target.value || null })} className={`bg-slate-950 border rounded-md px-2 py-1 text-sm text-white [color-scheme:dark] ${fromP ? 'border-rose-500/60' : 'border-slate-700'}`} aria-label="Rule applies from" data-testid="rule-valid-from" />
                <span className="text-xs text-slate-500">to</span>
                <input type="date" value={rule.valid_to || ''} onChange={(e) => setRule({ valid_to: e.target.value || null })} className={`bg-slate-950 border rounded-md px-2 py-1 text-sm text-white [color-scheme:dark] ${toP ? 'border-rose-500/60' : 'border-slate-700'}`} aria-label="Rule applies until" />
              </div>
              <p className={`mt-0.5 text-[11px] ${fromP || toP ? 'text-rose-300' : 'text-slate-500'}`}>{(fromP || toP)?.message || 'Leave empty to follow the version’s own dates. The end date is not included.'}</p>
            </div>
            <div>
              <div className="text-xs text-slate-400 mb-1">Facts it needs before it can decide</div>
              <div className="flex flex-wrap gap-1">
                {doc.facts.map((f) => {
                  const on = (rule.requires || []).includes(f.path);
                  return (
                    <button key={f.path} type="button" onClick={() => setRule({ requires: on ? (rule.requires || []).filter((p) => p !== f.path) : [...(rule.requires || []), f.path] })} className={`text-[11px] px-1.5 py-0.5 rounded border ${on ? 'border-cyan-500/50 bg-cyan-500/10 text-cyan-200' : 'border-slate-700 text-slate-400 hover:text-white'}`} aria-pressed={on}>
                      {f.label || f.path}
                    </button>
                  );
                })}
              </div>
              <p className="mt-0.5 text-[11px] text-slate-500">Missing ones return “missing facts” instead of a guess.</p>
            </div>
          </div>

          <div className="border-t border-slate-800 pt-4">
            <div className="flex items-center gap-1.5 text-xs text-slate-400 mb-1"><Quote className="w-3.5 h-3.5" /> Sources</div>
            <div className="flex flex-wrap items-center gap-1.5">
              {citations.map((c, i) => (
                <span key={i} className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-200">
                  {c}
                  <button type="button" onClick={() => setRule({ provenance: { ...(rule.provenance || {}), citations: citations.filter((_, j) => j !== i) } })} aria-label={`Remove ${c}`} className="text-slate-400 hover:text-white"><X className="w-3 h-3" /></button>
                </span>
              ))}
              <input
                placeholder={citations.length ? 'Add another…' : 'Carrier tariff 2026, section 4.2'}
                onKeyDown={(e) => {
                  const v = (e.target as HTMLInputElement).value.trim();
                  if (e.key === 'Enter' && v) { setRule({ provenance: { ...(rule.provenance || {}), citations: [...citations, v] } }); (e.target as HTMLInputElement).value = ''; }
                }}
                className="flex-1 min-w-[220px] bg-slate-950 border border-slate-700 rounded-md px-2 py-1 text-xs text-white"
                aria-label="Add a source citation"
                data-testid="rule-citation"
              />
            </div>
          </div>
        </section>
      ) : (
        <div className="rounded-xl border border-dashed border-slate-700 p-8 text-center text-sm text-slate-400">Pick a rule on the left, or add one.</div>
      )}
    </div>
  );
}
