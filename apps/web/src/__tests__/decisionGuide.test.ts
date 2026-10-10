import { describe, expect, it, vi } from 'vitest';
import { nextStep, type GuideHandlers, type GuideInput } from '@/components/decisions/DecisionGuide';
import type { RuleDoc, VersionFull } from '@/lib/decisions';
import type { SignOffInfo } from '@/components/decisions/SignOff';

const h = (): GuideHandlers => ({
  openTable: vi.fn(), openTry: vi.fn(), openTests: vi.fn(), showProblem: vi.fn(), check: vi.fn(), propose: vi.fn(),
  publish: vi.fn(), sole: vi.fn(), newDraft: vi.fn(), openVersion: vi.fn(),
});
const doc = (rules = 1): RuleDoc => ({ kind: 'rules', hit_policy: 'first', facts: [], outputs: [], rules: Array.from({ length: rules }, (_, i) => ({ id: `r${i}`, when: { all: [] }, then: {} })) });
const signoff = (over: Partial<SignOffInfo> = {}): SignOffInfo => ({
  required: 1, tier: 'high', policy_text: 'High risk: one person who did not author it must approve.', approval_id: 'a1', status: null,
  signoffs: [], eligible_approvers: [{ id: 'u2', name: 'Rita', email: 'r@x' }], author_can_approve: false, sole_operator_available: false, ...over,
});
const input = (over: Partial<GuideInput> = {}): GuideInput => ({
  version: { version: 1, state: 'draft' } as VersionFull, doc: doc(), errors: [], testCount: 1, validation: null, signoff: signoff(),
  canAuthor: true, canPublish: true, isAdmin: true, liveVersion: null, agentHref: '/builder', ...over,
});

describe('the what-now guide', () => {
  it('starts an empty decision with a paste', () => {
    const handlers = h();
    const g = nextStep(input({ doc: doc(0) }), handlers);
    expect(g.step).toBe('rules');
    g.action!.onClick!();
    expect(handlers.openTable).toHaveBeenCalled();
  });

  it('asks for a golden test, then Check, then a proposal', () => {
    expect(nextStep(input({ testCount: 0 }), h())).toMatchObject({ step: 'try', action: { label: 'Open Try it' } });
    expect(nextStep(input(), h())).toMatchObject({ step: 'check', action: { label: 'Check' } });
    const ready = nextStep(input({ validation: { ok: true, summary: 'Ready.' } as any }), h());
    expect(ready.step).toBe('signoff');
    expect(ready.text).toContain('Rita can approve it');
  });

  it('points at the problems first', () => {
    expect(nextStep(input({ errors: [{ path: '/rules/0/key', message: 'x', severity: 'error', code: '' }] }), h())).toMatchObject({ step: 'rules', tone: 'warn' });
  });

  it('says who it waits for, or offers to sign alone, or tells the reviewer they can approve', () => {
    const proposed = { version: 1, state: 'proposed' } as VersionFull;
    expect(nextStep(input({ version: proposed }), h()).text).toContain('Waiting for Rita');
    expect(nextStep(input({ version: proposed, signoff: signoff({ eligible_approvers: [], sole_operator_available: true }) }), h()).action!.label).toBe('Approve as the only approver');
    expect(nextStep(input({ version: proposed, meId: 'u2' }), h()).text).toContain('You can approve this');
  });

  it('tells someone without publish rights who can publish', () => {
    const g = nextStep(input({ version: { version: 1, state: 'approved' } as VersionFull, canPublish: false, signoff: signoff({ signoffs: [{ user_id: 'u2', name: 'Rita', at: '', sole_operator: false, reason: null }] }) }), h());
    expect(g.text).toContain('such as Rita');
    expect(g.action).toBeUndefined();
  });

  it('after publishing, says how to use it, and asks for the review a raise needs', () => {
    const live = { version: 2, state: 'published' } as VersionFull;
    const g = nextStep(input({ version: live }), h());
    expect(g.tone).toBe('ok');
    expect(g.more?.map((m) => m.label)).toEqual(['From a pipeline', 'From the SDK', 'Over REST']);
    const re = nextStep(input({ version: live, reattest: { approval_id: 'a9', version: 2, from_tier: 'low', to_tier: 'high' } }), h());
    expect(re.text).toContain('needs a High-risk review');
    expect(re.action!.href).toBe('/approvals#a9');
  });
});

describe('a version with only part of a check stored', () => {
  it('asks for Check instead of failing', () => {
    const g = nextStep(input({ validation: { returned: { note: '', at: '' } } as any }), h());
    expect(g.text).toBeTruthy();
  });
  it('treats a stored note without a summary as not checked yet', () => {
    expect(nextStep(input({ validation: { ok: false } as any }), h()).action!.label).toBe('Check');
  });
});
