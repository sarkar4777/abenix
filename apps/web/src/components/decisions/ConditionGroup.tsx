'use client';

import { useMemo, useState } from 'react';
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core';
import { SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { FolderPlus, GripVertical, Plus, Trash2 } from 'lucide-react';
import {
  OPERATORS,
  TYPE_LABEL,
  conditionText,
  defaultOp,
  groupItems,
  groupKind,
  isGroup,
  opsFor,
  problemAt,
  withItems,
  type Condition,
  type Fact,
  type FactType,
  type Group,
  type Node,
  type Problem,
  type RuleDoc,
} from '@/lib/decisions';
import { numberDraft } from '@/lib/decisionValues';
import FactPicker from './FactPicker';
import ValueInput from './ValueInput';

type Path = number[];
const idOf = (p: Path) => `n:${p.join('.')}`;
const parseId = (id: string): Path => (id === 'n:' ? [] : id.slice(2).split('.').map(Number));

function getAt(root: Group, path: Path): Node {
  let cur: Node = root;
  for (const i of path) cur = groupItems(cur as Group)[i];
  return cur;
}

function replaceAt(root: Group, path: Path, fn: (n: Node) => Node | null): Group {
  if (!path.length) return fn(root) as Group;
  const [head, ...rest] = path;
  const items = [...groupItems(root)];
  if (rest.length) items[head] = replaceAt(items[head] as Group, rest, fn);
  else {
    const out = fn(items[head]);
    if (out === null) items.splice(head, 1);
    else items[head] = out;
  }
  return withItems(root, items);
}

function insertAt(root: Group, groupPath: Path, index: number, node: Node): Group {
  return replaceAt(root, groupPath, (g) => {
    const items = [...groupItems(g as Group)];
    items.splice(Math.max(0, Math.min(index, items.length)), 0, node);
    return withItems(g as Group, items);
  });
}

function isPrefix(a: Path, b: Path) {
  return a.length <= b.length && a.every((v, i) => b[i] === v);
}

export function moveNode(root: Group, from: Path, toGroup: Path, toIndex: number): Group {
  if (isPrefix(from, toGroup)) return root;
  const node = getAt(root, from);
  let next = replaceAt(root, from, () => null);
  // removing an earlier sibling shifts the target group path and index
  const adj = [...toGroup];
  const fromParent = from.slice(0, -1);
  const fromIdx = from[from.length - 1];
  if (fromParent.length < adj.length && isPrefix(fromParent, adj.slice(0, fromParent.length)) && adj[fromParent.length] > fromIdx) {
    adj[fromParent.length] -= 1;
  }
  let idx = toIndex;
  if (fromParent.join('.') === adj.join('.') && fromIdx < toIndex) idx -= 1;
  next = insertAt(next, adj, idx, node);
  return next;
}

interface Ctx {
  doc: RuleDoc;
  problems: Problem[];
  base: string;
  referenceSets: { key: string; name: string; count: number }[];
  onAddFact: (f: Fact) => void;
  onFactType: (path: string, type: FactType) => void;
  set: (path: Path, fn: (n: Node) => Node | null) => void;
  add: (groupPath: Path, node: Node) => void;
  testPrefix: string;
  readOnly: boolean;
}

function pathStr(ctx: Ctx, root: Group, path: Path): string {
  let s = ctx.base;
  let cur: Group = root;
  for (const i of path) {
    s += `/${groupKind(cur)}/${i}`;
    const n = groupItems(cur)[i];
    if (isGroup(n)) cur = n;
  }
  return s;
}

function Row({ ctx, root, path, cond }: { ctx: Ctx; root: Group; path: Path; cond: Condition }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: idOf(path) });
  const fact = ctx.doc.facts.find((f) => f.path === cond.fact);
  // a fact added a moment ago is not in this render's doc yet, so trust the operator's type
  const type = fact?.type ?? (OPERATORS[cond.op]?.types.length === 1 ? OPERATORS[cond.op].types[0] : 'string');
  const at = pathStr(ctx, root, path);
  const pFact = problemAt(ctx.problems, `${at}/fact`);
  const pOp = problemAt(ctx.problems, `${at}/op`);
  const pVal = problemAt(ctx.problems, `${at}/value`) || problemAt(ctx.problems, `${at}/values`) || problemAt(ctx.problems, `${at}/set`);
  const msg = pFact || pOp || pVal;
  const tid = `${ctx.testPrefix}-c${path.join('-')}`;
  const ro = ctx.readOnly;
  const looksNumeric = type === 'string' && !!fact && [cond.value, ...(cond.values || [])].some((v) => v !== undefined && v !== '' && numberDraft(String(v)).kind === 'number');

  return (
    <div ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.4 : 1 }} className="group/row">
      <div className="flex flex-wrap items-center gap-1.5">
        {ro ? <span className="w-6" /> : (
          <button type="button" {...attributes} {...listeners} className="p-1 rounded text-slate-600 hover:text-slate-300 cursor-grab active:cursor-grabbing" aria-label="Drag to move this condition">
            <GripVertical className="w-4 h-4" />
          </button>
        )}
        <div className="flex-1 min-w-[160px] sm:flex-none">
        <FactPicker
          facts={ctx.doc.facts}
          value={cond.fact}
          onChange={(p, newType) => {
            const t = newType ?? ctx.doc.facts.find((f) => f.path === p)?.type ?? 'string';
            const keep = OPERATORS[cond.op]?.types.includes(t);
            ctx.set(path, () => (keep ? { ...cond, fact: p } : { fact: p, op: defaultOp(t) }));
          }}
          onAddFact={ctx.onAddFact}
          onFactType={ctx.onFactType}
          invalid={!!pFact}
          testId={`${tid}-fact`}
          readOnly={ro}
        />
        </div>
        {fact && !ro && (
          <select
            value={fact.type}
            onChange={(e) => ctx.onFactType(fact.path, e.target.value as FactType)}
            className="bg-slate-950 border border-slate-700 rounded-md px-1.5 py-1.5 text-xs text-slate-300"
            aria-label={`Type of ${fact.path}`}
            title="What kind of value this fact holds. Changing it here changes it everywhere."
            data-testid={`${tid}-type`}
          >
            {(Object.keys(TYPE_LABEL) as FactType[]).map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
          </select>
        )}
        <select
          disabled={ro}
          value={cond.op}
          onChange={(e) => {
            const op = e.target.value;
            const shape = OPERATORS[op]?.shape;
            const nxt: Condition = { fact: cond.fact, op };
            if (shape === 'one') nxt.value = cond.value ?? cond.values?.[0];
            if (shape === 'two') nxt.values = cond.values?.slice(0, 2) ?? (cond.value !== undefined ? [cond.value] : []);
            if (shape === 'many') nxt.values = cond.values ?? (cond.value !== undefined && cond.value !== '' ? [cond.value] : []);
            if (shape === 'set') nxt.set = cond.set;
            ctx.set(path, () => nxt);
          }}
          className={`bg-slate-950 border rounded-md px-2 py-1.5 text-sm text-white ${pOp ? 'border-rose-500/60' : 'border-slate-700'}`}
          aria-label="Comparison"
          data-testid={`${tid}-op`}
        >
          {!OPERATORS[cond.op] && <option value="">Pick a comparison</option>}
          {opsFor(type).map((op) => <option key={op} value={op}>{OPERATORS[op].label}</option>)}
          {type === 'string' && <option disabled value="__number">more than, less than: switch to Number to compare amounts</option>}
        </select>
        <ValueInput cond={cond} type={type} onChange={(patch) => ctx.set(path, () => ({ ...cond, ...patch }))} invalid={!!pVal} referenceSets={ctx.referenceSets} testId={`${tid}-value`} readOnly={ro} />
        {!ro && (
          <button type="button" onClick={() => ctx.set(path, () => null)} className="p-1 rounded text-slate-600 hover:text-rose-300 opacity-60 group-hover/row:opacity-100" aria-label="Remove this condition" data-testid={`${tid}-remove`}>
            <Trash2 className="w-4 h-4" />
          </button>
        )}
      </div>
      {msg && <p className="ml-7 mt-0.5 text-xs text-rose-300" role="alert">{msg.message}</p>}
      {!msg && looksNumeric && !ro && (
        <p className="ml-7 mt-0.5 text-xs text-amber-200" data-testid={`${tid}-text-hint`}>
          {fact!.label || fact!.path} is Text, so this compares words, not amounts. Switch to Number to compare amounts.{' '}
          <button type="button" onClick={() => ctx.onFactType(fact!.path, 'number')} className="text-cyan-300 underline hover:text-cyan-200">Switch to Number</button>
        </p>
      )}
    </div>
  );
}

