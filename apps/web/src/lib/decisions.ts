// Types and helpers shared by the decision screens. Mirrors engine/decisions/authoring.py.

export type FactType = 'string' | 'number' | 'boolean' | 'date' | 'list';
export type Shape = 'one' | 'two' | 'many' | 'set' | 'none';
export type Tier = 'low' | 'medium' | 'high' | 'critical';

export interface Fact { path: string; type: FactType; label?: string; required?: boolean }
export interface Outcome { field: string; type?: string; label?: string }
export interface Condition { fact: string; op: string; value?: any; values?: any[]; set?: string }
export interface Group { all?: Node[]; any?: Node[]; negate?: boolean }
export type Node = Condition | Group;
export type ThenCell = { value?: any; formula?: string; _as?: string };
export interface Rule {
  id: string;
  key?: string;
  description?: string;
  enabled?: boolean;
  requires?: string[];
  when: Group;
  then: Record<string, ThenCell>;
  valid_from?: string | null;
  valid_to?: string | null;
  provenance?: { sourceSnapshotId?: string; citations?: string[]; [k: string]: any } | null;
  meta?: Record<string, any>;
}
export interface RuleDoc {
  kind: 'rules';
  hit_policy: 'first' | 'collect';
  facts: Fact[];
  outputs: Outcome[];
  rules: Rule[];
}
export interface Problem { path: string; message: string; severity: 'error' | 'warning'; code: string }

export interface VersionSummary {
  id: string;
  version: number;
  state: 'draft' | 'proposed' | 'approved' | 'rejected' | 'published' | 'superseded' | 'retired';
  content_hash: string;
  valid_from: string | null;
  valid_to: string | null;
  recorded_at: string | null;
  published_at: string | null;
  superseded_at: string | null;
  change_note: string;
  approval_id: string | null;
  has_builder: boolean;
  etag: string;
  updated_at: string | null;
}
export interface VersionFull extends VersionSummary {
  authoring: RuleDoc | null;
  content: any;
  required_facts: string[];
  fact_types: Record<string, FactType>;
  provenance: any;
  validation: Validation | null;
  editing_now: { user_id: string; email: string; at: string }[];
}
export interface Validation {
  ok: boolean;
  summary: string;
  problems: Problem[];
  overlaps: { rule: string; other: string; kind: 'shadowed' | 'conflict'; message: string; example: any; fields?: string[] }[];
  tests: TestResult[];
  tests_failed: number;
  changes: { source: string; name: string; facts: any; before: any; after: any }[];
}
export interface TestResult {
  test_id: string; name: string; passed: boolean; expected_outcome: string; expected: any;
  outcome: string; result: any; missing_facts: string[]; invalid_facts: any[]; applied_rules: string[];
}
export interface Evaluation {
  outcome: 'decided' | 'no_match' | 'missing_facts' | 'invalid_facts' | 'not_ready';
  result: any;
  applied_rules: string[];
  missing_facts: string[];
  invalid_facts: { fact: string; expected: string; got: string; value: string }[];
  normalised: { fact: string; from: any; to: any }[];
  trace: { node: string; rule_id: string; description: string; values_seen: Record<string, any> }[];
  trace_hash: string;
  duration_us: number;
  problems?: Problem[];
}

export const OPERATORS: Record<string, { label: string; types: FactType[]; shape: Shape }> = {
  eq: { label: 'is', types: ['string', 'number', 'boolean', 'date'], shape: 'one' },
  neq: { label: 'is not', types: ['string', 'number', 'boolean', 'date'], shape: 'one' },
  gt: { label: 'is more than', types: ['number'], shape: 'one' },
  gte: { label: 'is at least', types: ['number'], shape: 'one' },
  lt: { label: 'is less than', types: ['number'], shape: 'one' },
  lte: { label: 'is at most', types: ['number'], shape: 'one' },
  after: { label: 'is after', types: ['date'], shape: 'one' },
  on_or_after: { label: 'is on or after', types: ['date'], shape: 'one' },
  before: { label: 'is before', types: ['date'], shape: 'one' },
  on_or_before: { label: 'is on or before', types: ['date'], shape: 'one' },
  between: { label: 'is between', types: ['number', 'date'], shape: 'two' },
  in: { label: 'is one of', types: ['string', 'number'], shape: 'many' },
  not_in: { label: 'is none of', types: ['string', 'number'], shape: 'many' },
  in_reference_set: { label: 'is in reference set', types: ['string', 'number'], shape: 'set' },
  not_in_reference_set: { label: 'is not in reference set', types: ['string', 'number'], shape: 'set' },
  contains: { label: 'contains', types: ['string', 'list'], shape: 'one' },
  not_contains: { label: 'does not contain', types: ['string', 'list'], shape: 'one' },
  starts_with: { label: 'starts with', types: ['string'], shape: 'one' },
  ends_with: { label: 'ends with', types: ['string'], shape: 'one' },
  is_true: { label: 'is true', types: ['boolean'], shape: 'none' },
  is_false: { label: 'is false', types: ['boolean'], shape: 'none' },
  is_set: { label: 'has a value', types: ['string', 'number', 'boolean', 'date', 'list'], shape: 'none' },
  is_not_set: { label: 'has no value', types: ['string', 'number', 'boolean', 'date', 'list'], shape: 'none' },
};

