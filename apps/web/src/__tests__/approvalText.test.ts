import { changesText, refusal, signoffError, takesOutOfService } from '@/lib/approvalText';
import { effectiveOutcomeType } from '@/lib/decisionValues';
import { pairs } from '@/components/decisions/TestsTab';

describe('approval wording', () => {
  it('leads a denied card with who denied it and why', () => {
    const row = { id: 'a', status: 'denied', signoffs: [{ decision: 'deny', user_email: 'r@x.com', user_name: 'Rita Reviewer', reason: 'Keep it until the audit' }] };
    expect(refusal(row)).toEqual({ verb: 'Denied', by: 'Rita Reviewer', reason: 'Keep it until the audit' });
    expect(refusal({ ...row, status: 'approved' })).toBeNull();
  });

  it('asks twice only for taking a high or critical rule out of service', () => {
    expect(takesOutOfService({ id: 'a', gate_kind: 'decision_archive', payload: { tier: 'high' } })).toBe(true);
    expect(takesOutOfService({ id: 'a', gate_kind: 'decision_retire', payload: { tier: 'critical' } })).toBe(true);
    expect(takesOutOfService({ id: 'a', gate_kind: 'decision_archive', payload: { tier: 'medium' } })).toBe(false);
    expect(takesOutOfService({ id: 'a', gate_kind: 'decision_restore', payload: { tier: 'high' } })).toBe(false);
  });

  it('never shows a zero change count from an old payload', () => {
    expect(changesText({ id: 'a', payload: { changes: 0 } })).toBeNull();
    expect(changesText({ id: 'a', payload: {}, changes: 4 })).toBe('4 rule changes');
    expect(changesText({ id: 'a', payload: {}, changes: 1 })).toBe('1 rule change');
  });

  it('says a typed reason did not arrive', () => {
    expect(signoffError('REASON_REQUIRED', 'Write a reason', 'Not safe yet')).toMatch(/Couldn't send your reason/);
    expect(signoffError('REASON_REQUIRED', 'Write a reason', '')).toBe('Write a reason');
  });
});

describe('decision wording', () => {
  it('reads a Text outcome holding only numbers as Number', () => {
    const doc: any = { facts: [], outputs: [{ field: 'margin_m', type: 'string' }, { field: 'action', type: 'string' }], rules: [{ id: 'r', then: { margin_m: { value: 4 }, action: { value: 'stop' } } }] };
    expect(effectiveOutcomeType(doc, doc.outputs[0])).toBe('number');
    expect(effectiveOutcomeType(doc, doc.outputs[1])).toBe('string');
  });

  it('shows golden test facts by their labels', () => {
    expect(pairs({ tip_speed: 3, worker: { clearance_m: 2 } }, { tip_speed: 'Tip speed', 'worker.clearance_m': 'Clearance' })).toBe('Tip speed = 3, Clearance = 2');
  });
});
