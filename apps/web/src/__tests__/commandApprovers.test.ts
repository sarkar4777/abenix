import { commandApprovers } from '@/lib/approvalText';

const base = { id: 'a', gate_kind: 'telemetry.command', requested_by: 'me' };

describe('commandApprovers', () => {
  it('lists you first, two names, then the rest as a count', () => {
    const r = commandApprovers({ ...base, approvers: [{ id: 'me', name: 'Me', is_requester: true }, { id: '1', name: 'Ana' }, { id: '2', name: 'Raj' }, { id: '3', name: 'Kim' }], can_self_approve: true }, 'me');
    expect(r.who).toBe('Who can approve: you and Ana, Raj (+1)');
    expect(r.mine).toBe('You asked for this. You can approve it, or anyone listed can.');
  });
  it('says only you when nobody else can', () => {
    const r = commandApprovers({ ...base, approvers: [{ id: 'me', name: 'Me', is_requester: true }], can_self_approve: true }, 'me');
    expect(r.who).toBe('Who can approve: only you');
    expect(r.mine).toBe('You asked for this. You can approve it.');
  });
  it('respects a requester who may not approve', () => {
    const r = commandApprovers({ ...base, approvers: [{ id: '1', name: 'Ana' }], can_self_approve: false }, 'me');
    expect(r.who).toBe('Who can approve: Ana');
    expect(r.mine).toMatch(/one of the people listed has to approve it/);
  });
  it('says nothing about yourself on someone else\'s request you cannot sign', () => {
    const r = commandApprovers({ ...base, requested_by: 'x', approvers: [{ id: 'x', name: 'Xi', is_requester: true }] }, 'me');
    expect(r.mine).toBeNull();
    expect(r.who).toBe('Who can approve: Xi (asked)');
  });
  it('never goes quiet when the server sends no approvers', () => {
    const r = commandApprovers({ ...base, requested_by: 'x' }, 'me');
    expect(r.mine).toBeNull();
    expect(r.who).toMatch(/Couldn't load who can approve/);
  });
});

describe('commandApprovers with the final server shape', () => {
  it('counts the rest from approvers_total, the list is capped', () => {
    const list = [{ id: 'me', name: 'Me', is_requester: true }, { id: '1', name: 'Ana' }, { id: '2', name: 'Raj' }];
    const r = commandApprovers({ ...base, approvers: list, approvers_total: 60, can_self_approve: true }, 'me');
    expect(r.who).toBe('Who can approve: you and Ana, Raj (+57)');
  });
  it('says plainly when who can approve could not load', () => {
    const r = commandApprovers({ ...base, approvers: null, can_self_approve: null }, 'me');
    expect(r.who).toMatch(/Couldn't load who can approve/);
  });
  it('explains why the requester cannot approve when the workspace says so', () => {
    const r = commandApprovers({ ...base, approvers: [{ id: '1', name: 'Ana' }], approvers_total: 1, can_self_approve: false }, 'me');
    expect(r.mine).toMatch(/someone other than the requester/);
    expect(r.who).toBe('Who can approve: Ana');
  });
});
