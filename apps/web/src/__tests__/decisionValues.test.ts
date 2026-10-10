import { describe, expect, it } from 'vitest';
import { normProblemPath, normProblems, orderedResult, pickDefault, problemPlace, thenText, type RuleDoc, type VersionSummary } from '@/lib/decisions';
import {
  changeFactType, changeOutcomeType, coerceTo, guessFactType, inferColumnType, inferValueType, numberDraft, parseThen, setOutcomeCell, thenCellText,
} from '@/lib/decisionValues';

const doc = (over: Partial<RuleDoc> = {}): RuleDoc => ({ kind: 'rules', hit_policy: 'first', facts: [], outputs: [], rules: [], ...over });

describe('typing a number key by key', () => {
  it('keeps the point while it is typed', () => {
    expect(numberDraft('0')).toEqual({ kind: 'number', value: 0 });
    expect(numberDraft('0.')).toEqual({ kind: 'number', value: 0 });
    expect(numberDraft('0.5')).toEqual({ kind: 'number', value: 0.5 });
    expect(numberDraft('2.50')).toEqual({ kind: 'number', value: 2.5 });
    expect(numberDraft('.5')).toEqual({ kind: 'number', value: 0.5 });
  });

  it('holds what is not a number yet and passes on what never will be', () => {
    expect(numberDraft('-').kind).toBe('partial');
    expect(numberDraft('.').kind).toBe('partial');
    expect(numberDraft('1e').kind).toBe('partial');
    expect(numberDraft('').kind).toBe('empty');
    expect(numberDraft('fifty').kind).toBe('text');
    expect(numberDraft('1,000')).toEqual({ kind: 'number', value: 1000 });
  });
});

describe('guessing a fact type from its name', () => {
  it.each([
    ['machine.tip_speed_ms', 'number'], ['worker.clearance_m', 'number'], ['load_kg', 'number'], ['crane.speed', 'number'],
    ['parcel_count', 'number'], ['share_pct', 'number'], ['shipment.date', 'date'], ['start_date', 'date'], ['created_at', 'date'],
    ['worker.is_inside', 'boolean'], ['has_permit', 'boolean'], ['isActive', 'boolean'], ['shipment.postcode', 'string'], ['action', 'string'],
  ])('%s is %s', (path, type) => expect(guessFactType(path)).toBe(type));
});

describe('inferring an outcome type from values', () => {
  it('reads one value', () => {
    expect(inferValueType('4')).toBe('number');
    expect(inferValueType('0.5')).toBe('number');
    expect(inferValueType('yes')).toBe('boolean');
    expect(inferValueType('2026-01-01')).toBe('date');
    expect(inferValueType('stop')).toBe('string');
  });

  it('reads a column, text when the values disagree', () => {
    expect(inferColumnType(['4', '3', '7'])).toBe('number');
    expect(inferColumnType(['stop', 'warn'])).toBe('string');
    expect(inferColumnType(['4', 'stop'])).toBe('string');
    expect(inferColumnType(['', '""'])).toBeNull();
  });

  it('takes the type from the first value given to a text outcome', () => {
    const d = doc({
      outputs: [{ field: 'margin_m', type: 'string' }],
      rules: [{ id: 'r1', when: { all: [] }, then: {} }, { id: 'r2', when: { all: [] }, then: {} }],
    });
    const one = setOutcomeCell(d, 'r1', 'margin_m', { value: '4' });
    expect(one.outputs[0].type).toBe('number');
    expect(one.rules[0].then.margin_m).toEqual({ value: 4 });
    const two = setOutcomeCell(one, 'r2', 'margin_m', { value: 'wide' });
    expect(two.outputs[0].type).toBe('number');
    expect(two.rules[1].then.margin_m).toEqual({ value: 'wide' });
  });

  it('converts every rule when the type changes', () => {
    const d = doc({ outputs: [{ field: 'm', type: 'string' }], rules: [{ id: 'r1', when: { all: [] }, then: { m: { value: '2.5' } } }, { id: 'r2', when: { all: [] }, then: { m: { formula: 'a*2' } } }] });
    const n = changeOutcomeType(d, 'm', 'number');
    expect(n.rules[0].then.m).toEqual({ value: 2.5 });
    expect(n.rules[1].then.m).toEqual({ formula: 'a*2' });
    expect(changeOutcomeType(n, 'm', 'string').rules[0].then.m).toEqual({ value: '2.5' });
  });
});

describe('changing a fact type', () => {
  it('keeps the conditions valid', () => {
    const d = doc({
      facts: [{ path: 'speed', type: 'string' }],
      rules: [{ id: 'r1', when: { all: [{ fact: 'speed', op: 'eq', value: '4' }, { any: [{ fact: 'speed', op: 'starts_with', value: '1' }] }] }, then: {} }],
    });
    const n = changeFactType(d, 'speed', 'number');
    expect(n.facts[0].type).toBe('number');
    expect(n.rules[0].when.all![0]).toEqual({ fact: 'speed', op: 'eq', value: 4 });
    expect((n.rules[0].when.all![1] as any).any[0]).toEqual({ fact: 'speed', op: 'gt', value: 1 });
  });

  it('coerces lists and leaves what does not fit alone', () => {
    expect(coerceTo('number', ['1', '2.5', 'x'])).toEqual([1, 2.5, 'x']);
    expect(coerceTo('boolean', 'yes')).toBe(true);
    expect(coerceTo('string', 4)).toBe('4');
  });
});

