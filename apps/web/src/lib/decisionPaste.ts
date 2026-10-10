// Rows pasted from a spreadsheet into the decision table, with a header row that names the columns.
import {
  PATH_RE, groupItems, isGroup, newRuleId, parseCell,
  type Condition, type FactType, type OutcomeType, type Rule, type RuleDoc,
} from '@/lib/decisions';
import { guessFactType, inferColumnType, numberDraft, parseThen } from '@/lib/decisionValues';

export type ColRole = 'rule' | 'description' | 'sources' | 'requires' | 'valid_from' | 'valid_to' | 'fact' | 'outcome' | 'skip';

export interface PasteColumn {
  header: string;
  role: ColRole;
  // fact path or outcome field
  target: string;
  type: FactType | OutcomeType;
  // false when pasting will create the fact or outcome
  exists: boolean;
}

export interface PastePlan {
  columns: PasteColumn[];
  rows: string[][];
  hasHeader: boolean;
}

export const EXTRA_COLUMNS: { role: Exclude<ColRole, 'rule' | 'fact' | 'outcome' | 'skip'>; label: string; re: RegExp }[] = [
  { role: 'description', label: 'What it means', re: /^(description|what it means|meaning|notes?)$/i },
  { role: 'requires', label: 'Facts it needs', re: /^(facts? (it )?needs?|facts needed|requires( facts)?|required facts)$/i },
  { role: 'sources', label: 'Sources', re: /^(sources?|citations?|provenance)$/i },
  { role: 'valid_from', label: 'Valid from', re: /^(valid ?from|applies from|in force from|from)$/i },
  { role: 'valid_to', label: 'Valid to', re: /^(valid ?(to|until)|applies until|in force until|until|to)$/i },
];

const RULE_RE = /^(rule|rule ?key|rulekey|key)$/i;
const OP_RE = /^(>=|<=|>|<|!=|=|between\s|not\s|in\s+[A-Z0-9_]+$|any$|starts with\s|ends with\s|(not )?contains\s|has a value$|no value$)/i;

// tab separated, with Excel's quoting for cells that hold tabs or line breaks
export function splitPasted(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;
  const s = String(text ?? '').replace(/\r\n?/g, '\n');
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (quoted) {
      if (ch === '"' && s[i + 1] === '"') { cell += '"'; i++; }
      else if (ch === '"') quoted = false;
      else cell += ch;
      continue;
    }
    // a bare "" is how people type empty text, keep it as written
    if (ch === '"' && cell === '' && s[i + 1] === '"' && (i + 2 >= s.length || s[i + 2] === '\t' || s[i + 2] === '\n')) { cell = '""'; i++; continue; }
    if (ch === '"' && cell === '') { quoted = true; continue; }
    if (ch === '\t') { row.push(cell); cell = ''; continue; }
    if (ch === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; continue; }
    cell += ch;
  }
  if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
  return rows.filter((r) => r.some((c) => c.trim()));
}

// Clearance or Tip speed become lowercase snake_case, a path typed like shipment.weightKg stays as typed
export function toPath(header: string): string {
  const raw = header.trim();
  if (PATH_RE.test(raw) && /^[a-z_]/.test(raw)) return raw;
  const t = raw.replace(/([a-z0-9])([A-Z])/g, '$1_$2');
  let p = t.toLowerCase().replace(/[^a-z0-9_.]+/g, '_').replace(/_+/g, '_').replace(/\._|_\./g, '.').replace(/^[_.]+|[_.]+$/g, '');
  if (!p) return '';
  if (/^\d/.test(p)) p = `c_${p}`;
  return PATH_RE.test(p) ? p : '';
}

function findFact(doc: RuleDoc, h: string) {
  const l = h.toLowerCase();
  return doc.facts.find((f) => f.path === h || (f.label || '').toLowerCase() === l);
}

function findOutcome(doc: RuleDoc, h: string) {
  const l = h.toLowerCase();
  return doc.outputs.find((o) => o.field === h || (o.label || '').toLowerCase() === l);
}

function knownRole(doc: RuleDoc, h: string): ColRole | null {
  if (RULE_RE.test(h)) return 'rule';
  const extra = EXTRA_COLUMNS.find((c) => c.re.test(h));
  if (extra) return extra.role;
  if (findFact(doc, h)) return 'fact';
  if (findOutcome(doc, h)) return 'outcome';
  return null;
}

function looksLikeHeader(cells: string[]): boolean {
  const vals = cells.map((c) => c.trim()).filter(Boolean);
  if (!vals.length) return false;
  return vals.every((v) => /^[A-Za-z_][A-Za-z0-9_ .()/%-]*$/.test(v) && !OP_RE.test(v) && numberDraft(v).kind !== 'number');
}

function operand(cell: string): string {
  return cell.trim().replace(/^(>=|<=|>|<|!=|=)\s*/, '').replace(/^between\s+(.+?)\s+and\s+.+$/i, '$1');
}

function factTypeFor(path: string, cells: string[]): FactType {
  const t = inferColumnType(cells.map(operand).filter((c) => !/^any$/i.test(c)));
  if (t === 'number' || t === 'date' || t === 'boolean') return t;
  return guessFactType(path);
}