export const TYPE_LABEL: Record<FactType, string> = {
  string: 'Text', number: 'Number', boolean: 'Yes / no', date: 'Date', list: 'List',
};

export const PATH_RE = /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$/;
export const KEY_RE = /^[a-z0-9][a-z0-9._-]{0,159}$/;
export const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export function opsFor(type: FactType): string[] {
  return Object.entries(OPERATORS).filter(([, o]) => o.types.includes(type)).map(([k]) => k);
}

export function defaultOp(type: FactType): string {
  return { string: 'eq', number: 'gt', boolean: 'is_true', date: 'on_or_after', list: 'contains' }[type];
}

export function isGroup(n: Node): n is Group {
  return !!n && typeof n === 'object' && ('all' in n || 'any' in n);
}

export function groupItems(g: Group): Node[] {
  return (g.all ?? g.any ?? []) as Node[];
}

export function groupKind(g: Group): 'all' | 'any' {
  return 'any' in g && g.any !== undefined ? 'any' : 'all';
}

export function withItems(g: Group, items: Node[]): Group {
  const kind = groupKind(g);
  const out: Group = { [kind]: items } as Group;
  if (g.negate) out.negate = true;
  return out;
}

export function newRuleId(doc: RuleDoc): string {
  const used = new Set(doc.rules.map((r) => r.id));
  let i = doc.rules.length + 1;
  while (used.has(`r${i}`)) i++;
  return `r${i}`;
}

export function emptyDoc(): RuleDoc {
  return { kind: 'rules', hit_policy: 'first', facts: [], outputs: [], rules: [] };
}

export function factLabel(doc: RuleDoc, path: string): string {
  return doc.facts.find((f) => f.path === path)?.label || path;
}

function fmtValue(v: any): string {
  if (v === null || v === undefined || v === '') return '…';
  if (typeof v === 'string') return `“${v}”`;
  return String(v);
}

export function conditionText(doc: RuleDoc, c: Condition): string {
  const op = OPERATORS[c.op];
  const f = factLabel(doc, c.fact || '…');
  if (!op) return `${f} …`;
  switch (op.shape) {
    case 'one': return `${f} ${op.label} ${fmtValue(c.value)}`;
    case 'two': return `${f} ${op.label} ${fmtValue(c.values?.[0])} and ${fmtValue(c.values?.[1])}`;
    case 'many': return `${f} ${op.label} ${(c.values || []).map(fmtValue).join(', ') || '…'}`;
    case 'set': return `${f} ${op.label} ${c.set || '…'}`;
    default: return `${f} ${op.label}`;
  }
}

export function groupText(doc: RuleDoc, g: Group, top = true): string {
  const items = groupItems(g);
  if (!items.length) return top ? 'always' : '…';
  const joiner = groupKind(g) === 'all' ? ' and ' : ' or ';
  const inner = items.map((n) => (isGroup(n) ? `(${groupText(doc, n, false)})` : conditionText(doc, n))).join(joiner);
  return g.negate ? `not (${inner})` : inner;
}

export function thenText(doc: RuleDoc, r: Rule): string {
  const parts = Object.entries(r.then || {}).map(([k, cell]) => {
    const label = doc.outputs.find((o) => o.field === k)?.label || k;
    if (cell && typeof cell === 'object' && 'formula' in cell) return `${label} = ${cell.formula}`;
    return `${label} = ${fmtValue(cell?.value)}`;
  });
  return parts.join(', ') || 'nothing yet';
}

export function ruleSentence(doc: RuleDoc, r: Rule): string {
  return `When ${groupText(doc, r.when)}, then ${thenText(doc, r)}.`;
}

