// Typing, inferring and converting the values people enter on the decision screens.
import {
  DATE_RE, OPERATORS, defaultOp, groupItems, isGroup, withItems,
  type Condition, type FactType, type Group, type Node, type Outcome, type OutcomeType, type RuleDoc, type ThenCell,
} from '@/lib/decisions';

// typing a number key by key passes through "0." and "-", which are not numbers yet
export type NumberDraft = { kind: 'empty' } | { kind: 'number'; value: number } | { kind: 'partial' } | { kind: 'text' };

export function numberDraft(text: string): NumberDraft {
  let t = String(text ?? '').trim();
  if (!t) return { kind: 'empty' };
  if (/^[-+]?\d{1,3}(,\d{3})+(\.\d*)?$/.test(t)) t = t.replace(/,/g, '');
  if (/^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(t)) return { kind: 'number', value: Number(t) };
  if (/^[-+]?\.?$/.test(t) || /^[-+]?(\d+\.?\d*|\.\d+)[eE][-+]?$/.test(t)) return { kind: 'partial' };
  return { kind: 'text' };
}

export const OUTCOME_TYPE_LABEL: Record<OutcomeType, string> = {
  number: 'Number', string: 'Text', boolean: 'Yes / no', date: 'Date', object: 'Other (JSON)',
};

export function outcomeType(o: Outcome | undefined): OutcomeType {
  const t = o?.type;
  return t === 'number' || t === 'boolean' || t === 'date' || t === 'object' ? t : 'string';
}

// what the answers really are: a Text outcome whose every value is a number reads as Number
export function effectiveOutcomeType(doc: RuleDoc | null | undefined, o: Outcome | undefined): OutcomeType {
  const declared = outcomeType(o);
  if (declared !== 'string' || !doc || !o) return declared;
  const vals = doc.rules.map((r) => r.then?.[o.field]).filter((c): c is ThenCell => !!c && !('formula' in c) && c.value !== '' && c.value !== undefined && c.value !== null).map((c) => c.value);
  if (!vals.length) return declared;
  if (vals.every((v) => typeof v === 'number')) return 'number';
  if (vals.every((v) => typeof v === 'boolean')) return 'boolean';
  return declared;
}

// a first guess from the name, people can change it
export function guessFactType(path: string): FactType {
  const raw = (path.split('.').pop() || '').trim();
  const leaf = raw.toLowerCase();
  if (!leaf) return 'string';
  if (/^(is|has|can|should|was|did)([_A-Z]|$)/.test(raw) || /^(is|has|can|should|was|did)_/.test(leaf)) return 'boolean';
  if (/date/.test(leaf) || /(_at|_on|_day|since|until|deadline|expiry|expires)$/.test(leaf)) return 'date';
  if (/(_ms|_m|_mm|_cm|_km|_kg|_g|_t|_s|_sec|_min|_h|_hrs|_pct|_percent|_mph|_kmh|_kph|_usd|_eur|_gbp|_qty|_num|_count|_kw|_kwh)$/.test(leaf)) return 'number';
  if (/(speed|count|pct|percent|amount|price|cost|rate|qty|quantity|weight|mass|tonnes|tons|volume|value|share|emission|distance|clearance|height|width|length|depth|radius|score|total|level|temperature|temp|duration|limit|load|size|age|kg|km|number|ratio|margin|balance|fee|days|hours|minutes|seconds|years)/.test(leaf)) return 'number';
  return 'string';
}

export function inferValueType(text: string): OutcomeType {
  const t = String(text ?? '').trim();
  if (!t) return 'string';
  if (/^(true|false|yes|no)$/i.test(t)) return 'boolean';
  if (DATE_RE.test(t)) return 'date';
  if (numberDraft(t).kind === 'number') return 'number';
  return 'string';
}

// one type for a column of values, text when they disagree, null when there is nothing to go on
export function inferColumnType(values: string[]): OutcomeType | null {
  const seen = values.map((v) => String(v ?? '').trim()).filter((v) => v && v !== '""');
  if (!seen.length) return null;
  const types = new Set(seen.map(inferValueType));
  return types.size === 1 ? [...types][0] : 'string';
}