function GroupBox({ ctx, root, path, group, depth }: { ctx: Ctx; root: Group; path: Path; group: Group; depth: number }) {
  const sortable = useSortable({ id: idOf(path), disabled: depth === 0 });
  const { setNodeRef: dropRef, isOver } = useDroppable({ id: `g:${path.join('.')}` });
  const items = groupItems(group);
  const kind = groupKind(group);
  const mode = group.negate ? 'none' : kind;
  const ids = items.map((_, i) => idOf([...path, i]));
  const at = pathStr(ctx, root, path);
  const empty = problemAt(ctx.problems, `${at}/${kind}`);
  // a new condition starts on a fact this group does not test yet, so it is not a copy of the last one
  const usedHere = new Set(items.filter((n) => !isGroup(n)).map((n) => (n as Condition).fact));
  const firstFact = ctx.doc.facts.find((f) => !usedHere.has(f.path));

  function setMode(m: 'all' | 'any' | 'none') {
    ctx.set(path, (g) => {
      const its = groupItems(g as Group);
      const out: Group = m === 'any' ? { any: its } : { all: its };
      if (m === 'none') { out.any = its; delete out.all; out.negate = true; }
      return out;
    });
  }

  const label = depth === 0 ? (mode === 'all' ? 'all of these are true' : mode === 'any' ? 'any of these is true' : 'none of these is true') : mode === 'all' ? 'all of' : mode === 'any' ? 'any of' : 'none of';

  return (
    <div
      ref={depth === 0 ? undefined : sortable.setNodeRef}
      style={depth === 0 ? undefined : { transform: CSS.Transform.toString(sortable.transform), transition: sortable.transition, opacity: sortable.isDragging ? 0.4 : 1 }}
      className={depth === 0 ? '' : 'rounded-lg border border-slate-700/80 bg-slate-950/40 pl-1 pr-2 py-2'}
    >
      <div className="flex items-center gap-1.5 mb-2">
        {depth > 0 && !ctx.readOnly && (
          <button type="button" {...sortable.attributes} {...sortable.listeners} className="p-1 rounded text-slate-600 hover:text-slate-300 cursor-grab" aria-label="Drag to move this group">
            <GripVertical className="w-4 h-4" />
          </button>
        )}
        <span className="text-xs text-slate-400">{depth === 0 ? 'When' : ''}</span>
        <select value={mode} disabled={ctx.readOnly} onChange={(e) => setMode(e.target.value as any)} className="bg-slate-900 border border-slate-700 rounded px-1.5 py-1 text-xs text-white" aria-label="How the conditions combine" data-testid={`${ctx.testPrefix}-g${path.join('-')}-mode`}>
          <option value="all">{depth === 0 ? 'all of these are true' : 'all of'}</option>
          <option value="any">{depth === 0 ? 'any of these is true' : 'any of'}</option>
          <option value="none">{depth === 0 ? 'none of these is true' : 'none of'}</option>
        </select>
        {depth === 0 && !items.length && <span className="text-xs text-slate-500">No conditions, so this rule always applies. Useful as a default at the end.</span>}
        {depth > 0 && !ctx.readOnly && (
          <button type="button" onClick={() => ctx.set(path, () => null)} className="ml-auto p-1 rounded text-slate-600 hover:text-rose-300" aria-label="Remove this group">
            <Trash2 className="w-4 h-4" />
          </button>
        )}
        <span className="sr-only">{label}</span>
      </div>
      <div ref={dropRef} className={`space-y-1.5 ${depth > 0 ? 'pl-4 border-l border-slate-700/60 ml-3' : ''} ${isOver && !items.length ? 'rounded bg-cyan-500/5 min-h-[36px]' : ''}`}>
        <SortableContext items={ids} strategy={verticalListSortingStrategy}>
          {items.map((n, i) =>
            isGroup(n) ? (
              <GroupBox key={idOf([...path, i])} ctx={ctx} root={root} path={[...path, i]} group={n} depth={depth + 1} />
            ) : (
              <Row key={idOf([...path, i])} ctx={ctx} root={root} path={[...path, i]} cond={n} />
            ),
          )}
        </SortableContext>
        {!items.length && depth > 0 && !ctx.readOnly && <p className="text-xs text-slate-500 py-1">Drop a condition here, or add one.</p>}
        {empty && <p className="text-xs text-rose-300" role="alert">{empty.message}</p>}
        {!ctx.readOnly && <div className="flex items-center gap-2 pt-1">
          <button
            type="button"
            onClick={() => ctx.add(path, firstFact ? { fact: firstFact.path, op: defaultOp(firstFact.type) } : { fact: '', op: 'eq' })}
            className="inline-flex items-center gap-1 text-xs text-cyan-300 hover:text-cyan-200"
            data-testid={`${ctx.testPrefix}-g${path.join('-')}-add`}
          >
            <Plus className="w-3.5 h-3.5" /> Condition
          </button>
          {depth < 5 && (
            <button type="button" onClick={() => ctx.add(path, { any: [] })} className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-white" data-testid={`${ctx.testPrefix}-g${path.join('-')}-addgroup`}>
              <FolderPlus className="w-3.5 h-3.5" /> Group
            </button>
          )}
        </div>}
      </div>
    </div>
  );
}