// work out what each column is before anything changes
export function planPaste(text: string, doc: RuleDoc, defaultColumns: PasteColumn[]): PastePlan {
  const rows = splitPasted(text);
  if (!rows.length) return { columns: [], rows: [], hasHeader: false };
  const first = rows[0].map((h) => h.trim());
  const empty = !doc.facts.length && !doc.outputs.length;
  const anyKnown = first.some((h) => h && knownRole(doc, h));
  const hasHeader = anyKnown || (empty && looksLikeHeader(first));
  const body = hasHeader ? rows.slice(1) : rows;
  if (!hasHeader) return { columns: defaultColumns.slice(0, Math.max(...rows.map((r) => r.length), 0)), rows: body, hasHeader };
  const columns: PasteColumn[] = first.map((h, ci) => {
    if (!h) return { header: h, role: 'skip', target: '', type: 'string', exists: true };
    const role = knownRole(doc, h);
    const cells = body.map((r) => r[ci] ?? '');
    if (role === 'fact') { const f = findFact(doc, h)!; return { header: h, role, target: f.path, type: f.type, exists: true }; }
    if (role === 'outcome') { const o = findOutcome(doc, h)!; return { header: h, role, target: o.field, type: (o.type as OutcomeType) || 'string', exists: true }; }
    if (role) return { header: h, role, target: '', type: 'string', exists: true };
    const target = toPath(h);
    if (!target) return { header: h, role: 'skip', target: '', type: 'string', exists: false };
    const conditionLike = cells.some((c) => OP_RE.test(c.trim()));
    const asFact = conditionLike || h.includes('.');
    if (asFact) return { header: h, role: 'fact', target, type: factTypeFor(target, cells), exists: false };
    const t = inferColumnType(cells) ?? (guessFactType(target) === 'number' ? 'number' : 'string');
    return { header: h, role: 'outcome', target, type: t, exists: false };
  });
  return { columns, rows: body, hasHeader };
}

export function newColumns(plan: PastePlan): PasteColumn[] {
  return plan.columns.filter((c) => !c.exists && (c.role === 'fact' || c.role === 'outcome'));
}

function setFactConditions(rule: Rule, fact: string, conds: Condition[]): Rule {
  const items = groupItems(rule.when).filter((n) => isGroup(n) || (n as Condition).fact !== fact);
  return { ...rule, when: { all: [...items, ...conds.map((c) => ({ ...c, fact }))] } };
}

function day(v: string): string | null {
  const t = v.trim();
  if (!t) return null;
  const m = t.match(/^(\d{4}-\d{2}-\d{2})/);
  return m ? m[1] : t;
}

// apply the plan, adding missing facts and outcomes first; rows with a known rule key update that rule
export function applyPaste(doc: RuleDoc, plan: PastePlan): { doc: RuleDoc; added: number; updated: number; skipped: string[] } {
  let next: RuleDoc = { ...doc, facts: [...doc.facts], outputs: [...doc.outputs], rules: [...doc.rules] };
  for (const c of plan.columns) {
    if (c.exists || !c.target) continue;
    if (c.role === 'fact' && !next.facts.some((f) => f.path === c.target)) {
      // a fact any rule tests is one callers must send, the same as a fact added by hand
      const ci = plan.columns.indexOf(c);
      const used = plan.rows.some((r) => (r[ci] ?? '').trim() && !/^any$/i.test((r[ci] ?? '').trim()));
      next.facts.push({ path: c.target, type: c.type as FactType, label: c.header && c.header !== c.target ? c.header : c.target, required: used });
    }
    if (c.role === 'outcome' && !next.outputs.some((o) => o.field === c.target)) {
      next.outputs.push({ field: c.target, label: c.header && c.header !== c.target ? c.header : c.target, type: c.type as OutcomeType });
    }
  }
  let added = 0;
  let updated = 0;
  const skipped = plan.columns.filter((c) => c.role === 'skip' && c.header).map((c) => c.header);
  for (const cells of plan.rows) {
    let rule: Rule = { id: newRuleId(next), key: '', enabled: true, when: { all: [] }, then: {} };
    const keyCol = plan.columns.findIndex((c) => c.role === 'rule');
    const key = keyCol >= 0 ? (cells[keyCol] ?? '').trim() : '';
    const at = key ? next.rules.findIndex((r) => r.key === key) : -1;
    if (at >= 0) rule = { ...next.rules[at] };
    rule.key = key || rule.key;
    const then = { ...(rule.then || {}) };
    plan.columns.forEach((col, ci) => {
      const v = (cells[ci] ?? '').trim();
      switch (col.role) {
        case 'description': rule.description = v; break;
        case 'sources': {
          const list = v.split(/\s*[;|\n]\s*/).map((s) => s.trim()).filter(Boolean);
          rule.provenance = { ...(rule.provenance || {}), citations: list };
          break;
        }
        case 'requires': rule.requires = v.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean); break;
        case 'valid_from': rule.valid_from = day(v); break;
        case 'valid_to': rule.valid_to = day(v); break;
        case 'fact': {
          const f = next.facts.find((x) => x.path === col.target);
          const parsed = parseCell(v, (f?.type ?? col.type) as FactType);
          if (parsed) rule = setFactConditions(rule, col.target, parsed);
          break;
        }
        case 'outcome': {
          const o = next.outputs.find((x) => x.field === col.target);
          const cell = parseThen(v, (o?.type as OutcomeType) ?? (col.type as OutcomeType));
          if (cell) then[col.target] = cell;
          else delete then[col.target];
          break;
        }
        default:
      }
    });
    rule.then = then;
    // without a facts-needed column, a rule needs the facts its own cells test
    if (!plan.columns.some((c) => c.role === 'requires')) {
      const used = plan.columns.filter((c, ci) => c.role === 'fact' && (cells[ci] ?? '').trim() && !/^any$/i.test((cells[ci] ?? '').trim())).map((c) => c.target);
      rule.requires = used;
    }
    if (at >= 0) { next.rules[at] = rule; updated++; }
    else { next.rules.push(rule); added++; }
    next = { ...next, rules: [...next.rules] };
  }
  return { doc: next, added, updated, skipped };
}
