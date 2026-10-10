import { describe, expect, it } from 'vitest';
import { stateChips } from '@/lib/decisionState';
import type { VersionSummary } from '@/lib/decisions';

const v = (version: number, state: VersionSummary['state']) => ({ version, state }) as VersionSummary;
const row = (over = {}) => ({ published: [], drafts: [], proposed: [], latest_version: 0, ...over });

describe('list cards say where a decision stands', () => {
  it('says retired, not "not published yet", when the only version was retired', () => {
    expect(stateChips(row({ latest_version: 1, state: 'retired' })).map((c) => c.text)).toEqual(['Retired, nothing in force']);
    expect(stateChips(row({ latest_version: 1 }))[0].text).toBe('Retired, nothing in force');
  });

  it('tells an approved version from one still waiting', () => {
    const texts = stateChips(row({ published: [v(1, 'published')], waiting: [{ version: 3, state: 'proposed' }, { version: 4, state: 'approved' }], drafts: [v(2, 'draft')] })).map((c) => c.text);
    expect(texts).toEqual(['v1 in force', 'v3 waiting for sign-off', 'v4 approved, ready to publish', '1 draft']);
  });

  it('says not published yet for a new decision', () => {
    expect(stateChips(row({ drafts: [v(1, 'draft')], latest_version: 1, state: 'draft_only' }))[0].text).toBe('Not published yet');
  });

  it('names a denied version instead of leaving only not published yet', () => {
    expect(stateChips(row({ latest_version: 1, state: 'never_published' })).map((c) => c.text)).toEqual(['Not published yet', 'v1 denied']);
    expect(stateChips(row({ published: [v(1, 'published')], latest_version: 1, state: 'in_force', in_force_version: 1 })).map((c) => c.text)).toEqual(['v1 in force']);
  });
});