export function coerceTo(type: FactType | OutcomeType, v: any): any {
  if (v === undefined || v === null) return v;
  if (Array.isArray(v)) return v.map((x) => coerceTo(type, x));
  if (type === 'number') {
    if (typeof v !== 'string') return v;
    const d = numberDraft(v);
    return d.kind === 'number' ? d.value : v;
  }
  if (type === 'boolean') {
    if (typeof v === 'boolean') return v;
    if (/^(true|yes|y|1)$/i.test(String(v).trim())) return true;
    if (/^(false|no|n|0)$/i.test(String(v).trim())) return false;
    return v;
  }
  if (type === 'string' || type === 'date' || type === 'list') return typeof v === 'object' ? v : String(v);
  return v;
}

function retypeGroup(g: Group, fact: string, type: FactType): Group {
  const items = groupItems(g).map((n): Node => {
    if (isGroup(n)) return retypeGroup(n, fact, type);
    if (n.fact !== fact) return n;
    const ok = OPERATORS[n.op]?.types.includes(type);
    const c: Condition = { ...n, op: ok ? n.op : defaultOp(type) };
    const shape = OPERATORS[c.op]?.shape;
    if (shape === 'none') { delete c.value; delete c.values; delete c.set; }
    if (c.value !== undefined) c.value = coerceTo(type, c.value);
    if (c.values !== undefined) c.values = coerceTo(type, c.values);
    return c;
  });
  return withItems(g, items);
}

// changing a fact's type keeps every condition on it valid where it can
export function changeFactType(doc: RuleDoc, path: string, type: FactType): RuleDoc {
  return {
    ...doc,
    facts: doc.facts.map((f) => (f.path === path ? { ...f, type } : f)),
    rules: doc.rules.map((r) => ({ ...r, when: retypeGroup(r.when, path, type) })),
  };
}

export function changeOutcomeType(doc: RuleDoc, field: string, type: OutcomeType): RuleDoc {
  return {
    ...doc,
    outputs: doc.outputs.map((o) => (o.field === field ? { ...o, type } : o)),
    rules: doc.rules.map((r) => {
      const cell = r.then?.[field];
      if (!cell || 'formula' in cell || cell.value === '' || cell.value === undefined) return r;
      return { ...r, then: { ...r.then, [field]: { ...cell, value: coerceTo(type, cell.value) } } };
    }),
  };
}

function hasOtherValue(doc: RuleDoc, field: string, ruleId: string): boolean {
  return doc.rules.some((r) => {
    if (r.id === ruleId) return false;
    const c = r.then?.[field];
    return !!c && (('formula' in c && !!c.formula) || (c.value !== undefined && c.value !== ''));
  });
}

function typeOfValue(v: any): OutcomeType {
  if (typeof v === 'number') return 'number';
  if (typeof v === 'boolean') return 'boolean';
  if (typeof v === 'string') return inferValueType(v);
  return 'string';
}

// the first value given to an outcome still on the default type decides its type
export function setOutcomeCell(doc: RuleDoc, ruleId: string, field: string, cell: ThenCell | null): RuleDoc {
  const out = doc.outputs.find((o) => o.field === field);
  let next: RuleDoc = {
    ...doc,
    rules: doc.rules.map((r) => {
      if (r.id !== ruleId) return r;
      const then = { ...(r.then || {}) };
      if (cell === null) delete then[field];
      else then[field] = cell;
      return { ...r, then };
    }),
  };
  const isValue = !!cell && !('formula' in cell) && cell.value !== '' && cell.value !== undefined && cell.value !== null;
  if (out && isValue && outcomeType(out) === 'string' && !hasOtherValue(doc, field, ruleId)) {
    const t = typeOfValue(cell!.value);
    if (t !== 'string') next = changeOutcomeType(next, field, t);
  }
  return next;
}