export default function ConditionGroup({
  doc,
  when,
  onChange,
  problems,
  base,
  referenceSets,
  onAddFact,
  onFactType,
  testPrefix,
  readOnly = false,
}: {
  doc: RuleDoc;
  when: Group;
  onChange: (g: Group) => void;
  problems: Problem[];
  base: string;
  referenceSets: { key: string; name: string; count: number }[];
  onAddFact: (f: Fact) => void;
  onFactType: (path: string, type: FactType) => void;
  testPrefix: string;
  readOnly?: boolean;
}) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));
  const [dragging, setDragging] = useState<Path | null>(null);
  const ctx: Ctx = useMemo(
    () => ({
      doc,
      problems,
      base,
      referenceSets,
      onAddFact,
      onFactType,
      testPrefix,
      readOnly,
      set: (path, fn) => { if (!readOnly) onChange(replaceAt(when, path, fn)); },
      add: (groupPath, node) => { if (!readOnly) onChange(insertAt(when, groupPath, 1e9, node)); },
    }),
    [doc, problems, base, referenceSets, onAddFact, onFactType, onChange, when, testPrefix, readOnly],
  );

  function onDragStart(e: DragStartEvent) {
    setDragging(parseId(String(e.active.id)));
  }

  function onDragEnd(e: DragEndEvent) {
    setDragging(null);
    if (!e.over) return;
    const from = parseId(String(e.active.id));
    const overId = String(e.over.id);
    if (overId === String(e.active.id)) return;
    if (overId.startsWith('g:')) {
      const g = overId === 'g:' ? [] : overId.slice(2).split('.').map(Number);
      const target = getAt(when, g);
      onChange(moveNode(when, from, g, groupItems(target as Group).length));
      return;
    }
    const to = parseId(overId);
    const overNode = getAt(when, to);
    // dropping on a group's header moves into it, on a condition takes its place
    if (isGroup(overNode) && !isPrefix(from, to) && from.slice(0, -1).join('.') !== to.slice(0, -1).join('.')) {
      onChange(moveNode(when, from, to, groupItems(overNode).length));
      return;
    }
    onChange(moveNode(when, from, to.slice(0, -1), to[to.length - 1] + (from.slice(0, -1).join('.') === to.slice(0, -1).join('.') && from[from.length - 1] < to[to.length - 1] ? 1 : 0)));
  }

  const ghost = dragging ? getAt(when, dragging) : null;

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragStart={readOnly ? undefined : onDragStart} onDragEnd={readOnly ? undefined : onDragEnd} onDragCancel={() => setDragging(null)}>
      <GroupBox ctx={ctx} root={when} path={[]} group={when} depth={0} />
      <DragOverlay>
        {ghost && (
          <div className="rounded-md border border-cyan-500/50 bg-slate-900 px-3 py-1.5 text-sm text-white shadow-xl">
            {isGroup(ghost) ? `Group of ${groupItems(ghost).length}` : conditionText(doc, ghost)}
          </div>
        )}
      </DragOverlay>
    </DndContext>
  );
}