describe('outcome cells in the table', () => {
  it('tells empty text from not set', () => {
    expect(parseThen('', 'string')).toBeNull();
    expect(parseThen('""', 'string')).toEqual({ value: '' });
    expect(thenCellText({ value: '' })).toBe('""');
    expect(thenCellText(undefined)).toBe('');
  });

  it('parses by the outcome type', () => {
    expect(parseThen('4', 'number')).toEqual({ value: 4 });
    expect(parseThen('4', 'string')).toEqual({ value: '4' });
    expect(parseThen('0.5', 'number')).toEqual({ value: 0.5 });
    expect(parseThen('yes', 'boolean')).toEqual({ value: true });
    expect(parseThen('= a * 2', 'number')).toEqual({ formula: 'a * 2' });
    expect(parseThen('"4"', 'number')).toEqual({ value: '4' });
    expect(thenCellText({ value: true })).toBe('yes');
  });
});

describe('problems', () => {
  it('reads either way of naming a field', () => {
    expect(normProblemPath('rules[2].then.margin_m')).toBe('/rules/2/then/margin_m');
    expect(normProblemPath('/rules/0/key')).toBe('/rules/0/key');
    expect(normProblems([{ field: 'rules[0].then.x', message: 'm', code: 'OUTCOME_TYPE' } as any])[0]).toMatchObject({ path: '/rules/0/then/x', severity: 'error' });
  });

  it('rewrites messages that carry an example from another domain', () => {
    expect(normProblems([{ path: '/outputs', message: 'Add at least one outcome, for example obligation.', severity: 'error', code: 'no_outputs' }])[0].message).not.toMatch(/obligation/);
  });

  it('says where a problem lives', () => {
    const d = doc({ facts: [{ path: 'a', type: 'number' }], outputs: [{ field: 'm' }], rules: [{ id: 'r1', key: 'stop.any', when: { all: [] }, then: {} }] });
    expect(problemPlace(d, { path: '/rules/0/then/m', message: '', severity: 'error', code: '' })).toMatchObject({ tab: 'rules', ruleId: 'r1', where: 'Rule 1 (stop.any) · Then m' });
    expect(problemPlace(d, { path: '/facts/0/type', message: '', severity: 'error', code: '' })).toMatchObject({ tab: 'facts', where: 'Facts · a' });
  });
});

describe('opening a decision', () => {
  const v = (version: number, state: VersionSummary['state']) => ({ version, state }) as VersionSummary;
  it('shows the version in force, not a draft', () => {
    expect(pickDefault([v(1, 'published'), v(2, 'draft')])).toBe(1);
    expect(pickDefault([v(1, 'superseded'), v(2, 'published'), v(3, 'proposed')])).toBe(2);
    expect(pickDefault([v(1, 'draft'), v(2, 'draft')])).toBe(2);
    expect(pickDefault([v(1, 'retired')])).toBe(1);
  });
});

describe('outcome order', () => {
  it('follows the outcome list, not the order the store returns', () => {
    const d = doc({ outputs: [{ field: 'action' }, { field: 'margin_m' }, { field: 'reason' }], rules: [{ id: 'r1', when: { all: [] }, then: { reason: { value: 'x' }, margin_m: { value: 4 }, action: { value: 'stop' } } }] });
    expect(thenText(d, d.rules[0])).toBe('action = “stop”, margin_m = 4, reason = “x”');
    expect(Object.keys(orderedResult(d, { reason: 'x', action: 'stop', margin_m: 4, _rule: 'r' }))).toEqual(['action', 'margin_m', 'reason', '_rule']);
  });
});

describe('refusals in plain words', () => {
  it('maps the decision error codes to what to do', async () => {
    const { decisionErrorText } = await import('@/lib/decisionValues');
    expect(decisionErrorText('TIER_LOCKED', 'Version 3 is waiting for sign-off. Withdraw it or let it finish before changing the risk tier.')).toContain('Version 3');
    expect(decisionErrorText('TIER_CHANGED', 'Tier changed.')).toContain('propose it again');
    expect(decisionErrorText('REASON_REQUIRED', 'reason required')).toBe('Write a reason first. It goes on the record with the change.');
    expect(decisionErrorText('OTHER_APPROVERS_EXIST', '2 people can approve this. Ask one of them.')).toContain('in Needs you');
    expect(decisionErrorText('VALIDATION_FAILED', 'Not ready', { summary: '1 golden test fails.' })).toContain('1 golden test fails');
    expect(decisionErrorText('SOLE_OPERATOR_OFF', 'off')).toContain('Risk and Controls');
    expect(decisionErrorText(undefined, 'Plain server text.')).toBe('Plain server text.');
  });
});