export function factsUsed(g: Group, out: Set<string> = new Set()): Set<string> {
  for (const n of groupItems(g)) {
    if (isGroup(n)) factsUsed(n, out);
    else if (n.fact) out.add(n.fact);
  }
  return out;
}

export function problemsAt(problems: Problem[], prefix: string): Problem[] {
  return problems.filter((p) => p.path === prefix || p.path.startsWith(`${prefix}/`));
}

export function problemAt(problems: Problem[], path: string): Problem | undefined {
  return problems.find((p) => p.path === path);
}

// table cells: a small grammar people can type or paste from a spreadsheet
// >50  >=2026-01-01  <=10  between 1 and 5  a, b, c  in SET_NAME  not in SET  starts with x  any  (empty)
export function parseCell(text: string, type: FactType): Condition[] | null {
  const t = text.trim();
  if (!t || t === '-' || /^any$/i.test(t)) return [];
  const mk = (op: string, rest: Partial<Condition>): Condition => ({ fact: '', op, ...rest });
  const val = (s: string): any => {
    const v = s.trim().replace(/^["“](.*)["”]$/, '$1');
    if (type === 'number') {
      const n = Number(v.replace(/,/g, ''));
      return Number.isFinite(n) ? n : v;
    }
    if (type === 'boolean') return /^(true|yes|y)$/i.test(v);
    return v;
  };
  let m: RegExpMatchArray | null;
  if ((m = t.match(/^between\s+(.+?)\s+and\s+(.+)$/i))) return [mk('between', { values: [val(m[1]), val(m[2])] })];
  if ((m = t.match(/^not in\s+([A-Z0-9_]+)$/))) return [mk('not_in_reference_set', { set: m[1] })];
  if ((m = t.match(/^in\s+([A-Z0-9_]+)$/))) return [mk('in_reference_set', { set: m[1] })];
  if ((m = t.match(/^starts with\s+(.+)$/i))) return [mk('starts_with', { value: val(m[1]) })];
  if ((m = t.match(/^ends with\s+(.+)$/i))) return [mk('ends_with', { value: val(m[1]) })];
  if ((m = t.match(/^(not )?contains\s+(.+)$/i))) return [mk(m[1] ? 'not_contains' : 'contains', { value: val(m[2]) })];
  if (/^(has a value|set)$/i.test(t)) return [mk('is_set', {})];
  if (/^(no value|empty|not set)$/i.test(t)) return [mk('is_not_set', {})];
  if (type === 'boolean' && /^(true|yes|false|no)$/i.test(t)) return [mk(/^(true|yes)$/i.test(t) ? 'is_true' : 'is_false', {})];
  if ((m = t.match(/^(>=|<=|>|<|!=|=)\s*(.+)$/))) {
    const date = type === 'date';
    const map: Record<string, string> = date
      ? { '>': 'after', '>=': 'on_or_after', '<': 'before', '<=': 'on_or_before', '=': 'eq', '!=': 'neq' }
      : { '>': 'gt', '>=': 'gte', '<': 'lt', '<=': 'lte', '=': 'eq', '!=': 'neq' };
    return [mk(map[m[1]], { value: val(m[2]) })];
  }
  if ((m = t.match(/^not\s+(.+)$/i))) {
    const parts = m[1].split(',').map((s) => s.trim()).filter(Boolean);
    return [parts.length > 1 ? mk('not_in', { values: parts.map(val) }) : mk('neq', { value: val(parts[0]) })];
  }
  if (t.includes(',')) return [mk('in', { values: t.split(',').map((s) => s.trim()).filter(Boolean).map(val) })];
  return [mk('eq', { value: val(t) })];
}

export function formatCell(conds: Condition[]): string {
  const sym: Record<string, string> = {
    gt: '>', gte: '>=', lt: '<', lte: '<=', after: '>', on_or_after: '>=', before: '<', on_or_before: '<=', neq: '!=',
  };
  return conds
    .map((c) => {
      const o = OPERATORS[c.op];
      if (!o) return '';
      if (c.op === 'eq') return String(c.value ?? '');
      if (sym[c.op]) return `${sym[c.op]} ${c.value ?? ''}`;
      if (c.op === 'between') return `between ${c.values?.[0] ?? ''} and ${c.values?.[1] ?? ''}`;
      if (c.op === 'in') return (c.values || []).join(', ');
      if (c.op === 'not_in') return `not ${(c.values || []).join(', ')}`;
      if (c.op === 'in_reference_set') return `in ${c.set ?? ''}`;
      if (c.op === 'not_in_reference_set') return `not in ${c.set ?? ''}`;
      if (c.op === 'starts_with') return `starts with ${c.value ?? ''}`;
      if (c.op === 'ends_with') return `ends with ${c.value ?? ''}`;
      if (c.op === 'contains') return `contains ${c.value ?? ''}`;
      if (c.op === 'not_contains') return `not contains ${c.value ?? ''}`;
      if (c.op === 'is_set') return 'has a value';
      if (c.op === 'is_not_set') return 'no value';
      if (c.op === 'is_true') return 'true';
      if (c.op === 'is_false') return 'false';
      return o.label;
    })
    .join(' and ');
}