// an outcome cell typed in the table: "" is an empty value, a blank cell is not set
export function parseThen(text: string, type?: OutcomeType): ThenCell | null {
  const t = String(text ?? '').trim();
  if (!t) return null;
  if (t === '""' || t === '“”' || t === "''") return { value: '' };
  if (t.startsWith('=')) return { formula: t.slice(1).trim() };
  const quoted = t.match(/^"([\s\S]*)"$/) || t.match(/^“([\s\S]*)”$/);
  if (quoted) return { value: quoted[1] };
  const kind = type ?? inferValueType(t);
  if (kind === 'number') {
    const d = numberDraft(t);
    return { value: d.kind === 'number' ? d.value : t };
  }
  if (kind === 'boolean') {
    if (/^(true|yes|y)$/i.test(t)) return { value: true };
    if (/^(false|no|n)$/i.test(t)) return { value: false };
    return { value: t };
  }
  if (kind === 'object') {
    try { return { value: JSON.parse(t) }; } catch { return { value: t }; }
  }
  return { value: t };
}

export function thenCellText(cell: ThenCell | undefined | null): string {
  if (!cell) return '';
  if ('formula' in cell && cell.formula !== undefined) return `=${cell.formula}`;
  const v = cell.value;
  if (v === undefined || v === null) return '';
  if (v === '') return '""';
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

// what happened and what to do next, for the refusals people meet on the decision screens
const ERROR_HELP: Record<string, string> = {
  TIER_LOCKED: 'The risk tier can only change once no version is waiting for sign-off. Withdraw that version, or let it be approved or rejected, then change the tier.',
  TIER_CHANGED: 'The risk tier changed after this version was approved, so its sign-off no longer fits the tier. Withdraw it and propose it again to get sign-off at the current tier.',
  SIGNOFF_INSUFFICIENT: 'This version does not have the sign-off its risk tier needs now. Withdraw it and propose it again, and an approver signs it at the current tier.',
  SOLE_OPERATOR_OFF: 'Signing your own change is turned off in this workspace. Invite someone who can approve under Team, or ask an admin to turn it on under Risk and Controls.',
  SOLE_OPERATOR_NOT_ALLOWED: 'This approval cannot be signed by the person who asked for it. Someone else has to approve it.',
  REASON_REQUIRED: 'Write a reason first. It goes on the record with the change.',
  TIER_CHANGE_PENDING: 'A tier change is already waiting for sign-off. Withdraw it on the decision page, or wait for it to be decided, then try again.',
  AUTHOR_CANNOT_APPROVE: 'You asked for this, so someone else has to approve it. Approvals shows who can.',
};

export function decisionErrorText(code: string | undefined | null, message: string | null | undefined, details?: any): string {
  const msg = (message || '').trim();
  if (code === 'VALIDATION_FAILED') {
    const summary = details?.summary ? String(details.summary).replace(/\.$/, '') : msg.replace(/\.$/, '');
    return `It can't be proposed yet: ${summary}. Fix what is listed under Rules and Golden tests, run Check, then propose again.`;
  }
  if (code === 'OTHER_APPROVERS_EXIST') return `${msg || 'Someone else can approve this.'} They see it in Needs you.`;
  const help = code ? ERROR_HELP[code] : undefined;
  if (!help) return msg || 'Something went wrong. Try again, and if it keeps happening reload the page.';
  // these already say what to do, with specifics such as the version number
  if (msg && /withdraw|propose it again|ask one of them/i.test(msg)) return msg;
  if (!msg || code === 'REASON_REQUIRED' || code === 'SOLE_OPERATOR_OFF' || code === 'AUTHOR_CANNOT_APPROVE') return help;
  return `${msg.replace(/\.?$/, '.')} ${help}`;
}

// the check summary reads "1 golden test pass", say it properly
export function tidySummary(t: string | null | undefined): string {
  return String(t ?? '').replace(/\b1 golden test pass\b/g, '1 golden test passes').replace(/\b1 golden test fail\b/g, '1 golden test fails');
}