// a rule fits the table when its conditions are a flat "all" list
export function tableable(r: Rule): boolean {
  if (r.when.negate || groupKind(r.when) === 'any') return false;
  return groupItems(r.when).every((n) => !isGroup(n));
}

export function cellsByFact(r: Rule): Record<string, Condition[]> {
  const out: Record<string, Condition[]> = {};
  for (const n of groupItems(r.when)) {
    if (!isGroup(n)) (out[n.fact] ||= []).push(n);
  }
  return out;
}

const same = (a: any, b: any) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

export interface MergeResult {
  doc: RuleDoc;
  conflicts: { ruleKey: string; mine: Rule | null; theirs: Rule | null }[];
}

// three-way merge by rule: a rule only one side changed is taken from that side
export function mergeDocs(base: RuleDoc, mine: RuleDoc, theirs: RuleDoc): MergeResult {
  const k = (r: Rule) => r.key || r.id;
  const b = new Map(base.rules.map((r) => [k(r), r]));
  const m = new Map(mine.rules.map((r) => [k(r), r]));
  const t = new Map(theirs.rules.map((r) => [k(r), r]));
  const order: string[] = [];
  for (const r of [...theirs.rules, ...mine.rules]) if (!order.includes(k(r))) order.push(k(r));
  const conflicts: MergeResult['conflicts'] = [];
  const rules: Rule[] = [];
  for (const key of order) {
    const rb = b.get(key) ?? null;
    const rm = m.get(key) ?? null;
    const rt = t.get(key) ?? null;
    const mineChanged = !same(rb, rm);
    const theirsChanged = !same(rb, rt);
    let pick: Rule | null;
    if (!mineChanged) pick = rt;
    else if (!theirsChanged) pick = rm;
    else if (same(rm, rt)) pick = rm;
    else {
      conflicts.push({ ruleKey: key, mine: rm, theirs: rt });
      pick = rt;
    }
    if (pick) rules.push(pick);
  }
  const facts = [...theirs.facts];
  for (const f of mine.facts) if (!facts.some((x) => x.path === f.path)) facts.push(f);
  const outputs = [...theirs.outputs];
  for (const o of mine.outputs) if (!outputs.some((x) => x.field === o.field)) outputs.push(o);
  const hit = !same(base.hit_policy, mine.hit_policy) ? mine.hit_policy : theirs.hit_policy;
  return { doc: { ...theirs, hit_policy: hit, facts, outputs, rules }, conflicts };
}

export function sampleFor(type: FactType): any {
  return { string: '', number: 0, boolean: false, date: new Date().toISOString().slice(0, 10), list: [] }[type];
}

export function setPath(obj: Record<string, any>, path: string, value: any): Record<string, any> {
  const out = structuredClone(obj ?? {});
  const parts = path.split('.');
  let cur: any = out;
  for (const p of parts.slice(0, -1)) {
    if (typeof cur[p] !== 'object' || cur[p] === null) cur[p] = {};
    cur = cur[p];
  }
  cur[parts[parts.length - 1]] = value;
  return out;
}

export function getPath(obj: any, path: string): any {
  return path.split('.').reduce((cur, p) => (cur && typeof cur === 'object' ? cur[p] : undefined), obj);
}

export const STATE_STYLE: Record<VersionSummary['state'], string> = {
  draft: 'text-slate-300 border-slate-600 bg-slate-700/30',
  proposed: 'text-amber-300 border-amber-500/40 bg-amber-500/10',
  approved: 'text-cyan-300 border-cyan-500/40 bg-cyan-500/10',
  rejected: 'text-rose-300 border-rose-500/40 bg-rose-500/10',
  published: 'text-emerald-300 border-emerald-500/40 bg-emerald-500/10',
  superseded: 'text-slate-400 border-slate-700 bg-slate-800/40',
  retired: 'text-slate-500 border-slate-700 bg-slate-800/40',
};

export const STATE_LABEL: Record<VersionSummary['state'], string> = {
  draft: 'Draft', proposed: 'Waiting for sign-off', approved: 'Approved, ready to publish', rejected: 'Rejected',
  published: 'In force', superseded: 'Replaced', retired: 'Retired',
};

export const CLIENT_SAMPLE = {
  ruleKey: 'freight.remote.surcharge',
  version: 4,
  jurisdiction: 'GB',
  regime: 'FREIGHT',
  status: 'IN_FORCE',
  validFrom: '2026-01-01',
  requiresFacts: ['shipment.date', 'shipment.postcode', 'shipment.parcelCount', 'shipment.weightKg'],
  when: {
    all: [
      { gte: [{ fact: 'shipment.date' }, '2026-01-01'] },
      { inReferenceSet: [{ fact: 'shipment.postcode' }, 'REMOTE_POSTCODES'] },
      { gt: [{ fact: 'shipment.weightKg' }, 50] },
    ],
  },
  then: { surcharge: 'REMOTE_AREA_SURCHARGE' },
  provenance: { sourceSnapshotId: 'snapshot-123', citations: ['Carrier tariff 2026, section 4.2'] },
};

// what decision_evaluate keeps on a run's tool call, see engine/decisions/service.py evaluation_summary
export interface DecisionRecord {
  key: string;
  name?: string;
  version: number;
  version_id?: string;
  outcome: 'decided' | 'no_match' | 'missing_facts' | 'invalid_facts';
  result: any;
  result_truncated?: boolean;
  applied_rules: { key: string; id?: string; description?: string; citations: string[] }[];
  missing_facts: string[];
  invalid_facts: { fact: string; expected?: string; got?: string; value?: string }[];
  explanation?: string | null;
  facts?: Record<string, any> | null;
  facts_truncated?: boolean;
  trace_hash: string;
  evaluation_id?: string | null;
  duration_us?: number;
  as_of?: string | null;
  known_at?: string | null;
}

export const OUTCOME_TEXT: Record<string, string> = {
  decided: 'Decided',
  no_match: 'No rule applies',
  missing_facts: 'Missing facts',
  invalid_facts: 'Facts with the wrong type',
};

export const OUTCOME_CHIP: Record<string, string> = {
  decided: 'text-emerald-300 border-emerald-500/30 bg-emerald-500/10',
  no_match: 'text-slate-300 border-slate-600 bg-slate-800/40',
  missing_facts: 'text-amber-300 border-amber-500/30 bg-amber-500/10',
  invalid_facts: 'text-rose-300 border-rose-500/30 bg-rose-500/10',
};

const TRY_SESSION_KEY = 'abenix.decisionTry';
const TRY_URL_LIMIT = 6000;

export interface TryPreload { facts: Record<string, any>; as_of?: string | null }

// link that opens the decision's Try panel with these facts filled in
export function tryHref(key: string, version: number | null | undefined, preload: TryPreload): string {
  const base = `/decisions/${encodeURIComponent(key)}?${version ? `version=${version}&` : ''}tab=rules`;
  const payload = JSON.stringify({ facts: preload.facts || {}, as_of: preload.as_of || null });
  const enc = encodeURIComponent(payload);
  if (enc.length <= TRY_URL_LIMIT) return `${base}&try=${enc}`;
  try { sessionStorage.setItem(TRY_SESSION_KEY, JSON.stringify({ key, ...JSON.parse(payload) })); } catch { /* storage off */ }
  return `${base}&try=session`;
}

export function readTryPreload(key: string, raw: string | null): TryPreload | null {
  if (!raw) return null;
  try {
    if (raw === 'session') {
      const v = JSON.parse(sessionStorage.getItem(TRY_SESSION_KEY) || 'null');
      if (!v || v.key !== key) return null;
      return { facts: v.facts && typeof v.facts === 'object' ? v.facts : {}, as_of: v.as_of || null };
    }
    const v = JSON.parse(raw);
    if (!v || typeof v !== 'object' || Array.isArray(v)) return null;
    const facts = v.facts && typeof v.facts === 'object' && !Array.isArray(v.facts) ? v.facts : {};
    return { facts, as_of: typeof v.as_of === 'string' ? v.as_of : null };
  } catch {
    return null;
  }
}

export function formatDuration(us?: number | null): string {
  if (!us) return '';
  return us < 1000 ? `${us} µs` : `${(us / 1000).toFixed(1)} ms`;
}
